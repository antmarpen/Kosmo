# Phase 2 work packages — execution record

> Living document maintained by the coordinator. Source plan was produced by the
> architect (2026-10-01) and is reconstructed here with execution status so a
> context loss does not lose the wave plan. Spec: `phase-2-provider-editor.md`
> (Approved). Test design: `phase-2-test-design.md`.

## Waves and status

| Package | Type | Scope | Status |
| --- | --- | --- | --- |
| P2-18 | Test | Phase 2 acceptance test design + E2E stubs | DONE 2026-10-01 |
| P2-01 | Dev | Frontend deps (@xyflow/react 12.12.0, @monaco-editor/react 4.7.0) | DONE 2026-10-01 |
| P2-19 | Dev | Group membership roles, scope_policy.py, GET /auth/capabilities, migration 0011 | DONE 2026-10-01 |
| P2-20 | Dev | Schema v1 extension: DecisionNode, WorkflowNode | DONE 2026-10-01 |
| P2-02 | Design | Main sidebar navigation restructure | DONE 2026-10-01 |
| P2-03 | Dev | Provider APIs + candidate operations (role matrix, metadata-only GET, keyed errors) | DONE with recorded gap: candidate verify-model lacks real container path (needs worker activity); workaround save-then-verify |
| P2-04 | Dev | Per-user workflow drafts backend, migration 0012, optimistic revisions | DONE 2026-10-01 |
| P2-07 | Dev | Provider capability descriptor (OpenCode available; Claude/Codex coming soon) | DONE 2026-10-01 |
| P2-10 | Dev | Editor definition model (pure TS): serialization, defaults, client validation | DONE 2026-10-01 |
| P2-05 | Dev | Publication without auto-activation, explicit activation, 5-min confirmation, migration 0013 | DONE 2026-10-01 |
| P2-06 | Dev | Typed frontend boundaries: useCurrentUser, KosmoErrorAlert | DONE 2026-10-01 |
| P2-08 | Design | Provider config wizard UI + /providers list page | DONE 2026-10-01 (64 tests, build green; contract gap → P2-03b) |
| P2-11 | Dev | Editor canvas (React Flow), palette, bridge to P2-10 model, /workflows/:id/edit route | DONE 2026-10-01 |
| P2-13 | Dev | Node properties panel (per-type forms) | DONE 2026-10-01 (8 focused tests; suite reconciliation pending on P2-14 landing) |
| P2-12 | Dev | Monaco editor for Script nodes (lazy loaded) | IN FLIGHT (wave 2) |
| P2-15 | Dev | Draft integration in editor (save/load/revisions UI) | DONE 2026-10-01 |
| P2-16 | Dev | Publish/activate UI (confirmation + stale-base flows) | IN FLIGHT (wave 2) |
| P2-17 | Dev | i18n parity verification + router/route titles reconciliation | DONE (314/314 en/es parity, nav keys integrated) |
| P2-09 | Dev | Provider list actions (verify/delete) | IN FLIGHT (retry) |
| Editor layout | Design | Canvas 0 px at 800 px → 512 px at 768, 544 at 800, 743 at 999, static panels from 1024 | DONE 2026-10-02 (measured in real browser) |
| Launch workflow (create task) | Dev | `/tasks/new` matched the name against `id` and fell back to a version-less workflow → 404 | IN FLIGHT |
| P2-14 | Design | Workflow list page + editor entry points | DONE 2026-10-01 |
| P2-03b | Dev | Gap fix: persist selected_model, real model_count + verification_status in metadata (migration 0014) | DONE 2026-10-01 (174 backend tests; follow-up: config-verify endpoint does not update status, only model-verify does) |

## Navigation restructure (owner decision 2026-10-01)

- Groups: Tareas (unchanged), **Espacio de trabajo** (Flujos de trabajo,
  Aplicaciones, Contexto), **Catálogo** (Agentes, MCP, Habilidades,
  Extensiones, Proveedores), Administración (Auditoría, Configuración
  global). Implemented in `AppShell.tsx` with `nav.workspace` and
  `nav.catalog`; `/applications` added as a placeholder route. Coordinator
  direct execution; 120 frontend tests and `tsc --noEmit` green.
- Routes for agents/MCPs/skills/extensions remain under `/admin/*` (unchanged)
  to avoid deep-link churn; revisit only if the path should mirror the group.

