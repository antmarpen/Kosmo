# Workflow editor refinements — node contracts, Start/End and script outputs

Status: Approved (2026-10-03) — scope approved by the owner.
Source: owner request, 2026-10-03 (nine items) plus two clarification rounds
(2026-10-03).
Related: `docs/specs/phase-2-provider-editor.md` (approved), `docs/architecture.md`,
`backend/shared/graph/schema.py`, `frontend/src/features/workflows/editor/`.

## Problem and intended users

Builders author workflows in the visual editor, but several node contracts and
interactions do not match how the owner expects the product to work. The editor
exposes Start/End as ordinary palette nodes, lets authors declare inputs/outputs
as free lists disconnected from the graph, edits the Start form through raw JSON,
lets the script code be read outside its editor, and does not derive script
outputs from the script itself.

Intended users: **builders** authoring and publishing workflows.

## Goals

1. Start and End are fixed structural nodes: always present, not in the node
   palette, and not deletable.
2. The Start node form is visual only; the per-field label is dropped in favour
   of the field name; "required" becomes a switch.
3. Script code is only viewable through the "Edit script" action.
4. Node details always present **Inputs** and **Outputs** sections; inputs are
   driven by the graph connections, with Start/End exceptions.
5. The AI node selects a provider and then that provider's models.
6. The HTTP node always exposes a single output: the request result.
7. The Decision node stays but is marked not functional (Jev design is later).
8. The Workflow node detail is responsive and shows the referenced workflow's
   inputs/outputs.
9. Script inputs are in-scope variables and script outputs are the variables the
   script returns.

## Non-goals

- Implementing the Decision/Jev decision model.
- Adding the AI node's agent selector, MCP and Skills sections.
- Making HTTP, Workflow or Decision nodes executable (still "not supported").
- The full **workflow definition vs workflow instance** model: binding a run to
  the user's concrete provider configuration at launch. This spec records the
  direction but does not implement instance-time selection (see "Direction").
- Phases/loops editing, scheduling, unrelated task UI.

## Expected behavior

### 1. Fixed Start and End nodes
- The palette lists only Script, HTTP, AI, Decision and Workflow.
- Every draft has exactly one Start and one End. They can be moved and
  configured but not deleted (canvas delete and "Delete selection" leave them).
- A loaded/legacy draft missing Start or End is repaired to include them.

### 2. Start node form (visual only)
- The Start panel shows only the visual field builder; the raw JSON control is
  removed.
- A field's user-facing label is its **name**.
- `label_message_key` is **removed from schema v1** (D3).
- "Required" is a switch/toggle, not a checkbox.
- Stored data carrying the removed field is discarded rather than kept
  compatible (D9).

### 3. Script code visibility
- The panel shows no script code (no preview, no line count). The only code
  affordance is "Edit script".

### 4. Node details: Inputs and Outputs sections
- Selecting a node always shows an **Inputs** and an **Outputs** section, subject
  to the Start/End exceptions.
- **Inputs** are graph-driven: connecting A → B adds **all of A's outputs** to
  B's Inputs (D2); removing the connection removes them. Items are non-free-text
  chips; edges stay `{from, to}`.
- **Outputs** by type: Script = returned variables; HTTP = the request result;
  AI = declared output artifacts (editable); Workflow = the referenced
  workflow's outputs.
- **Exceptions:** Start → manual Inputs, **no Outputs**; End → **no Outputs**,
  graph-driven Inputs.

### 5. AI node provider + model
- The AI panel replaces the free-text model field with a provider selector and a
  model selector populated from the selected provider instance.
- The node stores the provider **type** and the **model** (D4); it does not bind
  to a provider-config id.
- If the caller has several instances of a provider type, the definition does
  not pick one: the provider/model select is shown empty and the concrete
  configuration is expected to be chosen when the workflow is used (D10). See
  "Direction".
- Agent selector, MCP and Skills are out of scope.

### 6. HTTP node output
- One fixed output named `response`; no editable outputs list (D11). HTTP
  execution is still not implemented.

### 7. Decision node (deferred)
- Present in the palette, visibly marked not functional. Future behaviour:
  multiple inputs and a Jev-style decision model choosing the route.

### 8. Workflow node detail
- Responsive: no horizontal overflow/scroll; fits the side panel (`lg`+) or
  bottom sheet (below `lg`).
- With a workflow selected, shows its **Inputs** (the referenced workflow's
  Start fields) and **Outputs** (the artifacts that reach its End) (D5).

