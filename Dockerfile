# syntax=docker/dockerfile:1.7
ARG RUST_VERSION=1.88
ARG PYTHON_VERSION=3.15

FROM rust:${RUST_VERSION}-slim-bookworm AS builder

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

RUN uv python install 3.15 \
 && uv venv /opt/pyru --python 3.15 --seed

COPY --from=builder /wheels /wheels
RUN /opt/pyru/bin/pip install --no-cache-dir /wheels/*.whl \
 && rm -rf /wheels /root/.cache /root/.local/share

USER pyru
WORKDIR /home/pyru

ENTRYPOINT ["/opt/pyru/bin/pyru"]
CMD ["--help"]
