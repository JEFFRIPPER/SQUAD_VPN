"""Over-the-air updates: the safety rails around the agent's self-update.

An update reaches a computer only when it is safe:

1. the commit passed CI on GitHub (``ci_verdict``), or CI says nothing for
   hours (then the next rails still apply);
2. the new code imports and builds the API in a separate process
   (``smoke_test``) before anything running is touched;
3. the restarted agent must answer ``/health`` with the new commit, otherwise
   the old agent rolls the folder back and remembers the commit as bad.

Everything that happens is written to ``data/update.json`` for the app.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from . import __version__


JOURNAL_FILE = Path("data/update.json")
HISTORY_LIMIT = 30
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
# CI job that has to pass (.github/workflows/ci.yml, job "test").
CI_CHECK_NAME = "test"
# A commit CI never reported on is installed after this long anyway.
CI_WAIT_LIMIT = timedelta(hours=6)
# Changes outside these paths do not touch the running program.
RESTART_PATHS = ("src/", "pyproject.toml", "config/squad.yaml")
_VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')
_SHA = re.compile(r"[0-9a-f]{40}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Journal:
    """``data/update.json``: last check, history, commits known to be bad."""

    def __init__(self, root: Path) -> None:
        self.path = root / JOURNAL_FILE
        self.data: dict[str, object] = {
            "last_check": None,
            "next_check": None,
            "message": None,
            "history": [],
            "skipped": {},
            "pending": None,
        }
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    @property
    def history(self) -> list[dict[str, object]]:
        return self.data["history"]  # type: ignore[return-value]

    @property
    def skipped(self) -> dict[str, str]:
        return self.data["skipped"]  # type: ignore[return-value]

    def note(self, message: str) -> None:
        self.data["message"] = message

    def checked(self, next_in_seconds: float | None) -> None:
        self.data["last_check"] = _now()
        self.data["next_check"] = (
            None
            if next_in_seconds is None
            else (datetime.now(UTC) + timedelta(seconds=next_in_seconds)).isoformat(timespec="seconds")
        )

    def record(self, kind: str, result: str, **details: object) -> None:
        entry = {"at": _now(), "kind": kind, "result": result, **details}
        self.history.append(entry)
        del self.history[:-HISTORY_LIMIT]

    def skip(self, sha: str, reason: str) -> None:
        self.skipped[sha] = reason
        # Keep the list short: only the most recent bad commits matter.
        for old in list(self.skipped)[:-20]:
            del self.skipped[old]

    def waiting_since(self, sha: str) -> datetime:
        """When this commit was first seen waiting for CI."""
        pending = self.data.get("pending")
        if isinstance(pending, dict) and pending.get("sha") == sha:
            try:
                return datetime.fromisoformat(str(pending["since"]))
            except (KeyError, ValueError):
                pass
        self.data["pending"] = {"sha": sha, "since": _now()}
        return datetime.now(UTC)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_name(self.path.name + ".part")
            partial.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            partial.replace(self.path)
        except OSError:
            pass


def git_head(root: Path) -> str | None:
    """Current commit read straight from ``.git`` (no git process, no window)."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if _SHA.fullmatch(head):
            return head
        if not head.startswith("ref: "):
            return None
        ref = head[5:].strip()
        ref_file = git / ref
        if ref_file.exists():
            value = ref_file.read_text(encoding="utf-8").strip()
            return value if _SHA.fullmatch(value) else None
        packed = git / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                sha, _, name = line.partition(" ")
                if name.strip() == ref and _SHA.fullmatch(sha):
                    return sha
    except OSError:
        return None
    return None


def version_on_disk(root: Path) -> str | None:
    try:
        text = (root / "src" / "squad_vpn" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION.search(text)
    return match.group(1) if match else None


def needs_restart(changed: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix) for path in changed for prefix in RESTART_PATHS)


def ci_verdict(slug: str | None, sha: str, *, timeout: float = 10.0) -> str:
    """success | failure | pending | unknown for the CI job on ``sha``."""
    if not slug:
        return "unknown"
    url = f"https://api.github.com/repos/{slug}/commits/{sha}/check-runs"
    try:
        response = httpx.get(
            url,
            params={"check_name": CI_CHECK_NAME},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"SQUAD-VPN/{__version__}",
            },
            timeout=timeout,
            trust_env=False,
            follow_redirects=True,
        )
        response.raise_for_status()
        runs = response.json().get("check_runs") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return "unknown"
    if not runs:
        return "pending"  # CI has not picked the commit up yet
    latest = max(runs, key=lambda run: int(run.get("id") or 0))
    if latest.get("status") != "completed":
        return "pending"
    if latest.get("conclusion") in {"success", "neutral", "skipped"}:
        return "success"
    return "failure"


SMOKE_CODE = """
import tempfile
from pathlib import Path
import squad_vpn.agent, squad_vpn.cli, squad_vpn.ota
from squad_vpn.api import create_app
folder = Path(tempfile.mkdtemp(prefix="squad-smoke-"))
create_app(folder / "smoke.sqlite3", client_root=folder)
print("ok")
"""


def smoke_test(root: Path, python: str, *, timeout: float = 180.0) -> tuple[bool, str]:
    """Import the new code and build the API in a separate process."""
    try:
        result = subprocess.run(
            [python, "-c", SMOKE_CODE],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    # Judge by the exit code only: under pythonw there may be no stdout at all.
    if result.returncode == 0:
        return True, ""
    # The last traceback line says what is wrong ("SyntaxError: ...").
    lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return False, (lines[-1] if lines else f"код выхода {result.returncode}")[:300]


def wait_healthy(
    port: int,
    process: subprocess.Popen[bytes],
    expected_commit: str | None,
    *,
    timeout: float = 150.0,
    interval: float = 2.0,
) -> bool:
    """True when the new agent's server answers /health with the new commit."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False  # the new agent died
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3.0, trust_env=False)
            data = response.json()
            commit = data.get("commit")
            if data.get("status") == "ok" and (
                not expected_commit or not commit or expected_commit.startswith(str(commit))
            ):
                return True
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        time.sleep(interval)
    return False


def changelog(root: Path, sections: int = 3) -> list[dict[str, str]]:
    """The newest ``sections`` entries of CHANGELOG.md as {title, text}."""
    try:
        lines = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    result: list[dict[str, str]] = []
    current: dict[str, list[str]] | None = None
    for line in lines:
        if line.startswith("## "):
            if len(result) >= sections:
                break
            current = {"title": [line[3:].strip()], "text": []}
            result.append(current)  # type: ignore[arg-type]
        elif current is not None:
            current["text"].append(line)
    return [
        {"title": item["title"][0], "text": "\n".join(item["text"]).strip()}  # type: ignore[index]
        for item in result
    ]
