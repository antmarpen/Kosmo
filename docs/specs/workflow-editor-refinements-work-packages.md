# Workflow editor refinements — work packages (execution record)

Status: In progress (2026-10-03)
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
- **WP-13 — PENDING.** Integrated E2E: update the journeys to the new script
  contract (function body + `return`), the fixed Start/End nodes, the
  name-based task labels and the AI provider selector, then run the suite.

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
