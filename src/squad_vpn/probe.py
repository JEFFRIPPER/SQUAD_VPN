"""Probe network: every SQUAD VPN instance is a vantage point.

Each probe validates nodes from its own network and publishes the results as
``report.json`` on its own git branch ``probe-<id>`` (force-pushed, so no
conflicts between probes). Every probe fetches the other branches and merges
them, so a node gets a status per region: alive from RU, from US, ...

Reports carry only the probe id, its country and per-node results — no IP
address or provider of the person running the probe.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from . import __version__
from .publish import NO_WINDOW, PublishError, _git, force_push_tree
from .store import NodeStore


REPORT_FORMAT = 1
REPORT_FILE = "report.json"
BRANCH_PREFIX = "probe-"
MAX_REPORT_BYTES = 5_000_000
MAX_REPORT_AGE = timedelta(hours=48)
IDENTITY_FILE = Path("data/probe.json")

_PROBE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_REGION = re.compile(r"[A-Z]{2}|\?\?")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@dataclass(slots=True, frozen=True)
class ProbeIdentity:
    probe_id: str
    region: str
    kind: str = "local"


def branch_name(probe_id: str) -> str:
    return f"{BRANCH_PREFIX}{probe_id}"


def detect_region(timeout: float = 8.0) -> str:
    """Country code of this machine's public IP ("??" when unknown)."""
    try:
        response = httpx.get("https://ipwho.is/", timeout=timeout, trust_env=False)
        response.raise_for_status()
        code = str(response.json().get("country_code") or "").upper()
    except (httpx.HTTPError, ValueError):
        return "??"
    return code if _REGION.fullmatch(code) else "??"


def load_identity(
    path: Path = IDENTITY_FILE,
    *,
    probe_id: str | None = None,
    region: str | None = None,
    kind: str = "local",
) -> ProbeIdentity:
    """Stable identity of this probe, created once and kept in ``data/probe.json``.

    The id is random (``<region>-<6 hex>``): it identifies the installation,
    not the person.
    """
    stored: dict[str, str] = {}
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    stored_region = str(stored.get("region") or "").upper()
    if stored_region == "??":
        stored_region = ""  # detection failed last time: try again
    region = (region or stored_region).upper() or detect_region()
    probe_id = (
        probe_id
        or stored.get("probe_id")
        or f"{region.lower().replace('??', 'xx')}-{secrets.token_hex(3)}"
    ).lower()
    if not _PROBE_ID.fullmatch(probe_id):
        raise ValueError(f"Недопустимый probe id: {probe_id}")
    identity = ProbeIdentity(probe_id, region if _REGION.fullmatch(region) else "??", kind)
    if stored.get("probe_id") != identity.probe_id or stored.get("region") != identity.region:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(identity), indent=2), encoding="utf-8")
    return identity


def build_report(store: NodeStore, identity: ProbeIdentity, *, hours: int = 24) -> dict[str, object]:
    return {
        "format": REPORT_FORMAT,
        "probe_id": identity.probe_id,
        "region": identity.region,
        "kind": identity.kind,
        "version": __version__,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "results": store.probe_report_rows(identity.probe_id, hours=hours),
    }


