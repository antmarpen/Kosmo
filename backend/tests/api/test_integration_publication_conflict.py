"""Two-user publication conflict and recent-publication confirmation against
real PostgreSQL (R9), exercised through the real HTTP API.

Proves on the migrated test database:
  * a second user publishing while someone else published the same workflow
    less than five minutes ago must confirm explicitly (409
    `errors.workflow.publication_confirmation_required`) and succeeds once
    the confirmation is sent;
  * publishing never activates (AC-P2-06): the active version is unchanged
    until an explicit activation request lands;
  * every published version stays listed newest-first with honest
    `is_active` flags, so a previously published inactive version can be
    activated after a reload.

Run inside the backend container (host→localhost:5432 connections reset on
this Windows host, so the tests are skipped off-container):
    docker compose exec -T backend sh -c \
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \
       uv run pytest tests/api/test_integration_publication_conflict.py -q"

The app under test is wired to the migrated test database by overriding the
`get_db` dependency — never to the developer database. Workflow names are
globally case-insensitively unique, so every test uses a fresh uuid-suffixed
name and deletes its workflows and users afterwards.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.api.deps import get_current_user
from app.core.db import get_db
from app.main import create_app
from app.domain.identity.models import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_factory(migrated_test_database):
    """Session factory against the migrated test database.

    NullPool on purpose: requests run on the client's event loop, and pooled
    connections cannot survive loop changes.
    """
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture
def test_user_a(session_factory):
    """Admin user A, cleaned up after the test.

    Sync fixture on purpose: pytest-asyncio strict mode does not handle
    unmarked async fixtures, so the async boundaries run via asyncio.run
    (same convention as tests/domain/test_provider_operation_redemption_boundary.py).
    """
    user_id = str(uuid.uuid4())

    async def seed() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"pub-conflict-a-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.admin))
            await db.commit()

    async def cleanup() -> None:
        async with session_factory() as db:
            await db.execute(text("DELETE FROM users WHERE id = :id").bindparams(id=user_id))
            await db.commit()

    asyncio.run(seed())
    yield user_id
    asyncio.run(cleanup())


@pytest.fixture
def test_user_b(session_factory):
    """Builder user B, cleaned up after the test."""
    user_id = str(uuid.uuid4())

    async def seed() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"pub-conflict-b-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            await db.commit()

    async def cleanup() -> None:
        async with session_factory() as db:
            await db.execute(text("DELETE FROM users WHERE id = :id").bindparams(id=user_id))
            await db.commit()

    asyncio.run(seed())
    yield user_id
    asyncio.run(cleanup())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(session_factory, user_id: str, role: UserRole) -> TestClient:
    """TestClient wired to the migrated test database, authenticated as an
    in-database synthetic user through dependency overrides."""
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, username=f"user-{user_id}", password_hash="x", role=role)
    return TestClient(app, base_url="http://test")


def _unique_name(prefix: str) -> str:
    """Workflow names are globally unique; a uuid suffix keeps runs isolated."""
    return f"{prefix} {uuid.uuid4()}"


def _build_definition(name: str) -> dict:
    """A valid Start→Script→AI→End definition carrying the workflow name."""
    return {
        "schema_version": "v1",
        "name": name,
        "nodes": [
            {"type": "start", "id": "start",
             "input_form": [{"name": "topic", "type": "string", "required": True,
                             "label_message_key": "workflow.topic.label"}]},
            {"type": "script", "id": "script", "code": "pass",
             "inputs": ["topic"], "outputs": ["report"]},
            {"type": "ai", "id": "ai",
             "agent": {"runtime": "opencode", "model": "test-model", "instructions": "Review"},
             "prompt_template": "Topic: {{topic}}",
             "inputs": ["report"], "outputs": ["summary.md"],
             "validation": {"levels": [
                 {"name": "syntax", "message_key": "workflow.validation.syntax", "params_schema": {}},
                 {"name": "semantic", "message_key": "workflow.validation.semantic", "params_schema": {}},
                 {"name": "contract", "message_key": "workflow.validation.contract", "params_schema": {}},
             ]},
             "max_validation_cycles": 3},
            {"type": "end", "id": "end"},
        ],
        "edges": [{"from": "start", "to": "script"},
                  {"from": "script", "to": "ai"},
                  {"from": "ai", "to": "end"}],
    }


def _create_workflow(client: TestClient, name: str) -> dict:
    resp = client.post("/workflows", json={"name": name})
    assert resp.status_code == 201, f"create failed: {resp.text}"
    return resp.json()


def _create_draft(client: TestClient, workflow_id: str) -> dict:
    resp = client.post(f"/workflows/{workflow_id}/drafts")
    assert resp.status_code == 201, f"create draft failed: {resp.text}"
    return resp.json()


def _save_draft(client: TestClient, workflow_id: str, draft_id: str, revision: int, definition: dict) -> dict:
    resp = client.put(
        f"/workflows/{workflow_id}/drafts/{draft_id}",
        json={"definition": definition, "layout": {}, "expected_revision": revision},
    )
    assert resp.status_code == 200, f"save draft failed: {resp.text}"
    return resp.json()


def _publish_draft(client: TestClient, workflow_id: str, draft_id: str,
                   pub_revision: int, confirm_overwrite: bool = False) -> dict:
    resp = client.post(
        f"/workflows/{workflow_id}/drafts/{draft_id}/publish",
        json={"expected_pub_revision": pub_revision, "confirm_overwrite": confirm_overwrite},
    )
    assert resp.status_code == 201, f"publish failed: {resp.text}"
    return resp.json()


def _activate_version(client: TestClient, workflow_id: str, version_id: str,
                      expected_active_revision: int) -> dict:
    resp = client.post(
        f"/workflows/{workflow_id}/activate",
        json={"version_id": version_id, "expected_active_revision": expected_active_revision},
    )
    assert resp.status_code == 200, f"activate failed: {resp.text}"
    return resp.json()


async def _delete_workflows(session_factory, workflow_ids: list[str]) -> None:
    """Removes the test's workflows (versions/activations/drafts cascade)."""
    if not workflow_ids:
        return
    async with session_factory() as db:
        stmt = text("DELETE FROM workflows WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True))
        await db.execute(stmt, {"ids": workflow_ids})
        await db.commit()


# ---------------------------------------------------------------------------
# Real PostgreSQL-backed API tests
# ---------------------------------------------------------------------------

def test_two_user_publication_conflict_requires_confirmation(session_factory, test_user_a, test_user_b):
    """User B must explicitly confirm a publish that overwrites A's
    less-than-five-minute-old publication, then succeed once confirmed."""
    client_a = make_client(session_factory, test_user_a, UserRole.admin)
    client_b = make_client(session_factory, test_user_b, UserRole.builder)
    name = _unique_name("Conflict Flow")

    workflow = _create_workflow(client_a, name)
    workflow_id, draft_a = workflow["id"], workflow["draft_id"]
    try:
        _save_draft(client_a, workflow_id, draft_a, 1, _build_definition(name))
        published_a = _publish_draft(client_a, workflow_id, draft_a, 0)
        assert published_a["version"] == 1

        # B authors a separate draft of the same workflow and publishes while
        # A's publication is still fresh, without confirming.
        draft_b = _create_draft(client_b, workflow_id)
        _save_draft(client_b, workflow_id, draft_b["draft_id"], 1, _build_definition(name))
        conflict = client_b.post(
            f"/workflows/{workflow_id}/drafts/{draft_b['draft_id']}/publish",
            json={"expected_pub_revision": 1, "confirm_overwrite": False},
        )
        assert conflict.status_code == 409, f"expected 409, got: {conflict.text}"
        assert conflict.json()["message_key"] == "errors.workflow.publication_confirmation_required"

        # The explicit confirmation completes B's publication as version 2.
        published_b = _publish_draft(client_b, workflow_id, draft_b["draft_id"], 1,
                                     confirm_overwrite=True)
        assert published_b["version"] == 2

        # B's version did not silently become the active one (AC-P2-06).
        detail = client_b.get(f"/workflows/{workflow_id}").json()
        assert detail["active_version"] is None
    finally:
        asyncio.run(_delete_workflows(session_factory, [workflow_id]))


def test_publish_does_not_change_active_version(session_factory, test_user_a):
    """Publishing a second version must never auto-activate it (AC-P2-06)."""
    client = make_client(session_factory, test_user_a, UserRole.admin)
    name = _unique_name("NoActivate Flow")

    workflow = _create_workflow(client, name)
    workflow_id, draft_id = workflow["id"], workflow["draft_id"]
    try:
        _save_draft(client, workflow_id, draft_id, 1, _build_definition(name))
        v1 = _publish_draft(client, workflow_id, draft_id, 0)

        # Publishing alone left the workflow without an active version.
        detail = client.get(f"/workflows/{workflow_id}").json()
        assert detail["active_version"] is None

        # Explicit activation selects version 1.
        _activate_version(client, workflow_id, v1["id"], 0)
        detail = client.get(f"/workflows/{workflow_id}").json()
        assert detail["active_version"]["id"] == v1["id"]
        assert detail["active_version"]["version"] == 1

        # A second publication changes nothing about the active version.
        draft2 = _create_draft(client, workflow_id)
        _save_draft(client, workflow_id, draft2["draft_id"], 1, _build_definition(name))
        v2 = _publish_draft(client, workflow_id, draft2["draft_id"], 1)
        assert v2["version"] == 2
        detail = client.get(f"/workflows/{workflow_id}").json()
        assert detail["active_version"]["id"] == v1["id"]
        assert detail["active_version"]["version"] == 1
    finally:
        asyncio.run(_delete_workflows(session_factory, [workflow_id]))


def test_published_versions_stay_listed_and_activatable_after_reload(session_factory, test_user_a):
    """The version listing is newest-first with honest is_active flags, and a
    previously published inactive version can be activated afterwards (the
    editor reload contract behind the activation picker)."""
    client = make_client(session_factory, test_user_a, UserRole.admin)
    name = _unique_name("Reload Flow")

    workflow = _create_workflow(client, name)
    workflow_id, draft_id = workflow["id"], workflow["draft_id"]
    try:
        _save_draft(client, workflow_id, draft_id, 1, _build_definition(name))
        v1 = _publish_draft(client, workflow_id, draft_id, 0)
        _activate_version(client, workflow_id, v1["id"], 0)

        draft2 = _create_draft(client, workflow_id)
        _save_draft(client, workflow_id, draft2["draft_id"], 1, _build_definition(name))
        v2 = _publish_draft(client, workflow_id, draft2["draft_id"], 1)

        versions = client.get(f"/workflows/{workflow_id}/versions").json()
        assert [version["version"] for version in versions] == [2, 1]
        assert [version["is_active"] for version in versions] == [False, True]
        assert {versions[0]["id"], versions[1]["id"]} == {v1["id"], v2["id"]}

        # Activate the previously published inactive version; the expected
        # active revision is v1's version number (1).
        _activate_version(client, workflow_id, v2["id"], 1)
        detail = client.get(f"/workflows/{workflow_id}").json()
        assert detail["active_version"]["id"] == v2["id"]
        assert detail["active_version"]["version"] == 2
    finally:
        asyncio.run(_delete_workflows(session_factory, [workflow_id]))