## Provider onboarding (2026-10-01, coordinator) — working end to end

Five defects blocked provider onboarding; all are fixed and verified with the
owner's real files (39 models discovered, real container verification `ok` in
10.1 s, saved row shows `verified`):

1. **`KOSMO_CONFIG_ENCRYPTION_KEY` was unset**, so every provider-config
   write/read failed with 503 `errors.provider.storage_unavailable`. `.env`
   now defines a Fernet key; backend and worker share it.
2. **Candidate discovery was unimplemented**: `list_candidate_models` raised
   and only the worker has Docker access. Now the API stores an encrypted,
   single-use, 120 s candidate operation (migration
   `0015_candidate_operations`) and the worker consumes it, so credentials
   never enter the Temporal payload/history.
3. **Agent containers could not run OpenCode**: the root filesystem is
   read-only and only `.config/opencode` / `.local/share/opencode` were
   writable, so `opencode acp` died with EROFS on `.local/state` and `.cache`
   and the ACP stream closed instantly. Both directories now have tmpfs mounts.
4. **Provider models were unusable in the worker**: the string FK to `users.id`
   could not resolve because the worker loads only the provider module, raising
   `NoReferencedTableError` on every query. `provider_configs/models.py` now
   imports the identity models.
5. **Temporal invocation never worked**: the SDK's `execute_activity` requires
   an `id` and uses standalone activities, which the running server
   (1.31.1) does not support; the previous `client.close()` also did not exist.
   Probes now run inside `ProviderProbeWorkflow`, the project's standard
   workflow path.

Regression tests cover the tmpfs mounts, the standalone mapper configuration
(subprocess) and the probe-workflow invocation. Backend 196 passed / 8 skipped;
frontend 120 passed.

## Phase-2 additions made during execution (owner-approved)

- **Script code editing opens a modal** (2026-10-02): the properties panel shows
  a compact read-only script summary plus an **Edit script** button; the button
  opens a large modal with a lazily-loaded Monaco editor, with explicit Save
  (commits to the node model) and Cancel (discards). Monaco must load only when
  the modal is first opened and stay in its own build chunk.
- **Launch a workflow from the UI** (2026-10-02): `/tasks/new` must let the
  user pick a workflow and launch it. Root cause of the reported error: the
  page matched the workflow NAME against the `id` field, fell back to a
  version-less workflow, and the submission returned 404
  `errors.workflow.not_found`. Fix includes a real selector, disabling
  workflows without an active version, a `?workflowId=` deep link, honest
  error rendering, and a Run row action in the workflow list.

## Owner decisions on provider onboarding (2026-10-01, later)

- **A provider configuration stores no model.** Onboarding configures the
  config/auth files and proves the connection by choosing a model *for the
  test*; that model is not persisted on the provider. Model selection belongs
  to agent configuration, not to providers. The `selected_model` field is
  therefore removed from the provider contract.
- **Mandatory user-entered display name.** A provider carries a friendly name
  the user types (required, trimmed, 1..80 chars, no default and never the
  provider type). The list shows that name; the provider type stays separate.
- **Connection verification is mandatory before saving.** The wizard cannot
  save until a real container verification succeeds. The proof is not
  client-asserted: the verify call returns a short-lived `verification_id`, and
  the save records `verified` only when the uploaded config/auth match the
  operation that ran the test; otherwise the row is saved as `unverified`.
- **Wizard steps (owner-specified, in order):** (1) select provider type;
  (2) choose the configuration method for that provider — skipped entirely when
  the provider has only one method (OpenCode today: config file only);
  (3) provide the required data, including the mandatory display name;
  (4) validate the connection *and* that models can be listed, then show a
  model dropdown and run a validation with the model the user marks;
  (5) save (scope selection stays part of this step).
  No contract versioning: this remains the v1 provider configuration contract.
- **Verified live in the browser (2026-10-01)** with the owner's real files and
  `nan/qwen3.6`: 4 steps rendered for OpenCode (method step skipped), name
  required, connection verified in 6.5 s, saved row shows the user-entered name
  with `Verificado`, and the provider list no longer shows a models column.
  Backend 210 passed / 10 skipped; frontend 143 passed; catalog parity 314/314.

## Open gap found during the live run (2026-10-01)

