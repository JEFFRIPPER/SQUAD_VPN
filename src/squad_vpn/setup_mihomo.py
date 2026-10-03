from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx

from .validator import DEFAULT_BINARY


LATEST_RELEASE = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"


async def install_mihomo(target: str | Path = DEFAULT_BINARY) -> tuple[Path, str]:
    target = Path(target)
    headers = {"User-Agent": "SQUAD-VPN/0.4"}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=60.0) as client:
        response = await client.get(LATEST_RELEASE)
        response.raise_for_status()
        release = response.json()
        tag = str(release["tag_name"])
        expected = f"mihomo-windows-amd64-compatible-{tag}.zip"
        assets = release.get("assets") or []
        asset = next((item for item in assets if item.get("name") == expected), None)
        if asset is None:
            raise RuntimeError(f"Не найден официальный compatible asset {expected}")
        download = await client.get(str(asset["browser_download_url"]))
        download.raise_for_status()
        payload = download.content
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            actual = hashlib.sha256(payload).hexdigest()
            expected_hash = digest.split(":", 1)[1].lower()
            if actual.lower() != expected_hash:
                raise RuntimeError("SHA256 скачанного Mihomo не совпал с GitHub release")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith(".exe")]
        if not candidates:
            raise RuntimeError("В архиве Mihomo не найден .exe")
        binary_data = archive.read(candidates[0])

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(binary_data)
    partial.replace(target)
    return target, tag
