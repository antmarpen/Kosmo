# Workflow editor refinements — work packages (execution record)

Status: Complete (2026-10-04) — all work packages done; AR3 closed (architecture APPROVED).
Spec: `docs/specs/workflow-editor-refinements.md` (Approved 2026-10-03).
Plan produced by the architect (2026-10-03); this document persists the plan so
context loss does not lose the wave sequencing.

## Coordinator scope corrections to the architect plan

- **Keep `agent.instructions`** on AI nodes (the plan proposed removing it and
  folding instructions into `prompt_template`; that was not requested).
- **Keep the `agent.runtime` field name** as the provider type (the plan proposed
  renaming it to `agent.provider`; avoid unnecessary schema/seed churn).

## Contracts fixed by the plan

1. Authoring schema v1: remove `FormField.label_message_key`;
   `agent: {runtime, model, instructions}` where `runtime` is the provider type
   (never a config id); HTTP persists `outputs: ["response"]`; script
   inputs/outputs are derived snapshots validated against the graph; End/
   Decision/Workflow do not persist display-only input/output fields.
2. Graph contracts: Start has no Outputs section but its form field names are
   the source contract; Inputs are the ordered union of directly connected
   sources' outputs; duplicate names across producers surface a localized issue;
   Workflow references use the referenced **active published definition** (else a
   localized unavailable state); reference expansion is bounded and cycle-safe.
3. Script analysis: Python stdlib AST; wrap the the body to validate function-body
   syntax only; accept `return name` or tuples of distinct plain names; nested
   helper returns do not contribute; multiple outer returns must expose the same
   ordered names; no return → zero outputs; bare return invalid; names must be
   valid Python identifiers (not keywords, length limit); never execute authored
   code on the API/worker host.
4. Execution: select script inputs from direct predecessor completions (Start
   values supplied directly), keep artifact refs in Temporal history and parse
   content inside the sandbox; text/markdown → str, JSON objects/lists → dict/
   list; unsupported inputs error; returned str → text/plain, JSON-compatible →
   application/json, non-finite numbers rejected; media types come from
   serialization metadata, not filename; preserve digests, persistence,
   checkpoint/recovery, timeout and container isolation.

## Packages

| WP | Type | Objective | Depends on |
| --- | --- | --- | --- |
| WP-01 | Dev | Pure Python script-body AST analysis → ordered output names + keyed issues (no execution). | — |
| WP-02 | Dev | Authoritative schema + graph-contract validation (derive/validate inputs from edges, fixed HTTP output, reference contracts, Start/End counts). | WP-01 |
| WP-03 | Dev | `POST /workflows/script-analysis` (builder/admin) boundary + typed client regen. | WP-01, WP-02 |
| WP-04 | Test | Script runtime tests first (function-body execution, typed inputs, serialization, handoff, errors). | WP-01 |
| WP-05 | Dev | Container-side function-body runner + return serialization. | WP-01, WP-04 |
| WP-06 | Dev | Sandbox artifact persistence/recovery for returned values. | WP-05 |
| WP-07 | Dev | Edge-scoped execution handoff + provider-type resolution. | WP-02, WP-04, WP-06 |
| WP-08 | Dev | Frontend model: fixed Start/End, derived contracts, analysis lifecycle, normalization. | WP-02, WP-03 |
| WP-09 | Design | Properties sections + visual authoring controls (Start builder, no JSON/label, script visibility, fixed HTTP output, Decision warning, shared Switch). | WP-08 |
| WP-10 | Dev | AI provider/model authoring selector (type only; multiple instances → empty select). | WP-03, WP-08, WP-09 |
| WP-11 | Design | Responsive Workflow reference details + `/tasks/new` labels by field name. | WP-08, WP-09, WP-10 |
| WP-12 | Dev | Destructive dev-data cleanup migration + reference reseed (irreversible; isolated, last). | WP-01…WP-11 |
| WP-13 | Test | Integrated behavioral + browser verification (AC-01…AC-10). | WP-12 |

## Status log

- **WP-01 — DONE (2026-10-03).** `backend/shared/graph/script_contract.py` +
  tests; `analyze_script_body(code, input_names)`. Commit `c8335fe`.
- **WP-02 — DONE (2026-10-03), completed as WP-02b.** Schema (remove
  `label_message_key`; HTTP `outputs: ["response"]`; `inputs` snapshots on
  HTTP/End/Workflow; keep `agent.runtime/instructions`), graph-derived
  input/output validation, reference contracts from the referenced **active**
  version (existence vs contract distinguished), reference seed migrated.
  Focused suite 75 passed; full backend 305 passed / 39 skipped with only the
  intentionally-red WP-04 file failing. Commit `...`.
