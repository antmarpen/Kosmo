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
| P2-12 | Dev | Monaco editor for Script nodes (lazy loaded) | DONE 2026-10-02 (large modal, loads only on open, own build chunk) |
| P2-15 | Dev | Draft integration in editor (save/load/revisions UI) | DONE 2026-10-01 |
| P2-16 | Dev | Publish/activate UI (confirmation + stale-base flows) | DONE 2026-10-02 (versions listing, default-off Activate option; verified live) |
| P2-17 | Dev | i18n parity verification + router/route titles reconciliation | DONE (415/415 en/es, zero missing keys) |
| P2-09 | Dev | Provider list actions (verify/delete/edit) | DONE 2026-10-02 (targeted by config_id; Edit in R6) |
| Editor layout | Design | Canvas usable from 768px; properties/palette as sheets below lg | DONE 2026-10-02 (measured; canvas layout regression fixed later) |
| Launch workflow (create task) | Dev | `/tasks/new` real selector; 404 root-caused | DONE 2026-10-02 (verified live: 201 → task detail running) |
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

## Canvas layout regression (2026-10-02, found via E2E, fixed)

The E2E "author a workflow" journey started failing at its connect step
(`0 connections`). Root cause was NOT the connect wiring: `EditorPage`'s
`<main>` used `flex-1` with a viewport-locked height that did not hold inside
the shell's content-sized ancestor chain, so the canvas grew to the height of
the tallest properties panel (the AI panel, made taller by the R2/RR2 authoring
work). `Fit view` then centred the graph inside the phantom height, pushing
every handle off-screen so no connection gesture could ever start. Fixed with
`shrink-0` and no `flex-1`; panels scroll internally. A dedicated regression
spec (`frontend/e2e/editor-canvas-connect.e2e.ts`) pins the canvas height and
the drag-connect.

Also fixed in the same pass: the task-detail view could render a stale state
because overlapping `load()` responses committed out of order; `useTasks` now
keeps a monotonic sequence guard so only the latest issued load may commit.

E2E after the fix: 11 passed, 2 skipped (both documented credential-gated).
Frontend 313 passed. Backend 268 passed, 39 skipped.

## Re-review (2026-10-02) — RETURN FOR REMEDIATION (second round)

The architect re-reviewed the R1–R9 remediation. Resolved: R1 publication
bypass, R2 HTTP/reference validation, R3 authoring + launch inputs, R4 targeted
verification, R5 proof hardening and safe probe DTOs (partially), R6 instances
and update-by-id (partially), R7 activation/localization (partially), R8
interaction polish, R9 executable journeys.

New findings and their packages (status at time of writing):

- **RR1 (High)** workflow name lifecycle: creation seeds the draft with `{}`, the
  editor shows "Untitled workflow", publish accepts blank/whitespace names and
  renames the workflow; DB uniqueness is case-sensitive. → DONE 2026-10-02
  (migration 0020 case-insensitive index; name preserved and verified live).
- **RR2 (High)** Start JSON authoring can crash validation (`[{}]`,
  `{"name":3}`) and validation `params_schema` is not editable. → DONE 2026-10-02
- **RR3 (Medium)** partial provider replacement verifies a different pair than
  the one saved; auth-only editing disabled. → DONE 2026-10-02. The candidate
  validate/models/verify-model endpoints accept an optional `config_id` and
  attest the **effective pair** (uploaded files overlaid on the stored encrypted
  files) for the targeted instance; the wizard allows config-only, auth-only, or
  full file replacement. Backend 273 passed / 39 skipped; frontend 316 passed;
  build green.
- **RR4 (Medium)** migration 0019 backfill can exceed the 80-char limit. → DONE 2026-10-02
- **RR5 (Medium)** concurrent duplicate PATCH returns an unlocalized 500. → DONE 2026-10-02
- **RR6 (Medium)** version picker truncated at 50 with no pagination. → DONE
  2026-10-02. `GET /workflows/{id}/versions` gained `offset`; the activation
  dialog pages with an explicit "Load more versions" control and hides it when a
  short page returns. Backend 277 passed / 39 skipped; frontend 320 passed.
- **RR7 (Medium)** workflow-list draft count (spec line 93) still absent. → DONE
  2026-10-02. `WorkflowResponse.draft_count` counts the caller's own drafts via a
  single grouped query; the list renders it and hides it at zero.
- **RR8 (High verification gap)** AC-P2-08 not established: no test executes a
  visually authored Start→Script→AI→End graph to `success`. → DONE 2026-10-02.
  New `frontend/e2e/phase2-execution.e2e.ts` authors the executable graph
  through the real editor (Start input, script code via the modal fallback,
  AI model/validation, declared inputs/outputs), publishes, activates, launches
  from `/tasks/new`, and follows the task to `success` with `report.md` and
  `summary.md`. Verified live against the compose stack with the admin's
  verified OpenCode provider (`nan/qwen3.6`): **1 passed (42.4 s)**. The journey
  is credential-gated: it skips with a reason when no verified provider is
  visible, never reporting a false pass. A direct API probe also confirmed the
  same minimal graph reaches `success` in ~15 s.

