from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tasks.models import Artifact, NodeExecution, Task, TaskNote
from app.domain.workflows.models import Activation, Workflow, WorkflowVersion


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_version(self, workflow_id):
        return await self.db.scalar(select(WorkflowVersion).join(Activation, Activation.version_id == WorkflowVersion.id).where(Activation.workflow_id == workflow_id))

    async def create_task(self, **values):
        row = Task(**values)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_tasks(self, user_id=None):
        query = select(Task, Workflow.name).join(Workflow, Workflow.id == Task.workflow_id).order_by(Task.created_at.desc())
        if user_id is not None:
            query = query.where(Task.created_by == user_id)
        return list((await self.db.execute(query)).all())

    async def get_task(self, task_id):
        return await self.db.get(Task, task_id)

    async def get_detail_parts(self, task_id):
        nodes = list((await self.db.scalars(select(NodeExecution).where(NodeExecution.task_id == task_id))).all())
        notes = list((await self.db.scalars(select(TaskNote).where(TaskNote.task_id == task_id))).all())
        artifacts = list((await self.db.scalars(select(Artifact).where(Artifact.task_id == task_id))).all())
        return nodes, notes, artifacts

    async def update_state(self, task, state):
        task.state = state
        await self.db.flush()
        return task

    async def record_answer(self, task_id, answer, node_execution_id, request_key):
        from shared.errors import ConflictError
        from sqlalchemy import desc, func
        # Serialize acceptance on the task row: concurrent HTTP/Temporal Updates
        # cannot both observe the same request as unanswered.
        task = await self.db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if task is None:
            raise ConflictError("errors.task.input_not_requested")
        request_scope = await self.get_open_input_request(task_id, node_execution_id, request_key)
        if request_scope is None:
            if await self.get_pending_answer(task_id, node_execution_id, request_key) is not None:
                raise ConflictError("errors.task.input_answer_pending")
            raise ConflictError("errors.task.input_request_stale")
        if await self.get_pending_answer(task_id, node_execution_id, request_key) is not None:
            raise ConflictError("errors.task.input_answer_pending")
        request_note = request_scope["note"]
        request_note.params = {**request_note.params, "answer_recorded": True}
        revision = (await self.db.scalar(select(func.max(TaskNote.revision)).where(TaskNote.task_id == task_id)) or 0) + 1
        self.db.add(TaskNote(task_id=task_id, revision=revision, message_key="tasks.notes.input_answer",
                             params={"answer": answer, "delivered": False,
                                     "node_execution_id": node_execution_id, "request_key": request_key}))
        await self.db.commit()

    async def get_open_input_request(self, task_id, node_execution_id=None, request_key=None):
        from sqlalchemy import desc
        notes = await self.db.scalars(select(TaskNote).where(
            TaskNote.task_id == task_id, TaskNote.message_key == "tasks.notes.input_requested",
        ).order_by(desc(TaskNote.revision)))
        for note in notes.all():
            if note.params.get("answer_recorded"):
                continue
            if node_execution_id is not None and note.params.get("node_execution_id") != node_execution_id:
                continue
            if request_key is not None and note.params.get("request_key") != str(request_key):
                continue
            if note.params.get("node_execution_id") and note.params.get("request_key"):
                return {"node_execution_id": note.params["node_execution_id"],
                        "request_key": note.params["request_key"], "request_id": note.params.get("request_id"),
                        "note": note}
        return None

    async def get_pending_answer(self, task_id, node_execution_id=None, request_key=None):
        from sqlalchemy import desc
        notes = await self.db.scalars(select(TaskNote).where(
            TaskNote.task_id == task_id, TaskNote.message_key == "tasks.notes.input_answer"
        ).order_by(desc(TaskNote.revision)))
        for note in notes.all():
            if note.params.get("delivered"):
                continue
            if node_execution_id is not None and note.params.get("node_execution_id") != node_execution_id:
                continue
            if request_key is not None and note.params.get("request_key") != str(request_key):
                continue
            return note
        return None

    async def mark_answer_delivered(self, note):
        note.params = {**note.params, "delivered": True}
        await self.db.commit()
