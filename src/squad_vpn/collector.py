from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .models import ProxyNode
from .parser import deduplicate, parse_subscription
from .sources import SourceReport, SourceSpec, SourceTimer, load_source_specs


DEFAULT_TIMEOUT = 20.0
DEFAULT_CONCURRENCY = 12


def load_sources(path: str | Path) -> list[str]:
    """Backward-compatible URL-only loader."""
    return [spec.url for spec in load_source_specs(path)]


def _spread_limit(nodes: list[ProxyNode], limit: int | None) -> list[ProxyNode]:
    if limit is None or limit >= len(nodes):
        return nodes
    if limit <= 0:
        return []
    step = len(nodes) / limit
    return [nodes[min(int(index * step), len(nodes) - 1)] for index in range(limit)]


async def _fetch_spec(
    client: httpx.AsyncClient,
    spec: SourceSpec,
    semaphore: asyncio.Semaphore,
) -> tuple[list[ProxyNode], SourceReport]:
    timer = SourceTimer()
    async with semaphore:
        try:
            response = await client.get(spec.url, follow_redirects=True)
            response.raise_for_status()
            parsed = parse_subscription(response.text, source=spec.url)
            selected = _spread_limit(parsed, spec.max_nodes)
            report = SourceReport(
                source=spec,
                ok=True,
                nodes_found=len(parsed),
                nodes_selected=len(selected),
                duration_ms=timer.elapsed_ms(),
            )
            return selected, report
        except Exception as exc:  # source failures must not abort the whole cycle
            return [], SourceReport(
                source=spec,
                ok=False,
                duration_ms=timer.elapsed_ms(),
                error=str(exc)[:1000],
            )


async def collect_source_specs(
    specs: list[SourceSpec],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> tuple[list[ProxyNode], list[SourceReport]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    headers = {"User-Agent": "SQUAD-VPN/0.9"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, trust_env=False) as client:
        results = await asyncio.gather(
            *[_fetch_spec(client, spec, semaphore) for spec in specs]
        )

    nodes: list[ProxyNode] = []
    reports: list[SourceReport] = []
    for batch, report in results:
        nodes.extend(batch)
        reports.append(report)
    return deduplicate(nodes), reports


async def collect_sources(
    urls: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> tuple[list[ProxyNode], dict[str, str]]:
    """Backward-compatible v0.2 API used by external callers/tests."""
    specs = [SourceSpec(name=f"source-{i}", url=url) for i, url in enumerate(urls, 1)]
    nodes, reports = await collect_source_specs(
        specs, timeout=timeout, concurrency=concurrency
    )
    errors = {
        report.source.url: report.error or "unknown error"
        for report in reports
        if not report.ok
    }
    return nodes, errors
