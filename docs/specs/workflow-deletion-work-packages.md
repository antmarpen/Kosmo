# Workflow deletion — work-package execution record

Status: **Implemented (2026-10-05)** — WP-DEL-01…05 delivered. Backend `DELETE /workflows/{id}` (lock + state/count checks, `delete_tasks`, post-commit traversal-safe storage cleanup) with `task_count`/`in_progress_task_count` in the workflow view; list Delete action + confirmation dialog; nested en/es. Backend host 482 passed / 79 skipped; deletion tests 4 passed in-container; frontend 510 passed, build green. Coordinator decisions: counts in the workflow DTO; authorization = `admin`/`builder` (workflows are shared, drafts per-author); workflow-row `FOR UPDATE` lock; best-effort post-commit cleanup accepted.

## Architecture and execution decisions

- Keep deletion behind the existing FastAPI workflow route, `WorkflowService`, and repository seams; mutations retain `require_roles("admin", "builder")`.
- **Storage cleanup belongs in the API process**, because the backend container mounts the shared task-storage volume and artifact routes already resolve `storage_path` there. Do not add a worker or a new service/dependency.
- On deletion, first collect task IDs and validate state/counts; delete task and workflow rows within one database transaction. Only **after commit**, remove each exact `<configured task-storage root>/<task_id>` directory. Cleanup is idempotent (missing directory succeeds), bounded to an immediate child under the resolved configured root, and best-effort: log/suppress per-directory `OSError` without undoing a committed DB deletion. This ordering avoids filesystem removal on DB rollback. It does mean storage cleanup is not transactionally atomic and a failed cleanup can leave orphan files; record that limitation and keep cleanup retry-friendly.
- Return 204 as specified by the expected behavior (rather than a summary body). Request body is `{"delete_tasks": boolean}` with default `false`.
- Stable error keys proposed: `workflows.delete.in_progress` and `workflows.delete.tasks_exist`, each with `count`; unknown workflow uses existing `errors.workflow.not_found`. Confirm these keys fit the established error envelope during implementation, without changing the agreed behavior.
- Prevent a race with task creation/state transitions: lock the workflow row, then perform task state/count selection and deletion in the same DB transaction. The developer must verify task creation uses a compatible workflow lock; if it does not, coordinate a narrow concurrency safeguard rather than claiming the lock closes the race.

## Work packages

### WP-DEL-01 — Backend deletion behavioral tests
- **Type / assigned role:** test / Tester.
- **Objective / acceptance IDs:** Establish failing integration tests for endpoint semantics, authorization and preservation before implementation. Covers WF-DEL-01–04, WF-DEL-06, WF-DEL-07.
- **Included scope / exclusions:** API-level DB tests for empty workflow delete/204; task count and keyed `tasks_exist` when opt-out; keyed `in_progress` with count; delete_tasks removes task and cascade children; unauthorized role and missing/non-owned workflow follow existing boundary; unrelated catalog/provider/identity records remain. No frontend, storage filesystem assertion, or implementation.
- **Files or modules / relevant context and existing patterns:** `backend/tests/api/` (add focused `test_workflow_deletion.py`), `backend/tests/conftest.py`; endpoint/auth patterns in `backend/app/api/routes/workflows.py`; workflow integration tests.
- **Changes / contracts / examples:** Exercise `DELETE /workflows/{workflow_id}` with JSON body `{"delete_tasks": true|false}`. Assert error envelope `message_key` plus `params.count`; validate no partial DB effects on either rejection. Seed terminal states (`stopped`, `failed`, `success`) and at least one of each in-progress state if practical; cover count correctness.
- **Dependencies / file ownership / execution order:** First. Tester owns only the new test module; hand exact failing outputs to WP-DEL-02. No parallel edits to its file during implementation.
- **Required skills and why they apply:** `test-driven-development`, `python-testing-patterns` — behavioral pytest tests and red-first execution.
- **Tests / verification commands when known / expected evidence:** `docker compose exec backend pytest -q tests/api/test_workflow_deletion.py`; run before implementation and show failures for missing route/behavior, then rerun after WP-DEL-02.
- **Completion criteria:** Tests fail for the expected absence/incorrect behavior, not setup errors; after implementation they pass and demonstrate transactional rejection and preserved unrelated records.
- **Risks / assumptions / unresolved blockers:** Confirm exact fixture/test DB invocation from current compose setup before reporting commands as available; endpoint tests must not assert internal method calls.

