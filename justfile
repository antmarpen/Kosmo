# Kosmo root task runner.
#
# Cross-platform recipes: plain single commands with no shell-only constructs,
# so they run under `sh` (Windows: Git for Windows) and PowerShell alike.
# Prerequisites: Docker Desktop running, just, uv (backend tests on the host).
# pnpm is only needed for frontend tests on the host; the compose frontend
# installs its own toolchain inside the container.

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# List the available recipes.
default:
    @just --list

# Start the full stack in the background and wait until health checks pass.
up:
    docker compose up -d --wait --wait-timeout 300

# Build the sandbox image used by script-node containers (one-off).
build-sandbox:
    docker compose --profile image-build build sandbox

# Build the OpenCode ACP image used by dynamically created AI-node containers.
build-opencode:
    docker compose --profile image-build build opencode

# Stop the stack and remove containers (named volumes keep their data).
down:
    docker compose down

# Follow logs; pass service names to filter, e.g. `just logs backend worker`.
logs *args:
    docker compose logs -f --tail 100 {{args}}

# Apply database migrations inside the running backend container.
migrate:
    docker compose exec backend uv run alembic upgrade head

# Run backend tests on the host (uv manages the virtualenv from uv.lock).
test-backend:
    uv run --project backend --directory backend pytest

# Run frontend tests on the host with pnpm (Vitest arrives with WP-02).
test-frontend:
    pnpm -C frontend test

# Run integrated Playwright checks against the running compose stack.
e2e:
    pnpm -C frontend e2e

# Regenerate the typed API client from the running backend (WP-06).
gen-client:
    pnpm -C frontend exec openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts

# Build the production images (backend + frontend).
build:
    docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# Start the stack in production mode (built images, no bind mounts, no --reload).
# Run `just down` first: dev and prod share the kosmo-* container names.
up-prod:
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait --wait-timeout 600

# Seed initial data (WP-05/WP-08: admin + runner users, reference workflow).
seed:
    docker compose exec backend sh -c "uv run alembic upgrade head && uv run python -m scripts.seed"

# Run the local CI-equivalent checks in sequence.
ci: test-backend test-frontend
    pnpm -C frontend build
    uv run --project backend --directory backend python -c "import json; from pathlib import Path; from app.main import create_app; Path('../openapi.json').write_text(json.dumps(create_app().openapi()), encoding='utf-8')"
    pnpm -C frontend exec openapi-typescript ../openapi.json -o src/api/schema.d.ts
    git diff --exit-code -- frontend/src/api/schema.d.ts
    docker compose -f docker-compose.yml config -q
