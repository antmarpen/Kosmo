# UI modernization and provider configuration instances

Status: Approved — scope revised 2026-10-01 (provider instance management moved
to the Phase 2 provider work; see "Scope revision" below).

## Scope revision (2026-10-01)

This spec was approved before discovering that a parallel Phase 2 development
effort is active in the same repository and already records newer owner
decisions for providers in `docs/specs/phase-2-provider-editor.md` and
`docs/specs/phase-2-work-packages.md`:

- A provider configuration **stores no model** (`0016_drop_selected_model`).
- Provider onboarding requires a **mandatory user-entered display name** that
  must not reuse the provider type.
- **Connection verification is mandatory before saving**, with redefined wizard
  steps.
- **P2-09** ("Provider management page actions: verify/delete/replace") is
  pending and owns provider row actions.

Decision (owner, 2026-10-01): this work is limited to the **visual/UX** changes.
Provider instance management (friendly name, multiple instances, reconfigure,
delete, provider row actions) is **removed from this spec** and delegated to
the Phase 2 provider work, where it will be reconciled with the decisions above.

- **In scope:** AC-01 through AC-08, AC-14, AC-15 (visual subset), AC-16.
- **Deferred to Phase 2:** AC-09 through AC-13, and all backend (B-*) packages.
  The provider-specific sections below are retained only as context and are not
  an implementation contract for this work.
- **Visual refinement (owner, 2026-10-02):** action buttons use a full pill
  silhouette, matching the supplied reference shape; the existing palette is
  unchanged. Icon-only buttons remain circular, while inputs/cards/menus keep
  their medium corner radius.

## Problem and intended users

Kosmo's Phase 1 UI is functional but reads as dated: navigation and shell use
hand-picked Unicode glyphs instead of a coherent icon system, controls are only
lightly rounded, there is no consistent hover/affordance language, action
buttons give little feedback while work is in progress, and lists expose few or
no row-level actions.

Provider configuration is also too rigid. The `provider_configs` table enforces
`UNIQUE (user_id, provider, visibility, group_id)`, so a user can keep only one
configuration per provider and scope, and configurations have no
user-chosen name. A user who connects the same provider twice through different
credentials (for example Codex with `config.toml` + `auth.json` versus a Codex
token with access to a different account) has no way to tell the two apart.

Intended users: all authenticated users (navigation, language, feedback);
builders and administrators who manage provider configurations and workflows.

## Goals and non-goals

### Goals

1. Adopt **Material Symbols** as the UI icon system, self-hosted.
2. Modernize the visual language with pill-shaped action buttons and a lighter,
   more contemporary surface/typography treatment.
3. Replace the header "Sign out" pill with an initial-avatar and a dropdown menu.
4. Guarantee a pointer cursor on every enabled interactive element.
5. Introduce a reusable generic "Add" translation key and representative icons
   on action buttons.
6. Show processing feedback (disabled button + inline spinner) while an action
   is in flight.
7. Provide a standard, right-aligned per-row actions column with icon buttons
   and tooltips across all lists.
8. Allow multiple provider configuration instances per user, each with a
   required friendly name, and support reconfigure + delete from the list.

### Non-goals

- Provider brand marks stay with `@lobehub/icons`; Material Symbols does not
  cover brand logos.
- Node-level provider/model selection and task-launch overrides are a future
  feature; see "Future direction" below.
- New list capabilities without a backend contract (for example, task deletion:
  no endpoint exists today).
- Redesign of the workflow editor canvas or node internals.

## Expected behavior

### 1. Icon system (Material Symbols)

- Add the self-hosted `material-symbols` package (Rounded variant) and a single
  `<Icon name="..." />` React component that wraps the font ligature, exposes
  `size`, `weight`, `fill`, and accepts an accessible label or `aria-hidden`.
- Replace the Unicode glyphs in `AppShell` navigation, sidebar collapse, mobile
  drawer, and header controls with Material Symbols names.
- Action buttons (add, edit, delete, stop, send, save) render a representative
  leading icon.
- Centrally declare the icon names in one module so nav and actions do not
  hard-code strings in multiple files.