### WP-DEL-02 — Workflow delete service, repository and API contract
- **Type / assigned role:** development / Developer.
- **Objective / acceptance IDs:** Implement authorized transactional workflow deletion and keyed blockers. Covers WF-DEL-01–04, WF-DEL-06, WF-DEL-07.
- **Included scope / exclusions:** Add request schema and DELETE route; service coordination and repository operations; evaluate all associated task states/count; block any non-terminal task before considering opt-out; delete task rows only when requested, then delete workflow and cascaded drafts/versions/activations. No filesystem deletion (WP-DEL-03) or UI.
- **Files or modules / relevant context and existing patterns:** `backend/app/api/routes/workflows.py`, `backend/app/domain/workflows/{service.py,repository.py,schemas.py}`, `backend/app/domain/tasks/models.py`, task state definitions in `backend/app/domain/tasks/service.py`; tests owned by WP-DEL-01.
- **Changes / contracts / examples:** `DELETE /workflows/{workflow_id}`; body `delete_tasks: bool = false`; 204 success. Reuse `require_roles("admin", "builder")`. Preserve the existing per-author ownership boundary (workflow author/creator field must be verified in source; enforce ownership as spec requires, do not infer admin bypass without existing convention). Proposed keys `workflows.delete.in_progress` and `workflows.delete.tasks_exist`, params `{count: N}`. Non-terminal set is exactly queued, allocating, running, waiting_for_input, stopping; terminal set stopped, failed, success. Perform validations and both row-deletion operations in one transaction; all rejection paths leave records untouched.
- **Dependencies / file ownership / execution order:** Depends on WP-DEL-01 red tests. Owns backend implementation files and schema; must not edit WP-DEL-01 tests. Coordinate transactional ownership with existing `get_db` behavior; ensure rollback on any DB error.
- **Required skills and why they apply:** `test-driven-development`, `fastapi-python`, `python-design-patterns` — route/schema and domain/repository separation.
- **Tests / verification commands when known / expected evidence:** `docker compose exec backend pytest -q tests/api/test_workflow_deletion.py`; also relevant workflow API/domain tests. Confirm exact command against compose service and package scripts before execution.
- **Completion criteria:** Endpoint returns specified outcomes, tests pass, DB mutation is atomic, permissions and ownership are proven, and catalog/provider/identity data remain intact.
- **Risks / assumptions / unresolved blockers:** The inspected workflow route confirms role gating but exact workflow author field/ownership enforcement and task creation locking must be verified before coding. If the existing data model cannot represent own-workflow authorization, stop and return to coordinator; do not silently broaden access. Locking only the workflow row may not serialize task creation.

### WP-DEL-03 — Safe task-storage cleanup after committed deletion
- **Type / assigned role:** development / Developer.
- **Objective / acceptance IDs:** Remove each deleted task's artifacts/workspace safely and idempotently. Covers WF-DEL-05; supports WF-DEL-02.
- **Included scope / exclusions:** Wire cleanup to the committed task-deletion path; use existing storage root/config and backend-mounted volume. No storage backend migration, broad recursive cleanup, or cleanup of tasks not selected for deletion.
- **Files or modules / relevant context and existing patterns:** `backend/app/api/routes/artifacts.py` (`storage_path` usage), task storage configuration references (`KOSMO_TASK_STORAGE_ROOT`), workflow delete service/repository from WP-DEL-02, focused tests under `backend/tests/api/` or `backend/tests/domain/` (coordinate test-file ownership with WP-DEL-01).
- **Changes / contracts / examples:** Resolve configured root once; accept only validated task identifiers and construct the immediate child path; ensure resolved candidate remains a direct descendant (not root itself, `..`, symlink escape, or arbitrary caller path). Delete directories with recursive filesystem operation; missing paths are success. Run only after DB commit; isolate per-task `OSError`, emit useful non-sensitive structured/logged context, and allow later retry. Never report failed deletion as rollback of already committed DB state.
- **Dependencies / file ownership / execution order:** Depends on WP-DEL-02 lifecycle contract. Own storage helper and its dedicated tests; coordinate with WP-DEL-01 to avoid same test file, or add `backend/tests/domain/test_workflow_deletion_storage.py`. Storage cleanup must be invoked after successful commit, not from inside rollback-capable DB transaction.
- **Required skills and why they apply:** `test-driven-development`, `python-testing-patterns`, `verification-before-completion` — safety boundaries, failure handling, and evidence.
- **Tests / verification commands when known / expected evidence:** Unit tests with temporary roots for directory removal, missing directory, repeated cleanup, invalid/traversal IDs and injected filesystem failure; assert unrelated sibling/task directories untouched. `docker compose exec backend pytest -q tests/domain/test_workflow_deletion_storage.py` (verify package/test path and service availability first).
- **Completion criteria:** Files are removed for successfully deleted tasks; cleanup is path-contained, repeatable, does not touch unrelated data, and filesystem failure does not corrupt/report a false DB rollback.
- **Risks / assumptions / unresolved blockers:** Best-effort cleanup permits orphaned storage on I/O failure; no retry queue is in scope. Verify config root is the same mounted volume path in runtime and tests. Do not follow symlinks outside root.

