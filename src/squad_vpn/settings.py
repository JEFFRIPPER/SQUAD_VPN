"""User settings changed from the desktop app (``data/settings.json``)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


SETTINGS_FILE = Path("data/settings.json")
ALLOWED_INTERVALS = (15, 30, 60, 120, 180, 360)


@dataclass(slots=True)
class Settings:
    interval_minutes: int = 60
    auto_update: bool = True
    update_hours: float = 3.0

    def validate(self) -> "Settings":
        if self.interval_minutes not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_minutes: допустимо {ALLOWED_INTERVALS}")
        if not 0.5 <= float(self.update_hours) <= 48:
            raise ValueError("update_hours: от 0.5 до 48")
        self.auto_update = bool(self.auto_update)
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
