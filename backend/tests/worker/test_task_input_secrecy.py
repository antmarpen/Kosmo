"""Temporal-history privacy and replay tests for task inputs.

These opt-in tests exercise the workflow boundary with Temporal's in-process
test environment. The recorded history is inspected as serialized events, not
by asserting internal helper calls.

Run where the in-process Temporal test server can start (it can hang in some
sandboxes):

    KOSMO_TEMPORAL_INTEGRATION=1 uv run pytest tests/worker/test_task_input_secrecy.py
"""

from __future__ import annotations

import json
import os

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from shared.execution import TaskExecutionInput
from worker.workflows.task_workflow import TaskWorkflow

pytestmark = pytest.mark.skipif(
    os.getenv("KOSMO_TEMPORAL_INTEGRATION") != "1",
    reason="Temporal in-process test server unavailable here; set KOSMO_TEMPORAL_INTEGRATION=1.",
)

SECRET = "SENTINEL_TASK_INPUT_9f23c6"
TASK_ID = "task-secrecy-test"
# Worker-local store: in production the opaque activity reads the persisted task.
STORE = {TASK_ID: SECRET}
NODES = [
    {"id": "start", "type": "start"},
    {"id": "agent", "type": "ai", "inputs": ["credential"]},
    {"id": "end", "type": "end"},
]


def _payload() -> TaskExecutionInput:
    """The production starter shape: no input values cross the workflow boundary."""
    return TaskExecutionInput(
        task_id=TASK_ID,
        definition={"nodes": NODES, "edges": [{"from": "start", "to": "agent"}, {"from": "agent", "to": "end"}]},
    )


def _history_text(history) -> str:
    return json.dumps(history, default=str)


def _register(name: str, result=None):
    """A fresh activity per name (the same function cannot be decorated twice)."""
    async def handler(*_args):
        return result
    return activity.defn(name=name)(handler)


def _activities(execute_opaque):
    return [
        _register("start_task"),
        _register("load_checkpoint"),
        _register("reconcile_checkpoint", {"completed": {}}),
        _register("ordered_nodes", NODES),
        _register("begin_node", "node-execution"),
        _register("acquire_agent", True),
        _register("validate_persisted_start_inputs", []),
        activity.defn(name="execute_opaque_node")(execute_opaque),
        _register("release_agent"),
        _register("finish_node"),
        _register("publish_completion", {"completed": {}}),
        _register("finish_task"),
    ]


def _secrecy_execute(seen):
    async def execute_opaque(payload):
        # Inputs are resolved inside the activity from storage, never from the
        # workflow arguments, so the sentinel must not appear here.
        assert SECRET not in json.dumps(payload, default=str)
        assert STORE[payload["task_id"]] == SECRET
        seen.append(payload)
        return {"state": "success", "outputs": {}, "error": None}
    return execute_opaque


@pytest.mark.asyncio
async def test_new_execution_keeps_task_input_out_of_history_and_activity_arguments():
    """The opaque path keeps the sentinel out of workflow/activity arguments and
    out of the recorded history."""
    seen: list = []
    activities = _activities(_secrecy_execute(seen))
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="secrecy", workflows=[TaskWorkflow], activities=activities):
            handle = await env.client.start_workflow(
                TaskWorkflow.run, _payload(), id="secrecy", task_queue="secrecy"
            )
            assert await handle.result() == "success"
            history = await handle.fetch_history()

    assert SECRET not in _history_text(history)
    assert seen and all(SECRET not in json.dumps(item, default=str) for item in seen)


@pytest.mark.asyncio
async def test_recorded_history_replays_with_the_current_workflow():
    """A recorded history replays against the current workflow definition. The
    explicit pre-patch legacy branch needs a history recorded before the patch
    marker and is not crafted here."""
    from temporalio.worker import Replayer

    activities = _activities(_secrecy_execute([]))
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="replay", workflows=[TaskWorkflow], activities=activities):
            handle = await env.client.start_workflow(
                TaskWorkflow.run, _payload(), id="replay", task_queue="replay"
            )
            await handle.result()
            history = await handle.fetch_history()

    await Replayer(workflows=[TaskWorkflow]).replay_workflow(history)