- No runtime request to Google Fonts; assets are bundled and work offline and
  inside Docker.

### 2. Visual language

- Use a full pill radius for buttons across sizes; square icon buttons become
  circles. Inputs, cards, and menus retain the medium radius scale from
  `--radius` and derived tokens.
- Refine surfaces, shadows, spacing, and typography for a more modern feel,
  keeping the existing OKLCH palette and brand mark.
- Preserve WCAG AA contrast; verify at mobile and desktop widths.

### 3. Header avatar menu

- The header's right side shows a circular avatar containing the uppercase
  first letter of the authenticated user's username.
- Clicking the avatar opens a menu with a single "Sign out" item.
- Keyboard accessible: Enter/Space opens, Escape closes, focus is managed and
  restored; the trigger exposes `aria-haspopup="menu"` and `aria-expanded`.
- Selecting "Sign out" performs the existing logout and redirects to `/login`.
- If the current user is not yet loaded, the avatar shows a neutral fallback
  (no crash, no layout shift).

### 4. Pointer cursor

- Every enabled interactive element shows a pointer cursor: buttons, links,
  the language switcher options, selects, checkboxes/radios, `label[for]`,
  menu items, and elements with `role="button"`.
- Disabled controls show `not-allowed` and never the pointer.
- Implemented as a base-layer rule so new components inherit it.

### 5. Generic "Add" key and action icons

- Add `common.add` = "Add" / "Añadir" and reuse it for add-entity and creation
  actions (provider, workflow, task): a single reusable key for the action
  label.
