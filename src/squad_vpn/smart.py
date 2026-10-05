from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

import yaml

from .branding import COUNTRY_NAMES, DEFAULT_BRANDING_PATH, Branding, load_branding
from .exporter import remove_stale_files, render_mihomo, render_plain
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
    # Only transports that look like ordinary HTTPS (TLS/Reality/QUIC):
    # plain Shadowsocks and unencrypted VMess/VLESS are cut by DPI in Russia.
    require_tls: bool = False
    # Minimum number of successful checks: one lucky ping is not enough.
    min_checks: int = 0
    # Nodes confirmed alive from these regions go first.
    prefer_regions: tuple[str, ...] = field(default_factory=tuple)
    # Then nodes from sources with these tags (config/sources.yaml), e.g.
    # ru-checked: collections their authors test from Russia.
    prefer_tags: tuple[str, ...] = field(default_factory=tuple)
    # Exit networks to put last (hosting providers throttled in Russia).
    deprioritize_asns: tuple[str, ...] = field(default_factory=tuple)
    # Throughput of the download check: nodes measured slower are dropped
    # (not yet measured ones stay), and "speed" ranks by it.
    min_speed_kbps: float = 0.0
    sort_by: str = "score"
    # Only nodes from curated white-list collections (sources tagged
    # "whitelist"), see _whitelisted.
    whitelist: bool = False
    # False: a node does not have to pass our own check (servers in Russia
    # often drop probes from abroad; the collection's author checks them from
    # Russia). Freshness then comes from seen_within_hours. Alive ones first.
    require_alive: bool = True
    # Diversity: duplicates of one server make failover useless.
    per_host: int | None = 1
    per_exit_ip: int | None = 1
    max_asn_share: float | None = 0.34


