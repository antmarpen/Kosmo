"""Real-PostgreSQL/API checks for catalog visibility boundaries.

Run in the backend container after migrations with KOSMO_TEST_DATABASE_URL set.
Authentication is injected as an in-database test identity; catalog services,
repositories, HTTP routing and PostgreSQL remain real.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.identity.models import User, UserRole
from app.main import create_app


@pytest.fixture(scope="module")
def sessions(migrated_test_database):
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _user(sessions, role=UserRole.runner):
    user_id = str(uuid.uuid4())
    async def seed():
        async with sessions() as db:
            db.add(User(id=user_id, username=f"catalog-{uuid.uuid4()}", password_hash="x", role=role))
            await db.commit()
    asyncio.run(seed())
    return user_id


def _client(sessions, user_id):
    app = create_app()
    async def db_override():
        async with sessions() as db:
            yield db
            await db.commit()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, username=user_id, password_hash="x", role=UserRole.runner)
    return TestClient(app, base_url="http://test")


@pytest.mark.parametrize(("route", "payload"), [
    ("agents", {"name": "agent", "model": "provider/model", "instructions": "instructions"}),
    ("mcp-servers", {"name": "mcp", "transport": {"type": "stdio", "command": "tool", "args": [], "env": []}}),
    ("skills", {"name": "skill", "description": "desc", "instructions": "instructions"}),
])
def test_personal_catalog_is_owner_visible_and_hidden_from_other_user(sessions, route, payload):
    owner, other = _user(sessions), _user(sessions)
    owner_client, other_client = _client(sessions, owner), _client(sessions, other)
    entity_id = None
    try:
        created = owner_client.post(f"/{route}", json=payload)
        assert created.status_code == 201, created.text
        entity_id = created.json()["id"]
        assert any(row["id"] == entity_id for row in owner_client.get(f"/{route}").json())
        assert all(row["id"] != entity_id for row in other_client.get(f"/{route}").json())
        hidden = other_client.get(f"/{route}/{entity_id}")
        # Provider-policy parity: an existing but invisible id is forbidden (403);
        # only an unknown id is 404. Runtime resolution (D9) is what must not
        # disclose existence/nonexistence.
        assert hidden.status_code == 403
        assert other_client.patch(f"/{route}/{entity_id}", json={"name": "mutated"}).status_code == 403
        assert other_client.delete(f"/{route}/{entity_id}").status_code == 403
        assert owner_client.get(f"/{route}/{entity_id}").status_code == 200
    finally:
        owner_client.close()
        other_client.close()
        async def cleanup():
            async with sessions() as db:
                if entity_id:
                    table = {"agents": "agents", "mcp-servers": "mcp_servers", "skills": "skills"}[route]
                    await db.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": entity_id})
                await db.execute(text("DELETE FROM users WHERE id IN (:owner, :other)"), {"owner": owner, "other": other})
                await db.commit()
        asyncio.run(cleanup())