- **WP-04 — DONE (tests written, intentionally RED).**
  `backend/tests/worker/test_script_runtime.py` staged; 11 red for the missing
  script-execution contract, to be made green by WP-05/WP-06. Not committed
  until green.
- **WP-03 — DONE (2026-10-03).** `POST /workflows/script-analysis`
  (admin/builder) over WP-01's analyzer; typed schemas + API tests (5 passed);
  typed client regenerated. Commit `b00f70f`.
- **WP-05 — DONE (2026-10-03).** `backend/worker/script_runner.py` (container
  harness, descriptor + manifest), sandbox image/Compose build-context updated,
  runner unit tests 7 passed / 1 skipped (Windows symlink), real container smoke
  test OK. Commit `3db5946`.
- **WP-06 — DONE (2026-10-03).** `run_script` stages declared inputs, invokes
  the runner, validates the manifest and persists outputs with explicit media
  types, preserving recovery/timeout/isolation. WP-04's tests green (21 passed);
  full backend 328 passed / 40 skipped (Docker-gated storage test still skipped
  on this host). Commit `6708f4f`.
- **WP-07 — DONE (2026-10-03).** Direct-predecessor input resolution, provider
  **type** resolution, keyed missing/ambiguous-input and unsupported-runtime
  failures. Full backend 332 passed / 40 skipped. Commit `6a62b2f`.
- **WP-08/WP-08b — DONE with gaps (2026-10-03).** Editor model derives inputs,
  protects Start/End, blocks structural add/delete, and requests script analysis
  (stale-safe, publish gate). Owned tests green (78). Open follow-ups for
  WP-08c: duplicate producer-name reporting (AC-04), normalizing derived inputs
  on load, behavioural tests for the analysis lifecycle and localized analysis
  issues, and **preserving `phases`** (WP-08b dropped them from the frontend
  contract — verify no data loss).
- **WP-09 — DONE (2026-10-03).** Panel sections, visual Start builder,
  name-based labels, required switch (new shared `components/ui/switch.tsx`),
  script code only behind Edit script, fixed HTTP `response`, Decision marked
  non-functional. Frontend green (317). Commit `8e59b6e` (with WP-08b).
- **WP-08c — DONE with a small follow-up (2026-10-03).** Derived inputs
  normalized on load, duplicate producer names reported, `phases` preserved.
  Follow-up deferred: behavioural tests for the script-analysis lifecycle and
  catalog keys for the new validation issues. Commit `91d84fa`.
- **WP-10 — DONE (2026-10-03).** AI provider/model cascade selector storing only
  provider type + model; multiple instances show an empty select. Commit
  `7299dc9`.
- **WP-11 — DONE (2026-10-03, finished by the coordinator).** Responsive
  referenced-workflow detail and `/tasks/new` labels by field name; fixed the
  duplicated referenced outputs and the obsolete label-key condition. Frontend
  green (325). Commit `f11e071`.
- **WP-12 — DONE (2026-10-03), applied.** Migration
  `0021_editor_contract_cleanup` + disposable-PostgreSQL test (both real bugs —
  the `tasks.definition` column and a 36-char revision id — were caught and
  fixed by running it in-container; 10 migration tests pass against PostgreSQL).
  Applied to the dev database after a fresh `pg_dump`
  (taken outside the repository): 185
  tasks, 110 versions and 89 empty (never-published) E2E workflows removed; the
  reference workflow was reseeded and is active. Final state: 1 workflow, 0
  tasks. Commit `38e3139`.
- **WP-13 — PARTIAL (2026-10-03).** E2E journeys updated for the new authoring
  contracts but the suite is not green (6 passed / 1 skipped / 7 failed). A
  direct API probe of the reference workflow exposed a **real blocking defect**
  that the mocked tests missed: the sandbox image's `ENTRYPOINT` is `python`
  while WP-06 passed `command=["python", "/opt/kosmo/script_runner.py", ...]`,
  producing `python python ...` (exit 2). Fixed in `4b40d97` with a regression
  test (`test_sandbox_command_uses_the_image_entrypoint_without_duplicating_python`).
  After the fix the reference script produces `report` + `data`; the AI node then
  reaches `waiting_for_input` (agent-initiated input/permission request) — needs
  follow-up (likely the seeded `model: "default"` and/or agent permission
  behaviour). Remaining E2E failures are stale expectations (old artifact names,
  validation-level locators, publish notices, terminal-state set) plus that AI
  behaviour. The tester's E2E edits are uncommitted.

## Wave sequencing

