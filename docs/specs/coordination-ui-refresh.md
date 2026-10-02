# Cross-session coordination — UI refresh (visual only)

From: the **UI-refresh session** (coordinator), 2026-10-01.
To: the **Phase 2 provider/editor session** (coordinator).

There is no supported inter-session messaging tool, so this note is the
handoff channel. The Phase 2 coordinator maintains
`docs/specs/phase-2-work-packages.md`; a short pointer to this file was added
there.

## What this session is doing

Implementing the owner-approved spec
`docs/specs/ui-refresh-and-provider-instances.md`, **limited to visual/UX**:

- AC-01/AC-02 — self-hosted Material Symbols (Rounded) icon system.
- AC-03/AC-04 — medium roundness + modern refinement; pointer cursor rules.
- AC-05 — header avatar (username initial) + dropdown with "Sign out".
- AC-06 — shared `common.add` key + icons on actions.
- AC-07 — processing feedback (disabled button + inline spinner).
- AC-08 — transversal `RowActions` presentation for **workflows and tasks**.
- AC-14 — Spanish catalog mojibake repaired (already applied).
- AC-16 — styled `ConfirmDialog` replacing `window.confirm` (task stop).

## Explicitly delegated to Phase 2 (NOT done here)

- **AC-09…AC-13** and all backend work: provider friendly name, multiple
  instances per provider, provider reconfigure ("Edit"), provider delete, and
  provider row actions. These belong to **P2-09** and the Phase 2 provider
  contract.
- The provider sections of the UI-refresh spec are retained only as context.

## Reconciled owner decisions (supersede the UI-refresh provider section)

From `docs/specs/phase-2-work-packages.md` (owner, 2026-10-01 later):

1. A provider configuration **stores no model** (`0016_drop_selected_model`).
2. Provider onboarding has a **mandatory user-entered display name**, which must
   not reuse the provider type.
3. **Connection verification is mandatory before saving** (redefined steps).

The reconciler must not treat the UI-refresh spec's provider acceptance
criteria as an active implementation contract.

## Requested coordination

1. Phase 2 owns provider naming/instances/reconfigure/delete and provider row
   actions (P2-09). This session did not touch the provider backend; it made
   only a bounded UI change to the provider list's primary Add CTA (generic
   `common.add` + Material Symbol), with no provider management or row CRUD.
2. To avoid concurrent edits on shared files while this session works, please
   coordinate ownership of: `frontend/src/index.css`,
   `frontend/src/components/ui/button.tsx`, `card.tsx`, `input.tsx`,
   `frontend/src/app/AppShell.tsx`, `frontend/src/i18n/locales/en.json`,
   `es.json`, `catalogs.test.ts`, `frontend/package.json`, `pnpm-lock.yaml`.
3. This session already repaired `es.json` mojibake and added shared vocabulary
   (`common.add/edit/delete/confirm`, action/avatar/confirmation keys) to both
   catalogs. If you edit the catalogs, preserve those keys; `catalogs.test.ts`
   enforces structural parity.
4. Both sessions shared one working tree with many uncommitted changes. Nothing
   here has been committed.

Relay further messages via the owner.
