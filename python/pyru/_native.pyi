"""Type stubs for the Rust-backed `_native` extension module."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence

__version__: str
DEFAULT_USER_AGENT: str

def scrape_urls_concurrent(
    urls: Sequence[str],
    selector: str,
    concurrency: int = 50,
    user_agent: str | None = None,
    timeout_ms: int = 10_000,
    connect_timeout_ms: int = 5_000,
) -> Awaitable[tuple[list[list[str]], list[str], list[int]]]:
    """Fetch `urls` concurrently and return `(elements, errors, latency_ms)`.

    * `elements[i]` — text nodes extracted for URL *i* (empty on failure).
    * `errors[i]`   — empty string on success, short diagnostic otherwise.
    * `latency_ms[i]` — per-URL wall-clock latency in milliseconds.
    """
    ...