AI nodes pass their own `agent.model` to the session. When it is `"default"`
(as in the seeded reference workflow), OpenCode picks its own per-session
default instead of the model selected in the provider wizard, and the seeded
`content_rule`/`supported_claims` validator is strict enough to fail a summary
whose source report is a stub — the reference task failed on attempt 3 with
`Internal error: OpenCode service failure`. A minimal workflow with an explicit
model and simple validation levels (`exists_and_parseable`,
`required_sections`, `required_terms`) completed with `success`.
Candidate fix to evaluate: resolve `"default"` to the provider configuration's
`selected_model` when starting an AI node.

## Owner configuration notes (structure only, no secrets)

- `~/.config/opencode/opencode.jsonc` uses the top-level key `providers`
  (plural) and has no `provider` map; credentials live in
  `~/.local/share/opencode/auth.json` (OAuth entries plus API keys).
- The container injects `opencode.json` into `.config/opencode` and
  `auth.json` into `.local/share/opencode`, which is where OpenCode reads them.

## Provider icons (2026-10-01)

- Provider marks now come from `@lobehub/icons` (already in the approved stack),
  replacing the hand-drawn SVGs: OpenCode, Claude Code and Codex, plus 130+
  other providers/tools available for future nodes and lists.
- Applied to the provider wizard type cards and the provider list rows.
- Import caveat: only the per-brand `components/*` entry points are imported.
  The package index also exports preview/combine/avatar widgets that pull
  `@lobehub/ui` and an emoji data set, which broke Vitest and would bloat the
  bundle. `components/Color` is safe (React + local style only).
- Colours: OpenCode mono in brand black `#000` (no colour variant ships),
  Claude Code `#D97757`, Codex gradient `#B1A7FF → #7A9DFF → #3941FF`.
  Codex's mono variant is white and invisible on light surfaces, so the
  colour variant is required for it.

## Dev HMR (resolved 2026-10-01)

- Root cause (proven in isolation): host edits reach the container files and
  their mtimes propagate, but no inotify events reach chokidar, so Vite's
  transform cache never invalidates and stale modules are served.
- Fix applied: Compose default `CHOKIDAR_USEPOLLING=true`, Vite polling with
  the default interval, `**/.pnpm-store/**` excluded, coarse 10s/15s intervals
  removed.
- Verified live on the main container: edits to `router.tsx`,
  `PlaceholderPage.tsx` and `AppShell.tsx` produced Vite `hmr update` events
  and the new navigation appeared in an already-open browser tab **without
  reload and without a container restart** (container start time unchanged).
- Note: earlier comment-string probes were invalid (transformed output drops
  comments) and the "mtimes never propagate" claim was wrong.

## Recorded gaps and follow-ups (for architect re-review)

0. **Editor selection loop (fixed 2026-10-01, coordinator)**: passing
   `selected` back through the React Flow nodes/edges props fought RF's
   internal selection store, producing an alternating []/[id] re-emit loop
   and "Maximum update depth exceeded". Fix: selection lives in RF's store,
   mirrored one-way via onSelectionChange; EditorPage's selection setter
   returns the current state when content is unchanged. Verified live:
   bounded selection events, properties panel opens, no crash.
0b. **Dev HMR investigation (not resolved)**: earlier conclusions that bind
   mount timestamps never propagate and polling reliably fixes HMR were not
   established. Comment-only probes are invalid because transformed modules
   can omit comments. Authenticated performance measurements found warm list
   requests around 17–24 ms and cold module loading around 1.5–2.1 seconds.
   Compose Watch is being tested in isolation with executable React changes,
   browser Fast Refresh/state preservation, and repeated timing samples.
   No replacement development topology has been integrated yet.

1. **Candidate verify-model** (P2-03): RESOLVED 2026-10-01 — candidate
   model discovery and verification now run through the worker activity
   (`list_opencode_candidate_models` / `verify_opencode_candidate_model`) via
   an encrypted single-use operation reference, and real container
   verification was confirmed against the owner's configuration.
2. **P2-05 concurrency**: five-minute rule uses latest version timestamp;
   concurrent version allocation not race-tested.
3. **Bundle size**: production bundle >500 kB; lazy-load the editor route
   (candidate remediation, pairs with P2-12 lazy Monaco).
