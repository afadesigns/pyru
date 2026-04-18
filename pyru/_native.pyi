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
) -> Awaitable[tuple[list[list[str]], list[str], list[int]]]: ...
