# Testing Strategy

## Overview
Kosmo follows a Test-Driven Development (TDD) approach. All new features must include behavioral tests derived from acceptance criteria.

## Live provider and agent tests (owner instruction, 2026-10-01)
- Whenever a test runs a real agent or model call, use the model **`nan/qwen3.6`**.
- Agent containers run `opencode` from `kosmo-opencode:local`; the provider
  configuration is injected as `opencode.json` (`.config/opencode`) plus
  `auth.json` (`.local/share/opencode`).
- Prefer an explicit model in the test workflow. AI nodes whose agent model is
  `"default"` let OpenCode choose its own default, which varies per session and
  is not the model selected in the provider wizard.

## Test Counts (current)
- **Backend:** 196 passed / 8 skipped (on Windows host).
  - *Note on skips:* 5 durable-input boundary tests run inside the backend container (5/5 pass); 3 platform-specific skips.
  - *Windows Quirk:* Connection reset observed on `localhost:5432` from host to container; migrations run inside container to avoid issues.
- **Frontend:** 120 passed.
- **Live provider/agent proof (2026-10-01):** real container runs discovered 39
  models from the owner's OpenCode configuration, provider verification
  returned `ok` in ~10 s, and a `start → AI → end` workflow completed with
  state `success` using an explicit model.

## Test Suites
- **Backend:** `pytest` with `uv`. Covers services, repositories, and API handlers.
- **Frontend:** `vitest` + `react-testing-library` for components/logic; `playwright` for E2E.
- **E2E:** Full user flows (login → submit → execute → inspect results).

## Migration & Data Integrity
- **Alembic Migrations:** `0001` → `0010` chain clean on reset DB.
- **Constraint Lesson:** Alembic revision-IDs must be $\le$ 32 characters (e.g., `0008_artifact_output_unique`).
