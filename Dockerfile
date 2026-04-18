# syntax=docker/dockerfile:1.7
ARG RUST_VERSION=1.88
# Pin the alpha build explicitly: `uv python install 3.15` can resolve to
# the newest stable <=3.15 that uv's download catalogue knows about
# (currently 3.14.x, which violates our `requires-python = ">=3.15.0a8"`).
ARG PYTHON_VERSION=3.15.0a8

FROM rust:${RUST_VERSION}-slim-bookworm AS builder
ARG PYTHON_VERSION

ENV CARGO_TERM_COLOR=always \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY _build ./_build
COPY native ./native
COPY pyru ./pyru

RUN uv python install ${PYTHON_VERSION} \
 && uv build --wheel --out-dir /wheels

FROM debian:bookworm-slim AS runtime
ARG PYTHON_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh \
 && groupadd --system --gid 10001 pyru \
 && useradd --system --uid 10001 --gid pyru --shell /sbin/nologin \
            --home-dir /home/pyru --create-home pyru

ENV PATH="/root/.local/bin:/opt/pyru/bin:${PATH}"

RUN uv python install ${PYTHON_VERSION} \
 && uv venv /opt/pyru --python ${PYTHON_VERSION} --seed

COPY --from=builder /wheels /wheels
RUN /opt/pyru/bin/pip install --no-cache-dir /wheels/*.whl \
 && rm -rf /wheels /root/.cache /root/.local/share

USER pyru
WORKDIR /home/pyru

ENTRYPOINT ["/opt/pyru/bin/pyru"]
CMD ["--help"]
