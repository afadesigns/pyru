# PyRu

> A high-throughput, low-latency async web scraper CLI — Python UX, Rust engine.

`pyru` (published on PyPI as `pyweb-scraper`) pairs a minimal [Click][click] CLI with
an async Rust core built on [`tokio`][tokio], [`reqwest`][reqwest] (rustls), and
[`scraper`][scraper], exposed to Python through [PyO3 0.28][pyo3] and
[`pyo3-async-runtimes`][pyo3-async]. HTTP fetching and HTML parsing happen
entirely in Rust — Python only drives the CLI and formats output.

## Why use it

- **Async Rust I/O.** Every URL is fetched concurrently with a tuned `reqwest`
  client (HTTP/1.1 + HTTP/2, keep-alive, TCP_NODELAY, configurable timeouts).
- **Parallel HTML parsing.** `scraper`'s selector is parsed once and shared
  across workers; each document is parsed on the Tokio blocking pool to keep
  the async runtime responsive.
- **Partial-failure safe.** One slow or broken URL never takes down the batch —
  per-URL errors and latencies are returned alongside successful results.
- **Tiny surface area.** One async Python function; one `scrape` subcommand;
  no thread pools, no C FFI you have to think about.

## Installation

```bash
pip install pyweb-scraper
```

Pre-built `abi3` wheels are published for Linux, macOS, and Windows on
Python 3.9+. A source distribution is also available and requires a working
Rust toolchain (`rustup`, stable) to build.

## Usage

```bash
pyru scrape [OPTIONS] URL [URL...]
```

Options:

| Flag                        | Default   | Description                                          |
| --------------------------- | --------- | ---------------------------------------------------- |
| `-s, --selector TEXT`       | *(required)* | CSS selector applied to each fetched page.           |
| `-o, --output [json\|text]` | `text`    | Output format.                                       |
| `-c, --concurrency INT`     | `50`      | Maximum in-flight requests (capped at 10 000).       |
| `-u, --user-agent TEXT`     | built-in  | Override the default `User-Agent` header.            |
| `--timeout-ms INT`          | `10000`   | Total per-request timeout (ms).                      |
| `--connect-timeout-ms INT`  | `5000`    | TCP/TLS connect timeout (ms).                        |

Example:

```bash
pyru scrape "https://books.toscrape.com/" -s "h3 > a" -c 200 -o json
```

Programmatic use:

```python
import asyncio
from pyru import scrape_urls_concurrent

async def main():
    elements, errors, latencies = await scrape_urls_concurrent(
        ["https://example.com/"], "h1", concurrency=8,
    )
    print(elements[0], errors[0], latencies[0])

asyncio.run(main())
```

## Benchmarks

A local-loopback benchmark harness lives in [`benchmarks/`](benchmarks/). It
spins up an `aiohttp` server, fires 100 requests through both `pyru` and
`httpx+selectolax`, and reports totals, averages, jitter, and tail latency.

Run it:

```bash
pip install "pyweb-scraper[benchmarks]"
python benchmarks/real_world_benchmark.py
```

Numbers vary with hardware, kernel, and network tuning — please run the
benchmark yourself and publish the raw output before quoting comparisons.

## Development

```bash
# Build the Rust extension into the current venv (editable-ish).
pip install maturin
maturin develop --release

# Install dev extras and run the test suite.
pip install -e ".[dev]"
pytest

# Rust side.
cargo clippy --manifest-path rust_scraper/Cargo.toml --all-targets -- -D warnings
cargo test  --manifest-path rust_scraper/Cargo.toml
cargo fmt   --manifest-path rust_scraper/Cargo.toml
```

The Rust crate lives under [`rust_scraper/`](rust_scraper/); the Python source
lives under [`python/pyru/`](python/pyru/) and is mapped via `tool.maturin` in
[`pyproject.toml`](pyproject.toml).

## License

MIT — see [`LICENSE`](LICENSE).

[click]: https://click.palletsprojects.com/
[pyo3]: https://pyo3.rs/
[pyo3-async]: https://docs.rs/pyo3-async-runtimes
[reqwest]: https://docs.rs/reqwest
[scraper]: https://docs.rs/scraper
[tokio]: https://tokio.rs/