- Those buttons include a representative leading icon.
- Descriptive first-run empty-state CTAs (for example "Configure your first
  provider") keep their own keys, since they are full sentences rather than the
  generic action label.

### 6. Processing feedback in action buttons

- Extend `Button` with a `loading` state: when active, the button is disabled,
  keeps its label, and renders an inline spinner next to the text; expose
  `aria-busy`.
- Apply to submit/save/delete/verify actions: login, create task, send answer,
  stop task, create workflow, provider wizard continue/save, provider delete.
- On failure the button re-enables and the localized error continues to render.
- Destructive confirmations (provider delete, task stop) use a shared styled
  `ConfirmDialog` component instead of `window.confirm`, with localized title,
  description, confirm, and cancel actions.

### 7. Standard list actions column

- Define one shared row-actions presentation: a right-aligned group of icon
  buttons at the end of each list item, each with a tooltip and an accessible
  name, using a reusable `RowActions` component.
- The pattern is transversal and implemented per list with its own actions; it
  is **not** a dynamic action registry that injects columns at runtime.
- The rest of the row keeps each list's own styling; the workflows list look is
  the visual reference.
- Actions per list:
  - **Providers**: Edit (reconfigure), Delete (with styled confirmation).
  - **Workflows**: Edit.
  - **Tasks**: Stop when the task is stoppable (`running` / `waiting_for_input`),
    with styled confirmation.
- Tooltips are provided by a shared `Tooltip` component.

### 8. Provider configuration instances

- `provider_configs` gains a user-facing `name` (friendly name).
- A user may have multiple configurations for the same provider.
- The friendly name is **required** and **unique per user + provider**
  (case-insensitive); duplicates are rejected with a localized error. Existing
  configurations are backfilled with the provider type as their name.
- The list shows the friendly name, the provider type, and the scope.
- **Reconfigure** ("Edit") reopens the configuration flow for that instance:
  the provider type is fixed, and name, scope/group, and selected model are
  prefilled. The stored encrypted files are **kept unless the user uploads
  replacements**; decrypted secrets are never sent to the browser. Saving
  updates the same instance id.
- **Delete** opens the styled confirmation dialog, calls the existing
  `DELETE /providers/opencode/config` by `config_id`, and refreshes the list.
- The uniqueness constraint is replaced so multiple instances can coexist.

## Constraints and affected contracts

- **Stack** (unchanged): Vite + React + TypeScript, Tailwind v4 + shadcn/ui,
  TanStack Query (not required here), Zod, React Router, openapi-typescript +
  openapi-fetch; FastAPI + SQLAlchemy async + Alembic on PostgreSQL.
- **New frontend dependencies**: `material-symbols`,
  `@radix-ui/react-dropdown-menu`, `@radix-ui/react-tooltip`, and
  `@radix-ui/react-dialog` (styled confirmation dialog). Each must be documented
  and pnpm-locked.
- **i18n**: nested JSON catalogs for `en` and `es`, identical key structure.
  `frontend/src/i18n/locales/es.json` currently contains literal `?`
  corruption (for example `"Iniciando sesi?n?"`, `"A?n no hay tareas"`); fix
  it as part of this work. No translated value may contain mojibake.
- **Backend provider contract**:
  - `ProviderConfig` model/table: add `name`; replace the
    `uq_provider_config_owner_provider_visibility_group` constraint with a
    `(user_id, provider, name)` uniqueness rule; backfill existing rows.
  - `ProviderConfigRepository`: create/update by `id` instead of
    overwrite-by-scope; keep read/verify paths resolvable per instance.
  - `ProviderConfigService`: `replace` becomes create-or-update-by-id;
    `list_visible` returns the friendly `name` plus `provider_type`; `read_files`
    / `metadata` and the verify endpoints must target a specific instance.
  - `app/api/routes/provider_configs.py`: `PUT` accepts `name` and an optional
    `config_id`; the GET list returns `name`; delete already accepts `config_id`.
  - `frontend/src/api/schema.d.ts` must be regenerated and committed.
- **Execution resolution**: with several instances for the same provider,
  `resolve_files` currently selects the first personal row. Until node-level
  selection exists, use a documented provisional rule (most recently updated
  instance for the resolved scope) and record it as temporary.
- **Security**: configuration ciphertext stays server-side; the reconfigure flow
  never returns decrypted `opencode.json`/`auth.json` to the client.
- **Verification commands** (host, `just` may be unavailable):
  `pnpm -C frontend test`, `pnpm -C frontend build`,
  `uv run --project backend --directory backend pytest`, and client regeneration
  as in the `just ci` recipe.

## Acceptance criteria

- **AC-01 — Material Symbols adopted.** UI chrome (sidebar navigation, shell
  controls, action buttons) renders Material Symbols Rounded through the shared
  `<Icon>` component; no Unicode glyph icons remain in `AppShell`/navigation.
  Provider brand marks remain `@lobehub/icons`.
- **AC-02 — Self-hosted icons.** The app renders icons with no network request
  to external font hosts (verified offline / by asset inspection).
- **AC-03 — Modern visual language.** Radius, surfaces, shadows, spacing, and
  typography are visibly refined; text contrast still meets WCAG AA; layout is
  intact at mobile and desktop.
- **AC-04 — Pointer cursor.** Enabled interactive elements show a pointer;
  disabled controls show `not-allowed`.
- **AC-05 — Avatar menu.** The header shows the username initial; clicking opens
  a single-item "Sign out" menu; it is keyboard accessible with correct ARIA;
  selecting it logs out and lands on `/login`.
- **AC-06 — Generic add key.** Add and creation action buttons (provider,
  workflow, task) use `common.add` with a representative icon; no per-entity
  action label key remains. Descriptive first-run empty-state CTAs may keep
  their own keys.
- **AC-07 — Processing feedback.** Submit/save/delete/verify buttons disable,
  show an inline spinner, keep their label, and set `aria-busy` while in flight;
  they re-enable on completion or failure.
- **AC-08 — Actions column.** Every list row with actions renders a right-aligned
  group of icon buttons with tooltips and accessible names, using the shared
  `RowActions` presentation implemented per list (no dynamic action registry);
  Providers offer Edit and Delete, Workflows offer Edit, Tasks offer Stop when
  stoppable.
- **AC-09 — Provider delete.** Delete opens the styled confirmation dialog, calls
  `DELETE` with the row's `config_id`, refreshes the list, and surfaces
  localized errors on failure.
- **AC-10 — Friendly name.** Creating a configuration requires a name that is
  unique per user + provider (case-insensitive); a duplicate is rejected with a
  localized error.
- **AC-11 — Multiple instances.** A user can create more than one configuration
  for the same provider; each is listed with its friendly name and type.
- **AC-12 — Reconfigure.** Edit opens the flow for that instance with the type
  locked and name/scope/model prefilled; stored files are preserved unless
  replaced; saving updates the same id; no decrypted secret reaches the client.
- **AC-13 — Migration and backfill.** Existing configurations receive a
  non-empty name (provider type) and remain usable; the constraint change is
  applied by an Alembic migration with a working downgrade.
- **AC-14 — Translations.** `es.json` corruption is fixed; catalogs keep
  identical key structure and no value contains mojibake.
- **AC-15 — No regressions.** Frontend unit tests, backend provider tests, and
  the production build pass; regenerated `schema.d.ts` matches the backend
  OpenAPI document.
- **AC-16 — Styled confirmations.** Destructive confirmations (provider delete,
  task stop) use the shared styled `ConfirmDialog`; no `window.confirm` remains
  in the application.

## Future direction (recorded, not implemented here)

Provider selection belongs to AI nodes: when a user adds an AI node they choose
the provider instance and model for that node, and at task launch the user may
override those choices with their configured providers. This spec only prepares
that direction by making provider instances identifiable (friendly name) and
allowing several per user; the node-level selection and launch override are
separate future work.

## Open questions

None blocking. The following were resolved with the owner on 2026-10-01:

- Provisional execution rule: use the most recently updated instance for the
  resolved scope until node-level selection exists (documented as temporary).
- Non-provider actions: workflows keep Edit only (no delete endpoint); tasks
  offer Stop only when stoppable.
- Creation verbs are unified under the generic `common.add` key.
- Deletion and other destructive confirmations use a styled dialog, never
  `window.confirm`.
- Friendly-name uniqueness is enforced at the database level
  (`UNIQUE(user_id, provider, name)`) in addition to application validation.

## Decisions and approval

Agreed with the owner before drafting:

- **D1.** Icons via the self-hosted `material-symbols` npm package, Rounded
  variant; provider brand marks stay `@lobehub/icons`.
- **D2.** Original visual direction: medium rounding plus modern refinement,
  keeping the current palette. Refined by the owner on 2026-10-02: action
  buttons use a full pill silhouette; icon-only buttons remain circular and
  other surfaces keep medium rounding. Palette remains unchanged.
- **D3.** Avatar dropdown implemented with `@radix-ui/react-dropdown-menu`.
- **D4.** Provider "Edit" reopens the configuration flow; provider instances get
  a required friendly name, unique per user + provider; existing rows are
  backfilled with the provider type.
- **D5.** Reconfigure keeps stored encrypted files unless replacements are
  uploaded; secrets are never sent to the browser.
- **D6.** Multiple instances per provider are allowed; node-level provider/model
  selection and launch override are future work.
- **D7.** List actions follow one shared, transversal `RowActions` presentation:
  right-aligned icon buttons with tooltips, implemented per list without a
  dynamic action registry; the workflows list is the visual reference.
- **D8.** Add and creation actions use the shared `common.add` key and carry a
  representative icon.
- **D9.** Processing actions disable the button and show an inline spinner.
- **D10.** Interactive elements consistently show a pointer cursor.
- **D11.** Fix the existing `es.json` corruption within this work.
- **D12.** Destructive confirmations use a shared styled `ConfirmDialog`; the
  existing task-stop `window.confirm` is replaced.
- **D13 — Migration policy (B-01/B-02).** Backfill existing configurations with a
  friendly name derived from the provider display label (for example
  "OpenCode"); if several rows would collide under the new uniqueness rule, keep
  one unsuffixed and suffix the rest deterministically, preserving IDs, scopes,
  ownership, and ciphertext. Downgrade succeeds for compatible data and refuses
  transactionally with an actionable error for incompatible data; it never
  deletes or merges credentials. The current development database holds a single
  configuration, which receives the name "OpenCode".

Approval: approved by the owner on 2026-10-01 for the scope above. Material
changes require renewed agreement before replanning; acceptance IDs stay stable.
