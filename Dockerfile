# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.11.6

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libfreetype6-dev \
        libjpeg62-turbo-dev \
        liblcms2-dev \
        libpng-dev \
        libraqm-dev \
        libwebp-dev \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-binary-package pillow

COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-binary-package pillow


FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:${PATH} \
    GUNICORN_WORKERS=1 \
    GUNICORN_TIMEOUT=120

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libfribidi0 \
        libharfbuzz0b \
        libjpeg62-turbo \
        liblcms2-2 \
        libwebp7 \
        libwebpdemux2 \
        libwebpmux3 \
        libraqm0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 sonakit \
    && useradd --system --uid 10001 --gid sonakit --home-dir /app --shell /usr/sbin/nologin sonakit

COPY --from=builder --chown=sonakit:sonakit /app/.venv /app/.venv

USER sonakit

EXPOSE 62793

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:62793/api/v1/health', timeout=3).read()"]

CMD ["sh", "-c", "exec gunicorn sonakit.app:app --bind 0.0.0.0:62793 --workers ${GUNICORN_WORKERS} --worker-class uvicorn.workers.UvicornWorker --timeout ${GUNICORN_TIMEOUT} --access-logfile - --error-logfile -"]