### Post-remediation review re-run (2026-10-02) — two blocking findings fixed

The architect re-reviewed the integrated remediation and returned CHANGES
REQUIRED with two blocking findings; both are fixed:

- **AR-01 (High)** edit-mode candidate operations (`config_id`) had no
  owner/admin gate: a non-owner who could merely SEE a shared group/global row
  could overlay their own files on the owner's stored credentials and probe with
  them (credential-exfiltration risk). `_effective_candidate_pair` now enforces
  owner-or-admin **before** decrypting/overlaying the stored files, mirroring the
  save path; a non-owner gets the localized 403 `errors.provider.forbidden` and
  no candidate operation is created. New backend test covers global and group
  cases and confirms an admin non-owner is still allowed.
- **AR-02 (Medium)** after publishing without activation and reloading, the
  activation picker had no preselected version, so Confirm was disabled while an
  option appeared offered. `EditorPage` now falls back to the newest available
  candidate (after the just-published and active choices), keeping the picker
  operable through ordinary interaction. New frontend test covers it.

Also outstanding from the review: one small package for SSE reconciliation on
the active task detail (missed events after a normal stream close), and
`frontend/probe/` must be excluded from the feature diff.

- **SSE reconciliation (detail)** → DONE 2026-10-02. Root cause: a normal stream
  close followed by a successful reconnect leaves changes whose event id is
  already committed to `Last-Event-ID` unreplayed, and the polling fallback never
  engages because the reconnect resets the failure counter, so the detail badge
  could freeze. `useTaskStream` now reloads once per resumed connection (cursor
  present); Last-Event-ID resume, backoff and the failure fallback are unchanged.
  Regression test red→green; frontend 316 passed.
- **`frontend/probe/`** excluded from the feature diff via `.gitignore`
  (including `frontend/tsconfig.tsbuildinfo`). DONE 2026-10-02.

Working state at hand-off: backend 268 passed / 39 skipped; frontend 313
passed; E2E 11 passed / 2 skipped; TypeScript and build clean; catalogs
415/415. Nothing is committed yet — the whole phase-2 diff (68 files at
hand-off) plus the remediations still needs grouped commits.

Residual limitations accepted by the re-review: migration 0018 downgrade loses
short-lived proof state; 0019 refuses incompatible downgrade; most-recent-wins
resolution is owner-approved; `as never` casts and two unused keys are cleanup
debt; bundle size is recorded debt; live spinner timing is component-verified.
`frontend/probe/` is temporary scratch and must not enter the feature diff.

## Final architecture review (2026-10-02) — changes required, not approved

The architect reviewed the integrated work against both approved specs plus the
owner additions. Verified positives: providers store no model; mandatory
trimmed names and single-method wizard-step skipping; encrypted
candidate-reference handoff; agent containers read-only with dropped
capabilities; navigation grouping; shared row actions and styled confirmations;
Monaco modal Save/Cancel and dynamic import.

Blocking findings (severity → remediation package):

1. **High (R1)** `POST /workflows` resolves by name and appends a published
   version; the list page reuses a fixed name, so repeated creation grows one
   workflow and bypasses publication locking/confirmation.
2. **High (R2)** HTTP nodes apply a string pattern to `list[str]` (raises
   `TypeError`, escaping the validation handler) and Workflow references are
   rejected when no existence resolver is passed.
3. **High (R3)** Properties authoring does not match schema v1: Start expects an
   object where an array is required, declared inputs/outputs are missing, and
   HTTP/End expose fields the schema rejects.
4. **High (R4)** Row verification does not target the clicked configuration
   (no `config_id`), so it can probe or update a different row.
5. **Medium (R5)** Proof expiry can let onboarding report success while saving
   `unverified`; probe output returns arbitrary agent text into Temporal
   history/responses.
6. **Medium (R6)** Deferred provider-instance criteria (AC-09 delete done;
   AC-10 uniqueness, AC-11 multiple instances, AC-12 reconfigure, AC-13
   migration/constraint) remain open, plus AC-08's provider Edit.
7. **Medium (R7)** Activation offers only client-known versions and lacks the
   spec's default-off Activate option; validation messages are hardcoded English.
8. **Medium (R8)** Dialog focus restoration, unchanged-label loading feedback,
   searchable/draggable node catalog and selection-dependent properties panel.
9. **Medium (R9)** `frontend/e2e/phase2.e2e.ts` journeys are still skipped
   placeholders; PostgreSQL concurrency and a visually authored workflow
   reaching `success` are not covered.

Execution is proceeding in waves (disjoint ownership): R1 ∥ R4, then R2 ∥ R5,
then R3 ∥ R6, then R7 ∥ R8, then R9. Deferred items are being implemented
rather than re-deferred.

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
