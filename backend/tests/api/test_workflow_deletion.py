"""PostgreSQL-backed workflow deletion contract tests."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Run DB-backed tests in the backend container")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.identity.models import User, UserRole
from app.domain.workflows.models import Workflow, WorkflowVersion
from app.domain.tasks.models import Task
from app.main import create_app


@pytest.fixture(scope="module")
def db_factory(migrated_test_database):
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    asyncio.run(engine.dispose())


@pytest.fixture
def deletion_data(db_factory):
    user_id, workflow_id, version_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    async def seed():
        async with db_factory() as db:
            db.add(User(id=user_id, username=f"delete-{uuid.uuid4()}", password_hash="x", role=UserRole.builder))
            db.add(Workflow(id=workflow_id, name=f"Delete {uuid.uuid4()}"))
            db.add(WorkflowVersion(id=version_id, workflow_id=workflow_id, version=1, definition={"schema_version": "v1", "name": "x", "nodes": [], "edges": []}))
            await db.commit()
    asyncio.run(seed())

    app = create_app()
    async def override_db():
        async with db_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id, username="builder", role=UserRole.builder)
    client = TestClient(app)
    yield client, db_factory, user_id, workflow_id, version_id
    async def cleanup():
        async with db_factory() as db:
            await db.execute(text("DELETE FROM tasks WHERE workflow_id=:id"), {"id": workflow_id})
            await db.execute(text("DELETE FROM workflows WHERE id=:id"), {"id": workflow_id})
            await db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            await db.commit()
    asyncio.run(cleanup())


def _add_task(factory, user_id, workflow_id, version_id, state="success"):
    task_id = str(uuid.uuid4())
    async def seed():
        async with factory() as db:
            db.add(Task(id=task_id, workflow_id=workflow_id, version_id=version_id, state=state,
                        input_values={}, resolved_definition={}, created_by=user_id))
            await db.commit()
    asyncio.run(seed())
    return task_id


def test_deletes_empty_workflow_and_returns_no_content(deletion_data):
    client, _, _, workflow_id, _ = deletion_data
    response = client.delete(f"/workflows/{workflow_id}")
    assert response.status_code == 204


def test_tasks_require_explicit_delete_and_in_progress_is_blocked(deletion_data):
    client, factory, user_id, workflow_id, version_id = deletion_data
    task_id = _add_task(factory, user_id, workflow_id, version_id, "running")
    blocked = client.request("DELETE", f"/workflows/{workflow_id}", json={"delete_tasks": True})
    assert blocked.status_code == 409
    assert blocked.json()["message_key"] == "errors.workflow.delete_in_progress"
    assert blocked.json()["params"]["count"] == 1
    async def state_remains():
        async with factory() as db:
            return await db.scalar(text("SELECT state FROM tasks WHERE id=:id"), {"id": task_id})
    assert asyncio.run(state_remains()) == "running"


def test_deletes_terminal_tasks_only_when_requested(deletion_data):
    client, factory, user_id, workflow_id, version_id = deletion_data
    task_id = _add_task(factory, user_id, workflow_id, version_id)
    blocked = client.delete(f"/workflows/{workflow_id}")
    assert blocked.status_code == 409
    assert blocked.json()["message_key"] == "errors.workflow.delete_tasks_exist"
    assert blocked.json()["params"]["count"] == 1
    deleted = client.request("DELETE", f"/workflows/{workflow_id}", json={"delete_tasks": True})
    assert deleted.status_code == 204


def test_task_storage_is_removed_when_tasks_are_deleted(deletion_data, tmp_path, monkeypatch):
    client, factory, user_id, workflow_id, version_id = deletion_data
    task_id = _add_task(factory, user_id, workflow_id, version_id)
    root = tmp_path / "tasks"
    artifact = root / task_id / "artifacts" / "n" / "0-1"
    artifact.mkdir(parents=True)
    (artifact / "out").write_text("x")
    monkeypatch.setenv("KOSMO_TASK_STORAGE_ROOT", str(root))

    response = client.request("DELETE", f"/workflows/{workflow_id}", json={"delete_tasks": True})

    assert response.status_code == 204
    assert not (root / task_id).exists()
