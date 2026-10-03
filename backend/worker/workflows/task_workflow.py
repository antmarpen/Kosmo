from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from shared.execution import TaskExecutionInput
from shared.checkpoint import is_execution_completed
from worker.interpreter import resolve_edge_inputs


@workflow.defn
class TaskWorkflow:
    def __init__(self):
        self._stop_requested = False
        self._waiting_for_input = False
        self._active_node_execution_id = None

    @workflow.update
    async def human_input(self, answer: str, node_execution_id: str | None = None,
                          request_key: str | None = None) -> str:
        if (not answer or len(answer) > 10000 or not self._waiting_for_input
                or not node_execution_id or node_execution_id != self._active_node_execution_id
                or not request_key):
            raise ValueError("No human input is currently requested")
        await workflow.execute_activity("record_answer", {
            "task_id": self._task_id, "answer": answer,
            "node_execution_id": node_execution_id, "request_key": request_key,
        },
                                        start_to_close_timeout=timedelta(minutes=1))
        return "recorded"

    @workflow.signal
    async def stop(self) -> None:
        self._stop_requested = True

    @workflow.run
    async def run(self, payload: TaskExecutionInput) -> str:
        self._task_id = payload.task_id
        await workflow.execute_activity("start_task", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
        await workflow.execute_activity("load_checkpoint", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
        checkpoint = await workflow.execute_activity("reconcile_checkpoint", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
        completed = checkpoint["completed"]
        order = await workflow.execute_activity("ordered_nodes", payload.definition, start_to_close_timeout=timedelta(minutes=1))
        edges = payload.definition.get("edges", [])
        for node in order:
            if self._stop_requested:
                await workflow.execute_activity("finish_task", (payload.task_id, "stopped"), start_to_close_timeout=timedelta(minutes=1))
                return "stopped"
            if is_execution_completed({"completed": completed}, node["id"], 0):
                continue
            node_execution_id = await workflow.execute_activity(
                "begin_node", (payload.task_id, node["id"]), start_to_close_timeout=timedelta(minutes=1),
            )
            self._active_node_execution_id = node_execution_id
            if node["type"] not in {"start", "end"}:
                if node["type"] == "ai":
                    acquired = await workflow.execute_activity("acquire_agent", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
                    while not acquired:
                        if self._stop_requested:
                            await workflow.execute_activity("cancel_agent_wait", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
                            await workflow.execute_activity("finish_task", (payload.task_id, "stopped"), start_to_close_timeout=timedelta(minutes=1))
                            return "stopped"
                        await workflow.sleep(5)
                        acquired = await workflow.execute_activity("acquire_agent", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
                    if self._stop_requested:
                        await workflow.execute_activity("release_agent", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
                        await workflow.execute_activity("finish_task", (payload.task_id, "stopped"), start_to_close_timeout=timedelta(minutes=1))
                        return "stopped"
                if node["type"] == "ai":
                    self._waiting_for_input = True
                    try:
                        try:
                            node_inputs = resolve_edge_inputs(payload.definition["nodes"], edges, node, completed, payload.input_values)
                        except (KeyError, ValueError) as exc:
                            ambiguous = isinstance(exc, ValueError)
                            result = {
                                "state": "failed", "outputs": {},
                                "error": {
                                    "code": "INPUT_AMBIGUOUS" if ambiguous else "INPUT_MISSING",
                                    "message_key": "errors.agent.input_missing",
                                    "params": {"inputs": str(exc)},
                                },
                            }
                        else:
                            result = await workflow.execute_activity(
                                "run_ai_node",
                                {"task_id": payload.task_id, "node": node,
                                 "task_prompt": payload.input_values.get("prompt", ""),
                                 "inputs": node_inputs,
                                 "node_execution_id": node_execution_id},
                                start_to_close_timeout=timedelta(minutes=30),
                                retry_policy=RetryPolicy(maximum_attempts=3),
                            )
                    except ActivityError:
                        result = {
                            "state": "failed", "outputs": {},
                            "error": {
                                "code": "AGENT_ACTIVITY_FAILED",
                                "message_key": "errors.agent.runtime_failed",
                                "params": {"reason": "activity_retries_exhausted"},
                            },
                        }
                    finally:
                        self._waiting_for_input = False
                        await workflow.execute_activity("release_agent", payload.task_id, start_to_close_timeout=timedelta(minutes=1))
                else:
                    try:
                        node_inputs = resolve_edge_inputs(payload.definition["nodes"], edges, node, completed, payload.input_values)
                    except (KeyError, ValueError) as exc:
                        code = "INPUT_AMBIGUOUS" if isinstance(exc, ValueError) else "INPUT_MISSING"
                        key = "errors.agent.input_missing"
                        result = {"state": "failed", "outputs": {}, "error": {"code": code, "message_key": key, "params": {"inputs": str(exc)}}}
                    else:
                        result = await workflow.execute_activity("run_node", (payload.task_id, node, node_inputs), start_to_close_timeout=timedelta(minutes=5))
            else:
                result = {"state": "success", "error": None}
            await workflow.execute_activity("finish_node", (payload.task_id, node["id"], result), start_to_close_timeout=timedelta(minutes=1))
            self._active_node_execution_id = None
            if self._stop_requested:
                await workflow.execute_activity("finish_task", (payload.task_id, "stopped"), start_to_close_timeout=timedelta(minutes=1))
                return "stopped"
            if result["state"] != "success":
                final_state = "stopped" if result["state"] == "stopped" else "failed"
                await workflow.execute_activity("finish_task", (payload.task_id, final_state), start_to_close_timeout=timedelta(minutes=1))
                return final_state
            completion = {
                "node_id": node["id"], "iteration": 0, "attempt": result.get("attempt", 1),
                "outputs": result.get("outputs", {}),
                "artifact_hashes": {name: ref["sha256"] for name, ref in result.get("outputs", {}).items() if ref.get("sha256")},
            }
            checkpoint = await workflow.execute_activity(
                "publish_completion", {"task_id": payload.task_id, "completion": completion,
                                       "expected_checkpoint": checkpoint},
                start_to_close_timeout=timedelta(minutes=1),
            )
            completed = checkpoint["completed"]
        await workflow.execute_activity("finish_task", (payload.task_id, "success"), start_to_close_timeout=timedelta(minutes=1))
        return "success"
