# Security Policy

## Reporting a Vulnerability

> [!IMPORTANT]
> Please do **not** open a public GitHub issue for security concerns.

Use **GitHub's private vulnerability reporting** on the repository's
[Security tab](https://github.com/afadesigns/pyru/security/advisories/new).
That route opens a confidential thread visible only to the maintainers.

What to include:

- Affected version (`pyru --version`).
- Proof-of-concept reproduction.
- Impact assessment (data exposure, availability, integrity).
- Any suggested mitigation.

## Expected Response

| Phase                     | Target SLA |
| ------------------------- | ---------- |
| Initial acknowledgement   | 48 hours   |
| Triage + severity ranking | 7 days     |
| Fix + disclosure plan     | 30 days    |

## Supported Versions

| Version range | Status                          |
| ------------- | ------------------------------- |
| `1.x`         | Actively supported, all fixes.  |
| `< 1.0`       | No further fixes — please upgrade. |

## Supply Chain

PyRu ships an `abi3` wheel built from a Rust crate. Its supply chain
surface is intentionally small:

- **Python runtime deps**: none. The CLI uses only the standard library.
- **Build backend**: in-tree (`_build/`), pure stdlib, no `maturin`,
  no `setuptools`, no `hatchling`.
- **Rust deps**: `pyo3`, `pyo3-async-runtimes`, `tokio`, `reqwest`
  (rustls + webpki-roots), `scraper`, `mimalloc`. Audited via
  `cargo deny` on every CI run (`advisories`, `bans`, `sources`).
- **Sigstore / provenance**: releases go through GitHub's
  [trusted publisher](https://docs.pypi.org/trusted-publishers/) flow
  so PyPI uploads are cryptographically bound to the tagged workflow
  run — no maintainer API tokens are involved.
- **Branch protection**: `main` requires signed commits, linear
  history, conversation resolution, and the full CI matrix to pass
  before merge. Force-push and branch deletion are disabled.

If any of the above assumptions breaks, treat it as an advisory-level
security finding and report it via the channel above.
