from shared.errors import ConflictError, ErrorDetail, NotFoundError, PermissionDeniedError, ValidationFailedError
from shared.state import TaskState
import math
import json

from app.domain.workflows.validation_logic import evaluate_content


TRANSITIONS = {
    TaskState.queued: {TaskState.running, TaskState.stopping, TaskState.allocating},
    TaskState.allocating: {TaskState.queued, TaskState.running, TaskState.stopping, TaskState.failed},
    TaskState.running: {TaskState.success, TaskState.failed, TaskState.waiting_for_input, TaskState.stopping},
    TaskState.waiting_for_input: {TaskState.running, TaskState.stopping},
    TaskState.stopping: {TaskState.stopped, TaskState.failed, TaskState.success},
    TaskState.stopped: set(), TaskState.failed: set(), TaskState.success: set(),
}


def value(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)


class TaskService:
    def __init__(self, repository, workflow_starter=None):
        self.repository = repository
        self.workflow_starter = workflow_starter or TemporalWorkflowStarter()

    async def submit(self, workflow_id, input_values, prompt, user_id):
        version = await self.repository.get_active_version(workflow_id)
        if version is None:
            raise NotFoundError("errors.workflow.not_found")
        definition = value(version, "definition")
        start = next((node for node in definition["nodes"] if node["type"] == "start"), None)
        errors = await validate_start_inputs(start, input_values)
        if errors:
            raise ValidationFailedError("errors.task.invalid_input", details=errors)
        task = await self.repository.create_task(workflow_id=workflow_id, version_id=value(version, "id"), state=TaskState.queued.value,
            prompt=prompt, input_values=input_values, resolved_definition=definition, created_by=user_id)
        task_id = value(task, "id")
        db = getattr(self.repository, "db", None)
        if db is not None:
            from app.domain.events.service import publish_event
            await publish_event(db, task_id, "task.state", state=TaskState.queued.value)
        if hasattr(self.repository, "db"):
            from app.core.config import settings
            from app.domain.scheduling.repository import SchedulingRepository
            from app.domain.scheduling.service import SchedulingService
            await SchedulingService(SchedulingRepository(self.repository.db), self.workflow_starter,
                                    settings.max_main_tasks, settings.max_agents).admit_queued()
        else:
            await self.workflow_starter.start(task_id, f"task-{task_id}", definition, input_values)
        return {"id": value(task, "id"), "state": value(task, "state")}


    async def list_tasks(self, user):
        rows = await self.repository.list_tasks()
        result = []
        for row in rows:
            if isinstance(row, dict):
                task, workflow_name = row, value(row, "workflow_name")
            else:
                task, workflow_name = row[0], row[1]
            result.append({"id": value(task, "id"), "workflow_id": value(task, "workflow_id"),
                           "workflow_name": workflow_name, "state": value(task, "state"),
                           "created_at": value(task, "created_at"), "updated_at": value(task, "updated_at")})
        return result

    async def get_task(self, task_id, user):
        task = await self.repository.get_task(task_id)
        if task is None:
            raise NotFoundError("errors.task.not_found")
        if _role(user) != "admin" and value(task, "created_by") != value(user, "id"):
            raise PermissionDeniedError("errors.permission.denied")
        nodes, notes, artifacts = await self.repository.get_detail_parts(task_id)
        return {"id": value(task, "id"), "workflow_id": value(task, "workflow_id"), "version_id": value(task, "version_id"),
            "state": value(task, "state"), "prompt": value(task, "prompt"), "input_values": value(task, "input_values"),
            "resolved_definition": value(task, "resolved_definition"), "created_by": value(task, "created_by"),
            "created_at": value(task, "created_at"), "updated_at": value(task, "updated_at"),
            "nodes": nodes, "notes": notes, "artifacts": artifacts}

    @staticmethod
    def transition_target(current, target):
        if target not in TRANSITIONS[TaskState(current)]:
            raise ConflictError("errors.task.invalid_transition", params={"from": str(current), "to": str(target)})
        return TaskState(target)

    async def transition(self, task_id, target):
        task = await self.repository.get_task(task_id)
        if task is None:
            raise NotFoundError("errors.task.not_found")
        state = self.transition_target(value(task, "state"), target)
        return await self.repository.update_state(task, state.value)

    async def record_answer(self, task_id, answer, user, node_execution_id=None, request_id=None):
        task = await self.repository.get_task(task_id)
        if task is None:
            raise NotFoundError("errors.task.not_found")
        if _role(user) != "admin" and value(task, "created_by") != value(user, "id"):
            raise PermissionDeniedError("errors.permission.denied")
        if value(task, "state") != TaskState.waiting_for_input.value:
            raise ConflictError("errors.task.input_not_requested")
        if not node_execution_id or request_id is None:
            raise ConflictError("errors.task.input_request_correlation_required")
        request_key = str(request_id) if request_id is not None else None
        request = await self.repository.get_open_input_request(task_id, node_execution_id, request_key)
        if request is None:
            raise ConflictError("errors.task.input_request_stale")
        await self.workflow_starter.submit_answer(
            task_id, answer, request["node_execution_id"], request["request_key"],
        )
        return {"id": task_id, "state": TaskState.running.value}

    async def request_stop(self, task_id, user):
        task = await self.repository.get_task(task_id)
        if task is None:
            raise NotFoundError("errors.task.not_found")
        if _role(user) != "admin" and value(task, "created_by") != value(user, "id"):
            raise PermissionDeniedError("errors.permission.denied")
        current = TaskState(value(task, "state"))
        if current not in {TaskState.queued, TaskState.allocating, TaskState.running, TaskState.waiting_for_input}:
            raise ConflictError("errors.task.invalid_transition", params={"from": current.value, "to": "stopping"})
        db = getattr(self.repository, "db", None)
        if current == TaskState.queued:
            target = TaskState.stopped
            await self.repository.update_state(task, target.value)
        else:
            await self.workflow_starter.signal_stop(task_id)
            target = TaskState.stopped if current == TaskState.waiting_for_input else TaskState.stopping
            await self.repository.update_state(task, target.value)
        if current == TaskState.allocating and db is not None:
            from app.domain.scheduling.repository import SchedulingRepository
            await SchedulingRepository(db).remove_agent_waiter(task_id)
        if db is not None:
            from app.domain.events.service import publish_event
            await publish_event(db, task_id, "task.state", state=target.value)
            await db.commit()
        return {"id": task_id, "state": target.value}


