//! Async Rust core that powers the PyRu / pyweb-scraper Python CLI.
//!
//! Exposes a single async Python entry point, `scrape_urls_concurrent`, which
//! fetches a batch of URLs in parallel using a tuned `reqwest` client, offloads
//! HTML parsing to a blocking pool, and returns per-URL results, errors, and
//! latencies aligned 1:1 with the input URL order.

use std::fmt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use mimalloc::MiMalloc;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use reqwest::{redirect, Client};
use scraper::{Html, Selector};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

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
const DEFAULT_RETRIES: u32 = 0;
const MAX_CONCURRENCY: usize = 10_000;
const MAX_RETRIES: u32 = 10;
const MAX_POOL_IDLE_PER_HOST: usize = 256;
const MAX_REDIRECTS: usize = 10;
const RETRY_BASE_DELAY_MS: u64 = 500;

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

async fn check_robots_txt(client: &Client, url: &str, user_agent: &str) -> bool {
    let parsed = match url::Url::parse(url) {
        Ok(p) => p,
        Err(_) => return true,
    };
    let robots_url = format!(
        "{}://{}/robots.txt",
        parsed.scheme(),
        parsed.host_str().unwrap_or("")
    );
    let req = client
        .get(&robots_url)
        .header("User-Agent", user_agent)
        .build();
    let Ok(req) = req else { return true };
    let response = client.execute(req).await;
    let Ok(resp) = response else { return true };
    if !resp.status().is_success() {
        return true;
    }
    let Ok(body) = resp.text().await else {
        return true;
    };
    for line in body.lines() {
        let stripped = line.trim();
        if stripped.starts_with("Disallow:") {
            let path = stripped.strip_prefix("Disallow:").unwrap().trim();
            if path.is_empty() || url.contains(path) {
                return false;
            }
        }
    }
    true
}

async fn fetch_with_retry(
    client: Client,
    url: String,
    selector: Arc<Selector>,
    index: usize,
    retries: u32,
    use_cache: bool,
    headers: Vec<(String, String)>,
) -> Outcome {
    let mut last_error = None;
    for attempt in 0..=retries {
        let result = fetch_single(
            &client,
            &url,
            Arc::clone(&selector),
            index,
            use_cache,
            None,
            None,
            &headers,
        )
        .await;
        match result {
            Ok(outcome) => return outcome,
            Err(e) => {
                last_error = Some(e);
                if attempt < retries {
                    let delay = RETRY_BASE_DELAY_MS * 2u64.pow(attempt);
                    tokio::time::sleep(Duration::from_millis(delay)).await;
                }
            }
        }
    }
    Outcome {
        index,
        elements: Vec::new(),
        error: last_error,
        latency_ms: 0,
    }
}

#[allow(clippy::too_many_arguments)]
async fn fetch_single(
    client: &Client,
    url: &str,
    selector: Arc<Selector>,
    index: usize,
    use_cache: bool,
    etag: Option<&str>,
    last_modified: Option<&str>,
    headers: &[(String, String)],
) -> Result<Outcome, String> {
    let started = Instant::now();
    let mut request = client.get(url);
    if let Some(e) = etag {
        request = request.header("If-None-Match", e);
    }
    if let Some(lm) = last_modified {
        request = request.header("If-Modified-Since", lm);
    }
    if !use_cache {
        request = request.header("Cache-Control", "no-cache");
    }
    for (k, v) in headers {
        request = request.header(k.as_str(), v.as_str());
    }
    let response = request
        .send()
        .await
        .map_err(|e| format!("request failed: {e}"))?;
    let status = response.status();
    if status.as_u16() == 304 && use_cache {
        return Ok(Outcome {
            index,
            elements: Vec::new(),
            error: None,
            latency_ms: started.elapsed().as_millis() as u64,
        });
    }
    if !status.is_success() {
        return Err(format!("HTTP {status}"));
    }
    let body = response
        .text()
        .await
        .map_err(|e| format!("body read failed: {e}"))?;
    let latency_ms = started.elapsed().as_millis() as u64;
    let parsed = tokio::task::spawn_blocking(move || -> Vec<String> {
        let document = Html::parse_document(&body);
        document
            .select(&selector)
            .map(|element| element.text().collect::<String>())
            .collect()
    })
    .await
    .map_err(|e| format!("parser task failed: {e}"))?;
    Ok(Outcome {
        index,
        elements: parsed,
        error: None,
        latency_ms,
    })
}

async fn fetch_and_parse(
    client: Client,
    url: String,
    selector: Arc<Selector>,
    index: usize,
    retries: u32,
    use_cache: bool,
    headers: Vec<(String, String)>,
) -> Outcome {
    fetch_with_retry(client, url, selector, index, retries, use_cache, headers).await
}