1. WP-01.
2. WP-02 + WP-04.
3. WP-03 + WP-05.
4. WP-06 + WP-08.
5. WP-07 + WP-09.
6. WP-10 → WP-11 (serialize shared panel/catalog edits).
7. Integrated preflight → WP-12 (destructive, last).
8. WP-13.
9. Architecture review → documentation.

## Acceptance coverage

AC-01 → WP-02/08; AC-02 → WP-02/09/11/12; AC-03 → WP-09; AC-04 →
WP-02/07/08/09/11; AC-05 → WP-02/07/08/10; AC-06 → WP-02/08/09; AC-07 → WP-09;
AC-08 → WP-11; AC-09 → WP-01…08/12; AC-10 → every UI package + WP-13.

## Verification baseline

```powershell
uv run --project backend --directory backend pytest
pnpm -C frontend test
pnpm -C frontend build
pnpm -C frontend e2e
```

Integration skips are not passing evidence. WP-12 is destructive and
irreversible: reconfirm with the owner, capture affected task IDs, and drain/
stop affected Temporal executions before applying; never test against the
owner's database.

## C3 increment — per-output validation (planned 2026-10-03)

Spec: `docs/specs/workflow-editor-refinements.md` → "Review corrections" C3.
C1/C2 are implemented and committed (`24a0541`).

### Architectural decisions

- Schema v1 gains `output_validation?: Record<string, ValidationContract>` on
  **Script, HTTP, AI and Workflow** nodes. Output-name lists are preserved.
  A contract keeps exactly three positional sections (syntax/parse,
  format/structure, rules). AI's node-wide `validation` is removed and
  normalized (deep-copied) onto each declared AI output; no destructive
  migration and no rewriting of published versions/task snapshots.
- Bounded rule catalogue (existing capabilities only): syntax `format`
  (auto/text/json/markdown); format = JSON required keys or Markdown required
  sections/heading levels; rules = required terms and the existing lexical
  `supported_claims` rule with an explicit input artifact. Unknown/incompatible
  options are keyed authoring errors.
- **Blocking** execution: all configured checks must pass before persistence/
  checkpoint. Scripts return `OUTPUT_VALIDATION_FAILED` (no automatic rerun);
  AI keeps its bounded three-cycle feedback. HTTP/Workflow execution remains
  unsupported.
- Provenance is **derived, not persisted**: an editor-only `OutputDescriptor`
  (name, source node, node type, kind, value type, validation) feeds the chip's
  info affordance.
- Seed/model: keep `"default"` but resolve it explicitly to the selected ACP
  session's advertised current model (fail clearly if none). `waiting_for_input`
  is a legitimate permission request, not a defect. Fix the seed's stale
  `report.md` references to `report`.

### Packages

| WP | Type | Objective | Depends on |
| --- | --- | --- | --- |
| WP-14 | Dev | General output contract + legacy AI normalization (schema). | — |
| WP-15 | Dev | Authoritative catalogue validation + publication boundaries. | WP-14 |
| WP-16 | Dev | Shared per-output validator + validator API. | WP-14, WP-15 |
| WP-17 | Dev | Blocking Script output validation. | WP-16 |
| WP-18 | Dev | AI completion/correction migrated to the general model. | WP-16 |
| WP-19 | Dev | Frontend types + provenance/output-contract resolver. | WP-14, WP-15 |
| WP-20 | Design | Per-output validation modal + chip info UI. | WP-19 |
| WP-21 | Dev | Explicit runtime default + seed `report` repair. | WP-14, WP-18 |
| WP-22 | Test | Finish WP-13 integrated E2E (AC-01…AC-10 + C1/C2/C3). | WP-17,18,20,21 |

Acceptance IDs: C3-01…C3-07, SEED-01, E2E-01 (as listed by the architect).

### Status

- WP-14 — DONE (`1a6dd33`). `output_validation` per output; legacy AI
  normalization (`normalize_output_validation`).
- WP-15 — DONE (`2221307`). Authoritative catalogue validation + publication
  boundaries + read-only legacy inventory.
- WP-16 — DONE (`2bac01d`). Shared per-output validator for runtime + API.
- WP-17 — DONE (`9340f1d`). Blocking script output validation; real-container
  proof skipped on this host.
- WP-18 — DONE (`9340f1d`). AI completion/correction migrated to per-output
  contracts.
- WP-19 — DONE (`fcc4177`). Frontend per-output types + provenance resolver.
- WP-20 / WP-20b — DONE (`fcc4177`, `657390f`). Per-output validation modal,
  provenance popover, input info, orphaned contracts. Build green. Browser
  responsive evidence still outstanding.
