# One image for every backend process (docs/architecture/10 §2.1): target `backend` runs the API role,
# Celery workers, beat and the one-shot jobs; target `models` adds the GPU dependency group for DCL_ROLE=models.
# Dependencies are compiled in a builder stage; runtime images carry the virtualenv only, no compiler.
# Build context: repository root. Secrets come from the runtime environment, never from the image.

FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM builder AS deps-backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups --no-install-project

FROM builder AS deps-models
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --group models --no-install-project

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH PYTHONPATH=/app
WORKDIR /app

FROM runtime AS backend
COPY --from=deps-backend /opt/venv /opt/venv
COPY backend ./backend
COPY config ./config
USER app
EXPOSE 8200
CMD ["python", "-m", "backend.main"]

FROM runtime AS models
ENV HF_HOME=/home/app/.cache/huggingface
COPY --from=deps-models /opt/venv /opt/venv
COPY backend ./backend
COPY config ./config
RUN mkdir -p "$HF_HOME" && chown -R app:app /home/app/.cache
USER app
EXPOSE 8500
CMD ["python", "-m", "backend.main"]
