"""PyRu — a high-throughput async web scraper CLI powered by a Rust core."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._native import DEFAULT_USER_AGENT, scrape_urls_concurrent

try:
    __version__ = version("pyweb-scraper")
except PackageNotFoundError:  # pragma: no cover - only hit in editable/source installs
    __version__ = "0.0.0"

__all__ = ["DEFAULT_USER_AGENT", "__version__", "scrape_urls_concurrent"]
