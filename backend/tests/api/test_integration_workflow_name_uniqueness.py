"""Database-level case-insensitive workflow-name uniqueness against real
PostgreSQL, exercised through the real HTTP API.

Proves on the migrated test database that the functional unique index on
lower(name) (migration 0020) closes the race the API-level precheck cannot:
concurrent creations of case-variant names ("Billing X" / "billing X") and
concurrent publications renaming two workflows onto the same case-variant
name yield exactly one winner each, while every loser fails with the
localized `errors.workflow.name_conflict` conflict and publishes nothing.

Run inside the backend container (host→localhost:5432 connections reset on
this Windows host, so the tests are skipped off-container):
    docker compose exec -T backend sh -c \
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \
       uv run pytest tests/api/test_integration_workflow_name_uniqueness.py -q"

The app under test is wired to the migrated test database by overriding the
`get_db` dependency — never to the developer database. Every test uses a
fresh uuid-suffixed name base and deletes its workflows and users afterwards.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Callable

import pytest
from fastapi import Response
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

    NullPool on purpose: concurrent test threads run separate event loops, and
    pooled connections cannot survive loop changes.
    """
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture
def test_user(session_factory):
    """Admin user, cleaned up after the test.

    Sync fixture on purpose: pytest-asyncio strict mode does not handle
    unmarked async fixtures, so the async boundaries run via asyncio.run
    (same convention as tests/api/test_integration_publication_conflict.py).
    """
    user_id = str(uuid.uuid4())

    async def seed() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"name-race-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.admin))
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

def make_client(session_factory, user_id: str) -> TestClient:
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
        id=user_id, username=f"user-{user_id}", password_hash="x", role=UserRole.admin)
    return TestClient(app, base_url="http://test")


def fire_concurrently(attempts: list[Callable[[], Response]]) -> list[Response | None]:
    """Runs the attempt callables at the same instant (barrier start) and
    returns their responses in order; a crashed attempt leaves None behind
    so the assertion failure points at the crash instead of a bogus winner."""
    barrier = threading.Barrier(len(attempts))
    responses: list[Response | None] = [None] * len(attempts)

    def run(index: int) -> None:
        barrier.wait(timeout=30)
        responses[index] = attempts[index]()

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        futures = [pool.submit(run, index) for index in range(len(attempts))]
        for future in futures:
            future.result(timeout=60)
    return responses


def _unique_base() -> str:
    """Workflow names are globally case-insensitively unique; a uuid base
    keeps runs isolated from each other and from the developer database."""
    return f"Race {uuid.uuid4()}"


def _build_definition(name: str) -> dict:
    """A valid Start→Script→End definition carrying the workflow name."""
    return {
        "schema_version": "v1",
        "name": name,
        "nodes": [
            {"type": "start", "id": "start",
             "input_form": [{"name": "topic", "type": "string", "required": True,
                             "label_message_key": "workflow.topic.label"}]},
            {"type": "script", "id": "script", "code": "pass",
             "inputs": ["topic"], "outputs": ["report"]},
            {"type": "end", "id": "end"},
        ],
        "edges": [{"from": "start", "to": "script"},
                  {"from": "script", "to": "end"}],
    }


def _save_draft(client: TestClient, workflow_id: str, draft_id: str, revision: int, definition: dict) -> None:
    resp = client.put(
        f"/workflows/{workflow_id}/drafts/{draft_id}",
        json={"definition": definition, "layout": {}, "expected_revision": revision},
    )
    assert resp.status_code == 200, f"save draft failed: {resp.text}"


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
# Real PostgreSQL-backed race tests
# ---------------------------------------------------------------------------

def test_concurrent_case_variant_creations_yield_exactly_one_workflow(session_factory, test_user):
    """The database index decides the race the precheck cannot see: exactly
    one case-variant creation wins, the rest get the localized conflict, and
    no draft is left behind for a loser."""
    base = _unique_base()
    variants = [base, base.lower(), base.upper(), base.swapcase()]
    clients = [make_client(session_factory, test_user) for _ in variants]

    responses = fire_concurrently([
        (lambda client=client, variant=variant: client.post("/workflows", json={"name": variant}))
        for client, variant in zip(clients, variants)
    ])
    assert all(response is not None for response in responses), "an attempt crashed"

    created = [response for response in responses if response.status_code == 201]
    conflicts = [response for response in responses if response.status_code == 409]
    assert len(created) == 1, [response.text for response in responses]
    assert len(conflicts) == len(variants) - 1
    for response in conflicts:
        body = response.json()
        assert body["message_key"] == "errors.workflow.name_conflict"
        assert body["code"] == "CONFLICT"

    winner = created[0].json()
    try:
        # Exactly one row carries the case-variant name, and the loser left
        # no draft behind (the rolled-back transaction created nothing).
        detail = clients[0].get(f"/workflows/{winner['id']}").json()
        assert detail["name"].lower() == base.lower()
        drafts = clients[0].get(f"/workflows/{winner['id']}/drafts").json()
        assert len(drafts) == 1
    finally:
        asyncio.run(_delete_workflows(session_factory, [winner["id"]]))


def test_concurrent_case_variant_renames_publish_exactly_one_version(session_factory, test_user):
    """Two workflows publishing renames onto the same case-insensitive name:
    exactly one publication wins, the loser's rename is refused with the
    localized conflict, and the loser publishes no version at all."""
    base = _unique_base()
    target_variants = (f"{base} Target", f"{base} target")
    client = make_client(session_factory, test_user)

    racers = []
    for index, (source, target) in enumerate(zip(("Alpha", "Beta"), target_variants)):
        created = client.post("/workflows", json={"name": f"{base} {source}"}).json()
        _save_draft(client, created["id"], created["draft_id"], 1, _build_definition(target))
        racers.append({"workflow_id": created["id"], "draft_id": created["draft_id"], "target": target})

    publish_clients = [make_client(session_factory, test_user) for _ in racers]
    responses = fire_concurrently([
        (lambda publish_client=publish_client, racer=racer: publish_client.post(
            f"/workflows/{racer['workflow_id']}/drafts/{racer['draft_id']}/publish",
            json={"expected_pub_revision": 0, "confirm_overwrite": False}))
        for publish_client, racer in zip(publish_clients, racers)
    ])
    assert all(response is not None for response in responses), "an attempt crashed"

    published = [response for response in responses if response.status_code == 201]
    conflicts = [response for response in responses if response.status_code == 409]
    assert len(published) == 1, [response.text for response in responses]
    assert len(conflicts) == len(racers) - 1
    for response in conflicts:
        body = response.json()
        assert body["message_key"] == "errors.workflow.name_conflict"
        assert body["code"] == "CONFLICT"

    winner_index = responses.index(published[0])
    loser_index = 1 - winner_index
    try:
        # The winner's workflow carries the (case-variant) target name...
        winner = client.get(f"/workflows/{racers[winner_index]['workflow_id']}").json()
        assert winner["name"] == racers[winner_index]["target"]
        # ...and the loser published nothing: no version exists for it.
        versions = client.get(f"/workflows/{racers[loser_index]['workflow_id']}/versions").json()
        assert versions == []
    finally:
        asyncio.run(_delete_workflows(session_factory, [racer["workflow_id"] for racer in racers]))
