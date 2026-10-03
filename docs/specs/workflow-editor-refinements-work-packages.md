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
