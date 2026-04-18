//! Async Rust core that powers the PyRu / pyweb-scraper Python CLI.
//!
//! Exposes a single async Python entry point, `scrape_urls_concurrent`, which
//! fetches a batch of URLs in parallel using a tuned `reqwest` client, offloads
//! HTML parsing to a blocking pool, and returns per-URL results, errors, and
//! latencies aligned 1:1 with the input URL order.

use std::fmt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::stream::{self, StreamExt};
use mimalloc::MiMalloc;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use reqwest::{redirect, Client};
use scraper::{Html, Selector};

#[global_allocator]
static GLOBAL: MiMalloc = MiMalloc;

const DEFAULT_USER_AGENT: &str = concat!(
    "pyru/",
    env!("CARGO_PKG_VERSION"),
    " (+https://github.com/afadesigns/pyru)"
);
const DEFAULT_TIMEOUT_MS: u64 = 10_000;
const DEFAULT_CONNECT_TIMEOUT_MS: u64 = 5_000;
const DEFAULT_CONCURRENCY: usize = 50;
const MAX_CONCURRENCY: usize = 10_000;
const MAX_POOL_IDLE_PER_HOST: usize = 256;
const MAX_REDIRECTS: usize = 10;

pub type ScrapeOutput = (Vec<Vec<String>>, Vec<String>, Vec<u64>);

#[derive(Debug)]
pub enum ScrapeError {
    InvalidSelector(String),
    ClientBuild(String),
}

impl fmt::Display for ScrapeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ScrapeError::InvalidSelector(msg) => write!(f, "{msg}"),
            ScrapeError::ClientBuild(msg) => write!(f, "{msg}"),
        }
    }
}

impl std::error::Error for ScrapeError {}

struct Outcome {
    index: usize,
    elements: Vec<String>,
    error: Option<String>,
    latency_ms: u64,
}

async fn fetch_and_parse(
    client: Client,
    url: String,
    selector: Arc<Selector>,
    index: usize,
) -> Outcome {
    let started = Instant::now();
    let response = match client.get(&url).send().await {
        Ok(resp) => resp,
        Err(e) => {
            return Outcome {
                index,
                elements: Vec::new(),
                error: Some(format!("request failed: {e}")),
                latency_ms: started.elapsed().as_millis() as u64,
            };
        }
    };

    let status = response.status();
    if !status.is_success() {
        return Outcome {
            index,
            elements: Vec::new(),
            error: Some(format!("HTTP {status}")),
            latency_ms: started.elapsed().as_millis() as u64,
        };
    }

    let body = match response.text().await {
        Ok(body) => body,
        Err(e) => {
            return Outcome {
                index,
                elements: Vec::new(),
                error: Some(format!("body read failed: {e}")),
                latency_ms: started.elapsed().as_millis() as u64,
            };
        }
    };

    let latency_ms = started.elapsed().as_millis() as u64;

    let parsed = tokio::task::spawn_blocking(move || -> Vec<String> {
        let document = Html::parse_document(&body);
        document
            .select(&selector)
            .map(|element| element.text().collect::<String>())
            .collect()
    })
    .await;

    match parsed {
        Ok(elements) => Outcome {
            index,
            elements,
            error: None,
            latency_ms,
        },
        Err(e) => Outcome {
            index,
            elements: Vec::new(),
            error: Some(format!("parser task failed: {e}")),
            latency_ms,
        },
    }
}

pub async fn scrape_all(
    urls: Vec<String>,
    selector_str: String,
    concurrency: usize,
    user_agent: String,
    timeout_ms: u64,
    connect_timeout_ms: u64,
) -> Result<ScrapeOutput, ScrapeError> {
    let total = urls.len();
    if total == 0 {
        return Ok((Vec::new(), Vec::new(), Vec::new()));
    }

    let concurrency = concurrency.clamp(1, MAX_CONCURRENCY);

    let selector = Selector::parse(&selector_str).map_err(|e| {
        ScrapeError::InvalidSelector(format!("invalid CSS selector {selector_str:?}: {e}"))
    })?;
    let selector = Arc::new(selector);

    let client = Client::builder()
        .user_agent(user_agent)
        .tcp_nodelay(true)
        .tcp_keepalive(Duration::from_secs(30))
        .pool_idle_timeout(Duration::from_secs(60))
        .pool_max_idle_per_host(concurrency.min(MAX_POOL_IDLE_PER_HOST))
        .timeout(Duration::from_millis(timeout_ms.max(1)))
        .connect_timeout(Duration::from_millis(connect_timeout_ms.max(1)))
        .redirect(redirect::Policy::limited(MAX_REDIRECTS))
        .https_only(false)
        .build()
        .map_err(|e| ScrapeError::ClientBuild(format!("HTTP client build failed: {e}")))?;

    let mut elements_out: Vec<Vec<String>> = (0..total).map(|_| Vec::new()).collect();
    let mut errors_out: Vec<String> = vec![String::new(); total];
    let mut latencies_out: Vec<u64> = vec![0; total];

    let mut stream = stream::iter(urls.into_iter().enumerate().map(|(i, url)| {
        let client = client.clone();
        let selector = Arc::clone(&selector);
        fetch_and_parse(client, url, selector, i)
    }))
    .buffer_unordered(concurrency);

    while let Some(outcome) = stream.next().await {
        let Outcome {
            index,
            elements,
            error,
            latency_ms,
        } = outcome;
        elements_out[index] = elements;
        if let Some(msg) = error {
            errors_out[index] = msg;
        }
        latencies_out[index] = latency_ms;
    }

    Ok((elements_out, errors_out, latencies_out))
}

