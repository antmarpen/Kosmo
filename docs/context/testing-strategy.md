# Testing Strategy

## Overview
Kosmo follows a Test-Driven Development (TDD) approach. All new features must include behavioral tests derived from acceptance criteria.

## Test Counts (Phase 1 Completion)
- **Backend:** 155 passed / 8 skipped (on Windows host).
  - *Note on skips:* 5 durable-input boundary tests run inside the backend container (5/5 pass); 3 platform-specific skips.
  - *Windows Quirk:* Connection reset observed on `localhost:5432` from host to container; migrations run inside container to avoid issues.
- **Frontend:** 36 passed.
- **E2E (Playwright):** 5/5 passed.
- **Recovery:** All checkpoint and restart assertions passed.
- **AC-01 (Repeatability):** Verified via `just up`/`down` cycle.

## Test Suites
- **Backend:** `pytest` with `uv`. Covers services, repositories, and API handlers.
- **Frontend:** `vitest` + `react-testing-library` for components/logic; `playwright` for E2E.
- **E2E:** Full user flows (login → submit → execute → inspect results).

## Migration & Data Integrity
- **Alembic Migrations:** `0001` → `0010` chain clean on reset DB.
- **Constraint Lesson:** Alembic revision-IDs must be $\le$ 32 characters (e.g., `0008_artifact_output_unique`).
