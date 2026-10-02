from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .models import ProxyNode
from .parser import deduplicate, parse_subscription


DEFAULT_TIMEOUT = 20.0
DEFAULT_CONCURRENCY = 12


def load_sources(path: str | Path) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | None, str | None]:
    async with semaphore:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return url, response.text, None
        except Exception as exc:  # network errors are recorded per source
            return url, None, str(exc)


async def collect_sources(
    urls: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> tuple[list[ProxyNode], dict[str, str]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    errors: dict[str, str] = {}
    nodes: list[ProxyNode] = []

    headers = {"User-Agent": "SQUAD-VPN/0.1"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        results = await asyncio.gather(
            *[_fetch_one(client, url, semaphore) for url in urls]
        )

    for url, text, error in results:
        if error is not None:
            errors[url] = error
            continue
        nodes.extend(parse_subscription(text or "", source=url))

    return deduplicate(nodes), errors
