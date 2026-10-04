# Delete a workflow from the UI

Status: **Approved (2026-10-05)** — owner decisions recorded below.
Owner: product owner. Related: `docs/context/project.md`,
`backend/app/domain/workflows/`, `frontend/src/features/workflows/WorkflowListPage.tsx`.

## Problem

There is no way to delete a workflow from the UI, and the backend has no
workflow delete endpoint. `tasks.workflow_id` and `tasks.version_id` are foreign
keys without `ondelete`, so deleting a workflow that has tasks fails at the
database level. Drafts, versions and activations cascade from the workflow, and
task children (notes, node executions, artifacts) cascade from the task.

## Intended users

Builders and admins managing their own workflows.

## Goals

- Delete a workflow from the workflow list, with a styled confirmation dialog.
- Offer, in the dialog, whether to also delete the workflow's associated tasks.
- Never delete while the workflow has tasks in progress.
- When tasks are deleted, remove their stored artifacts/workspace files too.

## Agreed decisions (owner, 2026-10-05)

- **D1 — Confirmation with a task option.** The confirmation dialog offers "also
  delete its N tasks". If unchecked and the workflow has tasks, deletion is
  blocked with a clear message.
- **D2 — Block while in progress.** If any task is in a non-terminal state
  (`queued`, `allocating`, `running`, `waiting_for_input`, `stopping`), deletion
  is blocked; the user must stop/await the tasks.
- **D3 — Delete stored artifacts.** When tasks are deleted, their artifact and
  workspace files under the task-storage volume are removed as well.

## Expected behavior

- `DELETE /workflows/{workflow_id}` (mutation permission consistent with the
  existing workflow mutations: `admin`/`builder`, own workflows; keep the
  established authorization boundary).
- Request carries `delete_tasks` (boolean, default false).
- Outcomes:
  - any task non-terminal -> blocked, keyed error (e.g.
    `workflows.delete.in_progress`) with the count.
  - `delete_tasks` false and tasks exist -> blocked, keyed error (e.g.
    `workflows.delete.tasks_exist`) with the count.
  - otherwise -> delete the tasks (when requested) and their storage, then the
    workflow (drafts/versions/activations cascade). Return 204.
- Task-storage cleanup removes only `/var/lib/kosmo/tasks/<task_id>` for the
  deleted tasks, idempotently and best-effort (a missing path is not an error).
- Run the database deletions in a transaction; do not leave rows in a partial
  state.

## UI

- Add a **Delete** action to each workflow row in `WorkflowListPage` using the
  shared styled confirmation dialog (`ConfirmDialog`).
- The dialog shows the workflow name; when tasks exist it shows a checkbox
  "Also delete its N tasks". While in-progress tasks exist, the dialog explains
  deletion is blocked (and the confirm action is disabled).
- After success, refetch the list and move focus sensibly (existing focus
  conventions). Errors are surfaced keyed via `KosmoErrorAlert`.
- Localized `en`/`es` strings (nested JSON).

## Acceptance criteria

- **WF-DEL-01** A workflow with no tasks can be deleted from the UI and
  disappears from the list.
- **WF-DEL-02** Deleting a workflow with tasks, with "also delete tasks"
  enabled, removes the workflow and all its task rows (and their cascade rows).
- **WF-DEL-03** Deleting a workflow with tasks, with "also delete tasks"
  disabled, is blocked with a keyed error and nothing is deleted.
- **WF-DEL-04** Deleting a workflow with any in-progress task is blocked with a
  keyed error and nothing is deleted.
- **WF-DEL-05** When tasks are deleted, their artifact/workspace files under the
  task-storage volume are removed.
- **WF-DEL-06** Only authorized users (admin/builder, own workflow) can delete.
- **WF-DEL-07** Catalog, provider and identity data are preserved.
- **WF-DEL-08** English and Spanish strings render for the action and dialog.

## Non-goals

- Bulk delete, soft-delete/undo, or an editor-embedded delete.
- A standalone per-task delete UI (not requested this iteration).
- Changing task execution semantics.

## Open implementation notes (architect/implementation)

- Define the exact keyed error identifiers and messages in `en`/`es`.
- Confirm whether the delete response is `204` or returns a small summary
  (deleted task count).
- Storage deletion runs in the API process (which mounts the task-storage
  volume); keep it bounded and safe against path traversal.
