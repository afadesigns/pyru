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
    retries: int = 0,
    respect_robots_txt: bool = False,
    use_cache: bool = False,
    proxy: str | None = None,
    headers: Sequence[tuple[str, str]] | None = None,
    insecure: bool = False,
) -> Awaitable[tuple[list[list[str]], list[str], list[int]]]: ...
