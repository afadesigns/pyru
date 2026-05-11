"""Argparse-based CLI wrapper around the PyRu Rust core.

Zero third-party Python runtime dependencies: only the standard library plus
the native `pyru._native` extension. Every extra dep is a supply-chain
surface we'd rather not take on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pyru._native import scrape_urls_concurrent

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

try:
    __version__ = version("pyru-scraper")
except PackageNotFoundError:  # editable install before wheel metadata exists
    __version__ = "0.0.0"

_SAFE_SCHEMES = frozenset({"http", "https"})
_DEFAULT_CONCURRENCY = 50
_MAX_CONCURRENCY = 10_000
_DEFAULT_TIMEOUT_MS = 10_000
_DEFAULT_CONNECT_TIMEOUT_MS = 5_000
_DEFAULT_RETRIES = 0
_MAX_RETRIES = 10

_EXIT_OK = 0
_EXIT_RUNTIME_ERROR = 1
_EXIT_USER_ERROR = 2


def _validate_urls(urls: Iterable[str]) -> list[str]:
    validated: list[str] = []
    for raw in urls:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in _SAFE_SCHEMES or not parts.netloc:
            msg = f"URL must use http(s) and include a host: {raw!r}"
            raise ValueError(msg)
        validated.append(raw)
    return validated


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        msg = f"must be an integer, got {value!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if n < 1:
        msg = f"must be >= 1, got {n}"
        raise argparse.ArgumentTypeError(msg)
    return n


def _concurrency(value: str) -> int:
    n = _positive_int(value)
    if n > _MAX_CONCURRENCY:
        msg = f"must be <= {_MAX_CONCURRENCY}, got {n}"
        raise argparse.ArgumentTypeError(msg)
    return n


def _retries(value: str) -> int:
    n = _positive_int(value)
    if n > _MAX_RETRIES:
        msg = f"must be <= {_MAX_RETRIES}, got {n}"
        raise argparse.ArgumentTypeError(msg)
    return n


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser for the `pyru` CLI.

    Returns:
        The configured parser, ready for `parse_args()`.
    """
    parser = argparse.ArgumentParser(
        prog="pyru",
        description="PyRu — a high-throughput async web scraper powered by Rust.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"pyru {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _add_scrape_subcommand(subparsers)
    return parser


def _add_scrape_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
        default=_DEFAULT_CONCURRENCY,
        help=f"Maximum in-flight requests (1-{_MAX_CONCURRENCY}, default: {_DEFAULT_CONCURRENCY}).",
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
        default=_DEFAULT_TIMEOUT_MS,
        help=f"Total per-request timeout in milliseconds (default: {_DEFAULT_TIMEOUT_MS}).",
    )
    scrape.add_argument(
        "--connect-timeout-ms",
        type=_positive_int,
        default=_DEFAULT_CONNECT_TIMEOUT_MS,
        help=f"TCP/TLS connect timeout in milliseconds (default: {_DEFAULT_CONNECT_TIMEOUT_MS}).",
    )
    scrape.add_argument(
        "-r",
        "--retries",
        type=_retries,
        default=_DEFAULT_RETRIES,
        help=f"Retry attempts on failure (0-{_MAX_RETRIES}, default: {_DEFAULT_RETRIES}).",
    )
    scrape.add_argument(
        "--respect-robots-txt",
        action="store_true",
        default=False,
        help="Obey robots.txt rules before fetching.",
    )
    scrape.add_argument(
        "--cache",
        action="store_true",
        default=False,
        help="Use ETag/Last-Modified headers for conditional requests.",
    )
    scrape.add_argument(
        "--proxy",
        default=None,
        help="HTTP/HTTPS proxy URL (e.g., http://proxy:8080).",
    )
    scrape.add_argument(
        "-H",
        "--header",
        action="append",
        default=[],
        dest="headers",
        help="Custom header (can be used multiple times).",
    )
    scrape.add_argument(
        "--output-file",
        default=None,
        help="Write output to file instead of stdout.",
    )
    scrape.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Allow insecure server connections (skip SSL verification).",
    )
    scrape.add_argument(
        "--stats",
        action="store_true",
        default=False,
        help="Print summary statistics after scraping.",
    )
    scrape.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress informational output.",
    )
    scrape.set_defaults(func=_cmd_scrape)


def _emit_text(url: str, latency_ms: int, elements: list[str]) -> None:
    print(f"\n{url}  ({latency_ms} ms)")
    for element in elements:
        print(f"- {element}")


def _emit_json(url: str, selector: str, latency_ms: int, elements: list[str]) -> None:
    print(
        json.dumps(
            {
                "url": url,
                "selector": selector,
                "latency_ms": latency_ms,
                "elements": elements,
            },
            ensure_ascii=False,
        ),
    )


async def _run(args: argparse.Namespace, urls: list[str]) -> int:
    results, errors, latencies = await scrape_urls_concurrent(
        urls,
        args.selector,
        args.concurrency,
        args.user_agent,
        args.timeout_ms,
        args.connect_timeout_ms,
        args.retries,
        args.respect_robots_txt,
        args.cache,
        args.proxy,
        args.headers,
        args.insecure,
    )

    exit_code = _EXIT_OK
    output_lines: list[str] = []

    if args.quiet:
        for elements in results:
            for elem in elements:
                print(elem)
        return exit_code

    for url, elements, err, latency in zip(
        urls,
        results,
        errors,
        latencies,
        strict=True,
    ):
        if err:
            exit_code = _EXIT_RUNTIME_ERROR
            line = f"[error] {url} ({latency} ms): {err}"
            output_lines.append(line)
            print(line, file=sys.stderr)
            continue
        if args.output == "json":
            line = json.dumps(
                {
                    "url": url,
                    "selector": args.selector,
                    "latency_ms": latency,
                    "elements": elements,
                },
                ensure_ascii=False,
            )
            output_lines.append(line)
            print(line)
        else:
            line = f"\n{url}  ({latency} ms)"
            output_lines.append(line)
            print(line)
            for elem in elements:
                line = f"- {elem}"
                output_lines.append(line)
                print(line)

    if args.output_file:
        pathlib.Path(args.output_file).write_text(  # noqa: ASYNC240
            "\n".join(output_lines), encoding="utf-8"
        )

    if args.stats:
        success_count = sum(1 for e in errors if not e)
        error_count = len(errors) - success_count
        total_elements = sum(len(r) for r in results)
        total_latency = sum(latencies)
        avg_latency = total_latency / len(latencies) if latencies else 0
        print("\n--- Stats ---", file=sys.stderr)
        print(f"URLs: {len(urls)}", file=sys.stderr)
        print(f"Success: {success_count}, Errors: {error_count}", file=sys.stderr)
        print(f"Elements: {total_elements}", file=sys.stderr)
        print(f"Avg latency: {avg_latency:.1f} ms", file=sys.stderr)

    return exit_code


def _cmd_scrape(args: argparse.Namespace) -> int:
    try:
        validated = _validate_urls(args.urls)
    except ValueError as exc:
        print(f"pyru scrape: error: {exc}", file=sys.stderr)
        return _EXIT_USER_ERROR

    try:
        return asyncio.run(_run(args, validated))
    except (ValueError, RuntimeError) as exc:
        print(f"pyru scrape: error: {exc}", file=sys.stderr)
        return _EXIT_RUNTIME_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the subcommand handler.

    Args:
        argv: Command-line arguments (defaults to `sys.argv[1:]`).

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def cli() -> None:
    """Entry point used by the `pyru` / `pyweb` console scripts."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
