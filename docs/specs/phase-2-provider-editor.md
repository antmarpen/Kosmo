# Phase 2 — Provider Configuration and Visual Workflow Editor

Status: Approved (2026-10-01)
Date: 2026-10-01

Prerequisites: Phase 1 approved and implemented (see `phase-1-foundations.md`).
Requirements source: `docs/product-vision.md`. Technical reference:
`docs/architecture.md`. Backend provider-config API and workflow
schema/validation/publication API already exist.

## Problem and intended users

Phase 1 proved the execution engine but the platform is not usable by its
target audience (builders) because:

1. There is no UI to configure AI providers — agent execution is blocked on
   the owner manually uploading credentials.
2. There is no visual editor — workflows can only be created programmatically
   via seed scripts.

Phase 2 closes both gaps so a builder can configure a provider and then
create, publish, and execute workflows visually.

## Goals

1. **Provider configuration UI** (block A): providers are visible to all
   authenticated users in the main sidebar (moved out of Administration).
   Creation is a multi-step wizard: select provider type (OpenCode/Claude
   Code/Codex) → auth method (provider-specific: OpenCode = config file;
   Claude Code and Codex = API key or config) → schema validation → model
   discovery and selection → real container verification. Scoping depends on
   role: runner/builder = personal; group manager = personal or group;
   admin = personal, group, or global. All users VIEW configs scoped to
   them; non-owners see metadata only (never credentials).
2. **Visual workflow editor** (block C): builders create and edit workflow
   graphs on a React Flow canvas with a node catalog, node properties panel,
   draft saves, publication, and activation.

## Non-goals

- Claude/Codex adapter implementations (the adapter interface exists).
- Phases/loop visual editing (schema fields exist; editor UI is phase 3).
- Bounded-loop configuration UI (phase 3).
- Advanced validation-rule builder UI (validation contracts are defined in
  node properties as JSON; a visual rule builder is phase 3).
- TanStack Query migration (local state + refetch is recorded as acceptable).
- Destination-level agent egress filtering.
- Notes/audit UI.
- Task detail/list refinements beyond what the editor needs.
- Production deployment.

## Expected behavior

### Block A — Provider configuration UI

- **Navigation:** Agents, MCPs, Skills, Extensions, and Providers are moved
  OUT of Administration into the main sidebar — they are visible to ALL
  authenticated users. The difference is permissions: anyone can VIEW
  configs scoped to them; create/edit depends on role and scope. The
  Administration section shrinks to Audit and global settings only.
- **Visibility and role model:** the user's role determines what scope they
  can create at:
  - Runner/Builder: personal (only themselves).
  - Group Manager: personal or their group.
  - Admin: personal, group, or global.
  All users can VIEW configs scoped to them (personal + their groups +
  global), but credential/config contents are hidden from non-owners
  (metadata only: name, provider type, visibility, model count, status).
- **Provider creation flow** (multi-step wizard):
  1. Select provider type: OpenCode, Claude Code, Codex (extensible).
  2. Auth method depends on the selected type:
     - OpenCode: config file upload only (`opencode.json` — supports
       multiple providers within the config).
     - Claude Code: API key OR config file.
     - Codex: API key OR config file.
  3. Upload/configure the auth method.
  4. Schema validation on upload: checks auth, providers, and models
     sections only (MCP/skill sections are ignored). Violations render as a
     structured error list (localized).
  5. If valid: model list fetched from the backend (ACP `session/new` model
     options). User selects one model.
  6. "Verify" button: launches a real container test (trivial prompt →
     non-empty response assertion) with a visible result
     (success/latency/structured failure).
  7. Select visibility scope (per role model above).
- Edit/replace/delete existing configs (owner or admin; respecting scope).
- Uses the existing backend API: `POST/GET/DELETE /provider-configs` with
  scoped visibility, encrypted storage, and the provider handler protocol
  (validate_config, list_models, verify_model).

### Block C — Visual workflow editor

- `/workflows` page: list of workflows with status (draft count, active
  version), "Create workflow" button.
- `/workflows/{id}/edit` page: React Flow canvas with:
  - **Left panel:** searchable node-type catalog (Script, HTTP, AI, Decision,
    Workflow, Start, End) with icons and short descriptions; always visible.
  - **Center:** React Flow canvas — drag nodes from the catalog, connect
    outputs (right side) to inputs (left side). Node deletion via keyboard or
    context menu.
  - **Right panel:** selected-node properties (appears on node selection,
    closes on canvas click, swaps on different node selection). Per-type
    fields:
    - Script: code editor using **Monaco** (VS Code editor component) loaded
      via lazy/dynamic import — the heavy Monaco bundle is only fetched when
      a Script node's properties panel is opened, not on page load. Declared
      inputs/outputs fields alongside.
    - AI: agent config (runtime, model, instructions), prompt template,
      declared inputs/outputs, validation contract (JSON editor for level
      params).
    - HTTP: method, URL, declared outputs.
    - Workflow: select existing workflow or "use definition" (phase 3).
    - Decision: decision logic (phase 3 adds model-backed decisions; phase 2
      supports manual route selection).
  - Node visual style: each node type is rendered as the same base React Flow
    shape (rounded rectangle) differentiated by icon and border color (e.g.,
    blue for AI, green for script, orange for HTTP). Custom shapes/sizes per
    node type are a phase-3 refinement. Connections: output handles on the
    right edge, input handles on the left edge; edges are straight (or
    smooth-step) lines from right to left.
    - Start: dynamic input-form builder (add/remove fields: name, type,
      required, label).
  - Properties panel must be responsive: full-width overlay on mobile.