#[allow(clippy::too_many_arguments)]
pub async fn scrape_all(
    urls: Vec<String>,
    selector_str: String,
    concurrency: usize,
    user_agent: String,
    timeout_ms: u64,
    connect_timeout_ms: u64,
    retries: u32,
    respect_robots_txt: bool,
    use_cache: bool,
    proxy: Option<String>,
    headers: Vec<(String, String)>,
    insecure: bool,
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

    let mut client_builder = Client::builder()
        .user_agent(user_agent.clone())
        .tcp_nodelay(true)
        .tcp_keepalive(Duration::from_secs(30))
        .pool_idle_timeout(Duration::from_secs(60))
        .pool_max_idle_per_host(concurrency.min(MAX_POOL_IDLE_PER_HOST))
        .timeout(Duration::from_millis(timeout_ms.max(1)))
        .connect_timeout(Duration::from_millis(connect_timeout_ms.max(1)))
        .redirect(redirect::Policy::limited(MAX_REDIRECTS))
        .https_only(false)
        .danger_accept_invalid_certs(insecure);
    if let Some(p) = &proxy {
        if let Ok(proxy) = reqwest::Proxy::http(p) {
            client_builder = client_builder.proxy(proxy);
        }
    }
    let client = client_builder
        .build()
        .map_err(|e| ScrapeError::ClientBuild(format!("HTTP client build failed: {e}")))?;

    let retries = retries.clamp(0, MAX_RETRIES);

    let semaphore = Arc::new(Semaphore::new(concurrency));
    let mut set: JoinSet<Outcome> = JoinSet::new();

    for (index, url) in urls.into_iter().enumerate() {
        let client = client.clone();
        let selector = Arc::clone(&selector);
        let permit_source = Arc::clone(&semaphore);
        let user_agent = user_agent.clone();
        let headers = headers.clone();
        set.spawn(async move {
            // Semaphore is never closed here; `expect` documents that invariant.
            let _permit = permit_source
                .acquire_owned()
                .await
                .expect("semaphore closed while tasks were running");
            if respect_robots_txt && !check_robots_txt(&client, &url, &user_agent).await {
                return Outcome {
                    index,
                    elements: Vec::new(),
                    error: Some("disallowed by robots.txt".to_string()),
                    latency_ms: 0,
                };
            }
            fetch_and_parse(client, url, selector, index, retries, use_cache, headers).await
        });
    }

    let mut elements_out: Vec<Vec<String>> = (0..total).map(|_| Vec::new()).collect();
    let mut errors_out: Vec<String> = vec![String::new(); total];
    let mut latencies_out: Vec<u64> = vec![0; total];

    while let Some(join_res) = set.join_next().await {
        match join_res {
            Ok(Outcome {
                index,
                elements,
                error,
                latency_ms,
            }) => {
                elements_out[index] = elements;
                if let Some(msg) = error {
                    errors_out[index] = msg;
                }
                latencies_out[index] = latency_ms;
            }
            Err(join_err) => {
                // A tokio task panicked or was cancelled. Record a diagnostic at
                // whatever slot is still empty so the batch remains complete.
                if let Some(slot) = errors_out.iter_mut().find(|s| s.is_empty()) {
                    *slot = format!("task join error: {join_err}");
                }
            }
        }
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
        retries = DEFAULT_RETRIES,
        respect_robots_txt = false,
        use_cache = false,
        proxy = None,
        headers = None,
        insecure = false,
    ),
    text_signature = "(urls, selector, concurrency=50, user_agent=None, \
                      timeout_ms=10000, connect_timeout_ms=5000, \
                      retries=0, respect_robots_txt=False, use_cache=False, \
                      proxy=None, headers=None, insecure=False)"
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
    retries: u32,
    respect_robots_txt: bool,
    use_cache: bool,
    proxy: Option<String>,
    headers: Option<Vec<(String, String)>>,
    insecure: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let user_agent = user_agent.unwrap_or_else(|| DEFAULT_USER_AGENT.to_owned());
    let headers = headers.unwrap_or_default();
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        scrape_all(
            urls,
            selector,
            concurrency,
            user_agent,
            timeout_ms,
            connect_timeout_ms,
            retries,
            respect_robots_txt,
            use_cache,
            proxy,
            headers,
            insecure,
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
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
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
                0,
                false,
                false,
                None,
                vec![],
                false,
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
                0,
                false,
                false,
                None,
                vec![],
                false,
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
                0,
                false,
                false,
                None,
                vec![],
                false,
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
                0,
                false,
                false,
                None,
                vec![],
                false,
            ))
            .expect("scrape_all handles concurrency=0");
        assert_eq!(errors.len(), 1);
    }

    #[test]
    fn semaphore_caps_inflight_below_url_count() {
        let rt = runtime();
        // 50 URLs, concurrency=2, all go to a closed port. Should still return
        // 50 per-URL errors and not hang or over-spawn.
        let urls = (0..50).map(|_| "http://127.0.0.1:1/".to_string()).collect();
        let (elements, errors, latencies) = rt
            .block_on(scrape_all(
                urls,
                "p".into(),
                2,
                DEFAULT_USER_AGENT.into(),
                200,
                100,
                0,
                false,
                false,
                None,
                vec![],
                false,
            ))
            .expect("scrape_all completes");
        assert_eq!(elements.len(), 50);
        assert_eq!(errors.len(), 50);
        assert_eq!(latencies.len(), 50);
        assert!(errors.iter().all(|e| !e.is_empty()));
    }
}
