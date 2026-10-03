"""User settings changed from the desktop app (``data/settings.json``)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path


SETTINGS_FILE = Path("data/settings.json")
ALLOWED_INTERVALS = (15, 30, 60, 120, 180, 360)


@dataclass(slots=True)
class Settings:
    interval_minutes: int = 60
    auto_update: bool = True
    update_hours: float = 3.0
    # Country of this computer for the probe network: "auto" = by IP.
    # Set it by hand when another VPN changes the IP (e.g. shows NL while in RU).
    probe_region: str = "auto"
    # VPN client (v0.8)
    client_profile: str = "balanced"
    client_autoconnect: bool = False
    # Serve subscriptions to phones in the same Wi-Fi (needs an API key).
    lan_access: bool = False

    def validate(self) -> "Settings":
        if self.interval_minutes not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_minutes: допустимо {ALLOWED_INTERVALS}")
        if not 0.5 <= float(self.update_hours) <= 48:
            raise ValueError("update_hours: от 0.5 до 48")
        self.auto_update = bool(self.auto_update)
        self.client_autoconnect = bool(self.client_autoconnect)
        self.lan_access = bool(self.lan_access)
        self.probe_region = str(self.probe_region or "auto").strip()
        if self.probe_region != "auto":
            self.probe_region = self.probe_region.upper()
            if not re.fullmatch(r"[A-Z]{2}", self.probe_region):
                raise ValueError("probe_region: auto или код страны из 2 букв")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(self.client_profile)):
            raise ValueError("client_profile: недопустимое имя профиля")
        return self


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {item.name for item in fields(Settings)}
    try:
        return Settings(**{k: v for k, v in data.items() if k in known}).validate()
    except (TypeError, ValueError):
        return Settings()


def save_settings(settings: Settings, path: Path = SETTINGS_FILE) -> Settings:
    settings.validate()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return settings