class TemporalWorkflowStarter:
    async def start(self, task_id, workflow_id, definition, input_values):
        import logging
        from temporalio.client import Client
        from app.core.config import settings
        from shared.execution import TaskExecutionInput
        from worker.workflows.task_workflow import TaskWorkflow

        try:
            client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
            await client.start_workflow(TaskWorkflow.run, TaskExecutionInput(task_id, definition, input_values),
                                       id=workflow_id, task_queue=settings.temporal_task_queue)
        except Exception:
            logging.getLogger(__name__).exception("Could not start Temporal workflow for task %s", task_id)
            raise

    async def signal_stop(self, task_id):
        from temporalio.client import Client
        from app.core.config import settings

        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(f"task-{task_id}")
        await handle.signal("stop")

    async def submit_answer(self, task_id, answer, node_execution_id, request_key):
        from temporalio.client import Client
        from app.core.config import settings

        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(f"task-{task_id}")
        return await handle.execute_update("human_input", answer, node_execution_id, request_key)


def _role(user):
    return str(value(user, "role").value if hasattr(value(user, "role"), "value") else value(user, "role"))


def _matches_type(value_, type_):
    return {"string": lambda x: isinstance(x, str), "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x),
            "boolean": lambda x: isinstance(x, bool)}[type_](value_)


async def validate_start_inputs(start, input_values, rule_validation=None):
    """Shared submission/worker structural and contract checks for Start fields."""
    errors = []
    fields = {field["name"]: field for field in start.get("input_form", [])}
    for name, field in fields.items():
        if field["required"] and name not in input_values:
            errors.append(ErrorDetail("errors.task.input_required", {"field": name}))
            continue
        if name not in input_values:
            continue
        submitted = input_values[name]
        if not _matches_type(submitted, field["type"]):
            errors.append(ErrorDetail("errors.task.input_type", {"field": name, "type": field["type"]}))
            continue
        contract = field.get("validation")
        if contract:
            validation_value = submitted if isinstance(submitted, str) else json.dumps(submitted, allow_nan=False)
            validation_bytes = validation_value.encode("utf-8")
            for level in (1, 2, 3):
                if level == 3 and contract.get("rules_code"):
                    if rule_validation:
                        failures = await rule_validation(name, validation_value, contract)
                    else:
                        from app.api.routes.mcp import _validation_probe
                        failures = await _validation_probe(validation_bytes, contract, level, name)
                else:
                    failures = evaluate_content(validation_bytes, contract, level)
                if failures:
                    errors.extend(ErrorDetail(item["message_key"], {"field": name, **item["params"]}) for item in failures)
                    break
    for name in input_values.keys() - fields.keys():
        errors.append(ErrorDetail("errors.task.input_unknown", {"field": name}))
    return errors