DEFAULT_PROFILES = (
    SmartProfile(
        "top", "10 самых надёжных — начни с неё",
        min_score=75, min_stability=80, min_checks=4, max_latency=400, limit=10,
        require_tls=True, max_asn_share=0.2,
    ),
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
GROUP_PROFILE = SmartProfile("group", limit=50)

_TUPLE_FIELDS = {
    "countries", "exclude_countries", "protocols", "require_regions", "avoid_blocked_in",
    "prefer_regions", "deprioritize_asns", "prefer_tags",
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


def is_masked(item: RankedNode) -> bool:
    """True when the node's traffic looks like TLS/QUIC rather than a raw tunnel."""
    node = item.node
    protocol = node.protocol.lower()
    params = {key.lower(): str(value).lower() for key, value in node.params.items()}
    if protocol in {"hysteria2", "hy2"}:
        return True
    if protocol == "trojan":
        return params.get("security", "tls") not in {"none", "false", ""}
    if protocol == "vless":
        return params.get("security", "") in {"tls", "reality", "xtls"}
    if protocol == "vmess":
        return (params.get("tls") or params.get("security") or "") in {"tls", "1", "true"}
    return False


def _asn_number(asn: str | None) -> str:
    return (asn or "").split()[0].upper() if asn else ""


DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
def sources_with_tags(tags: tuple[str, ...], path: Path = DEFAULT_SOURCES_PATH) -> set[str]:
    """Enabled sources carrying any of ``tags``: names and URLs (nodes store
    the URL they were collected from in ``source``)."""
    from .sources import load_source_specs

    try:
        specs = load_source_specs(path)
    except (OSError, ValueError):
        return set()
    wanted = set(tags)
    return {
        value for spec in specs if wanted & set(spec.tags) for value in (spec.name, spec.url)
    }


def _source_authors(tag: str, path: Path = DEFAULT_SOURCES_PATH) -> dict[str, str]:
    """Enabled sources carrying ``tag``: name/URL -> author (the GitHub owner,
    or the host for other sites). Several files of one author count once."""
    from urllib.parse import urlsplit

    from .sources import load_source_specs

    try:
        specs = load_source_specs(path)
    except (OSError, ValueError):
        return {}
    authors: dict[str, str] = {}
    for spec in specs:
        if tag not in spec.tags:
            continue
        url = urlsplit(spec.url)
        parts = [part for part in url.path.split("/") if part]
        github = url.hostname in {"raw.githubusercontent.com", "github.com"}
        author = (parts[0] if github and parts else url.hostname or spec.name).lower()
        authors[spec.name] = authors[spec.url] = author
    return authors


def _whitelisted(records: list[RankedNode], excluded: set[str] = frozenset()) -> list[RankedNode]:
    """Nodes from curated white-list collections (sources tagged "whitelist").

    Matching arbitrary nodes against public subnet lists does not work: the
    lists are aggregated into wide ranges and operators now check IP and
    domain together. Our own check runs from abroad and says little about
    Russian mobile networks, so the strongest signal is agreement: a server
    published by several independent authors (each checks it from Russia on
    their own operators) goes first. Then nodes our check confirmed, then
    those whose server and domain are both on the public lists.

    Authors mark the exit country with a flag; one server often carries
    several labels, so an exit country in ``excluded`` (usually RU, where
    Telegram stays blocked) named by any label drops the whole server.
    """
    from .whitelist import load_index

    authors = _source_authors("whitelist")
    kept = [
        item for item in records
        if item.node.source in authors and not item.node.host.startswith(("0.", "127."))
    ]

    from .branding import country_from_flag

    def exit_country(item: RankedNode) -> str:
        return (item.country or country_from_flag(item.node.name) or "").upper()

    by_host: dict[str, set[str]] = {}
    exits: dict[str, set[str]] = {}
    for item in kept:
        host = item.node.host.lower()
        by_host.setdefault(host, set()).add(authors[item.node.source])
        exits.setdefault(host, set()).add(exit_country(item))
    kept = [item for item in kept if not exits[item.node.host.lower()] & excluded]
    index = load_index()
    if not index.empty:
        index.resolve({item.node.host for item in kept})

    def order(item: RankedNode) -> tuple[int, int, int, int, int]:
        both = not index.empty and index.status(item) == "both"
        host = item.node.host.lower()
        # An exit in Russia keeps Discord/YouTube blocked: such relays go last,
        # and servers whose exit nobody named go after the named ones.
        exit_ru = "RU" in exits[host]
        unknown = exits[host] <= {""}
        agreed = len(by_host[host])
        return (
            1 if exit_ru else 0, 1 if unknown else 0, -agreed,
            0 if item.alive else 1, 0 if both else 1,
        )

    kept.sort(key=order)  # stable: keeps the ranking inside each group
    return kept


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
    own_check = not by_region and profile.require_alive
    records = store.list_ranked(
        alive_only=own_check,
        min_score=profile.min_score,
        min_stability=profile.min_stability,
        max_latency=profile.max_latency if own_check else None,
        country=single_country,
        protocol=single_protocol,
        checked_within_hours=profile.checked_within_hours if own_check else None,
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
        and (not profile.require_tls or is_masked(item))
        and item.success_count >= profile.min_checks
    ]
    if profile.min_speed_kbps:
        filtered = [
            item for item in filtered
            if item.speed_kbps is None or item.speed_kbps >= profile.min_speed_kbps
        ]
    if profile.sort_by == "speed":
        # Measured nodes by speed first; unmeasured keep their score order after.
        filtered.sort(key=lambda item: -(item.speed_kbps or 0.0))
    if profile.whitelist:
        filtered = _whitelisted(filtered, excluded)
    if profile.prefer_regions or profile.deprioritize_asns or profile.prefer_tags:
        avoided = {_asn_number(value) for value in profile.deprioritize_asns}
        preferred = [region.upper() for region in profile.prefer_regions]
        tagged = sources_with_tags(profile.prefer_tags) if profile.prefer_tags else set()

        def preference(item: RankedNode) -> tuple[int, int, int]:
            confirmed = any(item.region_status(region) == "ok" for region in preferred)
            return (
                0 if confirmed else 1,
                0 if item.node.source in tagged else 1,
                1 if _asn_number(item.asn) in avoided else 0,
            )

        # Stable sort: within each group the quality ranking is kept.
        filtered.sort(key=preference)
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


@dataclass(slots=True, frozen=True)
class RenderedSubscription:
    plain: str
    base64: str
    mihomo: str
    headers: dict[str, str]


def render_subscription(
    records: list[RankedNode],
    branding: Branding,
    name: str,
    description: str = "",
) -> RenderedSubscription:
    """One subscription in all formats, with the owners' title and node names."""
    nodes = branding.apply(records)
    header = branding.body_header(name, description, len(nodes))
    plain = header + render_plain(nodes)
    # Most mobile clients (v2rayNG, Hiddify, INCY…) expect base64 subscriptions.
    encoded = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    mihomo = header + render_mihomo(nodes, branding.brand, use_names=bool(branding.node_name))
    return RenderedSubscription(
        plain, encoded, mihomo, branding.metadata(name, description, len(nodes))
    )


def _export_pair(
    records: list[RankedNode],
    base: Path,
    branding: Branding,
    name: str,
    description: str = "",
) -> dict[str, object]:
    rendered = render_subscription(records, branding, name, description)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(rendered.plain, encoding="utf-8")
    Path(str(base) + ".b64").write_text(rendered.base64, encoding="utf-8")
    Path(str(base) + ".yaml").write_text(rendered.mihomo, encoding="utf-8")
    return {
        "count": len(records),
        "title": branding.title_for(name, description),
        "plain": base.name,
        "base64": base.name + ".b64",
        "mihomo": base.name + ".yaml",
    }


def export_smart_catalog(
    store: NodeStore,
    directory: str | Path,
    profiles: tuple[SmartProfile, ...] | None = None,
    branding: Branding | None = None,
) -> dict[str, object]:
    root = Path(directory)
    branding = load_branding(DEFAULT_BRANDING_PATH) if branding is None else branding
    root.mkdir(parents=True, exist_ok=True)
    profiles = DEFAULT_PROFILES if profiles is None else profiles
    index: dict[str, object] = {"profiles": {}, "countries": {}, "protocols": {}}

    for profile in profiles:
        records = select_profile(store, profile)
        meta = _export_pair(records, root / profile.name, branding, profile.name, profile.description)
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
            label = COUNTRY_NAMES.get(name, name) if key == "countries" else name.upper()
            index[key][name] = _export_pair(records, folder / name, branding, name, label)  # type: ignore[index]
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
    _export_pair(records, Path(path), load_branding(DEFAULT_BRANDING_PATH), "custom", "Своя подборка")
    return records