4. **TDD red evidence** not captured for P2-03 candidate tests and some P2-05
   follow-ups.
5. **Verification status semantics** (P2-03b): config-level verify endpoint
   leaves stored verification status unchanged; only the model-verification
   endpoint updates it. Confirm intended behavior at re-review.
6. **P2-15 draft load/save (landed 2026-10-01, coordinator)**: the editor now
   resolves a draft (requested `?draftId`, else the author's most recent, else
   creates one), loads its `definition` + `layout`, saves atomically with
   `expected_revision` and `validate=true`, and surfaces revision conflicts and
   server validation issues (as a localized alert block, not yet mapped
   per-node — that remains AC-P2-05). Backend adjustment: `create_draft` now
   seeds from the active version, else the latest published version, so a
   just-published workflow's draft is not empty. Drafts whose definition is
   still empty fall back to the blank start/end seed in the UI.
7. **Workflow access control (open, future phase)**: workflows have no
   owner/scope, so reads are open to any authenticated user and any builder can
   create a draft on any workflow. The editor correctly surfaces 404 for
   nonexistent workflows/drafts and for other users' drafts, and 403 for
   insufficient roles, but per-workflow visibility is unmodeled. Documented as
   a pending decision in `docs/context/project.md` (item 11). Follow-up: add
   `errors.auth.forbidden` to the en/es catalogs so role-denied responses show
   a specific message instead of the generic fallback.

## Verification checkpoints

### HMR-01 — Conditional integration plan

- Status: awaiting the isolated Compose Watch proof; no implementation claim.
- Objective: keep Vite inside Docker and update rendered React content from
  Windows edits without manual reloads or source-edit container restarts.
- Proposed ownership: developer owns development Compose configuration,
  `frontend/Dockerfile.dev`, Vite watch configuration, frontend build ignores,
  affected production overrides, and justfile development commands.
- Proposed transport: remove the frontend source bind mount and synchronize
  source into native container storage using Compose Watch with initial sync.
  Retain the existing named node_modules volume; exclude node_modules,
  .pnpm-store, build output, and test reports from synchronization.
- Lifecycle: source edits sync; Vite config syncs and restarts; dependency
  manifests and lockfiles rebuild. Watch must remain running explicitly.
- Acceptance: actual Fast Refresh preserves component state and the running
  container/process; repeated create/update/delete and watcher restart work;
  at least five edit-to-visible timing samples and warm request timings are
  recorded. Production configuration must remain free of development mounts
  and Watch rules and target nginx correctly.
- Constraints: preserve unrelated changes, do not prune images or volumes,
  and do not introduce speculative caching or dependency upgrades.
- Required integration checks: development and production Compose config,
  frontend tests/build, merged production configuration inspection, and real
  browser verification before architecture approval/documentation handoff.

- 2026-10-01 (integration): backend 173 passed / 8 skipped; frontend 52 tests
  green after coordinator added `nav.providers` + `nav.globalSettings` to both
  catalogs; production build passed.
- Next checkpoint due after P2-08 lands (expected: frontend suite green with
  wizard tests; build green once wizard TS errors resolved).

## Cross-session coordination — UI refresh (2026-10-01)

A separate session is implementing the owner-approved, **visual-only** spec
`docs/specs/ui-refresh-and-provider-instances.md`. See
`docs/specs/coordination-ui-refresh.md` for the full handoff.

- That session owns: Material Symbols, radius/design + cursor, header avatar
  dropdown, `common.add`, button loading spinner, `RowActions` for **workflows
  and tasks**, and a styled `ConfirmDialog` (replacing `window.confirm`).
- **Provider instance management (friendly name, multiple instances,
  reconfigure, delete) and provider row actions stay here** (`P2-09`); the
  UI-refresh spec defers AC-09…AC-13 and all backend work.
- It already repaired `es.json` mojibake and added shared catalog vocabulary
  (kept per owner): preserve those keys if editing the catalogs.
- Shared files to coordinate around: `frontend/src/index.css`,
  `frontend/src/components/ui/button.tsx`, `card.tsx`, `input.tsx`,
  `frontend/src/app/AppShell.tsx`, `frontend/src/i18n/locales/*.json`,
  `frontend/src/i18n/catalogs.test.ts`, `frontend/package.json`,
  `frontend/pnpm-lock.yaml`.
