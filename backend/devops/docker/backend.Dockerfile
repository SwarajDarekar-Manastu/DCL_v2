# One image for every backend process (docs/architecture/10 §2.1): target `backend` runs the API role,
# Celery workers and beat; target `models` adds the GPU dependency group for DCL_ROLE=models.
# Build context: repository root. Secrets come from the runtime environment, never from the image.

FROM python:3.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups --no-install-project
COPY backend ./backend
COPY config ./config
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups
USER app
EXPOSE 8200
CMD ["python", "-m", "backend.main"]

FROM base AS models
ENV HF_HOME=/home/app/.cache/huggingface
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups --group models --no-install-project
COPY backend ./backend
COPY config ./config
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups --group models \
    && mkdir -p "$HF_HOME" && chown -R app:app /home/app/.cache
USER app
EXPOSE 8500
CMD ["python", "-m", "backend.main"]
