# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.13
ARG RUST_VERSION=1.88

FROM rust:${RUST_VERSION}-slim-bookworm AS builder

ENV CARGO_TERM_COLOR=always \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --upgrade pip 'maturin>=1.7,<2'

WORKDIR /src
COPY native ./native
COPY pyru ./pyru
COPY pyproject.toml README.md LICENSE ./

RUN maturin build --release --strip --out /wheels

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG APP_USER=pyru
ARG APP_UID=10001

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid ${APP_UID} ${APP_USER} \
 && useradd --system --uid ${APP_UID} --gid ${APP_UID} --shell /sbin/nologin \
            --home-dir /home/${APP_USER} --create-home ${APP_USER} \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --upgrade pip \
 && pip install /wheels/*.whl \
 && rm -rf /wheels

USER ${APP_USER}
WORKDIR /home/${APP_USER}

ENTRYPOINT ["pyru"]
CMD ["--help"]
