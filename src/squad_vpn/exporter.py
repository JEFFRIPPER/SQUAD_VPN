from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .mihomo import dump_yaml, node_to_mihomo
from .models import ProxyNode, RankedNode


def render_plain(nodes: list[ProxyNode]) -> str:
    lines = [node.raw_uri for node in nodes if node.raw_uri]
    return "\n".join(lines) + ("\n" if lines else "")


def render_mihomo(nodes: list[ProxyNode]) -> str:
    proxies = []
    for index, node in enumerate(nodes, start=1):
        name = f"SQUAD-{index:05d}-{node.fingerprint[:8]}"
        converted = node_to_mihomo(node, name)
        if converted is not None:
            proxies.append(converted)
    return dump_yaml({"proxies": proxies})


def ranked_to_dict(item: RankedNode) -> dict[str, object]:
    """Public view of a ranked node (no credentials or raw URI)."""
    return {
        "fingerprint": item.node.fingerprint,
        "name": item.node.display_name(),
        "protocol": item.node.protocol,
        "host": item.node.host,
        "port": item.node.port,
        "alive": item.alive,
        "latency_ms": item.latency_ms,
        "jitter_ms": item.jitter_ms,
        "recent_success_rate": item.recent_success_rate,
        "stability_score": item.stability_score,
        "quality_score": item.quality_score,
        "last_checked": item.last_checked,
        "last_seen": item.last_seen,
        "exit_ip": item.exit_ip,
        "country": item.country,
        "asn": item.asn,
        "success_count": item.success_count,
        "failure_count": item.failure_count,
        "validation_error": item.validation_error,
    }


def export_plain(nodes: list[ProxyNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_plain(nodes), encoding="utf-8")
    return target


def remove_stale_files(directory: str | Path, keep: set[str]) -> list[Path]:
    """Delete files in ``directory`` whose names are not in ``keep``.

    Without this, a subscription for a protocol/country that vanished would
    keep serving its last (now dead) nodes under a stable URL.
    """
    root = Path(directory)
    removed: list[Path] = []
    if not root.is_dir():
        return removed
    for path in root.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()
            removed.append(path)
    return removed


def export_by_protocol(nodes: list[ProxyNode], directory: str | Path) -> list[Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for protocol in sorted({node.protocol for node in nodes}):
        selected = [node for node in nodes if node.protocol == protocol]
        created.append(export_plain(selected, root / protocol))
    remove_stale_files(root, {path.name for path in created})
    return created


def export_mihomo(nodes: list[ProxyNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_mihomo(nodes), encoding="utf-8")
    return target


def export_health(records: list[RankedNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = []
    for item in records:
        payload.append(
            {
                "fingerprint": item.node.fingerprint,
                "name": item.node.display_name(),
                "protocol": item.node.protocol,
                "alive": item.alive,
                "latency_ms": item.latency_ms,
                "jitter_ms": item.jitter_ms,
                "recent_success_rate": item.recent_success_rate,
                "stability_score": item.stability_score,
                "quality_score": item.quality_score,
                "last_checked": item.last_checked,
                "last_seen": item.last_seen,
                "exit_ip": item.exit_ip,
                "country": item.country,
                "asn": item.asn,
                "success_count": item.success_count,
                "failure_count": item.failure_count,
            }
        )
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
    jitters = [item.jitter_ms for item in alive if item.jitter_ms is not None]
    payload = {
        "version": "0.4",
        "updated_at": datetime.now(UTC).isoformat(),
        "total": len(records),
        "alive": len(alive),
        "dead": len(dead),
        "unchecked": len(unchecked),
        "average_latency_ms": (
            round(sum(latencies) / len(latencies), 2) if latencies else None
        ),
        "average_jitter_ms": (
            round(sum(jitters) / len(jitters), 2) if jitters else None
        ),
        "protocols": dict(sorted(counts.items())),
        "best": [
            {
                "fingerprint": item.node.fingerprint,
                "name": item.node.display_name(),
                "protocol": item.node.protocol,
                "score": item.quality_score,
                "stability": item.stability_score,
                "latency_ms": item.latency_ms,
                "jitter_ms": item.jitter_ms,
                "country": item.country,
                "asn": item.asn,
            }
            for item in alive[:20]
        ],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def export_catalog(nodes: list[ProxyNode], directory: str | Path) -> None:
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


def export_sources(status: list[dict[str, object]], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
