"""Minimal aiohttp server used by the benchmarks."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parent


async def handle(request: web.Request) -> web.Response:
    del request
    body = (ROOT / "test_page.html").read_text(encoding="utf-8")
    return web.Response(text=body, content_type="text/html")


async def main(host: str, port: int) -> None:
    app = web.Application()
    app.router.add_get("/test_page.html", handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    await asyncio.Future()


if __name__ == "__main__":
    bind_host = os.environ.get("BENCH_HOST", "127.0.0.1")
    bind_port = int(os.environ.get("BENCH_PORT", "8000"))
    try:
        asyncio.run(main(bind_host, bind_port))
    except KeyboardInterrupt:
        sys.exit(0)
