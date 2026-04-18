# PyRu

> A high-throughput, low-latency async web scraper CLI — Python UX, Rust engine.

PyRu (distributed on PyPI as `pyru-scraper`) pairs a zero-runtime-dependency
Python CLI with an async Rust core built on [`tokio`][tokio],
[`reqwest`][reqwest] (rustls), and [`scraper`][scraper], exposed through
[PyO3 0.28][pyo3] and [`pyo3-async-runtimes`][pyo3-async]. HTTP fetching and
HTML parsing happen entirely in Rust — Python only drives the CLI and formats
the output.

## Why use it

- **Async Rust I/O.** Every URL is fetched concurrently with a tuned
  `reqwest` client (HTTP/1.1 + HTTP/2, keep-alive, TCP_NODELAY, configurable
  timeouts, gzip/brotli/zstd decompression).
- **Parallel HTML parsing.** `scraper`'s selector is parsed once and shared
  across workers; each document is parsed on the Tokio blocking pool so the
  async runtime stays responsive.
- **Partial-failure safe.** One slow or broken URL never takes down the
  batch — per-URL errors and latencies are returned alongside successful
  results.
- **Zero third-party Python deps at runtime.** CLI is pure stdlib; the only
  thing you install is the native extension itself.
- **Tiny surface area.** One async Python function; one `scrape` subcommand.

## Installation

```bash
pip install pyru-scraper
```

Pre-built `abi3` wheels are published for Linux, macOS, and Windows on
Python 3.13+. A source distribution is also available and requires a working
Rust toolchain (`rustup`, stable) to build.

## Usage

```bash
pyru scrape [OPTIONS] URL [URL...]
```

| Flag                        | Default       | Description                                   |
| --------------------------- | ------------- | --------------------------------------------- |
| `-s, --selector TEXT`       | *(required)*  | CSS selector applied to each fetched page.    |
| `-o, --output {json,text}`  | `text`        | Output format.                                |
| `-c, --concurrency INT`     | `50`          | Maximum in-flight requests (1–10000).         |
| `-u, --user-agent TEXT`     | built-in      | Override the default `User-Agent` header.    |
| `--timeout-ms INT`          | `10000`       | Total per-request timeout (ms).               |
| `--connect-timeout-ms INT`  | `5000`        | TCP/TLS connect timeout (ms).                 |

Example:

```bash
pyru scrape "https://books.toscrape.com/" -s "h3 > a" -c 200 -o json
```

Programmatic use:

```python
import asyncio
from pyru import scrape_urls_concurrent


async def main() -> None:
    elements, errors, latencies = await scrape_urls_concurrent(
        ["https://example.com/"],
        "h1",
        concurrency=8,
    )
    print(elements[0], errors[0], latencies[0])


asyncio.run(main())
```

## Benchmarks

A local-loopback benchmark harness lives under [`benchmarks/`](benchmarks/).
It spins up an `aiohttp` server, fires requests through both `pyru` and
`httpx + selectolax`, and reports totals, averages, jitter, and tail
latency. Run it:

```bash
uv sync --group benchmarks
uv run python benchmarks/real_world_benchmark.py
```

Numbers vary with hardware, kernel tunables, and network — please run the
benchmark yourself and publish the raw output before quoting comparisons.

## Development

```bash
# Sync dev + test groups, build the native extension in release mode.
uv sync --all-groups
uv run maturin develop --release

# Python lint + type check.
uv run ruff check
uv run ruff format --check
uv run ty check

# Python tests.
uv run pytest

# Rust side.
cargo clippy --manifest-path native/Cargo.toml --all-targets -- -D warnings
cargo test  --manifest-path native/Cargo.toml
cargo fmt   --manifest-path native/Cargo.toml
```

The Rust crate lives under [`native/`](native/); the Python package under
[`pyru/`](pyru/). Layout is glued together by `tool.maturin` in
[`pyproject.toml`](pyproject.toml).

## License

MIT — see [`LICENSE`](LICENSE).

[pyo3]: https://pyo3.rs/
[pyo3-async]: https://docs.rs/pyo3-async-runtimes
[reqwest]: https://docs.rs/reqwest
[scraper]: https://docs.rs/scraper
[tokio]: https://tokio.rs/
