"""PyRu — a high-throughput async web scraper CLI powered by a Rust core."""

from pyru._native import DEFAULT_USER_AGENT, scrape_urls_concurrent

__all__ = ["DEFAULT_USER_AGENT", "scrape_urls_concurrent"]
