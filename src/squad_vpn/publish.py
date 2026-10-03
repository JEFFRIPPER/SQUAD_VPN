from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .smart import export_smart_catalog
from .store import NodeStore


PROTECTED_BRANCHES = {"main", "master", "develop", "dev"}
GITHUB_URL = re.compile(
    r"github\.com[/:](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
BOT_NAME = "SQUAD VPN bot"
BOT_EMAIL = "squad-vpn-bot@users.noreply.github.com"
PURGE_FILES = ("balanced", "fast", "stable", "all")


@dataclass(slots=True, frozen=True)
class PublishTarget:
    repo: str
    branch: str = "subs"
    workdir: Path = Path("data/publish")

    def github(self) -> tuple[str, str] | None:
        match = GITHUB_URL.search(self.repo)
        if not match:
            return None
        return match.group("owner"), match.group("repo")

    def raw_base(self) -> str | None:
        repo = self.github()
        if repo is None:
            return None
        return f"https://raw.githubusercontent.com/{repo[0]}/{repo[1]}/{self.branch}/"

    def cdn_base(self) -> str | None:
        # jsDelivr mirror: helps where raw.githubusercontent.com is blocked.
        repo = self.github()
        if repo is None:
            return None
        return f"https://cdn.jsdelivr.net/gh/{repo[0]}/{repo[1]}@{self.branch}/"


class PublishError(RuntimeError):
    pass


def _git(workdir: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        # Never echo credentials embedded in a remote URL.
        message = re.sub(r"://[^/@\s]+@", "://***@", message)
        raise PublishError(f"git {args[0]}: {message[-800:]}")
    return completed.stdout.strip()


def _force_remove(func, path, _exc) -> None:
    # Git marks object files read-only; on Windows rmtree cannot delete them as is.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)
    else:
        shutil.rmtree(path, onerror=_force_remove)


def detect_origin(project_dir: str | Path = ".") -> str | None:
    try:
        return _git(Path(project_dir), "remote", "get-url", "origin") or None
    except (PublishError, OSError):
        return None


def _links_table(target: PublishTarget, index: dict[str, object]) -> list[str]:
    raw = target.raw_base() or ""
    cdn = target.cdn_base()
    lines = [
        "| Подписка | Узлов | base64 (v2rayNG, Hiddify, INCY…) | Clash / Mihomo | plain |",
        "| --- | --- | --- | --- | --- |",
    ]

    def row(title: str, meta: dict[str, object]) -> str:
        b64 = f"{raw}{meta['base64']}"
        yaml = f"{raw}{meta['mihomo']}"
        plain = f"{raw}{meta['plain']}"
        return f"| {title} | {meta['count']} | {b64} | {yaml} | {plain} |"

    for name, meta in index["profiles"].items():  # type: ignore[union-attr]
        lines.append(row(f"**{name}**", meta))
    for name, meta in index["countries"].items():  # type: ignore[union-attr]
        lines.append(row(f"страна {name}", _prefixed(meta, "country/")))
    for name, meta in index["protocols"].items():  # type: ignore[union-attr]
        lines.append(row(f"протокол {name}", _prefixed(meta, "protocol/")))
    if cdn:
        lines += [
            "",
            "Если `raw.githubusercontent.com` не открывается, замени начало ссылки",
            f"`{raw}` на зеркало `{cdn}`.",
        ]
    return lines


def _prefixed(meta: object, prefix: str) -> dict[str, object]:
    data = dict(meta)  # type: ignore[call-overload]
    for key in ("plain", "base64", "mihomo"):
        data[key] = prefix + str(data[key])
    return data


def build_site(store: NodeStore, directory: Path, target: PublishTarget) -> dict[str, object]:
    """Render everything that goes onto the publish branch into ``directory``."""
    index = export_smart_catalog(store, directory)
    stats = store.stats()
    updated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    stats["updated_at"] = updated
    (directory / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    readme = [
        "# SQUAD VPN — подписки",
        "",
        f"Обновлено: **{updated}** · живых узлов: **{stats['alive']}**"
        f" из {stats['total']} · средний ping: {stats['average_latency_ms'] or '—'} ms",
        "",
        "Ветка генерируется автоматически и перезаписывается при каждом обновлении.",
        "Скопируй ссылку из нужной строки и добавь её в VPN-клиент как подписку.",
        "",
        *_links_table(target, index),
        "",
    ]
    (directory / "README.md").write_text("\n".join(readme), encoding="utf-8")
    return index


def publish(store: NodeStore, target: PublishTarget) -> dict[str, object]:
    """Publish subscriptions as a single orphan commit on ``target.branch``.

    The branch only ever holds generated files, so each publish force-pushes
    one fresh commit: history does not grow and concurrent runs cannot
    conflict (the last one wins).
    """
    if target.branch in PROTECTED_BRANCHES:
        raise PublishError(f"Публикация в ветку {target.branch} запрещена")
    workdir = Path(target.workdir)
    if workdir.exists():
        _rmtree(workdir)
    workdir.mkdir(parents=True)
    _git(workdir, "init", "-q")
    _git(workdir, "config", "user.name", BOT_NAME)
    _git(workdir, "config", "user.email", BOT_EMAIL)
    _git(workdir, "config", "core.autocrlf", "false")
    _git(workdir, "checkout", "-q", "--orphan", target.branch)

    index = build_site(store, workdir, target)
    _git(workdir, "add", "-A")
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    _git(workdir, "commit", "-q", "-m", f"subs: {stamp}")
    _git(
        workdir,
        "push",
        "--force",
        "--quiet",
        target.repo,
        f"HEAD:refs/heads/{target.branch}",
    )
    _purge_cdn(target)
    return {
        "branch": target.branch,
        "raw_base": target.raw_base(),
        "cdn_base": target.cdn_base(),
        "profiles": {
            name: meta["count"]  # type: ignore[index]
            for name, meta in index["profiles"].items()  # type: ignore[union-attr]
        },
    }


def _purge_cdn(target: PublishTarget) -> None:
    """Ask jsDelivr to drop its cached copy so the mirror follows quickly."""
    repo = target.github()
    if repo is None:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            for name in PURGE_FILES:
                for suffix in ("", ".b64", ".yaml"):
                    client.get(
                        f"https://purge.jsdelivr.net/gh/{repo[0]}/{repo[1]}"
                        f"@{target.branch}/{name}{suffix}"
                    )
    except httpx.HTTPError:
        return
