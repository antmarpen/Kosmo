# Execution Orchestration Assessment

Status: Temporal approved as the architecture baseline, subject to a recovery
and agent-interaction proof of concept before full engine implementation.
Date: 2026-09-30.

## Why reassess the original recommendation

An earlier suggestion favored an asyncio-based engine with PostgreSQL state.
The expanded requirements include durable human waits, cooperative stopping,
resuming, retries, cyclic graphs, parallel branches, nested workflows, and
long-lived agent sessions. These require orchestration correctness even for a
small installation, not only at high scale. Persisting a status row does not
itself restore a lost coroutine, process, or external operation.

## Options

| Option | Value | Work and operational cost |
| --- | --- | --- |
| Custom engine with PostgreSQL and workers | Complete control, fewer infrastructure components. | Kosmo must implement durable scheduling, claims/leases, crash recovery, messages, timers, checkpoints, retries, and concurrency correctness. |
| Temporal with Python workers | Durable orchestration, messages, retry/timer primitives, and child executions align with the product. | Adds Temporal infrastructure or a managed service, workers, deterministic replay constraints, versioning discipline, and deployment/operational knowledge. |

Decision: adopt Temporal as the architecture baseline and validate recovery and
agent interactions with a bounded proof of concept before full implementation.
The alternatives above explain the decision. No runtime is implemented yet.

## Task checkpoint file

The owner requires an atomically updated checkpoint file per task. Record a node
as completed only after its artifacts pass validation and are durably available.
Retry and resume preserve committed completions rather than repeating successful
work. Distinguish executions across child workflows, iterations, and attempts.

Proposed integration, pending detailed architecture:

- Temporal's durable history governs orchestration; the file materializes
  committed completions rather than acting as an independent scheduler.
- Persist validated artifacts, record completion through the orchestration, and
  publish the checkpoint using an Activity. File I/O does not run in deterministic
  Workflow code. Define whether publication gates downstream admission.
- Confirmed: exactly one writer per task consumes queued completion records
  sequentially and publishes atomic checkpoint updates. Nodes never write the
  file directly. Two simultaneous completion requests are queued and applied
  one after the other. Define durable queue/replay and completion deduplication
  so writer restarts do not lose or duplicate records; prevent an old writer
  from continuing after replacement.
- Store the file outside disposable agent containers. Temporary-file writing
  followed by replacement on the same filesystem is a candidate; verify atomicity
  and flush/durability guarantees on the chosen persistent storage.
- Include task/definition identity, checkpoint revision, completed execution IDs,
  and artifact references/integrity metadata, not credentials or raw prompts/notes.
- Reconcile crashes between artifact persistence, completion recording, and
  checkpoint publication. These are not one cross-system atomic transaction.
  Regenerate a lagging checkpoint from durable state; do not trust a file claim
  that conflicts with history or references missing artifacts.

## Out of scope: external-operation interception

Deferred by the owner on 2026-09-30. Recording, intercepting, or reconciling
external side effects is not part of the current requirements; the added
complexity is not justified now. Nodes and agents may perform external actions
without platform-level operation journals, gateways, idempotency guarantees, or
recovery mechanisms for them. If such an operation fails or repeats, resolution
happens outside the platform. Revisit only if recovery requirements change;
none of the earlier interception/gateway proposals is approved or implemented.

## Proposed mapping if adopted

- A Kosmo task maps to a durable orchestration execution; the exact relationship
  across retry/resume attempts and Temporal run IDs remains to be defined.
- A stable, code-defined interpreter reads a pinned Kosmo graph definition.
  Users still author visual graphs, not Python Temporal workflow definitions.
- External I/O, Docker operations, scripts, validation code, provider calls,
  and Git operations execute outside deterministic workflow code, through
  Activities and managed execution services.
- Signals or Updates carry human responses, message intents, and lifecycle
  requests. Updates can acknowledge acceptance/results; Signals do not mean
  the worker has already processed the request.
- Child Workflows can represent nested Kosmo workflow invocations with an
  explicit parent-close policy.
- Persist artifact content separately and carry references through orchestration
  history. Define bounded handling of streaming events and long execution
  histories rather than recording every token as a workflow event.

## Responsibilities Temporal does not remove

- Graph semantics, cycle limits, joins, validation, and workflow versioning.
- Resource admission and capacity checks before marking a task running.
- Docker isolation, container lifecycle, and agent session persistence.
- Authorization, repository scope enforcement, and secret handling.
- Application CRUD audit; execution history is not a substitute.
- Kosmo stop/resume semantics: terminating or cancelling an execution is not
  equivalent to a reversible application-level stop. A durable pause can retain
  orchestration state, but reconstructing a process/session needs explicit logic.

## Proposed proof-of-concept acceptance evidence

1. Recover orchestration after a worker restart without duplicating recorded
   checkpoint completions.
2. Retain a human question across restart and route the response to the correct
   node/session; handle duplicate or late responses explicitly.
3. Run parallel branches with a human wait, then stop/resume according to an
   agreed policy, including nested workflow behavior.
4. Execute a bounded feedback loop and prove the configured limit is enforced.
5. Demonstrate what happens to the Docker container and provider session during
   each recovery case. Separate durable task state from runtime survival.
6. Concurrent completions do not lose checkpoint entries, and stale retries cannot
   overwrite newer revisions. Exercise crashes between artifact persistence,
   completion recording, and checkpoint publication; verify recovery convergence.

These are proposed checks, not executed tests or an approved implementation plan.

## Sources reviewed

- [Python message passing: Queries, Signals, Updates, wait conditions](https://docs.temporal.io/develop/python/message-passing)
- [Python Child Workflows and parent-close policy](https://docs.temporal.io/develop/python/child-workflows)
