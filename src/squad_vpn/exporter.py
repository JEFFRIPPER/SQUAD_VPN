from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .mihomo import dump_yaml, node_to_mihomo
from .models import ProxyNode, RankedNode


def export_plain(nodes: list[ProxyNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [node.raw_uri for node in nodes if node.raw_uri]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def export_by_protocol(nodes: list[ProxyNode], directory: str | Path) -> list[Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for protocol in sorted({node.protocol for node in nodes}):
        selected = [node for node in nodes if node.protocol == protocol]
        created.append(export_plain(selected, root / protocol))
    return created


def export_mihomo(nodes: list[ProxyNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    proxies = []
    for index, node in enumerate(nodes, start=1):
        name = f"SQUAD-{index:05d}-{node.fingerprint[:8]}"
        converted = node_to_mihomo(node, name)
        if converted is not None:
            proxies.append(converted)
    target.write_text(dump_yaml({"proxies": proxies}), encoding="utf-8")
    return target


def export_health(records: list[RankedNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "fingerprint": item.node.fingerprint,
            "name": item.node.display_name(),
            "protocol": item.node.protocol,
            "alive": item.alive,
            "latency_ms": item.latency_ms,
            "quality_score": item.quality_score,
            "last_checked": item.last_checked,
            "exit_ip": item.exit_ip,
            "country": item.country,
            "asn": item.asn,
            "success_count": item.success_count,
            "failure_count": item.failure_count,
        }
        for item in records
    ]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def export_manifest(records: list[RankedNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    nodes = [item.node for item in records]
    counts = Counter(node.protocol for node in nodes)
    alive = [item for item in records if item.alive is True]
    dead = [item for item in records if item.alive is False]
    unchecked = [item for item in records if item.alive is None]
    latencies = [item.latency_ms for item in alive if item.latency_ms is not None]
    payload = {
        "version": "0.2",
        "updated_at": datetime.now(UTC).isoformat(),
        "total": len(records),
        "alive": len(alive),
        "dead": len(dead),
        "unchecked": len(unchecked),
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "protocols": dict(sorted(counts.items())),
        "best": [
            {
                "fingerprint": item.node.fingerprint,
                "name": item.node.display_name(),
                "protocol": item.node.protocol,
                "score": item.quality_score,
                "latency_ms": item.latency_ms,
                "country": item.country,
                "asn": item.asn,
            }
            for item in alive[:20]
        ],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def export_catalog(nodes: list[ProxyNode], directory: str | Path) -> None:
    """Compatibility export for unvalidated v0.1-style data."""
    root = Path(directory)
    export_plain(nodes, root / "all")
    export_by_protocol(nodes, root / "protocols")
    export_mihomo(nodes, root / "all.yaml")


def export_ranked_catalog(records: list[RankedNode], directory: str | Path) -> None:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    nodes = [item.node for item in records]
    alive_nodes = [item.node for item in records if item.alive is True]

    export_plain(nodes, root / "all")
    export_by_protocol(nodes, root / "protocols")
    export_mihomo(nodes, root / "all.yaml")
    export_plain(alive_nodes, root / "best")
    export_mihomo(alive_nodes, root / "best.yaml")
    export_health(records, root / "health.json")
    export_manifest(records, root / "main.json")
