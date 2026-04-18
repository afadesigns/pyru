# Contributing to PyRu

Thanks for spending your time here. This is a lean project — the rules
are correspondingly lean.

## Ground rules

- **Open an issue before a large PR.** Five-line bug fixes are fair
  game; architectural changes are best discussed first.
- **Every change ships as one focused commit** with a
  [Conventional Commits](https://www.conventionalcommits.org/) prefix:
  `feat`, `fix`, `perf`, `refactor`, `docs`, `build`, `ci`, `test`,
  `chore`, `revert`.
- **Signed commits only.** The `main` branch rejects unsigned pushes.
- **No unrelated reformatting** in a PR. Touch the code you need, nothing
  else — it makes review triage tractable.

## Local setup

```bash
# Install uv (https://docs.astral.sh/uv) and a Rust toolchain (rustup).
uv python install 3.15
uv sync --group dev                        # ruff + ty
uv pip install -e .                        # editable + builds native ext via cargo
```

## The full check chain

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run python -m unittest discover -s tests -v

cargo fmt  --manifest-path native/Cargo.toml --all -- --check
cargo clippy --manifest-path native/Cargo.toml --all-targets -- -D warnings
cargo test   --manifest-path native/Cargo.toml --all-targets
```

CI runs exactly this same chain across Linux, macOS, Windows. There is
no "works on my machine" slack; if the green chain above passes locally,
CI passes too.

## Benchmarks

The harness compares PyRu against `httpx + selectolax` on a local
`aiohttp` server. It lives under `benchmarks/` and is opt-in:

```bash
uv sync --group benchmarks
uv run python benchmarks/real_world_benchmark.py
```

When submitting perf-sensitive PRs, please paste the before/after table
into the PR description.

## Pull request checklist

- [ ] One focused commit with a Conventional-Commits subject
- [ ] `uv run ruff check` / `format --check` / `ty check` — all clean
- [ ] `python -m unittest discover tests` — all pass
- [ ] `cargo clippy -- -D warnings` — no warnings
- [ ] `cargo test` — all pass
- [ ] Benchmarks (if perf-relevant)
- [ ] Docs updated if user-facing behaviour changed
