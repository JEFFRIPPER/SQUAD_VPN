"""How subscriptions look in the user's VPN app: title, description, node names.

Everything comes from ``config/branding.yaml``, which the project owners edit
(on GitHub, without a computer); the next hourly update publishes it.

Clients read the metadata from HTTP headers (``/sub`` of the local server)
or from ``#key: value`` lines at the top of the subscription body (files on
GitHub, where headers cannot be set). Supported by Happ, Hiddify, v2RayTun,
INCY, Streisand and others; clients that do not know a line skip it.
Non-ASCII text is sent as ``base64:<...>``, the common convention.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

import yaml

from .models import ProxyNode, RankedNode


DEFAULT_BRANDING_PATH = Path("config/branding.yaml")

COUNTRY_NAMES = {
    "AE": "ОАЭ", "AM": "Армения", "AT": "Австрия", "AU": "Австралия", "BE": "Бельгия",
    "BG": "Болгария", "BR": "Бразилия", "BY": "Беларусь", "CA": "Канада", "CH": "Швейцария",
    "CN": "Китай", "CY": "Кипр", "CZ": "Чехия", "DE": "Германия", "DK": "Дания",
    "EE": "Эстония", "ES": "Испания", "FI": "Финляндия", "FR": "Франция",
    "GB": "Великобритания", "GE": "Грузия", "GR": "Греция", "HK": "Гонконг",
    "HU": "Венгрия", "IE": "Ирландия", "IL": "Израиль", "IN": "Индия", "IR": "Иран",
    "IS": "Исландия", "IT": "Италия", "JP": "Япония", "KR": "Корея", "KZ": "Казахстан",
    "LT": "Литва", "LU": "Люксембург", "LV": "Латвия", "MD": "Молдова", "MX": "Мексика",
    "NL": "Нидерланды", "NO": "Норвегия", "PL": "Польша", "PT": "Португалия",
    "RO": "Румыния", "RS": "Сербия", "RU": "Россия", "SE": "Швеция", "SG": "Сингапур",
    "SK": "Словакия", "TR": "Турция", "TW": "Тайвань", "UA": "Украина", "US": "США",
    "VN": "Вьетнам", "ZA": "ЮАР",
}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flag(code: str | None) -> str:
    """🇩🇪 for "DE"; a globe when the country is unknown."""
    code = (code or "").upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)


def encode_value(value: str) -> str:
    """ASCII stays as is, anything else becomes ``base64:...`` (header-safe)."""
    value = " ".join(str(value).split())  # no line breaks inside a header
    if value.isascii():
        return value
    return "base64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")


def _fill(template: str, values: dict[str, object]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


@dataclass(slots=True, frozen=True)
class ProfileBranding:
    title: str = ""
    announce: str = ""


@dataclass(slots=True, frozen=True)
class Branding:
    brand: str = "SQUAD VPN"
    # {brand}, {name} (profile id), {description} (from profiles.yaml)
    title: str = "{brand} · {description}"
    announce: str = ""
    update_interval_hours: int = 1
    support_url: str = ""
    web_page_url: str = ""
    # {flag}, {country}, {code}, {n}, {protocol}, {brand}; empty = keep source names
    node_name: str = "{flag} {country} {n}"
    profiles: dict[str, ProfileBranding] = field(default_factory=dict)

    def title_for(self, name: str, description: str = "") -> str:
        custom = self.profiles.get(name, ProfileBranding())
        template = custom.title or self.title
        return _fill(template, {
            "brand": self.brand, "name": name, "description": description or name,
        }).strip()

    def announce_for(self, name: str, count: int | None = None) -> str:
        custom = self.profiles.get(name, ProfileBranding())
        template = custom.announce or self.announce
        return _fill(template, {"brand": self.brand, "name": name, "count": count if count is not None else "—"}).strip()

    def metadata(self, name: str, description: str = "", count: int | None = None) -> dict[str, str]:
        """Header names and values, already encoded."""
        data = {
            "profile-title": self.title_for(name, description),
            "profile-update-interval": str(max(1, int(self.update_interval_hours))),
            "announce": self.announce_for(name, count),
            "support-url": self.support_url,
            "profile-web-page-url": self.web_page_url,
        }
        return {key: encode_value(value) for key, value in data.items() if value}

    def body_header(self, name: str, description: str = "", count: int | None = None) -> str:
        """The same metadata as ``#key: value`` lines for subscription files."""
        return "".join(
            f"#{key}: {value}\n" for key, value in self.metadata(name, description, count).items()
        )

    def node_names(self, records: list[RankedNode]) -> list[str]:
        """Display names in subscription order, unique within the list."""
        if not self.node_name:
            return [item.node.display_name() for item in records]
        per_country: dict[str, int] = {}
        names: list[str] = []
        seen: set[str] = set()
        for item in records:
            code = (item.country or "").upper()
            per_country[code] = per_country.get(code, 0) + 1
            name = " ".join(_fill(self.node_name, {
                "flag": flag(code),
                "country": COUNTRY_NAMES.get(code, code or "Мир"),
                "code": code or "??",
                "n": per_country[code],
                "protocol": item.node.protocol.upper(),
                "brand": self.brand,
            }).split())
            base, suffix = name, 2
            while name in seen:
                name = f"{base} ({suffix})"
                suffix += 1
            seen.add(name)
            names.append(name)
        return names

    def apply(self, records: list[RankedNode]) -> list[ProxyNode]:
        """Nodes renamed for display; servers and credentials are untouched."""
        if not self.node_name:
            return [item.node for item in records]
        return [
            replace(item.node, name=name, raw_uri=rename_uri(item.node, name))
            for item, name in zip(records, self.node_names(records), strict=True)
        ]


def rename_uri(node: ProxyNode, name: str) -> str:
    """The node's share link with a new display name (``#fragment`` / vmess ``ps``)."""
    uri = node.raw_uri
    if not uri:
        return uri
    if node.protocol == "vmess":
        scheme, _, payload = uri.partition("://")
        payload = payload.split("#", 1)[0]
        try:
            padded = payload + "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if not isinstance(data, dict):
                return uri
        except (ValueError, UnicodeDecodeError):
            return uri
        data["ps"] = name
        encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return f"{scheme}://{encoded}"
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")


def _profile_entries(data: object) -> dict[str, ProfileBranding]:
    if not isinstance(data, dict):
        return {}
    result = {}
    for name, value in data.items():
        if isinstance(value, dict):
            result[str(name)] = ProfileBranding(
                title=str(value.get("title") or ""), announce=str(value.get("announce") or "")
            )
    return result


_CACHE: dict[Path, tuple[float, Branding]] = {}


def load_branding(path: str | Path | None = DEFAULT_BRANDING_PATH) -> Branding:
    """Branding from YAML (re-read when the file changes), defaults otherwise."""
    if path is None:
        return Branding()
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return Branding()
    cached = _CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: ожидается словарь настроек")
    defaults = Branding()
    branding = Branding(
        brand=str(data.get("brand") or defaults.brand),
        title=str(data.get("title") or defaults.title),
        announce=str(data.get("announce") or ""),
        update_interval_hours=int(data.get("update_interval_hours") or defaults.update_interval_hours),
        support_url=str(data.get("support_url") or ""),
        web_page_url=str(data.get("web_page_url") or ""),
        node_name=str(data["node_name"] if data.get("node_name") is not None else defaults.node_name),
        profiles=_profile_entries(data.get("profiles")),
    )
    _CACHE[path] = (mtime, branding)
    return branding