### 9. Script inputs and outputs
- The user writes code as the **body of a function**: no `def`, no parameters
  declaration. The platform wraps it and calls it with the declared inputs (D1,
  D7).
- Each declared input is available as a variable **named after the input**,
  holding the **parsed content** of the artifact (text/markdown → `str`;
  JSON → `dict`/`list`; unsupported types are an explicit error).
- Input and output names must be **valid Python identifiers**; the editor
  validates this (the current safe-identifier rule allows `.`/`-`, which is not
  valid Python — script nodes tighten this).
- The script returns the values to expose. Output names are derived by parsing
  the `return` statement; tuple positions map to variable names
  (`return size, distance` → `size`, `distance`). A returned expression without
  a plain name is a validation error (D8).
- Returned values are exposed as individual artifacts (JSON for objects/scalars,
  text for strings) and are available to connected downstream nodes.

## Direction (future, not implemented here)

The owner wants to separate the **workflow definition** (authored: node types,
provider type and model, expected contracts) from the **workflow instance**
(a run that binds the user's concrete provider configuration, mainly for AI
nodes). This spec implements the definition side only; instance-time provider
selection and the launch override are future work and should be specified
separately.

## Constraints and affected contracts

- **Workflow schema v1** (`backend/shared/graph/schema.py` and the mirrored
  `frontend/.../editor/model.ts`): `FormField.label_message_key` (removed),
  `ScriptNode.inputs/outputs` (derived), `HttpNode.outputs` (fixed to
  `response`), `AiNode.agent` (provider type + model), and script identifier
  rules (valid Python identifiers).
- **Backend validation** (`backend/app/domain/workflows/validation.py`): Start
  count, end reachability, declared artifacts, exactly three AI validation
  levels. Derived inputs/outputs must keep these consistent.
- **Execution** (`backend/worker/activities/sandbox.py`, `ai_node.py`,
  `backend/worker/workflows/task_workflow.py`): the script wrapper (inputs as
  variables, captured return) and the artifact serialization of returned values
  are the largest change.
- **Task form** (`frontend/src/features/tasks/TaskPages.tsx`): uses the field
  name instead of `label_message_key`.
- **Provider selection** (item 5) reuses the provider-config listing and model
  discovery; stores only type + model.
- **i18n**: all new labels in en/es nested catalogs.
- Editing at 768px+; task views at 375px.

## Acceptance criteria

- **AC-01:** The palette never offers Start/End; a draft always has exactly one
  Start and one End; neither can be deleted; legacy drafts missing one are
  repaired.
- **AC-02:** The Start panel has no JSON control; fields use the visual builder;
  a field's label is its name; required is a switch.
- **AC-03:** The panel shows no script code text or line count; the only code
  affordance is "Edit script".
- **AC-04:** Selecting a non-Start/End node shows Inputs and Outputs; connecting
  a source's outputs appear in Inputs and disappear on disconnect; End shows
  Inputs but no Outputs; Start shows manual Inputs but no Outputs.
- **AC-05:** The AI node offers a provider selector that loads its models; the
  provider **type** and model persist in the draft; with several instances of a
  type the select is empty.
- **AC-06:** The HTTP node shows exactly one output, `response`.
- **AC-07:** The Decision node is present and marked not functional.
- **AC-08:** The Workflow node detail has no horizontal overflow and, with a
  workflow selected, shows its inputs and outputs.
- **AC-09:** A script returning `size, distance` exposes outputs `size` and
  `distance`; declared inputs are available as variables with parsed content;
  returned values reach connected downstream nodes at execution.
- **AC-10:** All new UI text exists in en and es with no hardcoded strings.

## Resolved questions

- **O1 → D7:** inputs are exposed as variables (named after the input) with
  parsed content; unsupported types error.
- **O2 → D8:** output names are derived by parsing the `return`; unnamed
  expressions are a validation error.
- **O3 → D9:** `label_message_key` is removed and deprecated data is deleted
  rather than kept compatible; if no workflows remain, seed one again.
- **O4 → D11:** HTTP's fixed output is `response`.
- **O5:** the panel shows nothing about the script (no line count).
- **O6:** a loaded draft missing Start/End is silently repaired.
- **O7 → D10:** provider resolution stays by type with the existing
  most-recent-in-scope rule; multiple instances show an empty select and the
  concrete configuration is chosen when the workflow is used.

## Decisions and approval

Owner decisions (2026-10-03):

- **D1 / D7 (item 9):** the script is executed as a function body; declared
  inputs are in-scope variables with parsed content; the script returns the
  values to expose.
