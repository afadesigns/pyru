"""Click-based CLI wrapper around the PyRu Rust core."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable
from urllib.parse import urlsplit

import click

from . import __version__
from ._native import scrape_urls_concurrent

_SAFE_SCHEMES = frozenset({"http", "https"})


def _validate_urls(urls: Iterable[str]) -> list[str]:
    validated: list[str] = []
    for raw in urls:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in _SAFE_SCHEMES or not parts.netloc:
            raise click.BadParameter(
                f"URL must use http(s) and include a host: {raw!r}",
                param_hint="URLS",
            )
        validated.append(raw)
    return validated


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
            click.echo(
                click.style(f"[error] {url} ({latency} ms): {err}", fg="red"),
                err=True,
            )
            continue

        if output == "json":
            click.echo(
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
            click.echo(click.style(f"\n{url}  ({latency} ms)", fg="green", bold=True))
            for element in elements:
                click.echo(f"- {element}")

    return exit_code


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="pyru")
def cli() -> None:
    """PyRu — a high-throughput async web scraper powered by Rust."""


@cli.command()
@click.argument("urls", nargs=-1, required=True)
@click.option(
    "--selector",
    "-s",
    required=True,
    help="CSS selector applied to each fetched page.",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["json", "text"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--concurrency",
    "-c",
    type=click.IntRange(min=1, max=10_000),
    default=50,
    show_default=True,
    help="Maximum in-flight requests.",
)
@click.option(
    "--user-agent",
    "-u",
    default=None,
    help="Override the default User-Agent header.",
)
@click.option(
    "--timeout-ms",
    type=click.IntRange(min=1),
    default=10_000,
    show_default=True,
    help="Total per-request timeout (milliseconds).",
)
@click.option(
    "--connect-timeout-ms",
    type=click.IntRange(min=1),
    default=5_000,
    show_default=True,
    help="TCP/TLS connect timeout (milliseconds).",
)
def scrape(
    urls: tuple[str, ...],
    selector: str,
    output: str,
    concurrency: int,
    user_agent: str | None,
    timeout_ms: int,
    connect_timeout_ms: int,
) -> None:
    """Scrape one or more URLs concurrently and emit extracted elements."""
    validated = _validate_urls(urls)
    try:
        exit_code = asyncio.run(
            _run(
                validated,
                selector,
                output.lower(),
                concurrency,
                user_agent,
                timeout_ms,
                connect_timeout_ms,
            )
        )
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    cli()
