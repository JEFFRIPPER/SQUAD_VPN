"""Static configuration: ``config/squad.yaml`` with ``SQUAD_*`` overrides.

Things the user changes from the app live in ``data/settings.json``
(see settings.py); this file holds operational limits that rarely change.
Environment variables win: ``SQUAD_<SECTION>_<KEY>``, e.g.
``SQUAD_LOGGING_LEVEL=DEBUG`` or ``SQUAD_BACKUP_KEEP=14``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

import yaml


CONFIG_FILE = Path("config/squad.yaml")


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    max_mb: float = 2.0
    keep: int = 5


@dataclass(slots=True)
class RateLimitConfig:
    sub_per_minute: int = 30
    api_per_minute: int = 120
    auth_failures_per_minute: int = 10
    block_minutes: int = 10


@dataclass(slots=True)
class CacheConfig:
    sub_seconds: int = 60
    stats_seconds: int = 10


@dataclass(slots=True)
class BackupConfig:
    every_hours: float = 24.0
    keep: int = 7


@dataclass(slots=True)
class AppConfig:
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)


def _coerce(value: object, current: object) -> object:
    if isinstance(current, bool):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(value)  # type: ignore[call-overload]
    if isinstance(current, float):
        return float(value)  # type: ignore[arg-type]
    return str(value)


def load_config(path: str | Path = CONFIG_FILE, env: dict[str, str] | None = None) -> AppConfig:
    env = dict(os.environ) if env is None else env
    data: dict[str, object] = {}
    try:
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, yaml.YAMLError):
        data = {}
    config = AppConfig()
    for section_field in fields(config):
        section = getattr(config, section_field.name)
        if not is_dataclass(section):
            continue
        raw = data.get(section_field.name)
        values = raw if isinstance(raw, dict) else {}
        for item in fields(section):
            current = getattr(section, item.name)
            env_key = f"SQUAD_{section_field.name}_{item.name}".upper()
            value = env.get(env_key, values.get(item.name))
            if value is None:
                continue
            try:
                setattr(section, item.name, _coerce(value, current))
            except (TypeError, ValueError):
                continue  # a bad value keeps the default instead of crashing
    config.logging.level = config.logging.level.upper()
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        config.logging.level = "INFO"
    return config