- WP-21 — DONE (`a93493c`). Explicit ACP default-model resolution; seed
  migrated to per-output validation and `report` reference. New keyed error
  `workflow.agent.model_default_unavailable` still needs en/es catalog entries.
- WP-22 — PARTIAL. Backend 348/42, frontend 334, build green. E2E phase-2:
  4 passed / 1 skipped / 3 failed. Root cause of the authoring publish failure
  (diagnosed via API): the AI node's `inputs` snapshot must equal the union of
  the predecessor Script's derived outputs (`["report","data"]`); otherwise
  publication returns `derived_contract_stale`. The authored journey must let
  the async script analysis resolve (and/or the UI must recompute derived inputs
  after it) before publishing. The E2E edits remain uncommitted.
- Outstanding: finish WP-22 (journey fixes + responsive evidence), architecture
  review, documentator.

## Round-2 validation model (planned 2026-10-03) — WP-23…WP-34

Spec: `docs/specs/workflow-editor-refinements.md` → "Review corrections — round 2" (C4/C5).

### Canonical contract (replaces the bounded catalogue)

`ValidationContract` discriminated by `format`:

- `text` / `markdown`: UTF-8 only; **no** format/structure and **no** rules.
- `json`: JSON Schema (Draft 2020-12) + optional **Python rules**; strict parse.
- `yaml`: standard safe YAML validation + optional **Python rules**; no JSON Schema.

Rules are optional Python function bodies run in the sandbox (like scripts) with
`value` and `content` available; they must return exactly `True` (pass) or
`False` (fail); exceptions/timeouts/malformed results fail closed. Start fields
gain the same `validation` contract, validated like outputs. Blocking semantics
remain. Legacy `levels` contracts stay readable via an isolated legacy reader
with deterministic conversion where demonstrable; ambiguous/`auto` cases require
explicit repair. No destructive migration.

### Packages

| WP | Type | Objective | Depends on |
| --- | --- | --- | --- |
| WP-23 | Dev | Canonical contracts + compatibility normalization (schema). | — |
| WP-24 | Dev | Authoritative publication validation for the new contracts. | WP-23 |
| WP-25 | Dev | Pure format/schema evaluator (JSON Schema, safe YAML, text/md) + deps. | WP-23/24 |
| WP-26 | Dev | Sandboxed Python-rule runner (container). | WP-25 |
| WP-27 | Dev | Shared async validation gateway + MCP bridge (no API Docker access). | WP-26 |
| WP-28 | Dev | Blocking Script/AI integration with the new evaluator. | WP-27 |
| WP-29 | Dev | Start submission + execution validation gates. | WP-27/28 |
| WP-30 | Dev | Frontend contract state + provenance (preserve Start validation). | WP-23/24 |
| WP-31 | Design | Format-dependent validation modal. | WP-30 |
| WP-32 | Design | Start-field authoring + missing localization. | WP-31 |
| WP-33 | Dev | Script-analysis lifecycle repair (WP-22 root cause). | WP-30 |
| WP-34 | Dev | Seed + legacy catalogue transition (non-destructive). | WP-24/28/29 |
| WP-22 | Test | Integrated acceptance + browser proof (C1…C5, C6/C7 regressions). | all |

Acceptance IDs: R2-01…R2-08.

### Status

- WP-23 — DONE (`448c290`). Round-2 format-discriminated contract + legacy normalization.
- WP-24 — DONE (`2c833b4`). Publication validation (JSON Schema/compile/forbidden props/Start compatibility/legacy repair).
- WP-25 — DONE (`0fc1ec4`). Pure evaluator (strict JSON + Draft 2020-12 + bounded safe YAML).
- WP-26 — DONE (`3312bba`). Sandboxed Python-rule runner (Docker proof done).
- WP-27 — DONE (`a9a5561`, `bcafdb1`). Shared async validation gateway + worker probe; API has no Docker access.
- WP-28 — DONE (`3dfe7e7`). Blocking Script/AI integration with the shared validator.
- WP-29 — DONE (`f181b67`). Start submission/execution gates + Temporal patch.
- WP-30 — DONE (`d860c42`). Frontend round-2 contract state + provenance.
- WP-31 — DONE (`d860c42`). Format-dependent validation modal.
- WP-32 — DONE (`e321d64`). Start-field validation authoring + `workflow.agent.model_default_unavailable` localization.
- WP-33 — DONE (`93cf96d`). Script-analysis lifecycle fixed (accepted outputs recompute downstream inputs).
- WP-34 — DONE (`80d5ed2`). Reference seed migrated; backend suite fully green.

Verification: **backend 403 passed / 42 skipped**; frontend **346 passed**, build green.

