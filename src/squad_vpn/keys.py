"""API keys with scopes, stored as hashes in ``data/api_keys.json``.

Scopes, from least to most powerful:

- ``sub``   — only subscriptions (``/sub``): safe to put into a phone;
- ``read``  — subscriptions and read-only API (stats, nodes, probes...);
- ``admin`` — everything a token from the network may do.

Control actions (VPN connect, settings, restart...) are additionally
allowed only from this computer, whatever the key.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


KEYS_FILE = Path("data/api_keys.json")
SCOPES = {"sub": 1, "read": 2, "admin": 3}
_NAME = re.compile(r"[\w .-]{1,40}", re.UNICODE)


@dataclass(slots=True)
class ApiKey:
    name: str
    scope: str
    hash: str
    created_at: str
    last_used: str | None = None
    prefix: str = ""

    def public(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items() if k != "hash"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class KeyStore:
    def __init__(self, path: Path = KEYS_FILE) -> None:
        self.path = Path(path)

    def load(self) -> list[ApiKey]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [ApiKey(**item) for item in data]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, keys: list[ApiKey]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(k) for k in keys], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def create(self, name: str, scope: str) -> tuple[ApiKey, str]:
        """Return the stored key and the token (shown to the user only once)."""
        name = name.strip()
        if not _NAME.fullmatch(name):
            raise ValueError("Имя ключа: 1–40 букв, цифр, пробелов, точек или дефисов")
        if scope not in SCOPES:
            raise ValueError(f"Права ключа: {', '.join(SCOPES)}")
        keys = self.load()
        if any(k.name == name for k in keys):
            raise ValueError("Ключ с таким именем уже есть")
        token = "sq_" + secrets.token_urlsafe(24)
        key = ApiKey(
            name=name,
            scope=scope,
            hash=_hash(token),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            prefix=token[:7],
        )
        self._save([*keys, key])
        return key, token

    def revoke(self, name: str) -> bool:
        keys = self.load()
        kept = [k for k in keys if k.name != name]
        if len(kept) == len(keys):
            return False
        self._save(kept)
        return True

    def match(self, token: str) -> ApiKey | None:
        if not token:
            return None
        digest = _hash(token)
        keys = self.load()
        for key in keys:
            if secrets.compare_digest(key.hash, digest):
                key.last_used = datetime.now(UTC).isoformat(timespec="seconds")
                try:
                    self._save(keys)
                except OSError:
                    pass
                return key
        return None


def allows(scope: str, needed: str) -> bool:
    return SCOPES.get(scope, 0) >= SCOPES[needed]