- Workflow-level settings: name (editable), bounded-loop fields present in
  schema (not editable in phase 2 UI — schema-only).
- **Save draft:** atomic; sends the full definition; server-side validation
  returns errors as structured details; client renders them inline per node.
  Draft saves increment an internal revision (optimistic concurrency).
- **Publish:** requires validation errors = 0; creates a new version
  automatically; offers an optional "Activate" checkbox (default off).
- **Validation:** server-side via the existing `POST /workflows` validation +
  client-side for immediate feedback (graph connectivity, required fields).
  Errors map to specific nodes/fields in the UI.
- Node type set for phase 2 editor: Start, End, Script, HTTP, AI, Decision,
  Workflow. All fields from the schema v1 contracts. HTTP and Workflow nodes
  can be placed but execution returns "not supported" (already implemented in
  the interpreter).
- Monaco lazy loading: use `React.lazy(() => import('@monaco-editor/react'))`
  (or equivalent dynamic import) so the Monaco bundle (~2 MB) is fetched only
  when a Script node is selected and its properties panel opens. All other
  node types never trigger the load.

### Cross-cutting

- Responsive: the editor must be usable at 768px+ (mobile editing of the
  canvas is not a phase 2 goal — the task views remain mobile-usable).
- i18n: all new labels in en/es nested catalogs.
- Error handling: all API errors render through the KosmoError contract
  (message_key + params localized via catalogs).

## Constraints

- Backend API already exists — this phase is frontend-focused plus minor
  backend adjustments only (if gaps are found during integration, report to
  coordinator rather than expanding scope).
- The provider-config backend (R-02 + WP-21a) is the contract for block A.
  The workflow schema/publication backend (WP-07/WP-08) is the contract for
  block C.
- React Flow is already a dependency; do not add a second graph library.
- Responsive at 768px+ for the editor (375px for task views, already done).
- The stack runs via `just up`; no new services needed.

## Acceptance criteria

- AC-P2-01: A builder can navigate to Administration > Providers, upload a
  valid `opencode.json`, see the model list, select a model, run "Verify",
  and see a success result (or a clear auth-missing error if credentials are
  absent in the config).
- AC-P2-02: An invalid config file (missing providers section, malformed
  JSON) shows specific schema violations per field/section; an invalid upload
  does NOT overwrite an existing valid config.
- AC-P2-03: A builder can set visibility to personal, a group they belong to,
  or (if admin) global; a builder attempting global gets a 403 with a
  localized error.
- AC-P2-04: A builder can create a new workflow from the /workflows page,
  add nodes (start, script, AI, end) to the canvas, connect them, configure
  each node's properties, and save as a draft.
- AC-P2-05: The draft editor validates the graph server-side and renders
  errors inline per node (e.g., "missing end node", "output not connected").
- AC-P2-06: Publishing a valid draft creates version N+1; the save/publish
  flow offers an optional "Activate" checkbox that is off by default;
  publishing alone does NOT change the active version.
- AC-P2-07: If another user published the workflow less than 5 minutes ago,
  the publish flow requires confirmation before overwriting the authoring
  state.
- AC-P2-08: After publishing and activating, a runner can submit a task from
  the /tasks/new page selecting that workflow, and the task executes
  end-to-end (start → script → AI → end) with the configured nodes.
- AC-P2-09: The editor renders correctly at 768px and 1280px widths; the
  task views remain usable at 375px (existing constraint preserved).
- AC-P2-10: All new UI text is localized in both en and es catalogs; no
  hardcoded strings.

## Open questions

1. Monaco/CodeMirror for the script code editor — or plain textarea for
   phase 2? (Recommendation: plain textarea; Monaco is a phase-3 upgrade.)
2. React Flow node rendering: custom node components per type, or a generic
   node with type-specific icon/color? (Recommendation: generic with icon +
   color per type; custom shapes are phase 3.)

## Decisions and approval

- Scope approved by owner on 2026-10-01: blocks A + C only; B (adapters),
  D (task view refinements), E (technical backlog) are phase 3.
- Monaco code editor with lazy loading approved for Script nodes (not
  textarea). Generic node visual style approved (icon + color, connections
  right-to-left). Navigation restructure approved: Agents/MCPs/Skills/
  Extensions/Providers move to main sidebar; Administration shrinks to
  Audit + global settings.
- Phase 2 excludes: phases/loop editor UI, Claude/Codex adapters, TanStack
  Query migration, egress filtering, notes/audit UI.
