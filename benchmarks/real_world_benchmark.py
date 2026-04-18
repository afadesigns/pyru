"""End-to-end benchmark harness.

Spawns a local aiohttp server and compares PyRu against `httpx + selectolax`
using identical URL batches. Run with:

    pip install -e ".[benchmarks]"
    python benchmarks/real_world_benchmark.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from competitor import scrape_httpx  # noqa: E402
from pyru import scrape_urls_concurrent  # noqa: E402

DEFAULT_PORT = 8000
DEFAULT_RUNS = 100
DEFAULT_SELECTOR = "p.item"
LATENCY_THRESHOLD_MS = 50


def _summarise(label: str, total: float, latencies: list[float]) -> None:
    floats = [float(x) for x in latencies]
    avg = statistics.fmean(floats)
    jitter = statistics.pstdev(floats) if len(floats) > 1 else 0.0
    slow = sum(1 for x in floats if x > LATENCY_THRESHOLD_MS)
    print(f"\n--- {label} ---")
    print(f"Total time       : {total:.4f} s")
    print(f"Average latency  : {avg:.2f} ms")
    print(f"Jitter (stdev)   : {jitter:.2f} ms")
    print(f"Requests > {LATENCY_THRESHOLD_MS} ms : {slow} ({slow / len(floats) * 100:.2f}%)")


async def _run(runs: int, selector: str, pyru_c: int, httpx_c: int, base_url: str) -> None:
    urls = [f"{base_url}/test_page.html"] * runs

    t0 = time.perf_counter()
    _elements, _errors, pyru_latencies = await scrape_urls_concurrent(urls, selector, pyru_c)
    _summarise("pyru (async Rust)", time.perf_counter() - t0, pyru_latencies)

    t0 = time.perf_counter()
    _, httpx_latencies = await scrape_httpx(urls, selector, httpx_c)
    _summarise("httpx + selectolax", time.perf_counter() - t0, httpx_latencies)


@click.command()
@click.option("--runs", default=DEFAULT_RUNS, show_default=True, help="Pages to fetch.")
@click.option("--selector", default=DEFAULT_SELECTOR, show_default=True)
@click.option("--pyru-concurrency", "-c", default=50, show_default=True)
@click.option("--httpx-concurrency", "-hc", default=50, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True)
def main(
    runs: int,
    selector: str,
    pyru_concurrency: int,
    httpx_concurrency: int,
    port: int,
) -> None:
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "http_server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "BENCH_PORT": str(port)},
    )
    try:
        time.sleep(1.5)
        asyncio.run(
            _run(
                runs,
                selector,
                pyru_concurrency,
                httpx_concurrency,
                f"http://127.0.0.1:{port}",
            )
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