Environment fixes required by the new deps: `jsonschema` (and the evaluator deps) must be synced inside the backend container (`uv sync`), and `@radix-ui/react-popover` inside the frontend container (`pnpm install`); a missing container dep had crashed the API/app.

- **WP-22 — DONE.** Integrated E2E now **14 passed / 2 skipped** (~8 min): the
  credential-gated real-model journey and an AI-failure journey whose premise did
  not materialize are documented skips. The launch and authored-execution journeys
  pass after: fixing the stale worker (restart to register `validate_start_inputs`),
  fixing the worker mapper (`tasks.created_by → users`, commit for
  `tasks/models.py`), and correcting the journeys to round-2 expectations
  (markdown parse-only, longer timeouts, `waiting_for_input` handling,
  `report`/`data` names). Commits: E2E journeys + the mapper fix.
- **Responsive/browser evidence — DONE (2026-10-04).**
  `frontend/e2e/responsive.e2e.ts` covers the editor at 1280/768 and the task form
  at 375 (`a9d972d`).
- **Architecture review — APPROVED (2026-10-04).** AR3-05's behavioral proof was
  executed and accepted; only documented residuals remain (see below).
- Environment notes: the worker does **not** hot-reload — restart it after
  worker-module changes; new backend deps require `uv sync` in the container.

## Final review (2026-10-03) — CHANGES REQUIRED (AR3 remediation)

The architect reproduced four validation-contract failures plus a Compose
sandbox failure:

- **AR3-01 (High)** runtime inspects `rules` while the schema/UI persist
  `rules_code`, so configured Python rules are bypassed (zero runner calls).
- **AR3-02 (High)** the rule sandbox bind-mounts worker-local `/tmp` paths and
  fails from the Compose worker (must use the task-storage volume/subpath).
- **AR3-03 (High)** boolean JSON Schemas (`false`/`true`) are not honored or
  preserved.
- **AR3-04 (High)** numeric/boolean Start fields are not validated (only string).
- **AR3-05 (High)** sensitive input content travels through Temporal payloads and
  validation diagnostics.
- **AR3-06 (Medium)** `window.confirm`/static loading text in the validation
  dialog; missing 768/1280/375 responsive browser evidence.

Accepted positives: no Docker socket on the API; MCP authorization intact;
legacy normalization deep-copies and does not rewrite history; the seed uses
canonical contracts; the script-analysis lifecycle fix has a regression test;
catalog parity 474/474. Operator asks for a fresh-process **task mapper**
regression alongside the users-table fix.

Status: AR3-01/02/03/04/06 IN PROGRESS→RESOLVED; AR3-04/05/06 QUEUED.

### AR3 remediation results (2026-10-03)

- **AR3-01/02/03/04/06 — RESOLVED** (re-review confirmed). Commits `413691d`,
  `b2de476`, `6a519da`, `0d38eb9`, AR3-06 dialog commit (`styled confirmation +
  LoadingControl`).
- **AR3-05 — implementation landed; behavioral proof executed.**
  Bounded validation diagnostics and an opaque `execute_opaque_node` /
  `validate_persisted_start_inputs` path gated by the `opaque-task-inputs-v1`
  Temporal patch are in place (commit `66d61ad`). The sentinel/history and replay
  proofs (`backend/tests/worker/test_task_input_secrecy.py`) **pass in the
  in-process Temporal test server inside the backend container** (2 passed):
  the sentinel is absent from workflow/activity arguments and from the recorded
  history, and a recorded history replays. The tests are opt-in
  (`KOSMO_TEMPORAL_INTEGRATION=1`) because the test server can hang on a bare
  Windows host; the explicit pre-patch legacy branch still needs a history
  recorded before the patch marker (documented residual).
- **Responsive evidence — DONE.** `frontend/e2e/responsive.e2e.ts` asserts no
  horizontal overflow at 1280px and 768px on the editor and at 375px on the task
  form (2 passed).
- Also fixed a flaky `ProviderModelSelect` full-suite test (`97562e1`).
- **Architecture sign-off — APPROVED (2026-10-04).** AR3-01/02/03/04/06 resolved;
  AR3-05 proven (Temporal test server, 2 passed). Accepted residuals: the explicit
  pre-patch legacy replay branch is not crafted; substitute activities are not a
  full production database/executor secrecy test; existing histories are not
  retroactively sanitized.
- **Linux-only latent flake fixed (2026-10-04).**
  `test_rejects_escaping_or_symlink_output_paths` used an undefined `result`; it
  passed on Windows only because the symlink branch is skipped there. It now
  assigns and returns `result`, and passes in the Linux container (8/8 in
  `test_script_runner.py`; verified failing before the fix).