### WP-DEL-04 — Workflow-list deletion interaction and localization
- **Type / assigned role:** design / Designer.
- **Objective / acceptance IDs:** Add a consistent, accessible row deletion flow with task option, in-progress explanation, errors and sensible focus. Covers WF-DEL-01, WF-DEL-03, WF-DEL-04, WF-DEL-08.
- **Included scope / exclusions:** Delete row action in `WorkflowListPage`, shared styled `ConfirmDialog`, checkbox/count presentation when tasks exist, disabled confirmation and explanatory copy when in-progress tasks exist, keyed error presentation, success list refresh/focus behavior, nested en/es messages. UI may need counts/state data supplied by an existing workflow/task API; do not fabricate counts from inaccessible data.
- **Files or modules / relevant context and existing patterns:** `frontend/src/features/workflows/WorkflowListPage.tsx`, its test module (owned by WP-DEL-05), `frontend/src/components/{ConfirmDialog,RowActions,KosmoErrorAlert}.tsx`, nested English/Spanish catalogs (locate actual paths), generated API schema/types and API client.
- **Changes / contracts / examples:** Reuse existing row action, shared confirmation component/dialog patterns and error alert; no new bespoke dialog primitive. Integrate `DELETE` body contract and localize action/dialog/error strings in matching nested structures. After success remove/refetch item and move focus according to existing list focus conventions; make loading/error behavior accessible.
- **Dependencies / file ownership / execution order:** Depends on WP-DEL-02 API contract and on WP-DEL-05 initial test authoring. Designer owns component/catalog implementation; tester owns tests and coordinates edits before implementation. Any required workflow task-count/state data contract must be resolved by coordinator/developer before UI implementation; list endpoint currently is not verified to expose it.
- **Required skills and why they apply:** `impeccable` (primary UI interaction and consistency), `test-driven-development` (behavioral UI cycle), `web-design-guidelines` optional targeted accessibility check.
- **Tests / verification commands when known / expected evidence:** Run targeted Vitest file and frontend type/build scripts discovered in `frontend/package.json`; inspect rendered interaction, keyboard focus, disabled state, both locales. Do not invent a count source.
- **Completion criteria:** Row action is coherent with surrounding controls, dialog satisfies all stated states, errors stay keyed/localized, successful delete updates list and focus, en/es strings render.
- **Risks / assumptions / unresolved blockers:** Spec calls for N and in-progress state in dialog, but current list contract may not include task counts. Decide data source before implementing (extend list contract vs dedicated count endpoint); no silent N=0 placeholder. Avoid adding a broad endpoint without coordinator approval.

