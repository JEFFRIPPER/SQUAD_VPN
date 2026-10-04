"""Delivery of the desktop app ``SQUAD VPN.exe`` into the project folder.

The exe is built by GitHub Actions on Windows and attached to the release
``app-latest`` together with ``app-manifest.json`` (version, SHA-256, size).
The agent (and install.cmd) download it next to the project files and
replace it when the release has a newer build; a download whose checksum
does not match the manifest is thrown away.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import httpx

from .publish import GITHUB_URL, detect_origin


RELEASE_TAG = "app-latest"
ASSET_EXE = "SQUAD-VPN.exe"
ASSET_VERSION = "app-version.txt"
ASSET_MANIFEST = "app-manifest.json"
APP_FILE = "SQUAD VPN.exe"
LOCAL_VERSION = Path("data/app-version.txt")

log = logging.getLogger("squad_vpn.agent")


def release_base(repo_url: str | None) -> str | None:
    match = GITHUB_URL.search(repo_url or "")
    if not match:
        return None
    return (
        f"https://github.com/{match.group('owner')}/{match.group('repo')}"
        f"/releases/download/{RELEASE_TAG}/"
    )


def _replace(target: Path, payload: bytes) -> None:
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(payload)
    if target.exists():
        try:
            target.unlink()
        except PermissionError:
            # A running exe cannot be deleted on Windows, but it can be renamed.
            old = target.with_name(target.name + ".old")
            if old.exists():
                old.unlink()
            target.rename(old)
    partial.replace(target)


def cleanup_old(root: Path) -> None:
    old = root / (APP_FILE + ".old")
    try:
        if old.exists():
            old.unlink()
    except OSError:
        pass


def ensure_app(
    root: Path,
    *,
    repo_url: str | None = None,
    force: bool = False,
    timeout: float = 180.0,
) -> str:
    """Download or refresh the desktop app. Returns a short status string."""
    if os.name != "nt" and not force:
        return "skipped: not windows"
    base = release_base(repo_url or detect_origin(root))
    if base is None:
        return "skipped: repository is not on GitHub"
    cleanup_old(root)
    target = root / APP_FILE
    local_version_path = root / LOCAL_VERSION
    local_version = ""
    if local_version_path.exists():
        local_version = local_version_path.read_text(encoding="utf-8").strip()
    expected_sha = ""
    expected_size = 0
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, trust_env=False) as client:
            manifest = client.get(base + ASSET_MANIFEST)
            if manifest.status_code == 200:
                data = manifest.json()
                remote_version = str(data["version"]).strip()[:80]
                expected_sha = str(data.get("sha256") or "").lower()
                expected_size = int(data.get("size") or 0)
            else:
                # Releases built before the manifest existed.
                response = client.get(base + ASSET_VERSION)
                if response.status_code == 404:
                    return "skipped: no release yet"
                response.raise_for_status()
                remote_version = response.text.strip()[:80]
            if target.exists() and remote_version == local_version:
                return f"up to date: {remote_version}"
            download = client.get(base + ASSET_EXE)
            download.raise_for_status()
            payload = download.content
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return f"error: {exc}"
    if len(payload) < 1_000_000 or payload[:2] != b"MZ":
        return "error: downloaded file is not a Windows program"
    if expected_size and len(payload) != expected_size:
        return f"error: size mismatch ({len(payload)} != {expected_size})"
    if expected_sha and hashlib.sha256(payload).hexdigest() != expected_sha:
        return "error: checksum mismatch, the download is damaged or replaced"
    _replace(target, payload)
    local_version_path.parent.mkdir(parents=True, exist_ok=True)
    local_version_path.write_text(remote_version, encoding="utf-8")
    log.info("Приложение %s обновлено до %s", APP_FILE, remote_version)
    return f"updated: {remote_version}"
