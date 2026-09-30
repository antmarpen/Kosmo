# Phase 1 — Work Packages

Status: Ready for coordinator review
Date: 2026-09-30
Source spec: `docs/specs/phase-1-foundations.md` (Approved 2026-09-30)
Technical reference: `docs/architecture.md`

Notes for coordinators and workers:

- Repo state: documentation only, no code exists. All paths below are proposed
  paths consistent with `docs/architecture.md` §2–§3; package owners create
  them. Where a decision is marked `Proposal`, it is the architect's proposed
  resolution of a spec open question — workers implement it as specified and
  report back; the coordinator records it in the architecture decisions table
  during documentation.
- Every package is sized for a fresh-context worker. Each handoff must include
  the package text below plus the spec section it references. Workers do not
  reopen the spec; blockers go to the coordinator.
- TDD applies where marked; the red step (test fails for the missing behavior)
  is part of the completion evidence.
- Workers record any decision they had to make beyond this plan in their report
  so the final architecture review and `documentator` can capture it.

## Package index

| ID | Name | Type / owner | Key ACs |
| --- | --- | --- | --- |
| WP-01 | Monorepo scaffolding and compose stack | development / developer | AC-01 (infra) |
| WP-02 | Frontend app shell, i18n scaffold, login page | design / designer | AC-01 (SPA) |
| WP-03 | Backend core: settings, DB, migrations, logging, KosmoError | development / developer | AC-05 (error model), AC-10 (test base) |
| WP-04 | Dynamic router registration + convention test | development / developer | AC-10 |
| WP-05 | Identity & access backend (JWT, roles, seeds) | development / developer | AC-02 (backend) |
| WP-06 | Frontend auth flow (login, silent refresh, logout) | development / developer | AC-02 (SPA) |
| WP-07 | Graph schema contracts + validation service | development / developer | AC-03/04/05 foundation |
| WP-08 | Workflow persistence, publication, seed reference workflow | development / developer | AC-03/04 foundation |
| WP-09 | Task submission, state machine, notes, artifact metadata models | development / developer | AC-03, AC-09, AC-05 (notes) |
| WP-10 | Temporal wiring + graph interpreter skeleton | development / developer | AC-03 |
| WP-11 | Script node sandbox execution + artifact store + artifact API | development / developer | AC-03, AC-04 (artifacts) |
| WP-12 | Checkpoint single writer + recovery semantics | development / developer | AC-07 |
| WP-13 | Capacity limits + FIFO admission | development / developer | AC-09 |
| WP-14 | Agent adapter interface + OpenCode ACP adapter | development / developer | AC-04 (adapter) |
| WP-15 | AI node execution: validation levels, correction cycles, validator MCP | development / developer | AC-04, AC-05 |
| WP-16 | Human input round trip + stop semantics | development / developer | AC-06 |
| WP-17 | SSE endpoints + event publishing | development / developer | AC-08 (backend) |
| WP-18 | Task views UI: list, detail, SSE live updates, localized labels | design / designer | AC-08 (SPA), AC-05/06/09 surfaces |
| WP-02b | Main app layout: sidebar + drawer navigation shell | design / designer | AC-01 (shell), foundation for WP-18 |
| WP-19 | CI pipeline (GitHub Actions) | development / developer | AC-10 (CI) |
| WP-20 | Integrated E2E verification suite | test / tester | AC-01..AC-09 evidence |

## Acceptance criteria coverage map

| AC | Packages | Verification locus |
| --- | --- | --- |
| AC-01 | WP-01, WP-02, WP-20 | `just up` from clean clone + Playwright login/language check |
| AC-02 | WP-05, WP-06, WP-20 | Backend service tests + SPA Vitest + Playwright |
| AC-03 | WP-09, WP-10, WP-11, WP-20 | API + interpreter + sandbox integration test + E2E |
| AC-04 | WP-11, WP-14, WP-15, WP-20 | Adapter round trip + validation + artifact API + E2E |
| AC-05 | WP-03, WP-15, WP-18, WP-20 | Error contract tests + validation-cycle tests + notes UI |
| AC-06 | WP-16, WP-18, WP-20 | Workflow Update tests + restart persistence test + E2E |
| AC-07 | WP-12, WP-20 | Checkpoint unit/concurrency tests + kill/restart scenario |
| AC-08 | WP-17, WP-18, WP-20 | SSE stream tests + SPA live-update component tests |
| AC-09 | WP-13, WP-18, WP-20 | Scheduling service tests + E2E observation |
| AC-10 | WP-04, WP-05, WP-19 | Convention test + fake-repo service tests + CI run |

---

### WP-01 — Monorepo scaffolding and compose stack
+
+> **Coordinator note (2026-09-30, post-remediation):** implemented and
+> verified. Remediation after first verification: (1) workflow modules must be
+> import-pure — `settings` import moved into `main()` (permanent constraint
+> for WP-10); (2) frontend healthcheck switched to busybox wget and
+> `CHOKIDAR_USEPOLLING` removed as root cause of 5–17 s responses (controlled
+> diagnostic evidence in the developer report; `vite.config.ts` keeps an
+> env-gated polling option for WP-02 to revisit); (3) `.pnpm-store/` ignored.
+> Compose verified twice: all `kosmo-*` containers healthy, healthz 200,
+> SPA 200 in <15 ms, worker polling `kosmo-tasks`. Follow-ups for the final
+> architecture review: thin healthcheck margin (raise `retries` before
+> `timeout` if flaky); WP-02 must confirm HMR works without polling;
+> `temporalio/auto-setup` 1.29.7 is end-of-line (plan migration to
+> `temporalio/server` + `AUTO_SETUP=true` later); backend `--reload` polling
+> watcher is small-scope today, revisit if latency matters (WP-17 SSE).
- Type / owner: development / developer
- Objective / acceptance IDs: From a clean clone, `just up` boots the full
  stack (frontend, backend, worker, postgres, temporal) with health checks
  passing; README documents the Windows/Docker Desktop quick start.
  AC-01 (infrastructure part).
- Included scope / exclusions:
  - In: repository root files (compose, justfile, .env.example, README quick
    start, .gitignore additions for `.agents/ .opencode/ .superpowers/
    .impeccable/` per AGENTS.md), `backend/` uv project skeleton, `frontend/`
    pnpm Vite scaffold (placeholder page only), Alembic initialized with an
    empty baseline migration, `backend/shared/` empty package, minimal Temporal
    worker process that connects and registers a no-op workflow, minimal
    FastAPI `/healthz`.
  - Out: i18n/login UI (WP-02), auth, any domain feature, CI (WP-19),
    migrations beyond baseline, sandbox/agent images (WP-11/WP-14).
- Files or modules / relevant context and existing patterns:
  - `docker-compose.yml`, `justfile`, `README.md`, `.env.example`, `.gitignore`
  - `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/main.py`,
    `backend/app/core/config.py`, `backend/alembic/`, `backend/worker/run_worker.py`,
    `backend/shared/__init__.py`
  - `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/main.tsx`
  - Architecture §2 (compose services table), §9 (version policy, just runner).
- Changes / contracts / examples:
  - Compose services: `frontend` (Vite dev server in container, port 5173,
    `/api` proxy → `backend:8000`), `backend` (uvicorn), `worker` (Temporal
    worker), `postgres` (app DB `kosmo`), `temporal`
    (`temporalio/auto-setup` with its own DB in the same postgres instance or a
    second postgres container — pick one, document in compose comments).
    Healthchecks; `backend`/`worker` depend on postgres+temporal healthy.
  - Settings via pydantic-settings, env prefix `KOSMO_` (DB URL, Temporal
    host/namespace, JWT secret placeholder — no real secret values committed).
  - justfile recipes (cross-platform, no shell-only syntax): `up`, `down`,
    `logs`, `migrate`, `test-backend`, `test-frontend`, `gen-client`
    (placeholder until WP-06), `seed` (placeholder until WP-05/08).
  - Version policy (architecture §9): Python 3.14 line, latest stable majors,
    lockfiles (`uv.lock`, `pnpm-lock.yaml`) committed.
- Dependencies / file ownership / execution order: first package; no
  dependencies. Owns all root scaffolding files. Later packages extend
  justfile/README by editing (serialize edits; WP-05, WP-08, WP-20 add
  recipes).
- Required skills and why they apply: `verification-before-completion`
  (evidence that the stack boots); `fastapi-python` for the minimal app wiring.
- Tests / verification commands when known / expected evidence:
  - `docker compose config -q` passes.
  - `just up` → `curl http://localhost:8000/healthz` returns 200;
    `curl http://localhost:5173` returns the SPA index; temporal UI (if
    exposed) or `temporal` CLI lists namespace reachable from worker logs
    (worker log line "connected").
  - `just down` leaves no orphan containers.
- Completion criteria: clean-clone `just up` works on Windows/Docker Desktop;
  healthchecks green; README quick start matches actual commands; lockfiles
  committed.
- Risks / assumptions / unresolved blockers: `temporalio/auto-setup` image tag
  compatibility; Python 3.14 wheel availability for pydantic/sqlalchemy/
  temporalio/alembic (if a package lacks wheels, pin latest compatible minor
  and report for the decisions table). Docker Desktop resource needs documented
  in README.

### WP-02 — Frontend app shell, i18n scaffold, login page
+
+> **Coordinator note (2026-09-30): DONE and verified.** `just test-frontend`
+> green (3 files / 11 tests: render, full en↔es swap, catalog key parity,
+> localStorage persistence, responsive smoke). Build passes (`tsc --noEmit` +
+> Vite). Responsive verified with real screenshots at 375/768/1280px. Design:
+> OKLCH token theme, steel-blue primary, brass accent reserved for brand;
+> shadcn/ui button/input/card only (two documented a11y micro-deviations in
+> card.tsx: CardTitle asChild→h1, CardDescription→p). Infra follow-ups applied
+> by coordinator: compose exposes `CHOKIDAR_USEPOLLING` gate (default false —
+> HMR over the bind mount needs it; designer finding); `.playwright-mcp/`
+> ignored; i18next recorded as decided in architecture §9. pnpm 11 finding:
+> build-script approvals live in `pnpm-workspace.yaml` under **allowBuilds**
+> (onlyBuiltDependencies/`pnpm` package.json field are removed settings) —
+> fixed and prod image builds verified.
- Type / owner: design / designer
- Objective / acceptance IDs: SPA loads an app frame; the login page renders;
  a language switcher toggles English/Spanish everywhere visible; catalogs are
  nested JSON with namespaced keys. AC-01 (SPA part).
- Included scope / exclusions:
  - In: app router + layout frame, i18next runtime with nested `en`/`es`
    catalogs (`common`, `auth` namespaces), language switcher (persisted in
    localStorage), login page UI (visual only — auth wiring is WP-06), minimal
    shared UI primitives.
  - Out: task views (WP-18), auth logic/token handling (WP-06), Playwright
    (WP-20).
- Files or modules / relevant context and existing patterns:
  - `frontend/src/app/` (router, root layout), `frontend/src/i18n/`
    (`en.json`, `es.json`, `index.ts`), `frontend/src/features/auth/`
    (`LoginPage`, `LanguageSwitcher`), `frontend/src/components/ui/`
  - Architecture §7: feature folders, shared UI in `src/components` (shadcn/ui
    base), nested catalogs with namespaced keys (`common.cancel`).
- Changes / contracts / examples:
  - Catalog shape: `{ "common": { "cancel": "Cancel", "submit": "Submit" },
    "auth": { "login": { "title": "Sign in", "username": "Username",
    "password": "Password", "action": "Sign in" } } }` and the Spanish
    equivalent. Spanish is translated content (allowed exception to
    English-only files).
  - Shared UI: adopt shadcn/ui init with `button`, `input`, `card` only (no
    speculative components); plain Tailwind otherwise.
  - Router: `/login` route; `/` placeholder frame that later hosts tasks.