### WP-DEL-05 — Frontend deletion tests (test-first)
- **Type / assigned role:** test / Tester.
- **Objective / acceptance IDs:** Define interaction and localization behavior before UI implementation. Covers WF-DEL-01, WF-DEL-03, WF-DEL-04, WF-DEL-08.
- **Included scope / exclusions:** Extend workflow list behavioral tests for opening/canceling, task checkbox/count, disabled in-progress confirm, request payload, keyed error, success list removal/refetch/focus, English/Spanish strings. No component implementation or backend tests.
- **Files or modules / relevant context and existing patterns:** `frontend/src/features/workflows/WorkflowListPage.test.tsx`, existing shared dialog/row action tests and test setup.
- **Changes / contracts / examples:** Mock API deletion as `DELETE /workflows/{id}` with `{delete_tasks: true|false}` and verify observable results. Use established i18n/test helpers; keep testing UI behavior rather than internal state.
- **Dependencies / file ownership / execution order:** First for frontend; hand red evidence to WP-DEL-04. Tester owns test file until it passes; designer may add/update it only by explicit coordination after test package handoff.
- **Required skills and why they apply:** `test-driven-development`, `verification-before-completion` — establish red/green behavior.
- **Tests / verification commands when known / expected evidence:** `pnpm --dir frontend test -- WorkflowListPage.test.tsx` is a candidate only; confirm actual package script/working-directory convention in `frontend/package.json`, then use exact configured Vitest command. Run targeted test pre/post implementation.
- **Completion criteria:** Tests fail only because behavior is absent and pass against completed UI, covering both locales and blocked/error/success branches.
- **Risks / assumptions / unresolved blockers:** Test expectations for task counts/in-progress facts depend on the data contract decision in WP-DEL-04; keep those cases blocked until coordinator resolves it.

## Dependency and acceptance map

1. WP-DEL-01 (backend test-first) → WP-DEL-02 → WP-DEL-03.
2. WP-DEL-05 (frontend test-first) → WP-DEL-04; UI integration requires WP-DEL-02 and resolution of list-count/state data contract.
3. Backend and frontend branches can proceed independently through their test-first stage. Final integration must verify OpenAPI/client types, count/state availability, authorization, DB transaction, and storage volume behavior together.

| Acceptance ID | Packages |
|---|---|
| WF-DEL-01 | WP-DEL-01, WP-DEL-02, WP-DEL-04, WP-DEL-05 |
| WF-DEL-02 | WP-DEL-01, WP-DEL-02, WP-DEL-03 |
| WF-DEL-03 | WP-DEL-01, WP-DEL-02, WP-DEL-04, WP-DEL-05 |
| WF-DEL-04 | WP-DEL-01, WP-DEL-02, WP-DEL-04, WP-DEL-05 |
| WF-DEL-05 | WP-DEL-03 |
| WF-DEL-06 | WP-DEL-01, WP-DEL-02 |
| WF-DEL-07 | WP-DEL-01, WP-DEL-02 |
| WF-DEL-08 | WP-DEL-04, WP-DEL-05 |

## Coordinator decisions (resolved 2026-10-05)

1. **Frontend count source: extend the workflow view DTO.** Add `task_count`
   and `in_progress_task_count` to the workflow list/get response
   (`WorkflowResponse`/`WorkflowView`), computed in the existing grouped query
   for `list_workflows` and in `get_workflow` (no N+1). No dedicated endpoint is
   added. This is an approved bounded API-contract addition; regenerate the
   frontend client accordingly.
2. **Ownership: author or admin.** Deletion is allowed for the workflow's
   **author** or an **admin**, following the existing publish/activate
   ownership behavior. Inspect the concrete fields; if a workflow is currently
   readable by id by any authenticated user, do not widen the delete
   authorization — keep author-or-admin and use the established not-found /
   forbidden conventions.
3. **Race: lock the workflow row and check within the transaction.** Perform
   `SELECT ... FOR UPDATE` on the workflow row, then the task state/count check
   and the deletions in the same transaction. Verify whether task creation locks
   the workflow row; if it does not, apply the minimal safeguard (task creation
   takes the same row lock) or, if that is disproportionate, rely on the FK as a
   backstop and document the bounded window. Prove the chosen behavior with a
   concurrency test where feasible.
4. **Accepted residual:** best-effort post-commit filesystem cleanup may leave an
   orphan directory on an I/O error; it must be logged and retry-friendly.
   Accepted for this iteration (no retry mechanism included).


## Verification limitations at planning time

The approved spec and durable context were read. Route and workflow service, repository, and workflow list source were inspected. Exact catalog locations, OpenAPI generation command, test scripts/compose test invocation, task creation lock behavior, workflow ownership model, and task count/state availability in the frontend list contract were not verified here. Confirm these from source/config before execution; no test command is represented as already run.
