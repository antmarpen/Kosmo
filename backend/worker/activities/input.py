"""Durable task input storage and polling used by the AI activity."""

import asyncio
from datetime import timedelta

from temporalio import activity


@activity.defn
async def record_answer(payload: dict) -> dict:
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.repository import TaskRepository

    async with AsyncSessionLocal() as db:
        await TaskRepository(db).record_answer(
            payload["task_id"], payload["answer"], payload["node_execution_id"], payload["request_key"],
        )
    return {"answer": payload["answer"], "node_execution_id": payload["node_execution_id"],
            "request_key": payload["request_key"]}


@activity.defn
async def pending_answer(task_id: str, node_execution_id: str, request_key: str):
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.repository import TaskRepository

    async with AsyncSessionLocal() as db:
        note = await TaskRepository(db).get_pending_answer(task_id, node_execution_id, request_key)
        if note is None:
            return None
        return {"id": note.id, "answer": note.params["answer"]}


@activity.defn
async def mark_answer_delivered(payload: dict):
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.repository import TaskRepository
    from app.domain.tasks.models import TaskNote

    async with AsyncSessionLocal() as db:
        note = await db.get(TaskNote, payload["id"])
        if note:
            await TaskRepository(db).mark_answer_delivered(note)


@activity.defn
async def await_human_answer(task_id: str, node_id: str, message_key: str, params: dict,
                             node_execution_id: str, request_id: str | int | None, request_key: str) -> str:
    from worker.activities.ai_node import _add_task_note
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Task
    from app.domain.events.service import publish_event

    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task:
            task.state = "waiting_for_input"
            await publish_event(db, task_id, "task.state", state="waiting_for_input")
            await db.commit()
    await _add_task_note(task_id, node_id, "tasks.notes.input_requested", {
        "message_key": message_key, **params,
        "node_execution_id": node_execution_id,
        "request_id": request_id if request_id is not None else request_key,
        "request_key": request_key,
        "answer_recorded": False,
    })
    while True:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            if task and task.state in {"stopping", "stopped"}:
                return None
        answer = await pending_answer(task_id, node_execution_id, request_key)
        if answer is not None:
            # Caller delivers to ACP before marking the answer consumed.
            return answer["answer"]
        await asyncio.sleep(0.5)
