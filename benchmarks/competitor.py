"""httpx + selectolax reference benchmark."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
from selectolax.parser import HTMLParser

if TYPE_CHECKING:
    from collections.abc import Iterable


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[str, float]:
    start = time.perf_counter()
    response = await client.get(url)
    response.raise_for_status()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return response.text, elapsed_ms


async def scrape_httpx(
    urls: Iterable[str],
    selector: str,
    concurrency: int,
) -> tuple[list[list[str]], list[float]]:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, http2=True) as client:
        pages_and_latencies = await asyncio.gather(*(_fetch(client, url) for url in urls))

    results: list[list[str]] = []
    latencies: list[float] = []
    for page, latency in pages_and_latencies:
        tree = HTMLParser(page)
        results.append([node.text(strip=True) for node in tree.css(selector)])
        latencies.append(latency)
    return results, latencies


def run_httpx_benchmark(
    urls: Iterable[str],
    selector: str,
    concurrency: int = 50,
) -> tuple[list[list[str]], list[float]]:
    return asyncio.run(scrape_httpx(urls, selector, concurrency))
