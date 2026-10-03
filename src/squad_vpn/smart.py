from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

import yaml

from .exporter import export_mihomo, export_plain, remove_stale_files, render_plain
from .models import RankedNode
from .store import NodeStore


DEFAULT_PROFILES_PATH = Path("config/profiles.yaml")


@dataclass(slots=True, frozen=True)
class SmartProfile:
    name: str
    description: str = ""
    min_score: float = 0.0
    min_stability: float = 0.0
    max_latency: float | None = None
    checked_within_hours: int = 12
    seen_within_hours: int = 48
    limit: int = 300
    countries: tuple[str, ...] = field(default_factory=tuple)
    exclude_countries: tuple[str, ...] = field(default_factory=tuple)
    protocols: tuple[str, ...] = field(default_factory=tuple)
    # Probe network: node must be confirmed alive from these regions...
    require_regions: tuple[str, ...] = field(default_factory=tuple)
    # ...and must not be known as blocked there (works elsewhere, fails here).
    avoid_blocked_in: tuple[str, ...] = field(default_factory=tuple)
    # Diversity: duplicates of one server make failover useless.
    per_host: int | None = 1
    per_exit_ip: int | None = 1
    max_asn_share: float | None = 0.34


DEFAULT_PROFILES = (
    SmartProfile(
        "balanced", "Баланс скорости и надёжности",
        min_score=70, min_stability=55, max_latency=500,
    ),
    SmartProfile(
        "fast", "Самые быстрые",
        min_score=60, min_stability=40, max_latency=150, limit=150,
    ),
    SmartProfile(
        "stable", "Стабильно живые много проверок подряд",
        min_score=65, min_stability=75, max_latency=800,
    ),
    SmartProfile(
        "all", "Все живые узлы",
        limit=500, per_host=None, per_exit_ip=None, max_asn_share=None,
    ),
)

# Used for per-country and per-protocol subscriptions.
GROUP_PROFILE = SmartProfile("group", limit=300)

_TUPLE_FIELDS = {
    "countries", "exclude_countries", "protocols", "require_regions", "avoid_blocked_in",
}
_FIELD_NAMES = {item.name for item in fields(SmartProfile)}


def _profile_from_dict(data: dict[str, object]) -> SmartProfile:
    unknown = set(data) - _FIELD_NAMES
    if unknown:
        raise ValueError(f"Неизвестные поля профиля: {', '.join(sorted(unknown))}")
    if not data.get("name"):
        raise ValueError("У профиля нет name")
    values: dict[str, object] = {}
    for key, value in data.items():
        if key in _TUPLE_FIELDS:
            items = value if isinstance(value, list) else [value] if value else []
            values[key] = tuple(str(item).strip() for item in items if str(item).strip())
        else:
            values[key] = value
    profile = SmartProfile(**values)  # type: ignore[arg-type]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", profile.name):
        raise ValueError(f"Недопустимое имя профиля: {profile.name}")
    return profile


def load_profiles(path: str | Path | None = DEFAULT_PROFILES_PATH) -> tuple[SmartProfile, ...]:
    """Profiles from YAML, or the built-in defaults when the file is absent."""
    if path is None or not Path(path).exists():
        return DEFAULT_PROFILES
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = data.get("profiles", data) if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: нужен непустой список profiles")
    profiles = tuple(_profile_from_dict(dict(item)) for item in entries)
    names = [item.name for item in profiles]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: имена профилей повторяются")
    return profiles


def diversify(
    records: list[RankedNode],
    limit: int,
    *,
    per_host: int | None = 1,
    per_exit_ip: int | None = 1,
    max_asn_share: float | None = None,
) -> list[RankedNode]:
    """Take the best ``limit`` nodes, skipping near-duplicates.

    ``records`` must already be ranked. A node is skipped when its server
    host, exit IP or ASN already has its quota, so the subscription spreads
    over independent servers and networks.
    """
    asn_cap = (
        None if max_asn_share is None else max(2, math.ceil(limit * max_asn_share))
    )
    counts: dict[tuple[str, str], int] = {}
    selected: list[RankedNode] = []
    for item in records:
        if len(selected) >= limit:
            break
        keys: list[tuple[tuple[str, str], int]] = []
        if per_host is not None:
            keys.append((("host", item.node.host.lower()), per_host))
        if per_exit_ip is not None and item.exit_ip:
            keys.append((("ip", item.exit_ip), per_exit_ip))
        if asn_cap is not None and item.asn:
            keys.append((("asn", item.asn.split()[0]), asn_cap))
        if any(counts.get(key, 0) >= cap for key, cap in keys):
            continue
        for key, _ in keys:
            counts[key] = counts.get(key, 0) + 1
        selected.append(item)
    return selected


