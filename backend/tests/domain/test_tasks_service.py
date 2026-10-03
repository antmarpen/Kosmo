import asyncio

import pytest

from app.domain.tasks.service import TaskService
from shared.errors import ConflictError, ValidationFailedError
from shared.state import TaskState


class FakeRepository:
    def __init__(self):
        self.active = {"id": "version-1", "definition": {"nodes": [{"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]}]}}
        self.created = []
        self.tasks = []
        self.answers = []

    async def get_active_version(self, workflow_id):
        return self.active

    async def create_task(self, **values):
        values["id"] = "a4bfa43b-127f-4807-a3e5-c8794a868794"
        self.created.append(values)
        return values

    async def list_tasks(self, user_id=None):
        return self.tasks

    async def get_task(self, task_id):
        return next((t for t in self.tasks if t["id"] == task_id), None)

    async def record_answer(self, task_id, answer):
        self.answers.append((task_id, answer))

    async def get_open_input_request(self, task_id, node_execution_id=None, request_key=None):
        if node_execution_id not in (None, "exec-1") or request_key not in (None, "47"):
            return None
        return {"node_execution_id": "exec-1", "request_key": "47"}

    async def update_state(self, task, state):
        task["state"] = state
        return task


class FakeWorkflowStarter:
    def __init__(self):
        self.calls = []
        self.answers = []

    async def start(self, task_id, workflow_id, definition, input_values):
        self.calls.append((task_id, workflow_id, definition, input_values))

    async def submit_answer(self, task_id, answer, node_execution_id=None, request_key=None):
        self.answers.append((task_id, answer, node_execution_id, request_key))

    async def signal_stop(self, task_id):
        self.calls.append(("stop", task_id))


def test_submission_binds_active_definition_and_inputs():
    repository = FakeRepository()
    starter = FakeWorkflowStarter()
    result = asyncio.run(TaskService(repository, starter).submit("workflow-1", {"topic": "test"}, None, "user-1"))
    assert result["state"] == "queued"
    assert repository.created[0]["version_id"] == "version-1"
    assert repository.created[0]["input_values"] == {"topic": "test"}
    assert repository.created[0]["resolved_definition"] == repository.active["definition"]
    assert starter.calls == [("a4bfa43b-127f-4807-a3e5-c8794a868794", "task-a4bfa43b-127f-4807-a3e5-c8794a868794", repository.active["definition"], {"topic": "test"})]


def test_submission_reports_invalid_input_fields():
    with pytest.raises(ValidationFailedError) as error:
        asyncio.run(TaskService(FakeRepository(), FakeWorkflowStarter()).submit("workflow-1", {}, None, "user-1"))
    assert error.value.details[0].params["field"] == "topic"


def test_submission_rejects_non_finite_number_before_task_creation():
    repository = FakeRepository()
    repository.active["definition"]["nodes"][0]["input_form"] = [
        {"name": "amount", "type": "number", "required": True}
    ]
    with pytest.raises(ValidationFailedError):
        asyncio.run(TaskService(repository, FakeWorkflowStarter()).submit(
            "workflow-1", {"amount": float("inf")}, None, "user-1"
        ))
    assert repository.created == []


def test_submission_rejects_invalid_json_start_field_before_task_creation():
    repository = FakeRepository()
    repository.active["definition"]["nodes"][0]["input_form"] = [
        {"name": "settings", "type": "string", "required": True,
         "validation": {"format": "json", "json_schema": {"type": "object"}}}
    ]
    with pytest.raises(ValidationFailedError):
        asyncio.run(TaskService(repository, FakeWorkflowStarter()).submit(
            "workflow-1", {"settings": "not json"}, None, "user-1"
        ))
    assert repository.created == []


def test_task_list_serialization_exposes_only_safe_summary_fields():
    from fastapi.encoders import jsonable_encoder

    repository = FakeRepository()
    repository.tasks = [{"id": "task-1", "workflow_id": "wf-1", "workflow_name": "Example",
                         "state": "running", "created_at": "today", "updated_at": "today",
                         "prompt": "secret", "input_values": {"secret": "value"},
                         "resolved_definition": {"secret": "definition"}}]
    result = asyncio.run(TaskService(repository, FakeWorkflowStarter()).list_tasks({"id": "user-b", "role": "runner"}))
    serialized = jsonable_encoder(result)
    assert serialized == [{"id": "task-1", "workflow_id": "wf-1", "workflow_name": "Example",
                           "state": "running", "created_at": "today", "updated_at": "today"}]
    assert not {"prompt", "input_values", "resolved_definition", "notes", "artifacts"} & serialized[0].keys()


@pytest.mark.parametrize("old,new", [("queued", "running"), ("running", "success"), ("running", "failed"), ("running", "waiting_for_input"), ("running", "stopping"), ("waiting_for_input", "running"), ("waiting_for_input", "stopping"), ("stopping", "stopped"), ("stopping", "failed"), ("stopping", "success")])
def test_legal_transitions(old, new):
    assert TaskService.transition_target(TaskState(old), TaskState(new)) == TaskState(new)


def test_illegal_transition_raises_conflict():
    with pytest.raises(ConflictError):
        TaskService.transition_target(TaskState.queued, TaskState.success)


def test_record_answer_requires_waiting_task_and_persists_before_return():
    repository = FakeRepository()
    repository.tasks.append({"id": "task-1", "state": "waiting_for_input", "created_by": "u1"})
    starter = FakeWorkflowStarter()
    result = asyncio.run(TaskService(repository, starter).record_answer(
        "task-1", "continue", {"id": "u1", "role": "runner"}, "exec-1", "47",
    ))
    assert result == {"id": "task-1", "state": "running"}
    assert starter.answers == [("task-1", "continue", "exec-1", "47")]


def test_record_answer_rejects_non_waiting_task():
    repository = FakeRepository()
    repository.tasks.append({"id": "task-1", "state": "running", "created_by": "u1"})
    with pytest.raises(ConflictError):
            asyncio.run(TaskService(repository, FakeWorkflowStarter()).record_answer(
                "task-1", "continue", {"id": "u1", "role": "runner"}, "exec-1", "47",
            ))


def test_record_answer_forwards_persisted_node_execution_and_request_correlation():
    repository = FakeRepository()
    repository.tasks.append({"id": "task-1", "state": "waiting_for_input", "created_by": "u1"})
    repository.get_open_input_request = async_def_get_open_request

    class CorrelatedStarter(FakeWorkflowStarter):
        async def submit_answer(self, task_id, answer, node_execution_id, request_key):
            self.answers.append((task_id, answer, node_execution_id, request_key))

    starter = CorrelatedStarter()
    asyncio.run(TaskService(repository, starter).record_answer(
        "task-1", "allow-once", {"id": "u1", "role": "runner"},
        node_execution_id="exec-1", request_id="47",
    ))
    assert starter.answers == [("task-1", "allow-once", "exec-1", "47")]


async def async_def_get_open_request(task_id, node_execution_id=None, request_key=None):
    return {"node_execution_id": "exec-1", "request_key": "47"}


def test_duplicate_answers_for_same_agent_request_are_serialized():
    import asyncio

    class CorrelatedRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.answers_for_request = set()
            self.lock = asyncio.Lock()

        async def get_open_input_request(self, task_id, node_execution_id=None, request_key=None):
            return {"node_execution_id": "exec-1", "request_key": "47"}

        async def record_answer(self, task_id, answer, node_execution_id, request_key):
            from shared.errors import ConflictError
            async with self.lock:
                key = (node_execution_id, request_key)
                if key in self.answers_for_request:
                    raise ConflictError("errors.task.input_answer_pending")
                self.answers_for_request.add(key)

    class PersistingWorkflowStarter(FakeWorkflowStarter):
        def __init__(self, repo):
            super().__init__()
            self.repo = repo

        async def submit_answer(self, task_id, answer, node_execution_id, request_key):
            await self.repo.record_answer(task_id, answer, node_execution_id, request_key)
            self.answers.append((task_id, answer, node_execution_id, request_key))

    repository = CorrelatedRepository()
    repository.tasks.append({"id": "task-1", "state": "waiting_for_input", "created_by": "u1"})
    starter = PersistingWorkflowStarter(repository)
    service = TaskService(repository, starter)

    async def concurrently_submit():
        results = await asyncio.gather(
            service.record_answer("task-1", "allow-once", {"id": "u1", "role": "runner"}, "exec-1", "47"),
            service.record_answer("task-1", "reject-once", {"id": "u1", "role": "runner"}, "exec-1", "47"),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, ConflictError) for result in results) == 1

    asyncio.run(concurrently_submit())


def test_stop_while_waiting_stops_immediately():
    repository = FakeRepository()
    repository.tasks.append({"id": "task-1", "state": "waiting_for_input", "created_by": "u1"})
    starter = FakeWorkflowStarter()
    result = asyncio.run(TaskService(repository, starter).request_stop("task-1", {"id": "u1", "role": "runner"}))
    assert result["state"] == "stopped"
    assert repository.tasks[0]["state"] == "stopped"


def test_stop_after_finished_task_conflicts():
    repository = FakeRepository()
    repository.tasks.append({"id": "task-1", "state": "success", "created_by": "u1"})
    with pytest.raises(ConflictError):
        asyncio.run(TaskService(repository, FakeWorkflowStarter()).request_stop("task-1", {"id": "u1", "role": "runner"}))
