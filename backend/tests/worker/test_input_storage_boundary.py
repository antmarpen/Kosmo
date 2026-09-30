"""Durable human-input storage boundary tests (RR-04).

Proves the real activity/repository boundary against the migrated test
database: answer delivery-once, duplicate-answer rejection, stale-request
rejection, and stop-at-wait cancellation — the AC-06 durable-input semantics
that fake-repository tests cannot establish.

NOTE: host→localhost:5432 connections reset on this Windows host (documented
quirk), so run this file inside the backend container where postgres:5432 is
stable: `docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=
'postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' uv run pytest
tests/worker/test_input_storage_boundary.py -q"`. Skipped on the Windows host
for that reason.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.tasks.models import Task, TaskNote
from app.domain.workflows.models import Activation, Workflow, WorkflowVersion
from shared.errors import ConflictError

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)


@pytest.fixture
def task_row(migrated_test_database, monkeypatch):
    """A real task row in the migrated test database.

    Sync fixture on purpose: each test drives async boundaries with its own
    asyncio.run loop, so the session factory uses NullPool (pooled connections
    cannot survive loop changes) and the patch replaces app.core.db's factory
    before any activity import resolves it at call time.
    """
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.AsyncSessionLocal", factory)

    async def setup() -> str:
        async with factory() as db:
            from app.domain.identity.models import User, UserRole
            user = User(id=str(uuid.uuid4()), username=f"runner-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.runner)
            db.add(user)
            workflow = Workflow(id=str(uuid.uuid4()), name=f"e2e-{uuid.uuid4()}")
            db.add(workflow)
            version = WorkflowVersion(id=str(uuid.uuid4()), workflow_id=workflow.id,
                                      version=1, definition={"schema_version": "v1",
                                                             "nodes": [], "edges": []})
            db.add(version)
            await db.flush()
            db.add(Activation(workflow_id=workflow.id, version_id=version.id))
            task = Task(id=str(uuid.uuid4()), workflow_id=workflow.id, version_id=version.id,
                        state="running", prompt=None, input_values={}, resolved_definition={},
                        created_by=user.id)
            db.add(task)
            await db.commit()
            return task.id

    task_id = asyncio.run(setup())
    yield task_id
    asyncio.run(engine.dispose())


def _open_request(task_id: str, node_execution_id: str, request_key: str) -> None:
    # Call-time import so the patched session factory applies.
    from app.core.db import AsyncSessionLocal

    async def insert() -> None:
        async with AsyncSessionLocal() as db:
            db.add(TaskNote(task_id=task_id, revision=1,
                            message_key="tasks.notes.input_requested",
                            params={"message_key": "agent.question",
                                    "node_execution_id": node_execution_id,
                                    "request_id": request_key, "request_key": request_key,
                                    "answer_recorded": False}))
            await db.commit()

    asyncio.run(insert())


def _mark_stopping(task_id: str) -> None:
    from app.core.db import AsyncSessionLocal

    async def update() -> None:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            task.state = "stopping"
            await db.commit()

    asyncio.run(update())


def test_record_answer_persists_pending_once_then_delivery_consumes_it(task_row):
    from worker.activities.input import mark_answer_delivered, pending_answer, record_answer

    task_id = task_row
    node_execution_id, request_key = str(uuid.uuid4()), "req-1"
    _open_request(task_id, node_execution_id, request_key)

    result = asyncio.run(record_answer({
        "task_id": task_id, "answer": "proceed",
        "node_execution_id": node_execution_id, "request_key": request_key,
    }))
    assert result["answer"] == "proceed"

    pending = asyncio.run(pending_answer(task_id, node_execution_id, request_key))
    assert pending is not None and pending["answer"] == "proceed"

    asyncio.run(mark_answer_delivered({"id": pending["id"]}))
    assert asyncio.run(pending_answer(task_id, node_execution_id, request_key)) is None


def test_duplicate_answer_for_same_request_is_rejected(task_row):
    from worker.activities.input import record_answer

    task_id = task_row
    node_execution_id, request_key = str(uuid.uuid4()), "req-dup"
    _open_request(task_id, node_execution_id, request_key)
    call = {"task_id": task_id, "answer": "first",
            "node_execution_id": node_execution_id, "request_key": request_key}
    asyncio.run(record_answer(call))
    with pytest.raises(ConflictError):
        asyncio.run(record_answer(call))


def test_answer_without_open_request_is_rejected(task_row):
    from worker.activities.input import record_answer

    with pytest.raises(ConflictError):
        asyncio.run(record_answer({
            "task_id": task_row, "answer": "unsolicited",
            "node_execution_id": str(uuid.uuid4()), "request_key": "missing",
        }))


def test_await_human_answer_returns_pending_answer_after_restart(task_row):
    from worker.activities.input import await_human_answer

    task_id = task_row
    node_execution_id, request_key = str(uuid.uuid4()), "req-restart"
    _open_request(task_id, node_execution_id, request_key)
    from worker.activities.input import record_answer
    asyncio.run(record_answer({"task_id": task_id, "answer": "post-restart",
                               "node_execution_id": node_execution_id, "request_key": request_key}))

    answer = asyncio.run(await_human_answer(
        task_id, "ai1", "agent.question", {}, node_execution_id, request_key, request_key,
    ))
    assert answer == "post-restart"


def test_await_human_answer_returns_none_when_task_is_stopping(task_row):
    import threading
    import time
    from worker.activities.input import await_human_answer

    task_id = task_row
    node_execution_id, request_key = str(uuid.uuid4()), "req-stop"
    _open_request(task_id, node_execution_id, request_key)

    def stop_once_polling() -> None:
        # The activity sets waiting_for_input on entry; stop once it is polling.
        for _ in range(20):
            time.sleep(0.25)
            state = _read_state(task_id)
            if state == "waiting_for_input":
                _mark_stopping(task_id)
                return

    stopper = threading.Thread(target=stop_once_polling)
    stopper.start()
    answer = asyncio.run(await_human_answer(
        task_id, "ai1", "agent.question", {}, node_execution_id, request_key, request_key,
    ))
    stopper.join(timeout=15)
    assert answer is None  # stop-at-wait: the pending wait is discarded


def _read_state(task_id: str) -> str:
    from app.core.db import AsyncSessionLocal

    async def read() -> str:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            return task.state

    return asyncio.run(read())