- Dependencies / file ownership / execution order: needs WP-01 (frontend
  scaffold). Parallel-safe with WP-03/WP-04 (backend). Owns
  `frontend/src/{app,i18n,features/auth,components}/**`; WP-06 later edits
  `features/auth` — serialize after this package.
- Required skills and why they apply: `impeccable` (primary design skill for
  Kosmo UI work); `vercel-react-best-practices` (React patterns).
- Tests / verification commands when known / expected evidence:
  - Vitest + RTL: LoginPage renders; clicking the switcher swaps all visible
    strings between en/es (assert both catalogs' keys exist and render);
    `just test-frontend` green.
- Completion criteria: `just up` → SPA loads, login page visible, switcher
  works, no untranslated keys in either catalog; component tests pass; the
  shell and login page are responsive and usable on a mobile viewport
  (owner requirement — verify at 375px width).
- Risks / assumptions / unresolved blockers: none expected; i18next is the
  proposed runtime (architecture §9 "Proposed") — implement it and report.

---

### WP-02b — Main app layout: sidebar + drawer navigation shell
+
+> **Coordinator note (2026-09-30): DONE and verified** (executed with
+> openai/gpt-6-luna#medium after a silent glm5.3-flash failure). `just
+> test-frontend` green: 16 tests (nav tree localized both locales, drawer
+> open/Escape/focus-trap/persistence, `/tasks/new` default landing). Build
+> green. Responsive verified at 375/768/1280 with screenshots in
+> `.impeccable/`. Administration rendered with a visual-only "Admin" hint.

> Added 2026-09-30 after owner review of the app information architecture.
> Decisions: sidebar (collapsible) on desktop + drawer on mobile; grouped
> "Administration" section with sub-items; default landing after login is the
> **task creation screen** (owner decision 2026-09-30; the screen's final
> format will be designed later — WP-18 defines the real creation flow, this
> package ships the scaffold route). Designer owns frontend/src/**; no backend
> files. Style work is guided by the `impeccable` skill (primary design skill).

- Type / owner: design / designer
- Objective / acceptance IDs: replace WP-02's placeholder frame with the real
  application layout shell that WP-18's task views will live in. AC-01 (usable
  shell part).
- Included scope / exclusions:
  - In: responsive layout (desktop sidebar collapsible to icons; mobile drawer
    via hamburger; sticky header with brand, language switcher, user-menu
    placeholder); navigation tree: Tasks (children: New task [landing route,
    active default], History [placeholder]), Workflows, Context,
    Administration (sub-items: Agents, MCPs, Skills, Extensions, Repositories,
    Applications, Audit); `/tasks/new` route as the default landing with a
    task-creation scaffold page (empty state: form region placeholder + note
    that WP-18 defines the real flow; no API calls); i18n keys for all nav
    labels (en/es); route guard placeholder for role-gated sections (visual
    only).
  - Out: task list/detail content (WP-18), auth logic (WP-06), any backend.
- Files or modules: `frontend/src/app/**` (layout, routes), 
  `frontend/src/components/**` (sidebar, drawer, nav primitives),
  `frontend/src/i18n/**`, `frontend/src/features/navigation/**` (if needed).
  WP-02's LoginPage and language switcher are reused, not rewritten.
- Changes / contracts: nav tree as typed config object (id, label_message_key,
  icon, children?, route) so WP-18/WP-06 plug in without restructuring;
  aria-compliant drawer (focus trap, Escape closes); skip-to-content preserved.
- Dependencies / order: after WP-02. Parallel-safe with backend wave 3
  (disjoint files). WP-18 consumes this shell.
- Required skills: `impeccable` (primary), `vercel-react-best-practices`.
- Tests / verification: Vitest+RTL — nav tree renders all sections with both
  locales, drawer opens/closes at mobile viewport, sidebar collapse persists;
  responsive checks at 375/768/1280px (owner requirement); `just test-frontend`
  green; `pnpm build` passes.
- Completion criteria: layout usable at all three breakpoints; every nav label
  present in both catalogs; no backend changes.
- Risks / assumptions: nav items link to placeholder pages until their phases
  land; role-gating visuals only (real enforcement is backend, WP-05+).


+
+> **Coordinator note (2026-09-30): DONE and verified.** Implemented with
+> TDD (handler tests red first): async engine/session (core/db.py), JSON
+> logging (core/logging.py), KosmoError + status subclasses (shared/errors.py),
+> FastAPI handlers returning exactly {code, message_key, params, details} with
+> internal stacktrace logged-never-returned, conftest with kosmo_test DB
+> strategy (Alembic upgrade head runs inside the backend container; host-side
+> localhost connection was reset — recorded as a Windows/Docker quirk).
+> `just test-backend` green: 4 passed. Executed with openai/gpt-6-luna#medium
+> after three silent glm5.3-flash session failures (model fallback per owner).
- Type / owner: development / developer
- Objective / acceptance IDs: App boots with typed settings, async SQLAlchemy
  session, Alembic migrations wired, JSON structured logging, and the
  `KosmoError` model with global exception handlers returning
  `{ code, message_key, params, details[] }` — stacktraces logged, never
  returned. AC-05 (error contract), AC-10 (service test base).
- Included scope / exclusions:
  - In: `core/config.py` finalization, `core/db.py` (async engine/session),
    `core/logging.py` (JSON formatter for app+worker), Alembic async env,
    `backend/shared/errors.py` (base `KosmoError` + subclasses + code
    registry), `app/api/errors.py` (FastAPI handlers), test conftest with app
    fixture + DB strategy, httpx-based handler tests.
  - Out: routes (WP-04), auth (WP-05), domain schemas.
- Files or modules / relevant context and existing patterns:
  - `backend/app/core/{config,db,logging}.py`, `backend/app/api/errors.py`,
    `backend/app/main.py`, `backend/alembic/env.py`,
    `backend/shared/errors.py`, `backend/tests/conftest.py`
  - Architecture §3 (layering, errors.py), §8 (error model), §4 (SQLAlchemy
    2.0 async + Alembic).
- Changes / contracts / examples:
  - `KosmoError(message_key: str, params: dict = {}, details:
    list[ErrorDetail] = [], code: str = "ERROR", http_status: int = 400,
    internal: str | None = None)`; `ErrorDetail { message_key: str, params:
    dict }`. Subclasses only set status/default code:
    `AuthError(401)`, `PermissionDeniedError(403)`, `NotFoundError(404)`,
    `ConflictError(409)`, `ValidationFailedError(422)`,
    `InternalError(500)`.
  - Handler response body exactly:
    `{"code": "...", "message_key": "...", "params": {...}, "details": [...]}`;
    `internal` is logged with stacktrace server-side and never serialized.
    Unexpected exceptions → 500 body with `code="INTERNAL_ERROR"`,
    `message_key="errors.internal"`, empty details.
  - Logging: stdlib logging + JSON formatter; `internal` always logged.
  - Test DB strategy `Proposal`: unit tests run against a dedicated test
    database on the compose postgres (`KOSMO_TEST_DATABASE_URL`, default
    `postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test`), schema
    created by Alembic in conftest; pure unit tests use fakes (no DB). Report
    if friction appears.
- Dependencies / file ownership / execution order: needs WP-01. Owns
  `backend/app/core/**`, `backend/shared/errors.py`, `backend/app/api/errors.py`,
  `backend/tests/conftest.py`. Parallel-safe with WP-02. WP-04 depends on it.
- Required skills and why they apply: `fastapi-python` (handler/session
  patterns), `python-design-patterns` (small exception hierarchy, layering),
  `python-testing-patterns` (conftest, fixtures), `test-driven-development`
  (handlers test-first).
- Tests / verification commands when known / expected evidence:
  - TDD: handler tests first (KosmoError → exact body; ValidationFailedError
    with two details entries serialized; unexpected exception → 500 body with
    no stacktrace, internals present in captured logs), then implement.
  - `just test-backend` (or `uv run pytest backend/tests`) green.
- Completion criteria: all handler tests pass; JSON logs visible in backend
  container; Alembic `upgrade head` runs on empty DB.
- Risks / assumptions / unresolved blockers: none blocking; pick argon2-cffi
  for hashing later (WP-05) and record in decisions table.

### WP-04 — Dynamic router registration + convention test
+
+> **Coordinator note (2026-09-30): DONE and verified.** `routes/__init__.py`
+> discovers sibling modules via pkgutil/importlib; missing `router` →
+> RuntimeError at registration; /healthz moved to routes/health.py.
+> `just test-backend` green: 8 passed. TDD red evidence recorded (DID NOT
+> RAISE before the check existed).
- Type / owner: development / developer
- Objective / acceptance IDs: `api/routes/__init__.py` auto-discovers sibling
  route modules via `pkgutil`/`importlib` and registers any module-level
  `router`; a convention test fails when a route module lacks `router`.
  AC-10 (first clause).
- Included scope / exclusions:
  - In: discovery function, registration into the FastAPI app, `health.py`
    example module (moved from WP-01's inline route if it created one),
    convention test + discovery unit tests.
  - Out: any real API area (WP-05+).
- Files or modules / relevant context and existing patterns:
  - `backend/app/api/routes/__init__.py`, `backend/app/api/routes/health.py`,
    `backend/app/main.py` (include the discovered routers),
    `backend/tests/api/test_router_registration.py`
  - Architecture §3 "Dynamic router registration" (exact mechanism).
- Changes / contracts / examples:
  - Discovery contract: every `*.py` sibling module (excluding `_`-prefixed)
    must expose `router: APIRouter`; discovery raises/warns via test, not at
    import time (registration skips nothing silently — a missing router fails
    the convention test, and registration raises `RuntimeError` naming the
    module to make the failure loud at startup).
- Dependencies / file ownership / execution order: needs WP-03 (main.py,
  conftest). Owns `backend/app/api/routes/**`. WP-05+ add route modules and
  must keep the convention test green.
- Required skills and why they apply: `test-driven-development` (write the
  convention test first, show it failing on a module without `router`), 
  `fastapi-python`.
- Tests / verification commands when known / expected evidence:
  - TDD red: create `routes/broken_example.py` without `router` in a temp
    fixture → convention test fails; implement discovery → green; remove the
    broken module. Unit test the discovery function against a fake package.
  - `just test-backend` green.
- Completion criteria: adding a new module with `router` requires zero
  changes elsewhere; convention test demonstrates the failure mode.
- Risks / assumptions / unresolved blockers: none.

---

### WP-05 — Identity & access backend: users, sessions, JWT, roles, seeds
+
+> **Coordinator note (2026-09-30): DONE and verified.** argon2-cffi (works on
+> Python 3.14), HS256 JWT 15-min access + rotating refresh with family reuse
+> detection, Bearer-header transport, idempotent seed (admin/test-runner).
+> Live round trip verified against compose: login → me → refresh (rotated,
+> old-token reuse → 401 family revocation) → logout 204 → post-logout refresh
+> 401. `just test-backend` green: 30 passed. Decisions for the table: logout
+> takes {refresh_token} in the body (package gap, implementer assumption);
+> KOSMO_JWT_SECRET now injected via compose with a dev-only fallback and
+> .env override (gitignored). Note: host-side alembic against localhost:5432
+> resets connections on this machine (Windows/Docker quirk) — migrations run
+> inside the container.
- Type / owner: development / developer
- Objective / acceptance IDs: Login issues a short-lived JWT access token plus
  a rotating refresh token persisted server-side; refresh rotates (old token
  invalidated); logout revokes; roles exist and are enforced via dependencies;
  seeds create one admin and one test runner. AC-02 (backend).
- Included scope / exclusions:
  - In: `domain/identity/` (models/repository/service/schemas), `api/routes/auth.py`,
    `api/deps.py` (`get_db`, `get_current_user`, `require_roles`),
    `core/security.py` (hashing + JWT encode/verify), `scripts/seed.py`
    (admin + runner users), migration, `just seed` recipe.
  - Out: SPA wiring (WP-06), task permissions (WP-09), groups beyond the role
    column (phase 1 needs roles only — no group tables yet; keep schema open).
- Files or modules / relevant context and existing patterns:
  - `backend/app/domain/identity/{models,repository,service,schemas}.py`,
    `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`,
    `backend/app/core/security.py`, `backend/scripts/seed.py`,
    `backend/alembic/versions/<new>`
  - Architecture §3 (layering: service/repository split, fake repos in tests),
    §8 (state/error contracts), spec "Identity and access (skeleton)".
- Changes / contracts / examples:
  - Tables: `users` (id, username unique, password_hash, role enum
    viewer|runner|builder|group_manager|admin, created_at), `sessions`
    (id, user_id, refresh_hash, family_id, expires_at, revoked_at nullable —
    rotation replaces refresh_hash within a family; logout revokes family).
  - Endpoints: `POST /auth/login {username,password} → 200
    {access_token, refresh_token, token_type:"bearer", expires_in}`;
    `POST /auth/refresh {refresh_token} → 200 new pair` (used refresh revoked;
    reuse of a revoked token revokes the whole family — reuse detection);
    `POST /auth/logout` (auth required) → revokes session, 204;
    `GET /auth/me` → user + roles.
  - Access token claims: `sub` (user id), `role`, `exp` (15 min Proposal);
    JWT via `pyjwt`, HS256 with `KOSMO_JWT_SECRET`. Hashing: `argon2-cffi`
    (record choice in decisions table).
  - Transport decision (spec open question) `Proposal`: Authorization header
    everywhere including SSE; refresh token returned in the JSON body and
    stored client-side by WP-06. Record in decisions table.
  - `require_roles(*roles)` dependency; `403 PermissionDeniedError` otherwise.
- Dependencies / file ownership / execution order: needs WP-03, WP-04. Owns
  `backend/app/domain/identity/**`, `api/routes/auth.py`, `api/deps.py`,
  `core/security.py`. WP-06 (SPA) and WP-09 (task permissions) depend on it.
  Extends `justfile` (`seed`) — serialize with WP-08's seed additions.
- Required skills and why they apply: `python-design-patterns` (service with
  fake repository seam), `python-testing-patterns` (fake repos, parametrized
  cases), `fastapi-python` (deps, routers), `test-driven-development`.
- Tests / verification commands when known / expected evidence:
  - TDD with fake repository: login ok / wrong password (401 `AuthError`,
    `message_key="errors.auth.invalid_credentials"`); refresh rotates and old
    token fails; reused revoked token kills family; logout revokes; `me`
    requires valid token; `require_roles("runner")` rejects viewer.
  - `just test-backend` green; `just seed` then login via curl works.
- Completion criteria: endpoints behave per contract; seeds idempotent;
  decisions (hashing lib, transport) reported for the decisions table.
- Risks / assumptions / unresolved blockers: none blocking; argon2-cffi must
  have Python 3.14 wheels (fallback: stdlib `hashlib.scrypt`, report).

### WP-06 — Frontend auth flow: login, silent refresh, logout
+
+> **Coordinator note (2026-09-30): DONE and verified.** Remediation round
+> fixed test isolation + mojibake literals and added a fetch-forwarding
+> wrapper; 21 frontend tests green (single-flight refresh on 401, failed-refresh
+> logout, logout API call), build green. Live verification (coordinator, real
+> browser): login with seeded admin → lands on /tasks/new with full shell;
+> Sign out → returns to /login. Root cause of the original UI failure was NOT
+> the app: the running Vite dev server had a stale config (host edits do not
+> cross the bind mount — same finding as WP-02b's HMR note); a container
+> restart picked up the /api proxy rewrite. **Operational rule:** after
+> changing vite.config.ts or adding route modules, restart `kosmo-frontend`
+> (or enable the CHOKIDAR_USEPOLLING gate).
- Type / owner: development / developer
- Objective / acceptance IDs: SPA logs in with the seeded admin; an expired
  access token triggers automatic single-flight silent refresh; logout revokes
  the refresh token (next refresh attempt fails). AC-02 (SPA part).
- Included scope / exclusions:
  - In: generated API client + auth middleware (attach bearer, 401 →
    single-flight refresh → retry once), auth context/store, login form
    submission wiring onto WP-02's LoginPage, logout action, route guard.
  - Out: login page visuals (WP-02), backend (WP-05), task views (WP-18).
- Files or modules / relevant context and existing patterns:
  - `frontend/src/api/` (generated `schema.d.ts` via `openapi-typescript` from
    `/openapi.json`, `client.ts` via `openapi-fetch` + auth middleware),
    `frontend/src/features/auth/` (hooks, `AuthProvider`, guard),
    `justfile` `gen-client` recipe finalized.
  - Architecture §7 (generated client, openapi-fetch), spec AC-02.
- Changes / contracts / examples:
  - Token storage `Proposal`: access token in memory (module-scoped),
    refresh token in `localStorage` for reload persistence; document the
    tradeoff and record in the decisions table. Silent refresh: on 401 from
    any call, run one shared refresh promise; on failure clear state and
    redirect to `/login`. `gen-client` regenerates from the running backend
    (`just gen-client`).
- Dependencies / file ownership / execution order: needs WP-02 (pages),
  WP-05 (endpoints), WP-01 (`gen-client`). Owns `frontend/src/api/**` and
  auth flow files in `features/auth`; WP-18 reuses (does not edit) these.
  Parallel-safe with WP-08/WP-09.
- Required skills and why they apply: `vercel-react-best-practices`
  (context/subscription patterns, no unnecessary re-renders),
  `verification-before-completion`.
- Tests / verification commands when known / expected evidence:
  - Vitest with mocked fetch/openapi-fetch: login stores tokens; a 401
    triggers exactly one refresh and retries the original request; failed
    refresh logs out; logout calls `POST /auth/logout`. Short-lived token test
    via fake clock/expired token fixture.
  - `just test-frontend` green.
- Completion criteria: Playwright-ready login flow works against compose
  stack (manual check acceptable here; automated check in WP-20); decisions
  reported.
- Risks / assumptions / unresolved blockers: none blocking; SSE header auth
  (WP-17/WP-18) relies on the header-transport decision above.

---

### WP-07 — Graph schema contracts + validation service
+
+> **Coordinator note (2026-09-30): DONE and verified.** Contracts v1 in
+> `shared/graph/` (discriminated nodes, edges, optional phases + LoopPolicy,
+> AI nodes with exactly 3 ValidationLevels) and a pure validator aggregating
+> all violations into ValidationFailedError("errors.workflow.invalid",
+> details=[...]) with per-rule message_keys. 16 package tests; combined suite
+> 29 passed. Contract interpretations recorded: outputs declare artifact
+> names, inputs reference declared names; errors.workflow.* namespace.
- Type / owner: development / developer
- Objective / acceptance IDs: Versioned Pydantic contracts for workflow graph
  definitions in `backend/shared/` (nodes start/end/script/http/ai minimal
  shapes, edges, input form on start, optional phases with bounded-loop
  fields) and a server-side validation service surfacing violations as
  structured `KosmoError` responses. Foundation for AC-03/04/05; implements
  spec "Workflow definition (programmatic, minimal)" validation.
- Included scope / exclusions:
  - In: `shared/graph/` contracts (schema v1), validation service in
    `domain/workflows/validation.py`, exhaustive tests of every rule.
  - Out: persistence/publication (WP-08), interpreter (WP-10), visual editor
    (non-goal).
- Files or modules / relevant context and existing patterns:
  - `backend/shared/graph/{__init__,schema}.py`,
    `backend/app/domain/workflows/validation.py`,
    `backend/tests/shared/test_graph_schema.py`,
    `backend/tests/domain/test_workflow_validation.py`
  - Architecture §3 (`backend/shared` = contracts used by both processes),
    spec "Workflow definition".
- Changes / contracts / examples:
  - Contracts (schema_version literal `"v1"`):
    `WorkflowDefinition {schema_version, name, input_form is on start node,
    nodes: list[Node], edges: list[Edge], phases: list[Phase] | None}`.
    `Edge {from: node_id, to: node_id}`. Node union discriminated by `type`:
    - `StartNode {id, input_form: list[FormField]}` with
      `FormField {name, type: "string"|"number"|"boolean", required: bool,
      label_message_key}` (namespaced key, e.g. `workflow.topic.label`).
    - `ScriptNode {id, code: str, inputs: list[str] (artifact names),
      outputs: list[str]}` — code executed inside the sandbox (WP-11).
    - `HttpNode {id, method, url, outputs: list[str]}` (minimal; execution in
      this phase optional — interpreter may treat as unsupported → clear
      error; state that choice in the worker, not here).
    - `AiNode {id, agent: AgentConfig, prompt_template: str,
      inputs: list[str], outputs: list[str],
      validation: ValidationContract, max_validation_cycles: int = 3}` with
      `AgentConfig {runtime: "opencode", model, instructions}`,
      `ValidationContract {levels: list[ValidationLevel]}` with exactly
      three `ValidationLevel {name, message_key, params_schema: dict}`.
    - `EndNode {id}`.
    - `Phase {id, node_ids: list[str], loop: LoopPolicy | None}` with
      `LoopPolicy {target_node_id, max_iterations: int}` — bounded-loop
      fields present in schema per spec (interpreter support beyond flat
      graphs is not required in phase 1; schema carries them).
  - Validation rules (each violation → one entry in `details[]` with its own
    `message_key`): unique node ids; edges reference existing nodes; exactly
    one start and one end; start has no incoming / end has no outgoing edges;
    graph is connected & acyclic; every `inputs`/`outputs` name resolves to a
    declared artifact contract (node outputs + start input form fields are
    the contract surface); start node has ≥1 form field; AI nodes declare
    exactly 3 validation levels. Aggregate under
    `ValidationFailedError(message_key="errors.workflow.invalid",
    details=[...])`.
- Dependencies / file ownership / execution order: needs WP-03 (errors).
  Owns `backend/shared/graph/**`, `domain/workflows/validation.py`. WP-08
  (persistence) and WP-10 (interpreter) consume; no file overlap.
- Required skills and why they apply: `python-design-patterns` (discriminated
  unions, small pure validation functions), `test-driven-development`,
  `python-testing-patterns`.
- Tests / verification commands when known / expected evidence:
  - TDD: a valid reference definition passes; each rule above has one
    red→green test asserting the exact `message_key` in `details`.
  - `just test-backend` green.
- Completion criteria: contracts importable from `shared` by app and worker;
  validation service returns all violations (not first-only).
- Risks / assumptions / unresolved blockers: AI node `agent` is inline config
  for phase 1 (no agents catalog table — that is a later phase's
  configuration catalog); recorded as a scope decision in the review.

### WP-08 — Workflow persistence, publication, seed reference workflow
+
+> **Coordinator note (2026-09-30): DONE and verified.** Publication service +
+> `/workflows` routes (403 for non-builders, 422 with per-issue details),
+> immutable versions enforced by a DB trigger (direct SQL update rejected),
+> activations table, idempotent seed of `reference-security-analysis`
+> (start[topic] → script[report.md+data.json] → ai[summary.md, 3 validation
+> levels, max 3 cycles] → end). `just test-backend` green: 36 passed; `just
+> seed` runs migrations + seed (verified). Open item handed to WP-11: script
+> node receives inputs via `KOSMO_INPUT_TOPIC` env convention — WP-11 aligns
+> sandbox execution with it.
- Type / owner: development / developer
- Objective / acceptance IDs: Published workflow versions are stored
  immutably; publication applies WP-07 validation server-side; a seed script
  publishes the reference workflow `start → script → ai → end` with declared
  artifacts and three-level validation metadata on the AI node's output.
  Foundation for AC-03/AC-04; spec "Workflow definition" + "seed script".
- Included scope / exclusions:
  - In: `domain/workflows/` models/repository/service, minimal API
    (`POST /workflows` create+publish for admin/builder, `GET /workflows`,
    `GET /workflows/{id}`), `activations` (one active version per workflow),
    seed script extension (`just seed` publishes the reference workflow
    idempotently), migration.
  - Out: drafts/authoring UI, version lifecycle beyond publish+activate
    (phase 2), agent catalog tables.
- Files or modules / relevant context and existing patterns:
  - `backend/app/domain/workflows/{models,repository,service,schemas}.py`,
    `backend/app/api/routes/workflows.py`,
    `backend/scripts/seed.py` (extend WP-05's), migration,
    `backend/tests/domain/test_workflow_publication.py`
  - Architecture §4 (workflows/workflow_versions/activations), spec seed
    description.
- Changes / contracts / examples:
  - Tables: `workflows` (id, name unique), `workflow_versions` (id,
    workflow_id, version int, definition JSONB immutable), `activations`
    (workflow_id unique → version_id).
  - `POST /workflows` (admin/builder): validate definition → store → publish
    v1 (next call publishes v(n+1)) → activate → 201. Validation failures →
    422 `KosmoError` with per-issue details.
  - Seed reference workflow `reference-security-analysis` (name adjustable):
    start (input form: `topic: string, required`), script node computing an
    artifact (writes `report.md` + `data.json` from inputs), AI node that
    transforms `report.md` into `summary.md` with outputs contract and a
    three-level `ValidationContract` (e.g. L1 file exists + parseable, L2
    required sections/fields present, L3 content rule), end. Idempotent:
    running seed twice does not duplicate.
- Dependencies / file ownership / execution order: needs WP-07 (contracts +
  validation), WP-05 (roles). Owns `domain/workflows/**` (except
  `validation.py` — WP-07 owns that file), `api/routes/workflows.py`,
  `scripts/seed.py` (after WP-05). WP-09 depends on it.
- Required skills and why they apply: `python-design-patterns`
  (service/repository layering), `python-testing-patterns`, 
  `test-driven-development`.
- Tests / verification commands when known / expected evidence:
  - TDD: invalid definition → 422 with details; valid → v1 published and
    activated; second publish → v2 active; versions immutable (update
    rejected); seed idempotency test with fake repos.
  - `just seed` against compose DB → workflows listed via API.
- Completion criteria: seeded workflow retrievable via `GET /workflows`;
  publication validation enforced server-side.
- Risks / assumptions / unresolved blockers: exact seed content (script code,
  validation levels) is the implementer's proposal in this package — keep it
  minimal and aligned with WP-15's validator capabilities; report the final
  seed shape so WP-15/WP-20 build against it.

---

### WP-09 — Task submission, state machine, notes, artifact metadata models
+
+> **R-07 remediation note (2026-09-30): DONE.** Task list returns a safe DTO
+> only (id, workflow_id/name, state, created_at, updated_at) — no prompt,
+> input_values, resolved_definition, notes or artifacts for non-detail users.
+> Aggregate SSE streams publish state summaries for all permitted tasks but
+> task.note payloads only to the submitter/admin. Detail permissions
+> unchanged. 143 tests green (TDD red on serialization leak). Live two-user
+> SSE evidence deferred to WP-20 follow-up.
+
+> **Coordinator note (2026-09-30): DONE and verified.** TaskState enum in
+> shared/state.py; tables tasks/task_notes/node_executions/artifacts
+> (migration 0004); POST /tasks validates inputs against the start-node form,
+> snapshots the definition, creates queued; GET list/detail with the package's
+> permission proposal (submitter/admin detail; others read-only list —
+> recorded decision). Live: runner submission → 201 queued; missing topic →
+> 422 with per-field detail. `just test-backend` green: 49 passed. WP-10 seam:
+> TaskService.submit documented, no Temporal dependency. Open: viewer-role
+> live check needs a seeded viewer account (defer; covered by unit tests).
- Type / owner: development / developer
- Objective / acceptance IDs: Runner can submit a task bound to the seeded
  published version with input-form values; task is created `queued`; state
  machine with explicit transitions; tables for `task_notes`,
  `node_executions`, `artifacts` metadata. AC-03 (submission), AC-09
  (queued state groundwork), AC-05 (notes storage), AC-04 (artifact metadata
  storage).
- Included scope / exclusions:
  - In: `domain/tasks/` (models/repository/service/schemas), `TaskState`
    enum in `backend/shared/state.py`, `api/routes/tasks.py`
    (`POST /tasks`, `GET /tasks`, `GET /tasks/{id}`), transition guard,
    migrations.
  - Out: Temporal start (WP-10), capacity admission (WP-13), SSE (WP-17),
    input/stop endpoints (WP-16), artifact download endpoints (WP-11).
- Files or modules / relevant context and existing patterns:
  - `backend/app/domain/tasks/{models,repository,service,schemas}.py`,
    `backend/app/api/routes/tasks.py`, `backend/shared/state.py`, migrations
  - Architecture §4 (tasks, task_notes, node_executions, artifacts), §8
    (state enums are language-independent identifiers; labels are keys).
- Changes / contracts / examples:
  - `TaskState` (shared, used by app+worker+SPA labels):
    `queued, running, waiting_for_input, stopping, stopped, failed, success,
    allocating` (exact architecture §8 list).
  - Tables: `tasks` (id, workflow_id, version_id, state, prompt, input_values
    JSONB, resolved_definition JSONB snapshot, created_by, created_at,
    updated_at), `task_notes` (id, task_id, revision, message_key, params
    JSONB, created_at), `node_executions` (id, task_id, node_id, iteration,
    attempt, state, started_at, finished_at, error JSONB nullable),
    `artifacts` (id, task_id, node_id, logical_name, iteration, attempt,
    media_type, size, sha256, storage_path, created_at).
  - `POST /tasks {workflow_id, input_values, prompt?}` → validates runner
    role, loads active version, validates input_values against the start
    node's input form, snapshots the definition, creates task `queued` → 201
    `{id, state:"queued"}`. `GET /tasks` list + `GET /tasks/{id}` (nodes from
    `node_executions`, notes, artifacts metadata).
  - Transition map enforced in service
    (`queued→running→{success,failed,waiting_for_input,stopping}`,
    `waiting_for_input→running|stopping`, `stopping→stopped|failed|success`,
    etc.); illegal transition → `ConflictError`.
  - Task permission model (AC-04 "subject to task permissions") `Proposal`:
    submitter and admin can view/submit; other runners read-only list.
    Record in decisions table.
- Dependencies / file ownership / execution order: needs WP-05 (roles/deps),
  WP-08 (versions). Owns `domain/tasks/**` (WP-13/WP-16 later extend service
  via separate scheduling/input modules — coordinate), `api/routes/tasks.py`
  (WP-16/WP-17 add endpoints to other modules; this file gets input/stop in
  WP-16 — serialize), `shared/state.py` (created here; workers read-only).
- Required skills and why they apply: `python-design-patterns` (explicit
  state machine, no god service), `python-testing-patterns`, 
  `test-driven-development`, `fastapi-python`.
- Tests / verification commands when known / expected evidence:
  - TDD with fake repos: submission binds active version + stores inputs +
    snapshot; invalid input values → 422 with per-field details; each legal
    transition passes, each illegal one raises `ConflictError`; runner can
    submit, viewer cannot (403).
  - `just test-backend` green; API reachable via curl with token.
- Completion criteria: endpoints per contract; state map covered by tests;
  tables migrate cleanly.
- Risks / assumptions / unresolved blockers: none blocking.

### WP-10 — Temporal wiring + graph interpreter skeleton
+
+> **Coordinator note (2026-09-30): DONE and verified.** TaskWorkflow replaces
+> NoOpWorkflow; deterministic interpreter (implicit phase, topological order,
+> activity-registry dispatch, structured failure for unregistered types);
+> submission seam starts `task-{task_id}`; state/node_executions via activities.
+> 52 tests green. Live smoke: start=success, collect(stub)=success,
+> summarize(AI, no executor yet)=failed → task failed (failure propagation
+> verified). Remediations: (1) workflow starter injected into TaskService —
+> unit tests no longer touch the live Temporal server (a test had polluted it
+> with a fake-ID workflow; terminated via temporal CLI); (2) worker activity
+> imports identity models so FK metadata registers users. FINDING for WP-13 +
+> final review: a task whose Temporal start fails stays `queued` forever —
+> no start-retry mechanism exists yet. Full `queued→running→success` proof is
+> deferred to WP-15 (AI executor) + WP-20 (E2E) rather than masked with a stub.
- Type / owner: development / developer
- Objective / acceptance IDs: Task submission starts one root Temporal
  workflow (`task-{task_id}`); a deterministic interpreter walks the snapshot
  graph (start→…→end), records `node_executions`, drives task state
  `queued→running→success/failed` through activities. AC-03 (execution
  path), foundation for AC-06/07.
- Included scope / exclusions:
  - In: Temporal client in backend service (start workflow on submit),
    worker process registration (task queue), `workflows/task_workflow.py`
    interpreter, initial activities (state transitions, start/end node
    execution, node dispatch seam), `worker/contracts.py`,
    `shared/execution.py` (activity payload dataclasses).
  - Out: script container execution (WP-11), checkpoint (WP-12), capacity
    (WP-13), adapter (WP-14), signals/updates (WP-16).
- Files or modules / relevant context and existing patterns:
  - `backend/worker/run_worker.py`, `backend/worker/workflows/task_workflow.py`,
    `backend/worker/activities/{state,nodes}.py`,
    `backend/worker/contracts.py`, `backend/shared/execution.py`,
    `backend/app/domain/tasks/service.py` (submission hook — coordinate with
    WP-09 owner or take over the one-line addition),
    `backend/tests/worker/test_interpreter.py`
  - Architecture §5 (one task = one root workflow; deterministic interpreter;
    all side effects in activities).
- Changes / contracts / examples:
  - Task queue `kosmo-tasks`, namespace `default` (Proposal — record).
    Workflow ID `task-{task_id}` (retry/resume reuses the ID family).
  - Interpreter algorithm (pure function over snapshot + activity results):
    load phases (None → one implicit phase containing all nodes); order nodes
    topologically within phase honoring edges; for each node: read
    `node_executions`/checkpoint (WP-12) → skip completed; dispatch per type
    via activity registry `run_node(node, ctx) -> NodeResult`; failure → task
    `failed` with structured error; after end node → `success`.
  - Determinism rules: no `datetime.now()`/random in workflow code; time comes
    from activity results; loop/phase iteration counters workflow-local.
  - `NodeResult {state, outputs: dict[str, ArtifactRef], error: KosmoErrorData | None}`.
- Dependencies / file ownership / execution order: needs WP-09 (tasks +
  states). Owns `backend/worker/**` and `shared/execution.py`. WP-11..WP-16
  extend worker files — serialize on `task_workflow.py` per package order
  below. `justfile` gains no changes.
- Required skills and why they apply: `python-design-patterns` (pure
  interpreter core separated from Temporal runtime), 
  `python-testing-patterns`, `test-driven-development`.
- Tests / verification commands when known / expected evidence:
  - TDD: unit tests for the pure graph-walk (flat graph, implicit phase,
    branch honoring edges, node failure → failed result) with a fake
    activity registry; integration test with
    `temporalio.testing.WorkflowEnvironment` (time-skipping): submit → task
    `running` → `success`, `node_executions` rows for start/end.
  - `just test-backend` green; manual: submit task via API against compose →
    task reaches `success`.
- Completion criteria: E2E `queued→running→success` against compose with the
  seed workflow's start/end (script node may fail cleanly with "executor not
  registered" until WP-11 — acceptable interim evidence; interpreter test
  uses a stub executor).
- Risks / assumptions / unresolved blockers: temporalio SDK compatibility with
  Python 3.14 (report immediately if blocked); WorkflowEnvironment availability
  on Windows (fallback: unit tests + manual compose verification).

---

### WP-11 — Script node sandbox execution + artifact store + artifact API
+
+> **Coordinator note (2026-09-30): DONE and verified.** Sandbox image
+> (python:3.14-slim, stdlib+requests+pydantic, non-root), network_mode none,
+> CPU/mem limits, timeout→failed node; replaces WP-10's stub for script
+> nodes. Env contract: KOSMO_INPUT_TOPIC + KOSMO_OUTPUT_<NAME> under
+> /workspace/output. Artifact store: sha256 + provenance rows; authenticated
+> list/download endpoints (submitter/admin). Remediation: task storage moved
+> to a shared named Docker volume `task-storage` (daemon-visible for
+> Docker-in-Docker; bind-mount path inside the worker container was not);
+> Docker-marked integration test passes INSIDE the worker (real sandbox run →
+> file via volume → sha256 match). `just test-backend` green: 65 passed,
+> 2 skipped (Docker-marked skipped on host by design). Live task-flow E2E
+> deferred to wave verification + WP-20. Output subpath permissions fixed for
+> the non-root user (subpath mount detail).
- Type / owner: development / developer
- Objective / acceptance IDs: Script nodes execute in a fresh Docker sandbox
  container (no internet by default, artifacts mounted, output directory
  writable, timeout + resource limits); outputs are validated against the
  declared contract and persisted to the task storage volume with PostgreSQL
  metadata (provenance node/iteration/attempt + integrity hash); artifacts
  are viewable/downloadable through the API subject to task permissions.
  AC-03 (sandbox isolation), AC-04 (artifact persistence + access).
- Included scope / exclusions:
  - In: sandbox image (`backend/docker/sandbox/Dockerfile`, compose builds
    it), sandbox runner activity, artifact persistence activity, artifact
    validation (existence/parse per declared contract — full three-level
    machinery is WP-15's), `domain/artifacts/` service+repository,
    `api/routes/artifacts.py` (list, view/download endpoints wired to task
    permissions from WP-09).
  - Out: AI node (WP-15), checkpoint (WP-12), HTTP node execution (deferred;
    interpreter returns a clear "unsupported in phase 1" error).
- Files or modules / relevant context and existing patterns:
  - `backend/docker/sandbox/Dockerfile`, `backend/worker/activities/sandbox.py`,
    `backend/worker/activities/artifacts.py`,
    `backend/app/domain/artifacts/{repository,service}.py`,
    `backend/app/api/routes/artifacts.py`, compose update (build sandbox
    image), `backend/tests/worker/test_sandbox.py`
  - Architecture §5 (script row), §6 (per-node network scope, mounts, limits,
    curated Python env), §9 (artifact storage decision).
- Changes / contracts / examples:
  - Storage layout: task volume root `/var/lib/kosmo/tasks/{task_id}/`
    (compose volume mounted into worker/backend), artifacts under
    `artifacts/{node_id}/{iteration}-{attempt}/{logical_name}`.
  - `run_script(node, task_dir, inputs) -> NodeResult`: create container from
    sandbox image with `network_mode: none` (or an `internal` compose network
    — pick one, document), mounts: input artifacts read-only, `output/`
    read-write, CPU/memory limits, timeout → container killed → node failed.
    Script receives artifact paths via env vars; writes outputs to
    `/workspace/output/{name}`.
  - Validation of declared outputs: file exists + parses when media type
    implies it; mismatch → node failed (deterministic nodes fail immediately,
    no retry — spec).
  - Persistence: compute sha256, insert `artifacts` row (provenance:
    node_id/iteration/attempt) — activity writes via the artifact repository
    (worker-side DB session; `Proposal`: worker imports domain repositories
    directly — same monorepo; record in decisions table).
  - API: `GET /tasks/{task_id}/artifacts`, 
    `GET /tasks/{task_id}/artifacts/{artifact_id}/download` (FileResponse;
    permission check per WP-09 model).
- Dependencies / file ownership / execution order: needs WP-10 (activity
  seam, NodeResult). Owns `worker/activities/{sandbox,artifacts}.py`,
  `domain/artifacts/**`, `api/routes/artifacts.py`, sandbox Dockerfile.
  Parallel-safe with WP-13/WP-14/WP-17 (disjoint files); WP-12 uses artifact
  presence for convergence.
- Required skills and why they apply: `python-testing-patterns` (docker-marked
  integration tests), `test-driven-development` (artifact logic first),
  `fastapi-python` (download endpoint).
- Tests / verification commands when known / expected evidence:
  - Unit: hashing + manifest + persistence with tmp dir + fake repo.
  - Integration `@pytest.mark.docker`: run a trivial script producing a file →
    artifact row + volume file + sha256 match; timeout case → failed node;
    no-network proof: script attempting outbound request fails.
  - `just test-backend` green; `docker compose build sandbox` succeeds.
- Completion criteria: seed workflow's script node completes end-to-end in
  compose; artifact downloadable via API with a runner token.
- Risks / assumptions / unresolved blockers: sandbox image contents (curated
  lib set) — keep minimal (stdlib + requests/pydantic) and record; Docker
  socket access from worker container on Windows (mount docker.sock or use
  `npipe` — document the chosen mechanism).

### WP-12 — Checkpoint single writer + recovery semantics
+
+> **R-04 remediation note (2026-09-30): DONE.** Reconciliation drops
+> checkpoint entries whose outputs are missing/fail hash re-verification
+> (re-execute rather than skip); execution activities consult durable
+> completion (artifact rows hash-verified) before rerunning — a retried
+> activity returns the recorded result (execution counter stays 1); artifact
+> persistence is idempotent by provenance (unique constraint 0008; matching
+> hash reuses the row, conflicting hash rejected); checkpoint publication
+> serialized with process locks + revision fencing (stale writers rejected,
+> identical completions idempotent). 139 tests green. Live kill/restart
+> evidence remains WP-20's; migration note: deployed DBs with duplicate
+> artifact provenance need cleanup before 0008.
+
+> **Coordinator note (2026-09-30): DONE and verified.** Versioned checkpoint
+> schema ({node_id}:{iteration} → attempt/outputs/artifact_hashes/recorded_at);
+> atomic writes (tmp + fsync + os.replace, directory fsync on non-Windows);
+> single writer via strictly awaited sequential activity calls; completion
+> dedup; startup load + skip of checkpointed iterations; convergence rule
+> (artifact row + file present but checkpoint missing → reconciled by hash,
+> never re-executed; hash conflict → error). 70 tests green. Live kill/restart
+> scenario deferred to WP-20's recovery_check; Docker Desktop volume fsync
+> durability not verified — noted for WP-20 evidence.
- Type / owner: development / developer
- Objective / acceptance IDs: One writer per task consumes queued completion
  records sequentially and publishes the checkpoint file atomically; restart
  or retry never re-executes nodes recorded in the checkpoint; concurrent
  completions lose nothing; a crash between artifact persistence and
  checkpoint publication converges on recovery. AC-07.
- Included scope / exclusions:
  - In: checkpoint schema in `shared/checkpoint.py`, writer activity,
    interpreter integration (queue completions; load on start/retry),
    reconciliation activity, unit/concurrency/integration tests.
  - Out: artifact persistence (WP-11), UI display of checkpoint.
- Files or modules / relevant context and existing patterns:
  - `backend/shared/checkpoint.py`, `backend/worker/activities/checkpoint.py`,
    `backend/worker/workflows/task_workflow.py` (queue + load + reconcile —
    serialize edits with WP-10 owner; this package follows WP-10),
    `backend/tests/worker/test_checkpoint.py`
  - Architecture §5 (checkpoint decision), §10 PoC item 2, spec "Task
    checkpoint".
- Changes / contracts / examples:
  - Checkpoint file: `{task_id}/checkpoint.json` on the task volume —
    `{"task_id", "version": int, "completed": {"{node_id}:{iteration}":
    {"attempt", "outputs", "artifact_hashes", "recorded_at"}}}`.
  - Write pattern: temp file + `os.replace` (atomic on same volume); writer
    activity invoked strictly sequentially by the interpreter (await previous
    writer before enqueueing next) — single writer guaranteed by workflow
    structure.
  - Convergence rule (make it explicit and test it): a node whose outputs
    exist on the volume + `artifacts` row exists but which is missing from
    the checkpoint is reconciled into the checkpoint on recovery (idempotent
    by artifact hash), never re-executed.
- Dependencies / file ownership / execution order: needs WP-10 (merged),
  WP-11 (artifact presence). Owns `shared/checkpoint.py`,
  `worker/activities/checkpoint.py`; edits `task_workflow.py` after WP-10.
  WP-15/WP-16 build on this merged interpreter.
- Required skills and why they apply: `test-driven-development`,
  `python-testing-patterns` (concurrency tests), `systematic-debugging` (if
  recovery cases misbehave).
- Tests / verification commands when known / expected evidence:
  - Unit: atomic replace (crash simulation between write and replace leaves
    old file valid), schema roundtrip, skip logic from loaded checkpoint.
  - Concurrency: enqueue N completion records concurrently → final file
    contains all N, no duplicates.
  - Integration (WorkflowEnvironment): run workflow, kill/cancel after
    artifact persistence but before checkpoint publish → rerun → node not
    re-executed (execution counter in a stub activity stays at 1) and
    checkpoint converges.
  - `just test-backend` green.
- Completion criteria: AC-07's three clauses each have a named passing test;
  manual compose kill/restart scenario documented in the package report (full
  automation in WP-20).
- Risks / assumptions / unresolved blockers: exact reconciliation needs the
  rules in `docs/research/execution-orchestration.md` — implementer should
  skim that section if present; deviations reported to coordinator.

---

### WP-13 — Capacity limits + FIFO admission
+
+> **R-09 remediation note (2026-09-30): DONE.** Agent-slot waiters persist in
+> `agent_slot_waiters` with a DB-generated ordering key — FIFO by insertion,
+> grant on release goes to the oldest waiter via its existing poll. Stop paths
+> fixed: stop during allocating → waiter removed → stopped (slot not granted
+> later); stop of a capacity-queued task without a live workflow → stopped
+> directly, excluded from admission; human-input cancellation → AI
+> orchestration exits as stopped, adapter closed, claim released. 141 tests
+> green (TDD red on FIFO ordering). Integration tests for the live
+> workflow-stop paths deferred to WP-20 follow-up.
+
+> **Coordinator note (2026-09-30): DONE and verified.** capacity_claims table
+> (advisory-lock serialized, FIFO by created_at then id); admission passes on
+> submission AND task completion; the WP-10 finding is addressed: queued tasks
+> whose workflow start failed are re-attempted by later admission passes
+> (claims released on start failure). KOSMO_MAX_MAIN_TASKS=3 /
+> KOSMO_MAX_AGENTS=2; agent slots via acquire/release activities with
+> allocating↔running transitions; AI-node hook in task_workflow.py.
+> `just test-backend` green: 65 passed, 2 skipped. Known limitation (recorded
+> for review): retry passes are event-triggered only — a queued task with no
+> later events can wait; periodic sweep deferred (acceptable for phase 1).
+> Live four-task scenario deferred to WP-20 (E2E).
- Type / owner: development / developer
- Objective / acceptance IDs: Global limits (max main tasks, max agents) as
  configured settings with small defaults; exceeding max tasks keeps the task
  `queued` with FIFO admission; an agent node without agent capacity leaves
  the task in `allocating` until a slot frees. AC-09.
- Included scope / exclusions:
  - In: `domain/scheduling/` (models/repository/service), settings additions,
    admission on submission + FIFO sweeper, agent-slot acquire/release
    activities, interpreter hook before AI nodes, migration.
  - Out: per-group limits, per-workflow concurrency (later phases).
- Files or modules / relevant context and existing patterns:
  - `backend/app/domain/scheduling/{models,repository,service}.py`,
    `backend/app/core/config.py` (add `KOSMO_MAX_MAIN_TASKS` default 3,
    `KOSMO_MAX_AGENTS` default 2), `backend/worker/activities/capacity.py`,
    `backend/worker/workflows/task_workflow.py` (pre-AI-node hook —
    serialize), migration, `backend/tests/domain/test_scheduling.py`
  - Spec "Task execution" (capacity + states), architecture §3 (scheduling
    area).
- Changes / contracts / examples:
  - Mechanism `Proposal` (record): DB-backed claims — `capacity_claims` table
    (id, task_id, kind: "main_task"|"agent_slot", claimed_at) with a unique
    constraint + transactional claim query ordered by task `created_at`
    (FIFO). Admission: `POST /tasks` always creates `queued`; a FIFO
    admission pass (on submission + `just`-invocable or Temporal schedule)
    starts workflows for queued tasks while `count(main_task) < limit`.
  - Agent slots: before an AI node runs, the interpreter calls
    `acquire_agent(task_id)` activity → granted → proceed; not granted →
    interpreter sets task/node state `allocating` (activity) and retries on a
    deterministic timer (workflow sleep) until granted; `release_agent` on
    node completion (success or failure). Keep the retry interval
    workflow-deterministic (e.g. `workflow.sleep(5)`).
- Dependencies / file ownership / execution order: needs WP-09 (tasks),
  WP-10 (interpreter hook point). Owns `domain/scheduling/**`,
  `worker/activities/capacity.py`. Must land before WP-15 (AI node) uses
  acquire/release; `task_workflow.py` edits serialized (after WP-12).
- Required skills and why they apply: `test-driven-development`, 
  `python-testing-patterns` (FIFO order, limit boundary cases), 
  `python-design-patterns` (small claim service).
- Tests / verification commands when known / expected evidence:
  - TDD with fake repo: tasks admitted strictly by created_at; limit
    respected; release frees exactly one slot; next waiter proceeds;
    `allocating` set while waiting and cleared on grant.
  - `just test-backend` green.
- Completion criteria: AC-09 behaviors demonstrated by service tests +
  compose manual check (submit limit+1 tasks → last stays queued).
- Risks / assumptions / unresolved blockers: sweeper mechanism choice
  (Temporal schedule vs on-submission hook) — implementer picks the simpler
  working option and reports it.

### WP-14 — Agent adapter interface + OpenCode ACP adapter
+
+> **R-06 remediation note (2026-09-30): DONE.** Agent containers: CPU 1.0 /
+> memory 512m (configurable KOSMO_AGENT_CPU/MEMORY), non-root 10001:10001,
+> read-only root filesystem with writable /tmp + config/state tmpfs,
+> capabilities dropped, no privilege escalation, kosmo-agent-local only.
+> Residual risk (recorded for the architecture doc): Docker Desktop bridge
+> networks do NOT filter destinations — agents can reach arbitrary internet
+> hosts; destination-level egress filtering requires a proxy/firewall layer
+> (phase-2 security backlog). Live docker-inspect evidence of effective limits
+> pending a real agent-container creation.
- Type / owner: development / developer
- Objective / acceptance IDs: Runtime adapter interface plus an OpenCode
  adapter speaking ACP: container launch, session start, prompt delivery,
  event normalization to the internal event model, completion request,
  validation-feedback delivery, artifact retrieval from the mounted output.
  AC-04 (agent round trip).
- Included scope / exclusions:
  - In: `shared/agent_events.py` (internal event model),
    `worker/adapters/base.py` (protocol), `worker/adapters/opencode_acp.py`,
    `worker/activities/agent.py` (container lifecycle driving the adapter),
    OpenCode agent image (`backend/docker/opencode/Dockerfile`),
    fake-transport unit tests.
  - Out: validation loop (WP-15), input-request handling (WP-16), Claude/
    Codex adapters (non-goal).
- Files or modules / relevant context and existing patterns:
  - `backend/shared/agent_events.py`, `backend/worker/adapters/{base,
    opencode_acp}.py`, `backend/worker/activities/agent.py`,
    `backend/docker/opencode/Dockerfile`, `backend/tests/worker/test_adapters.py`
  - Architecture §5 (AI row: adapter bridges to common internal model),
    spec "Agent interaction proof".
- Changes / contracts / examples:
  - Protocol `AgentRuntimeAdapter`: `start_session(cfg) -> SessionHandle`,
    `send_prompt(text)`, `events() -> AsyncIterator[AgentEvent]`,
    `request_completion(expected_artifacts: list[ArtifactContract]) ->
    CompletionResult`, `deliver_feedback(errors: list[ErrorDetail])`,
    `collect_artifacts() -> dict[str, ArtifactRef]`.
  - Internal event model (shared, bounded persistence later):
    `AgentStarted | AgentText(delta) | AgentToolUse(name) |
    InputRequested(payload: {message_key, params}) |
    CompletionProposed(artifacts) | AgentError(message_key, params)`.
  - ACP mechanics: agent container per execution; adapter talks JSON-RPC/ACP
    over the container's stdio via Docker exec; network scope allows runtime
    API egress + platform endpoints only (architecture §6). Container mounts
    task workspace + declared artifacts (output dir writable).
  - Normalization is pure and unit-tested: raw ACP frames → internal events.
- Dependencies / file ownership / execution order: needs WP-10 (activity
  infra). Owns `worker/adapters/**`, `shared/agent_events.py`,
  `worker/activities/agent.py`, opencode Dockerfile. Parallel-safe with
  WP-11/WP-13/WP-17 (disjoint files). WP-15/WP-16 consume.
- Required skills and why they apply: `python-design-patterns` (adapter
  protocol, pure normalization), `python-testing-patterns` (fake transport),
  `test-driven-development`.
- Tests / verification commands when known / expected evidence:
  - Unit with a scripted fake ACP transport: session start, prompt, event
    sequence normalization, completion request returns proposed artifacts,
    feedback delivery frame correct.
  - Integration `@pytest.mark.docker` (may require an OpenCode image +
    credentials — mark skipped if unavailable and say so honestly): real
    container start → prompt → completion round trip.
  - `just test-backend` green.
- Completion criteria: adapter protocol + OpenCode implementation with green
  unit tests; docker-marked round-trip status reported (pass or explicitly
  skipped with reason).
- Risks / assumptions / unresolved blockers: ACP frame details for OpenCode's
  current version; image build needs network at build time — keep the image
  thin and document; API keys via env at container creation (never logged).

---

### WP-15 — AI node execution: validation levels, correction cycles, validator MCP
+
+> **RR-01 remediation note (2026-10-01): DONE.** One canonical validator:
+> validation_logic.py is the single implementation; activities/validation.py
+> re-exports it (import-identity test). Regex escaping fixed; L3 source
+> artifacts resolve from the staged workspace/inputs/ via the R-05 safe-path
+> helper; missing staged source → structured L3 failure. Probe case
+> (unrelated summary.md) now fails L2/L3. 155 tests green.
+
+> **R-10 remediation note (2026-09-30): DONE.** MCP persistence moved behind
+> ValidatorRepository (task/artifact repositories + node-execution lookup);
+> shared validation relocated to app.domain.workflows.validation_logic (API +
+> worker import from the domain layer); MCP auth/permission/not-found and
+> malformed event cursors standardized on keyed KosmoError envelopes
+> ({code, message_key, params, details}); script output/exception text stays
+> in server logs only; AI infra failures logged with stacktraces. 147 backend
+> tests green; route modules thin.
+
+> **R-03 remediation note (2026-09-30): DONE.** The seeded validation contract
+> is now effective: L2 required_sections (exact case-insensitive heading
+> match, configurable levels #–######; seed allows #/##) and L3 content_rule
+> (deterministic bounded supported-claims check: each non-empty summary
+> sentence must share a ≥4-char alphanumeric token with report.md —
+> documented limitation: rejects valid paraphrases / may accept vocabulary
+> overlap; semantic entailment is out of scope). Validation failures flattened
+> into details with attempt+artifact+level+message_key+params; feedback
+> delivered to the adapter as JSON records over the existing session/prompt
+> text surface. The review's probe (unrelated summary.md) now fails L2/L3.
+> 117 tests green. Frontend must render detail params {reason, sections,
+> input_artifact, claims} and note params {attempt, level, details} — flag
+> for R-08.
+
+> **Coordinator note (2026-09-30): DONE and verified (fake-adapter scope).**
+> Validation.py (L1 format/L2 structure/L3 business rules per contract;
+> KOSMO_E2E_FAIL_VALIDATION forcing flag for WP-20), ai_node.py orchestration
+> (adapter session kept alive across corrections; deliver_feedback per failed
+> cycle + revisioned notes with SSE task.note events; artifacts persisted with
+> sha256 + checkpoint completion after success; exhaustion after 3 failed
+> cycles → errors.node.validation_exhausted with per-attempt details, no
+> stacktrace), AI dispatch registered in task_workflow.py, validator MCP
+> endpoint (artifact-id + level, Bearer auth). 75 tests green; worker clean
+> after restart. LIVE OpenCode round trip NOT run: OPENCODE_API_KEY unset in
+> this environment — flagged for the owner (provide the key to run the real
+> agent path) and WP-20. Validator rule conventions (required fields/terms)
+> are the phase-1 language; a general rule DSL is later-phase scope.
- Type / owner: development / developer
- Objective / acceptance IDs: AI nodes run the adapter with the full
  expected-artifact contract; completions pass three-level validation; failed
  validations feed back through the adapter (title/detail) and are recorded
  as task notes; after 3 failed validations the node and task fail with a
  structured error (short cause + per-attempt detail trail, no stacktrace);
  successful outputs persist with provenance and flow into the checkpoint.
  AC-04 (validation, persistence), AC-05.
- Included scope / exclusions:
  - In: `worker/activities/validation.py` (three-level validator driven by
    the AI node's `ValidationContract`), `worker/activities/ai_node.py`
    (orchestration: adapter → completion → validate → feedback loop), minimal
    validator MCP endpoint (`/mcp/validator`) so agents can self-check,
    task-note writes per cycle.
  - Out: adapter itself (WP-14), checkpoint writer (WP-12), notes UI (WP-18).
- Files or modules / relevant context and existing patterns:
  - `backend/worker/activities/{validation,ai_node}.py`,
    `backend/app/api/routes/mcp.py` (validator tool, minimal MCP-over-HTTP
    surface), `backend/tests/worker/test_ai_node.py`
  - Architecture §5 (AI row: validator MCP mounted; 3 failed validations →
    node failed), spec "Task execution" + AC-05.
- Changes / contracts / examples:
  - Cycle flow: prompt includes contract + validator endpoint; on
    `CompletionProposed` → run L1 (existence/parse), L2 (schema), L3 (content)
    against declared outputs; any failure → `deliver_feedback([ErrorDetail per
    failing level])` + task note (revisioned, `message_key`
    `tasks.notes.validation_failed` with attempt + level params) → next cycle.
    Cycle 4 (i.e., after 3 failed validations) → node failed; task failed
    with `KosmoError`-shaped payload: top-level short cause
    (`message_key="errors.node.validation_exhausted"`, params: node, attempts:
    3) + `details[]` one entry per attempt with per-level keys; stacktrace
    only in logs (WP-03 contract).
  - Deterministic note per attempt also on success path
    (`tasks.notes.validation_passed`).
  - Validator MCP: exposes `validate(artifact_ref, level)` backed by the same
    validation service — single implementation, two surfaces.
- Dependencies / file ownership / execution order: needs WP-11 (artifact
  persistence), WP-13 (agent slot acquire/release), WP-14 (adapter), WP-12
  (completion records). Owns `worker/activities/{validation,ai_node}.py`,
  `api/routes/mcp.py`. `task_workflow.py` dispatch edits serialized (this
  package after WP-12/WP-13 merged); WP-16 follows on the same file.
- Required skills and why they apply: `test-driven-development` (cycle logic
  with fake adapter), `python-testing-patterns`, `fastapi-python` (MCP route),
  `systematic-debugging` (if real-agent cycles misbehave).
- Tests / verification commands when known / expected evidence:
  - TDD with fake adapter + tmp volume: pass-first-cycle → artifact persisted,
    checkpoint record, success; fail×3 → exactly 3 notes, 4th cycle not
    requested, task failed with 3 `details` entries and correct keys; no
    stacktrace in the stored/returned error.
  - `just test-backend` green; compose E2E: seed workflow's AI node completes
    with a real OpenCode agent producing `summary.md` (manual evidence if
    real-agent flakiness; automated in WP-20).
- Completion criteria: AC-04 validation+provenance and AC-05 behaviors pass
  as named tests; real-agent round trip demonstrated or its blocker reported.
- Risks / assumptions / unresolved blockers: real OpenCode behavior
  (non-determinism) — tests use fakes for logic; real-agent check is evidence,
  not the gate. MCP-over-HTTP library choice (keep it a thin JSON tool
  endpoint; no heavy MCP SDK unless trivially available) — report choice.

### WP-16 — Human input round trip + stop semantics
+
+> **RR-04 evidence note (2026-10-01): DONE.** Durable-input storage boundary
+> tests added (backend/tests/worker/test_input_storage_boundary.py):
+> record→pending→delivered-once against the real migrated kosmo_test DB,
+> duplicate-answer rejection, stale-request rejection, recovery delivery
+> (persisted answer delivered by the resumed poll), and stop-at-wait
+> cancellation (background thread marks stopping once the activity is
+> polling → activity returns None). 5/5 pass inside the backend container;
+> skipped on the Windows host (documented connection-reset quirk). Residual:
+> full WorkflowEnvironment restart-replay evidence deferred (platform
+> limitation recorded).
+
+> **Coordinator note (2026-09-30): DONE and verified (service/unit scope).**
+> POST /tasks/{id}/input + /stop endpoints (submitter/admin), Temporal Update
+> `human_input` + Signal `stop`, answers stored durably in task_notes.params
+> with a delivered marker + recovery polling (no migration needed), AI activity
+> surfaces InputRequested via a polling callback while keeping the session
+> alive, run_worker registration. Policies: duplicate answers rejected while
+> one is undelivered; answers only accepted in waiting_for_input; stop during
+> waiting → immediate stopped. `just test-backend` green: 80 passed, 2
+> skipped. Honest gaps: exactly-once delivery is NOT guaranteed (worker death
+> between delivery and delivered-marker → redelivery on recovery — recorded
+> for review); WorkflowEnvironment restart/stop evidence deferred to WP-20.
- Type / owner: development / developer
- Objective / acceptance IDs: An agent input request flips the task to
  `waiting_for_input`; answering via the API resumes execution; the answer is
  durably recorded before delivery and survives a worker restart before
  delivery. Plus PoC stop semantics (`stopping`/`stopped`, immediate stop for
  a node waiting for input). AC-06 (+ spec stop path).
- Included scope / exclusions:
  - In: Temporal Update/Signal handlers on the root workflow, `POST
    /tasks/{id}/input` and `POST /tasks/{id}/stop` endpoints, durable answer
    recording activity (DB + task note) before delivery, resume logic
    (on restart, undelivered answers are read from the DB), adapter
    `deliver_answer` plumbing, stop handling in the interpreter.
  - Out: chat UI (phase 2), retry/clone commands.
- Files or modules / relevant context and existing patterns:
  - `backend/worker/workflows/task_workflow.py` (Update `human_input`, Signal
    `stop` — serialize with WP-15 owner), `backend/worker/activities/input.py`,
    `backend/app/api/routes/tasks.py` (add endpoints — serialize with WP-09),
    `backend/app/domain/tasks/service.py` (record_answer, request_stop),
    `backend/tests/worker/test_human_input.py`
  - Architecture §5 (human interaction via Signals/Updates; stop exception
    for waiting-for-input), spec AC-06.
- Changes / contracts / examples:
  - Flow: adapter `InputRequested` → workflow Update-waiter opens; task state
    `waiting_for_input` (activity) + note (`tasks.notes.input_requested`);
    `POST /tasks/{id}/input {answer}` → `record_answer` activity persists
    answer (task_notes + dedicated `task_inputs` row or note params —
    implementer picks, keep queryable) → Update completes → workflow delivers
    answer to adapter → task `running`.
  - Durability rule: answer is persisted via activity BEFORE the Update
    resolves; on workflow replay/restart the waiter re-queries the DB for an
    undelivered answer and proceeds without a new API call.
  - Stop: `POST /tasks/{id}/stop` → Signal → task `stopping`; interpreter
    finishes the active node then `stopped`; if state is
    `waiting_for_input`, stop immediately → `stopped` (spec exception).
- Dependencies / file ownership / execution order: needs WP-15 (adapter
  events + interpreter dispatch merged), WP-09 (tasks service/routes).
  Owns `worker/activities/input.py`; coordinated edits on
  `task_workflow.py` and `api/routes/tasks.py` (last writer merges).
- Required skills and why they apply: `test-driven-development`, 
  `python-testing-patterns` (WorkflowEnvironment update + restart tests),
  `fastapi-python`.
- Tests / verification commands when known / expected evidence:
  - TDD (WorkflowEnvironment + fake adapter): input request → state
    `waiting_for_input`; Update delivers answer → resumed; kill simulation
    (cancel + rerun) after persist-but-before-delivery → answer delivered on
    recovery exactly once; stop during running node → `stopped` after node
    completes; stop while waiting → immediate `stopped`.
  - `just test-backend` green.
- Completion criteria: AC-06 clauses covered by named tests; compose manual
  round trip recorded.
- Risks / assumptions / unresolved blockers: Temporal Update API version
  nuances — if Updates are unstable, fall back to Signal + DB poll with the
  same durability rules and report the substitution.

---

### WP-17 — SSE endpoints + event publishing
- Type / owner: development / developer
- Objective / acceptance IDs: SSE streams push task/node state changes (and
  notes) with header JWT auth and `Last-Event-ID` reconnection; events are
  persisted so reconnects replay from the last seen id. AC-08 (backend).
- Included scope / exclusions:
  - In: `task_events` table + `domain/events/` service (publish + replay),
    `api/routes/events.py` (`GET /tasks/events` list stream, `GET
    /tasks/{id}/events` detail stream), emission hooks from task/node state
    transitions (worker activities + app services call the events service),
    migration, streaming tests.
  - Out: SPA consumption (WP-18), WebSocket (reserved for agent chat, later).
- Files or modules / relevant context and existing patterns:
  - `backend/app/domain/events/{models,repository,service}.py`,
    `backend/app/api/routes/events.py`, `backend/app/domain/tasks/service.py`
    (emission hook — one-line, coordinate), `backend/worker/activities/state.py`
    (emit on node/task transitions — coordinate with WP-10 owner),
    `backend/tests/api/test_events_stream.py`
  - Architecture §7 (SSE, header auth, Last-Event-ID), §9 (SSE decided).
- Changes / contracts / examples:
  - Wire format (Proposal — record): 
    `event: task.state | node.state | task.note`; `id:` = monotonic
    `task_events.id`; `data:` = `{"task_id": "...", "node_id": "...|null",
    "state": "...", "note": {message_key, params}|null, "at": ISO8601}`.
    Heartbeat comment every ~15 s. `Last-Event-ID` header replays events with
    id > given value from the DB, then live.
  - Auth: same `Authorization: Bearer` dependency as other routes (header
    auth mandatory for SSE — architecture §7); clients use fetch-based SSE
    since `EventSource` cannot set headers.
- Dependencies / file ownership / execution order: needs WP-09 (states),
  WP-10 (transition emission points). Owns `domain/events/**`,
  `api/routes/events.py`. Parallel-safe with WP-13/WP-14 (disjoint files);
  WP-18 consumes.
- Required skills and why they apply: `fastapi-python` (StreamingResponse),
  `python-testing-patterns`, `test-driven-development`.
- Tests / verification commands when known / expected evidence:
  - TDD (httpx AsyncClient streaming): subscribe → publish two events →
    receive in order with ids; reconnect with `Last-Event-ID` replays only
    newer events; 401 without token; heartbeat present.
  - `just test-backend` green; manual curl shows `data:` lines during a task
    run.
- Completion criteria: streams authenticated, replayable, ordered; emission
  wired for task and node transitions.
- Risks / assumptions / unresolved blockers: none blocking; keep payloads
  minimal (no artifact content over SSE).

### WP-18 — Task views UI: list, detail, SSE live updates, localized labels
+
+> **RR-02/RR-03 remediation notes (2026-10-01): DONE.** Artifact downloads
+> go through authenticatedFetch (bearer + single-flight refresh; blob +
+> revoked object URLs; never tokens in URLs) — RR-02. The failure trail
+> renders the ACTUAL response shape: node_executions[].error localized under
+> each node and note params (attempt/level/details) in TaskNotes; dead
+> top-level task.error dependency removed — RR-03. Catalogs carry all
+> emitted keys (en/es). 36 frontend tests green; build green.
+
+> **R-08 remediation note (2026-09-30): DONE.** All task requests now route
+> through the shared typed openapi-fetch client with auth middleware (SSE uses
+> authenticatedFetch for single-flight renewal on 401); input answers send
+> node_execution_id + request_id from the pending note; unknown-task list
+> events trigger refetch; polling-restart lifecycle fixed; task pages
+> refactored into bounded components (TaskList/StateBadge/NodeTimeline/
+> TaskNotes/TaskArtifacts/TaskInputForm/WorkflowSummary); mojibake arrow
+> removed; errors.provider.* keys added (en/es); safe-DTO workflow_name used.
+> 34 frontend tests green; build green; live deep-link reload restore verified.
+
+> **Coordinator note (2026-09-30): DONE and verified.** Task list (badges,
+> live updates, FIFO-visible), detail (node timeline with localized node
+> errors — "Agent runtime failed. · RuntimeError" rendered live, notes feed,
+> artifacts with download), real creation flow (workflow summary + dynamic
+> start-form fields), fetch-based SSE hook with Last-Event-ID + backoff +
+> polling fallback, stop with confirm, input-answer form for waiting tasks.
+> 26 frontend tests green; build green; live browser verification done by the
+> coordinator (login → create → run → failed-with-localized-trail → artifacts;
+> responsive 375/768/1280 incl. drawer). Deviations recorded: local state +
+> refetch instead of TanStack Query (deferred to architecture review); fixes
+> during integration: SSE/list race (events before load trigger a refetch),
+> stale AppShell assertions, mojibake in es.json. Known UX gap: deep links
+> after a full page reload lose the target URL (guard redirects to /tasks/new
+> after silent-refresh restore) — deferred to phase 2.
- Type / owner: design / designer
- Objective / acceptance IDs: Task list and task detail views update in real
  time via SSE without manual refresh; state changes render localized labels
  in en/es; detail view shows nodes, notes (including validation correction
  cycles), artifacts with download, and an answer form when the task is
  waiting for input; minimal submit flow (choose seeded workflow, fill input
  form). AC-08 (SPA), surfaces for AC-03/05/06/09.
- Included scope / exclusions:
  - In: `features/tasks/` (list page, detail page, submit dialog, node
    timeline, notes feed, artifacts list, input-answer form, state badges),
    `useTaskStream` SSE hook (fetch-based, header auth, `Last-Event-ID`
    reconnection, polling fallback on connection gap), TanStack Query cache
    updates from the stream, i18n additions (`tasks.*`, `task.state.*` en/es),
    router entries.
  - Out: workflow editor (non-goal), auth flow (WP-06), E2E automation
    (WP-20).
- Files or modules / relevant context and existing patterns:
  - `frontend/src/features/tasks/**`, `frontend/src/api/` (regenerate client,
    consume generated types), `frontend/src/i18n/{en,es}.json` (extend),
    `frontend/src/app/` (routes)
  - Architecture §7 (SSE + TanStack Query cache updates, polling fallback,
    feature folders, shadcn primitives), spec AC-08.
- Changes / contracts / examples:
  - Hook contract: subscribe on mount, apply `task.state`/`node.state`/
    `task.note` events to the query cache; on error → exponential backoff
    reconnect with `Last-Event-ID`; after N failures fall back to query
    polling until reconnect succeeds.
  - State labels: `task.state.queued|running|waiting_for_input|stopping|
    stopped|failed|success|allocating` in both catalogs (keys only; states
    are language-independent identifiers per architecture §8).
  - Submit dialog: pick active workflow, render start-node input form fields,
    `POST /tasks`, navigate to detail.
- Dependencies / file ownership / execution order: needs WP-17 (streams),
  WP-06 (auth), WP-02 (shell), regenerated client (WP-05/08/09/11 endpoints
  exist). Owns `frontend/src/features/tasks/**` + i18n additions (merge with
  WP-02's catalogs — this package appends keys only).
- Required skills and why they apply: `impeccable` (primary design skill),
  `vercel-react-best-practices` (cache updates, subscriptions, rendering).
- Tests / verification commands when known / expected evidence:
  - Vitest + RTL with a mocked SSE source: state badge updates without
    reload; labels swap en/es; waiting_for_input renders the answer form and
    submitting calls the API; failed task shows localized note trail
    (message_keys resolved via catalogs).
  - `just test-frontend` green.
- Completion criteria: manual compose session shows live updates on two
  browser windows; both catalogs complete for all new keys (no missing-key
  warnings); list and detail views are responsive and usable on a mobile
  viewport (owner requirement — verify at 375px width, including the answer
  form and notes feed).
- Risks / assumptions / unresolved blockers: none blocking; keep components
  small and reuse shadcn primitives from WP-02.

---

### WP-19 — CI pipeline (GitHub Actions)
+
+> **RR-05 remediation note (2026-10-01): DONE.** The backend CI job now
+> provisions a health-checked PostgreSQL 18 service and sets
+> KOSMO_TEST_DATABASE_URL to kosmo_test, so RR-04's durable-input boundary
+> tests run on Linux CI (the obsolete "no PostgreSQL needed" comment is
+> corrected). Compose config still validates. Host evidence: backend suite
+> green (155 passed, 8 skipped — 5 boundary tests skip on Windows by design
+> and run in CI/container). First real hosted CI run remains to be observed
+> (recorded limitation).
- Type / owner: development / developer
- Objective / acceptance IDs: On push/PR, CI runs backend tests, frontend
  tests, and the client-regeneration check. AC-10 (CI clause).
- Included scope / exclusions:
  - In: `.github/workflows/ci.yml` with jobs: backend (`astral-sh/setup-uv`
    → `uv sync` → `pytest`), frontend (`pnpm install --frozen-lockfile` →
    `vitest run`), client-regen check (start backend briefly or use committed
    OpenAPI snapshot → `openapi-typescript` → `git diff --exit-code` on
    generated files), compose config lint.
  - Out: docker-marked integration tests and Playwright in CI (local-only
    for phase 1; revisit later — record as known limitation).
- Files or modules / relevant context and existing patterns:
  - `.github/workflows/ci.yml` (new); may add `just ci` aggregation recipe.
- Changes / contracts / examples:
  - Regen-check strategy `Proposal`: commit the generated `schema.d.ts`;
    CI regenerates from the backend's exported OpenAPI (via a tiny pytest
    fixture that dumps `app.openapi()` to JSON, no server needed) and fails
    on diff. Keep it dependency-light and deterministic.
- Dependencies / file ownership / execution order: needs WP-01 (recipes),
  WP-05+ (backend tests meaningful), WP-06 (generated client committed).
  Owns `.github/**` only. Can be built incrementally once backend+frontend
  test suites exist (after WP-06/WP-07 wave).
- Required skills and why they apply: `verification-before-completion`
  (verify the pipeline on a real push, not assumed green).
- Tests / verification commands when known / expected evidence:
  - Evidence: green run on GitHub (or `act` locally if unavailable — report
    which) for a push containing an intentional test failure → red, fix →
    green; regen check red when client is stale.
- Completion criteria: pipeline green on main; failing tests or stale client
  block merge.
- Risks / assumptions / unresolved blockers: GitHub runners have no Docker
  Desktop-side containers for marked tests — unit-only scope accepted for
  phase 1; Postgres-service container optional if DB-backed tests need it
  (add `services: postgres` if conftest requires a live DB).

### WP-20 — Integrated E2E verification suite
- Type / owner: test / tester
- Objective / acceptance IDs: Automated end-to-end evidence across the
  running compose stack for the user-visible ACs and a scripted worker-kill
  recovery check. AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-09
  (E2E locus; AC-07 via the recovery script).
- Included scope / exclusions:
  - In: Playwright setup (`frontend/e2e/`, `playwright.config.ts`, `just e2e`),
    specs: login + language switcher (AC-01/02), submit task → live state
    transitions → artifacts listed/downloadable (AC-03/04/08), validation
    failure path shows note trail + structured failure without stacktrace
    (AC-05), answer input request (AC-06), capacity queue observation
    (AC-09, low max limits). Plus `scripts/recovery_check.py`: API-driven
    scenario that kills/restarts the `worker` compose service mid-task and
    asserts no re-execution + convergence (AC-07) — may use docker CLI via
    subprocess; runs locally, not CI.
  - Out: new product code; fixing bugs found (report them to the coordinator
    as findings — remediation packages get planned).
- Files or modules / relevant context and existing patterns:
  - `frontend/e2e/*.spec.ts`, `frontend/playwright.config.ts`, `justfile`
    (`e2e` recipe), `scripts/recovery_check.py`, `docs`-level run instructions
    in the package report (README updates happen via documentator later).
- Changes / contracts / examples:
  - Fixtures: seeded admin/runner credentials from env; base URLs from
    compose; deterministic seed workflow; for AC-05 the seed's AI validation
    contract must have a forcing mechanism (e.g. env `KOSMO_E2E_FAIL_VALIDATION=1`
    read by the validator activity) so failure paths are reproducible —
    coordinate the flag with WP-15 (single owner adds it: WP-15 implements,
    WP-20 consumes).
- Dependencies / file ownership / execution order: after all implementation
  packages (WP-01..WP-19). Owns `frontend/e2e/**`, `scripts/recovery_check.py`,
  adds the `e2e` justfile recipe (serialize justfile edits).
- Required skills and why they apply: `python-testing-patterns` (recovery
  script assertions), `verification-before-completion` (evidence before
  claims).
- Tests / verification commands when known / expected evidence:
  - `just e2e` green on Windows/Docker Desktop; `uv run python
    scripts/recovery_check.py` prints a per-assertion report; flaky runs
    retried once and reported honestly.
- Completion criteria: every AC-01..AC-09 has a named automated check or an
  explicit, honest manual-evidence note in the report; findings list handed
  to the coordinator.
- Risks / assumptions / unresolved blockers: real OpenCode agent variability —
  prefer the validation-forcing flag over prompt-tuning; Playwright in CI is
  out of scope (WP-19); recovery script needs Docker access from the host.

---

## Execution order and parallelization

Serial spine (spec's phase ordering): WP-01 → WP-03 → WP-04 → WP-05 → WP-08
→ WP-09 → WP-10 → WP-12 → WP-15 → WP-16 → WP-20.

Parallelization opportunities (disjoint file ownership):

- Wave 1: WP-01 (alone).
- Wave 2: WP-02 (frontend) ∥ WP-03 (backend core).
- Wave 3: WP-04 → then WP-05 ∥ WP-07 (identity vs graph contracts; disjoint
  files).
- Wave 4: WP-06 (SPA auth) ∥ WP-08 (workflow persistence+seed). WP-19 may be
  drafted once WP-05+WP-06 merged.
- Wave 5: WP-09 (tasks) → WP-10 (interpreter).
- Wave 6 (after WP-10): WP-11 ∥ WP-13 ∥ WP-14 ∥ WP-17 (sandbox+artifacts /
  scheduling / adapter / SSE — disjoint files; none edits
  `task_workflow.py` yet). WP-12 starts after WP-11 (needs artifact
  presence) and edits `task_workflow.py` first among this generation.
- Wave 7: WP-15 (AI node; after WP-11/12/13/14) → WP-16 (input/stop; after
  WP-15 — both edit `task_workflow.py` and `api/routes/tasks.py`; serialize
  in that order).
- Wave 8: WP-18 (task UI; after WP-17 + WP-06).
- Wave 9: WP-20 (E2E + recovery evidence; after everything).

Serialization rules to respect:

- `justfile` and README edits: WP-01 creates; WP-05 (seed), WP-08 (seed),
  WP-20 (e2e) append — apply sequentially.
- `backend/app/api/routes/tasks.py`: WP-09 creates; WP-16 adds input/stop
  endpoints.
- `backend/worker/workflows/task_workflow.py`: WP-10 creates; WP-12, WP-13
  (hook), WP-15, WP-16 extend — order as waves above.
- i18n catalogs: WP-02 creates; WP-18 appends keys.
- CI (WP-19) can be prepared early but only declared done after backend and
  frontend suites exist.

## Decisions to be recorded in the architecture decisions table

Resolved in packages as `Proposal`s and reported back by workers (coordinator
records via documentator): JWT transport + client token storage (WP-05/06),
password hashing library (WP-05), Temporal namespace/task-queue naming
(WP-10), sandbox image contents + network mechanism (WP-11), worker→DB access
pattern (WP-09/11), capacity claim mechanism + sweeper style (WP-13), SSE
wire format (WP-17), MCP-over-HTTP surface for the validator (WP-15), Update
vs Signal fallback for human input (WP-16), task permission model (WP-09).

## Blocking questions

None blocking execution. All former spec open questions have a proposed
resolution inside a package; if any proposal proves infeasible during
implementation, the worker reports it and the coordinator returns it to the
architect for replanning rather than expanding scope silently.










