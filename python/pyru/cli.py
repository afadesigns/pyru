"""Argparse-based CLI wrapper around the PyRu Rust core.

Zero third-party Python runtime dependencies: only the standard library plus
the native `pyru._native` extension. That's deliberate — every extra dep is a
supply-chain surface we'd rather not have, and it forces us to own the UX.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from . import __version__
from ._native import scrape_urls_concurrent

_SAFE_SCHEMES = frozenset({"http", "https"})


def _validate_urls(urls: Iterable[str]) -> list[str]:
    validated: list[str] = []
    for raw in urls:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in _SAFE_SCHEMES or not parts.netloc:
            raise ValueError(f"URL must use http(s) and include a host: {raw!r}")
        validated.append(raw)
    return validated


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:  # pragma: no cover - argparse handles display
        raise argparse.ArgumentTypeError(f"must be an integer, got {value!r}") from exc
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _concurrency(value: str) -> int:
    n = _positive_int(value)
    if n > 10_000:
        raise argparse.ArgumentTypeError(f"must be <= 10000, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyru",
        description="PyRu — a high-throughput async web scraper powered by Rust.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"pyru {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    scrape = subparsers.add_parser(
        "scrape",
        help="Scrape one or more URLs concurrently.",
        description="Scrape one or more URLs concurrently and emit extracted elements.",
    )
    scrape.add_argument("urls", nargs="+", metavar="URL", help="HTTP/HTTPS URL(s) to fetch.")
    scrape.add_argument(
        "-s",
        "--selector",
        required=True,
        help="CSS selector applied to each fetched page.",
    )
    scrape.add_argument(
        "-o",
        "--output",
        choices=("json", "text"),
        default="text",
        help="Output format (default: text).",
    )
    scrape.add_argument(
        "-c",
        "--concurrency",
        type=_concurrency,
        default=50,
        help="Maximum in-flight requests (1-10000, default: 50).",
    )
    scrape.add_argument(
        "-u",
        "--user-agent",
        default=None,
        help="Override the default User-Agent header.",
    )
    scrape.add_argument(
        "--timeout-ms",
        type=_positive_int,
        default=10_000,
        help="Total per-request timeout in milliseconds (default: 10000).",
    )
    scrape.add_argument(
        "--connect-timeout-ms",
        type=_positive_int,
        default=5_000,
        help="TCP/TLS connect timeout in milliseconds (default: 5000).",
    )
    scrape.set_defaults(func=_cmd_scrape)

    return parser


async def _run(
    urls: list[str],
    selector: str,
    output: str,
    concurrency: int,
    user_agent: str | None,
    timeout_ms: int,
    connect_timeout_ms: int,
) -> int:
    results, errors, latencies = await scrape_urls_concurrent(
        urls,
        selector,
        concurrency,
        user_agent,
        timeout_ms,
        connect_timeout_ms,
    )

    exit_code = 0
    for url, elements, err, latency in zip(urls, results, errors, latencies):
        if err:
            exit_code = 1
            print(f"[error] {url} ({latency} ms): {err}", file=sys.stderr)
            continue

        if output == "json":
            print(
                json.dumps(
                    {
                        "url": url,
                        "selector": selector,
                        "latency_ms": latency,
                        "elements": elements,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"\n{url}  ({latency} ms)")
            for element in elements:
                print(f"- {element}")

    return exit_code


def _cmd_scrape(args: argparse.Namespace) -> int:
    try:
        validated = _validate_urls(args.urls)
    except ValueError as exc:
        print(f"pyru scrape: error: {exc}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(
            _run(
                validated,
                args.selector,
                args.output,
                args.concurrency,
                args.user_agent,
                args.timeout_ms,
                args.connect_timeout_ms,
            )
        )
    except (ValueError, RuntimeError) as exc:
        print(f"pyru scrape: error: {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:  # pragma: no cover - argparse enforces subcommand
        parser.print_help(sys.stderr)
        return 2
    return int(func(args))


def cli() -> None:
    """Entry point used by the `pyru` console script."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