- **D2 (item 4):** connecting A → B adds all of A's outputs to B's Inputs; no
  artifact mapping in edges.
- **D3 / D9 (item 2):** `label_message_key` removed from schema v1; deprecated
  records are deleted (destructive dev-data migration), reseeding if the
  instance is left without workflows. **Operational note:** removing workflows
  also removes their versions/drafts and (per the owner's deletion intent)
  their tasks; confirm at execution time.
- **D4 / D10 (item 5):** the node stores the provider type + model; execution
  resolves the task user's accessible configuration of that type; the
  definition/instance split is a future direction.
- **D5 (item 8):** Workflow-node inputs = referenced Start fields; outputs =
  artifacts reaching its End.
- **D6 (item 7):** Decision node stays, marked not functional.
- **D8 (item 9):** output names derive from parsing the `return`.

- Status: **Approved** (2026-10-03). The owner explicitly approved this scope,
  including the destructive dev-data cleanup in D9 (delete deprecated
  workflows/versions/drafts/tasks; reseed if the instance is left without
  workflows). The coordinator's next action is to hand this spec to `architect`
  for work-package planning.

## Review corrections (2026-10-03, post-implementation)

### C1 — Start/End panel and delete affordance (bugs)
- The Start node currently renders **two Inputs sections**; it must show exactly
  one Inputs section (the manual form fields) and no Outputs. The End node is
  correct.
- When Start or End is selected, the **"Delete selection" action still appears**;
  it must not be available for the protected structural nodes (hide or disable
  it, in addition to the existing model/canvas guard).

### C2 — In-control loading with a spinner (global platform pattern)
- For requests that can take time (e.g. provider model discovery), the loading
  state must render **inside the control** — the select shows a spinner and a
  live label — instead of a plain "Loading models…" text elsewhere.
- This is a **global platform pattern** for any request that may be slow, not
  only the AI model selector: prefer in-place, lively feedback (spinner/skeleton)
  over static loading text.

### C3 — Output provenance and core output validation (material extension)
- Every Input/Output chip should offer an affordance (e.g. an info "i") that
  reveals: the **source node** the value comes from, the **output kind/type**, and
  whether it has **validation** configured.
- Validation (syntax, format, rules) becomes a **core, cross-cutting capability
  configurable on the outputs of every node**, not only AI nodes.
- **Resolved (2026-10-03):** validation is a **per-output contract** with the
  three sections (syntax/parse, format/structure, rules), configured through a
  **modal** opened from a button on each output chip (compact in the panel;
  viewable on demand). The AI node migrates from its AI-specific 3-level contract
  to this general model. The chip's info "i" affordance summarises provenance
  (source node), output kind/type, and whether validation is configured.
- Still to design: the exact rule catalogue rendered by the modal and the
  execution semantics for a failed non-AI output validation (blocking vs
  feedback).

## Review corrections — round 2 (2026-10-03, post-C3)

### C4 — Start inputs are validated like outputs (material)
- Start is the external boundary: its fields have no prior workflow control, so
  each declared input field must support the **same validation contract as node
  outputs**, configured the same way. This extends per-output validation to
  Start form fields (whose "outputs" are the field names available downstream).

### C5 — Format-dependent validation modal + Python rules (material)
- Format selector: **text | json | yaml | markdown** (no "automatic").
- The format/structure section depends on the selected format:
  - **json / yaml** → a **JSON Schema** editor (validated and enforced on the value);
  - **text / markdown** → no format/structure content;
  - **rules** → like scripts, **Python code** (sandboxed), replacing the current
    bounded terms/`supported_claims` catalogue.
- Questions: does "no rules" apply to text/markdown (the owner wrote both "ni
  reglas" and "reglas como los scripts")? Which JSON Schema draft? What is the
  Python-rule execution interface (variable name / return contract) and is it run
  in the same sandbox as scripts?
- **Resolved (2026-10-03):** for **text/markdown**, neither format/structure nor
  rules apply (format/structure and rules are only for json/yaml). For
  **json/yaml**, use the standard validation for the selected type (JSON Schema
  for JSON; the standard YAML validation for YAML). Rules are **Python code run
  as a body in the sandbox** (same model as scripts). **C4:** each Start input
  field is validated exactly like an output — by type, schema/format and rules —
  using the same authoring criteria.

### C6 — AI model loading spinner overlaps text (bug)
- The in-control loading spinner currently overlaps its text; show only the
  spinner plus the label, with no overlap.

### C7 — Chip info popover formatting
- The provenance popover presents too much unformatted information; it needs
  clear visual separation and structure (labelled rows/sections).