fn lift(err: ScrapeError) -> PyErr {
    match err {
        ScrapeError::InvalidSelector(msg) => PyValueError::new_err(msg),
        ScrapeError::ClientBuild(msg) => PyRuntimeError::new_err(msg),
    }
}

/// Async: scrape each URL, apply the selector, return `(elements, errors, latency_ms)`.
///
/// - `elements[i]` — list of extracted text nodes for URL *i* (empty on failure).
/// - `errors[i]`   — empty string when the URL succeeded, otherwise a short
///   diagnostic. Partial failures never abort the whole batch.
/// - `latency_ms[i]` — per-URL wall-clock latency in milliseconds.
#[pyfunction]
#[pyo3(
    signature = (
        urls,
        selector,
        concurrency = DEFAULT_CONCURRENCY,
        user_agent = None,
        timeout_ms = DEFAULT_TIMEOUT_MS,
        connect_timeout_ms = DEFAULT_CONNECT_TIMEOUT_MS,
    ),
    text_signature = "(urls, selector, concurrency=50, user_agent=None, \
                      timeout_ms=10000, connect_timeout_ms=5000)"
)]
#[allow(clippy::too_many_arguments)]
fn scrape_urls_concurrent<'py>(
    py: Python<'py>,
    urls: Vec<String>,
    selector: String,
    concurrency: usize,
    user_agent: Option<String>,
    timeout_ms: u64,
    connect_timeout_ms: u64,
) -> PyResult<Bound<'py, PyAny>> {
    let user_agent = user_agent.unwrap_or_else(|| DEFAULT_USER_AGENT.to_owned());
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        scrape_all(
            urls,
            selector,
            concurrency,
            user_agent,
            timeout_ms,
            connect_timeout_ms,
        )
        .await
        .map_err(lift)
    })
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(scrape_urls_concurrent, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime builds")
    }

    #[test]
    fn empty_urls_returns_empty_tuple() {
        let rt = runtime();
        let (elements, errors, latencies) = rt
            .block_on(scrape_all(
                Vec::new(),
                "p".into(),
                8,
                DEFAULT_USER_AGENT.into(),
                DEFAULT_TIMEOUT_MS,
                DEFAULT_CONNECT_TIMEOUT_MS,
            ))
            .expect("scrape_all succeeds");
        assert!(elements.is_empty());
        assert!(errors.is_empty());
        assert!(latencies.is_empty());
    }

    #[test]
    fn invalid_selector_is_value_error() {
        let rt = runtime();
        let err = rt
            .block_on(scrape_all(
                vec!["http://127.0.0.1:1".into()],
                ":::not-a-selector".into(),
                1,
                DEFAULT_USER_AGENT.into(),
                DEFAULT_TIMEOUT_MS,
                DEFAULT_CONNECT_TIMEOUT_MS,
            ))
            .expect_err("selector must fail");
        assert!(
            matches!(err, ScrapeError::InvalidSelector(_)),
            "got: {err:?}"
        );
    }

    #[test]
    fn unreachable_host_produces_per_url_error_not_panic() {
        let rt = runtime();
        let (elements, errors, latencies) = rt
            .block_on(scrape_all(
                vec!["http://127.0.0.1:1/".into()],
                "p".into(),
                1,
                DEFAULT_USER_AGENT.into(),
                200,
                100,
            ))
            .expect("scrape_all returns Ok even on connection refusal");
        assert_eq!(elements.len(), 1);
        assert_eq!(errors.len(), 1);
        assert_eq!(latencies.len(), 1);
        assert!(elements[0].is_empty());
        assert!(
            !errors[0].is_empty(),
            "expected an error string for unreachable host"
        );
    }

    #[test]
    fn concurrency_is_clamped_to_valid_range() {
        let rt = runtime();
        // concurrency=0 should be clamped to 1, not divide-by-zero or panic.
        let (_, errors, _) = rt
            .block_on(scrape_all(
                vec!["http://127.0.0.1:1/".into()],
                "p".into(),
                0,
                DEFAULT_USER_AGENT.into(),
                100,
                50,
            ))
            .expect("scrape_all handles concurrency=0");
        assert_eq!(errors.len(), 1);
    }
}
