from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .exporter import export_mihomo, export_plain, remove_stale_files
from .models import RankedNode
from .store import NodeStore


@dataclass(slots=True, frozen=True)
class SmartProfile:
    name: str
    min_score: float = 0.0
    min_stability: float = 0.0
    max_latency: float | None = None
    checked_within_hours: int = 12
    seen_within_hours: int = 48
    limit: int = 300


DEFAULT_PROFILES = (
    SmartProfile("balanced", min_score=70, min_stability=55, max_latency=500),
    SmartProfile("fast", min_score=60, min_stability=40, max_latency=150, limit=150),
    SmartProfile("stable", min_score=65, min_stability=75, max_latency=800),
)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_name(value: str) -> str:
    """Make a value from external data safe to use as a file name."""
    return _SAFE_NAME.sub("_", value.strip()).strip("_")[:64]


def _export_pair(records: list[RankedNode], base: Path) -> dict[str, object]:
    nodes = [item.node for item in records]
    export_plain(nodes, base)
    export_mihomo(nodes, Path(str(base) + ".yaml"))
    return {
        "count": len(records),
        "plain": base.name,
        "mihomo": base.name + ".yaml",
    }


def export_smart_catalog(
    store: NodeStore,
    directory: str | Path,
    profiles: tuple[SmartProfile, ...] = DEFAULT_PROFILES,
) -> dict[str, object]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    index: dict[str, object] = {"profiles": {}, "countries": {}, "protocols": {}}

    for profile in profiles:
        records = store.list_ranked(
            alive_only=True,
            min_score=profile.min_score,
            min_stability=profile.min_stability,
            max_latency=profile.max_latency,
            checked_within_hours=profile.checked_within_hours,
            seen_within_hours=profile.seen_within_hours,
            limit=profile.limit,
        )
        meta = _export_pair(records, root / profile.name)
        meta["criteria"] = asdict(profile)
        index["profiles"][profile.name] = meta

    fresh = store.list_ranked(
        alive_only=True,
        checked_within_hours=12,
        seen_within_hours=48,
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
            index[key][name] = _export_pair(groups[name], folder / name)
            keep.update({name, name + ".yaml"})
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
    records = store.list_ranked(
        alive_only=True,
        min_score=min_score,
        min_stability=min_stability,
        max_latency=max_latency,
        country=country,
        protocol=protocol,
        checked_within_hours=checked_within_hours,
        seen_within_hours=seen_within_hours,
        limit=limit,
    )
    target = Path(path)
    _export_pair(records, target)
    return records
