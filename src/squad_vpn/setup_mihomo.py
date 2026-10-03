from __future__ import annotations

import gzip
import hashlib
import io
import os
import platform
import stat
import zipfile
from pathlib import Path

import httpx

from .validator import DEFAULT_BINARY


LATEST_RELEASE = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"


def asset_name(tag: str, system: str | None = None, machine: str | None = None) -> str:
    """Official Mihomo release asset for this OS/CPU."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if arch is None:
        raise RuntimeError(f"Неподдерживаемая архитектура: {machine}")
    os_name = {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(system)
    if os_name is None:
        raise RuntimeError(f"Неподдерживаемая ОС: {system}")
    # "compatible" builds avoid newer CPU instructions; they exist for amd64 only.
    flavor = f"{arch}-compatible" if arch == "amd64" else arch
    extension = "zip" if os_name == "windows" else "gz"
    return f"mihomo-{os_name}-{flavor}-{tag}.{extension}"


def extract_binary(name: str, payload: bytes) -> bytes:
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            candidates = [
                item for item in archive.namelist()
                if item.lower().endswith(".exe") or "mihomo" in item.lower()
            ]
            if not candidates:
                raise RuntimeError("В архиве Mihomo не найден бинарник")
            return archive.read(candidates[0])
    if name.endswith(".gz"):
        return gzip.decompress(payload)
    raise RuntimeError(f"Неизвестный формат архива: {name}")


async def install_mihomo(target: str | Path = DEFAULT_BINARY) -> tuple[Path, str]:
    target = Path(target)
    headers = {"User-Agent": "SQUAD-VPN/0.7"}
    # In GitHub Actions the token lifts the 60 requests/hour anonymous limit.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=60.0) as client:
        response = await client.get(LATEST_RELEASE)
        response.raise_for_status()
        release = response.json()
        tag = str(release["tag_name"])
        expected = asset_name(tag)
        assets = release.get("assets") or []
        asset = next((item for item in assets if item.get("name") == expected), None)
        if asset is None:
            raise RuntimeError(f"Не найден официальный asset {expected}")
        download = await client.get(str(asset["browser_download_url"]))
        download.raise_for_status()
        payload = download.content
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            actual = hashlib.sha256(payload).hexdigest()
            expected_hash = digest.split(":", 1)[1].lower()
            if actual.lower() != expected_hash:
                raise RuntimeError("SHA256 скачанного Mihomo не совпал с GitHub release")

    binary_data = extract_binary(expected, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(binary_data)
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    partial.replace(target)
    return target, tag