def validate_report(data: object, *, now: datetime | None = None) -> dict[str, object]:
    """Check an untrusted report; raise ValueError when it is malformed or stale."""
    if not isinstance(data, dict) or data.get("format") != REPORT_FORMAT:
        raise ValueError("неизвестный формат отчёта")
    probe_id = str(data.get("probe_id") or "")
    region = str(data.get("region") or "")
    generated = str(data.get("generated_at") or "")
    if not _PROBE_ID.fullmatch(probe_id) or not _REGION.fullmatch(region):
        raise ValueError("некорректные probe_id/region")
    if not _TIMESTAMP.fullmatch(generated):
        raise ValueError("некорректный generated_at")
    now = now or datetime.now(UTC)
    generated_at = datetime.strptime(generated, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    if now - generated_at > MAX_REPORT_AGE:
        raise ValueError("отчёт устарел")
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("нет results")
    results = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        fp = str(item.get("fp") or "")
        checked = str(item.get("checked_at") or "")
        if not _FINGERPRINT.fullmatch(fp) or not _TIMESTAMP.fullmatch(checked):
            continue
        latency = item.get("latency_ms")
        results.append(
            {
                "fp": fp,
                "alive": bool(item.get("alive")),
                "latency_ms": float(latency) if isinstance(latency, int | float) else None,
                "checked_at": checked,
                "rate": min(1.0, max(0.0, float(item.get("rate") or 0.0))),
                "checks": max(0, int(item.get("checks") or 0)),
                "error": str(item["error"])[:200] if item.get("error") else None,
            }
        )
    return {
        "probe_id": probe_id,
        "region": region,
        "kind": str(data.get("kind") or "remote")[:20],
        "version": str(data.get("version") or "")[:20] or None,
        "generated_at": generated,
        "results": results,
    }


def publish_report(
    store: NodeStore,
    identity: ProbeIdentity,
    repo: str,
    *,
    workdir: Path = Path("data/probe-publish"),
) -> dict[str, object]:
    report = build_report(store, identity)

    def write(directory: Path) -> None:
        (directory / REPORT_FILE).write_text(
            json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    force_push_tree(
        repo,
        branch_name(identity.probe_id),
        workdir,
        write,
        f"probe {identity.probe_id}: {report['generated_at']} UTC",
    )
    return {
        "branch": branch_name(identity.probe_id),
        "results": len(report["results"]),  # type: ignore[arg-type]
    }


def fetch_reports(repo: str, *, cache: Path = Path("data/probes-cache")) -> list[dict[str, object]]:
    """Fetch every ``probe-*`` branch of ``repo`` and return their raw reports."""
    cache = Path(cache)
    if not (cache / "HEAD").exists():
        cache.mkdir(parents=True, exist_ok=True)
        _git(cache, "init", "-q", "--bare")
    # Ask first: fetching a glob that matches nothing fails without a message.
    listed = _git(cache, "ls-remote", "--heads", repo, f"{BRANCH_PREFIX}*")
    if not listed.strip():
        return []
    _git(
        cache,
        "fetch",
        "--quiet",
        "--prune",
        "--depth",
        "1",
        "--force",
        repo,
        f"+refs/heads/{BRANCH_PREFIX}*:refs/probes/{BRANCH_PREFIX}*",
    )
    refs = _git(cache, "for-each-ref", "--format=%(refname)", "refs/probes/").split()
    reports: list[dict[str, object]] = []
    for ref in refs:
        try:
            completed = subprocess.run(
                ["git", "cat-file", "-s", f"{ref}:{REPORT_FILE}"],
                cwd=cache, capture_output=True, text=True, creationflags=NO_WINDOW,
            )
            if completed.returncode != 0 or int(completed.stdout.strip()) > MAX_REPORT_BYTES:
                continue
            body = _git(cache, "show", f"{ref}:{REPORT_FILE}")
            reports.append(json.loads(body))
        except (PublishError, ValueError):
            continue
    return reports


def import_reports(
    store: NodeStore,
    reports: list[dict[str, object]],
    identity: ProbeIdentity,
) -> dict[str, object]:
    imported: dict[str, int] = {}
    skipped: dict[str, str] = {}
    for raw in reports:
        try:
            report = validate_report(raw)
        except ValueError as exc:
            skipped[str(raw.get("probe_id") if isinstance(raw, dict) else "?")] = str(exc)
            continue
        if report["probe_id"] == identity.probe_id:
            continue
        imported[str(report["probe_id"])] = store.import_probe_results(
            str(report["probe_id"]),
            str(report["region"]),
            report["results"],  # type: ignore[arg-type]
            kind=str(report["kind"]),
            version=report["version"],  # type: ignore[arg-type]
            generated_at=str(report["generated_at"]),
        )
    return {"imported": imported, "skipped": skipped}


def sync_probes(
    store: NodeStore,
    identity: ProbeIdentity,
    repo: str,
    *,
    cache: Path = Path("data/probes-cache"),
) -> dict[str, object]:
    return import_reports(store, fetch_reports(repo, cache=cache), identity)


def default_kind() -> str:
    return "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
