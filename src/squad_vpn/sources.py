from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

import yaml


@dataclass(slots=True, frozen=True)
class SourceSpec:
    name: str
    url: str
    enabled: bool = True
    priority: int = 100
    max_nodes: int | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class SourceReport:
    source: SourceSpec
    ok: bool
    nodes_found: int = 0
    nodes_selected: int = 0
    duration_ms: float = 0.0
    error: str | None = None


def _normalize_entry(item: object, index: int) -> SourceSpec | None:
    if isinstance(item, str):
        return SourceSpec(name=f"source-{index}", url=item)
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    tags = item.get("tags") or []
    return SourceSpec(
        name=str(item.get("name") or f"source-{index}"),
        url=url,
        enabled=bool(item.get("enabled", True)),
        priority=int(item.get("priority", 100)),
        max_nodes=(
            int(item["max_nodes"])
            if item.get("max_nodes") not in (None, "")
            else None
        ),
        tags=tuple(str(tag) for tag in tags),
    )


def load_source_specs(path: str | Path) -> list[SourceSpec]:
    source_path = Path(path)
    if source_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        entries = data.get("sources", data) if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise ValueError("sources.yaml должен содержать список sources")
        specs = [_normalize_entry(item, i) for i, item in enumerate(entries, 1)]
        return sorted(
            (spec for spec in specs if spec and spec.enabled),
            key=lambda spec: (spec.priority, spec.name.lower()),
        )
    lines = source_path.read_text(encoding="utf-8").splitlines()
    result: list[SourceSpec] = []
    for index, line in enumerate(lines, 1):
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        result.append(SourceSpec(name=f"source-{index}", url=url))
    return result


class SourceTimer:
    def __init__(self) -> None:
        self.started = monotonic()

    def elapsed_ms(self) -> float:
        return round((monotonic() - self.started) * 1000.0, 2)