def select_profile(store: NodeStore, profile: SmartProfile) -> list[RankedNode]:
    """Ranked, filtered and diversified nodes for one profile."""
    single_country = profile.countries[0] if len(profile.countries) == 1 else None
    single_protocol = profile.protocols[0] if len(profile.protocols) == 1 else None
    # With required regions, liveness comes from those regions' probes,
    # not from this machine's own checks (a node may work only from there).
    by_region = bool(profile.require_regions)
    records = store.list_ranked(
        alive_only=not by_region,
        min_score=profile.min_score,
        min_stability=profile.min_stability,
        max_latency=None if by_region else profile.max_latency,
        country=single_country,
        protocol=single_protocol,
        checked_within_hours=None if by_region else profile.checked_within_hours,
        seen_within_hours=profile.seen_within_hours,
    )
    countries = {item.upper() for item in profile.countries}
    excluded = {item.upper() for item in profile.exclude_countries}
    protocols = {item.lower() for item in profile.protocols}
    filtered = [
        item for item in records
        if (not countries or (item.country or "").upper() in countries)
        and (item.country or "").upper() not in excluded
        and (not protocols or item.node.protocol.lower() in protocols)
        and all(item.region_status(region) == "ok" for region in profile.require_regions)
        and not any(item.region_status(region) == "blocked" for region in profile.avoid_blocked_in)
    ]
    if by_region:
        # Rank and cap by the latency measured from the required region itself.
        region = profile.require_regions[0].upper()

        def region_latency(item: RankedNode) -> float:
            value = item.regions.get(region, {}).get("latency_ms")
            return float(value) if value is not None else 1e9  # type: ignore[arg-type]

        if profile.max_latency is not None:
            filtered = [i for i in filtered if region_latency(i) <= profile.max_latency]
        filtered.sort(key=lambda item: (region_latency(item), -item.quality_score))
    return diversify(
        filtered,
        profile.limit,
        per_host=profile.per_host,
        per_exit_ip=profile.per_exit_ip,
        max_asn_share=profile.max_asn_share,
    )


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_name(value: str) -> str:
    """Make a value from external data safe to use as a file name."""
    return _SAFE_NAME.sub("_", value.strip()).strip("_")[:64]


def _export_pair(records: list[RankedNode], base: Path, title: str) -> dict[str, object]:
    nodes = [item.node for item in records]
    export_plain(nodes, base)
    export_mihomo(nodes, Path(str(base) + ".yaml"), title=title)
    # Most mobile clients (v2rayNG, Hiddify, INCY…) expect base64 subscriptions.
    Path(str(base) + ".b64").write_text(
        base64.b64encode(render_plain(nodes).encode("utf-8")).decode("ascii"),
        encoding="utf-8",
    )
    return {
        "count": len(records),
        "plain": base.name,
        "base64": base.name + ".b64",
        "mihomo": base.name + ".yaml",
    }


def export_smart_catalog(
    store: NodeStore,
    directory: str | Path,
    profiles: tuple[SmartProfile, ...] | None = None,
) -> dict[str, object]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    profiles = DEFAULT_PROFILES if profiles is None else profiles
    index: dict[str, object] = {"profiles": {}, "countries": {}, "protocols": {}}

    for profile in profiles:
        records = select_profile(store, profile)
        meta = _export_pair(records, root / profile.name, f"SQUAD {profile.name}")
        meta["criteria"] = asdict(profile)
        index["profiles"][profile.name] = meta  # type: ignore[index]

    fresh = store.list_ranked(
        alive_only=True,
        checked_within_hours=GROUP_PROFILE.checked_within_hours,
        seen_within_hours=GROUP_PROFILE.seen_within_hours,
    )
    by_country: dict[str, list[RankedNode]] = {}
    by_protocol: dict[str, list[RankedNode]] = {}
    for item in fresh:
        country = _safe_name((item.country or "").upper())
        if country:
            by_country.setdefault(country, []).append(item)
        protocol = _safe_name(item.node.protocol.lower())
        if protocol:
            by_protocol.setdefault(protocol, []).append(item)

    for key, groups, folder in (
        ("countries", by_country, root / "country"),
        ("protocols", by_protocol, root / "protocol"),
    ):
        keep: set[str] = set()
        for name in sorted(groups):
            records = diversify(
                groups[name],
                GROUP_PROFILE.limit,
                per_host=GROUP_PROFILE.per_host,
                per_exit_ip=GROUP_PROFILE.per_exit_ip,
                max_asn_share=GROUP_PROFILE.max_asn_share,
            )
            index[key][name] = _export_pair(records, folder / name, f"SQUAD {name}")  # type: ignore[index]
            keep.update({name, name + ".yaml", name + ".b64"})
        remove_stale_files(folder, keep)

    (root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index


def export_custom_subscription(
    store: NodeStore,
    path: str | Path,
    *,
    min_score: float = 0.0,
    min_stability: float = 0.0,
    max_latency: float | None = None,
    country: str | None = None,
    protocol: str | None = None,
    checked_within_hours: int = 12,
    seen_within_hours: int = 48,
    limit: int = 300,
) -> list[RankedNode]:
    profile = replace(
        GROUP_PROFILE,
        name="custom",
        min_score=min_score,
        min_stability=min_stability,
        max_latency=max_latency,
        countries=(country,) if country else (),
        protocols=(protocol,) if protocol else (),
        checked_within_hours=checked_within_hours,
        seen_within_hours=seen_within_hours,
        limit=limit,
    )
    records = select_profile(store, profile)
    _export_pair(records, Path(path), "SQUAD custom")
    return records
