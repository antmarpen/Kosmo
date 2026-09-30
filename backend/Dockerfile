# Kosmo backend production image (used by docker-compose.prod.yml).
# Dev mode does NOT use this image: dev bind-mounts ./backend and runs
# uvicorn with --reload for live changes.

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

# Dependencies first for layer caching; --no-dev excludes pytest/httpx.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --compile-bytecode

COPY app ./app
COPY worker ./worker
COPY shared ./shared
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Import path stays /app (app, worker, shared are top-level packages).
WORKDIR /app

# --no-sync: the image is already synced; never reach for the network at start.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
