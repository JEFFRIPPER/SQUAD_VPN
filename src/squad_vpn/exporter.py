from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .models import ProxyNode


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
    protocols = sorted({node.protocol for node in nodes})
    for protocol in protocols:
        selected = [node for node in nodes if node.protocol == protocol]
        created.append(export_plain(selected, root / protocol))
    return created


def export_manifest(nodes: list[ProxyNode], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter(node.protocol for node in nodes)
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "total": len(nodes),
        "protocols": dict(sorted(counts.items())),
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
    export_manifest(nodes, root / "main.json")
