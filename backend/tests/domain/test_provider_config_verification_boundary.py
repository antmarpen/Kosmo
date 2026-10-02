"""Verification status boundary test for the targeted provider flow (F4).

Proves the real repository conditional update against the migrated test
database: `set_verification_status` writes only when the row is unchanged
since the caller read it, so a stale result can never mark a replaced (or
deleted) configuration as verified — and it always targets exactly the
requested row id.

NOTE: host→localhost:5432 connections reset on this Windows host (documented
quirk), so run this file inside the backend container where postgres:5432 is
stable: `docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=
'postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' uv run pytest
tests/domain/test_provider_config_verification_boundary.py -q"`. Skipped on
the Windows host for that reason.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.identity.models import User, UserRole
from app.domain.provider_configs.models import ProviderConfig
from app.domain.provider_configs.repository import ProviderConfigRepository

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)

CONFIG_CIPHERTEXT = "encrypted-config-placeholder"


@pytest.fixture
def session_factory(migrated_test_database, monkeypatch):
    """Real session factory against the migrated test database.

    NullPool on purpose: each test drives async boundaries with its own
    asyncio.run loop, and pooled connections cannot survive loop changes.
    """
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.AsyncSessionLocal", factory)
    return factory


def test_verification_status_update_is_row_targeted_and_stale_guarded(session_factory):
    async def scenario():
        async with session_factory() as db:
            user_id = str(uuid.uuid4())
            other_user_id = str(uuid.uuid4())
            db.add(User(id=user_id, username=f"builder-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            db.add(User(id=other_user_id, username=f"builder-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            repo = ProviderConfigRepository(db)
            first = await repo.create(user_id, "opencode", CONFIG_CIPHERTEXT, None,
                                      display_name="Boundary Config")
            other = await repo.create(other_user_id, "opencode", CONFIG_CIPHERTEXT, None,
                                      display_name="Other Config")
            await db.commit()
            version_before = first.updated_at

        # The configuration is replaced after the caller read it (an update by
        # id bumps `updated_at` via onupdate).
        async with session_factory() as db:
            repo = ProviderConfigRepository(db)
            row = await repo.by_id(first.id)
            await repo.update(row, config_ciphertext="replaced-ciphertext", auth_ciphertext=None,
                              verification_status="unverified", display_name="Replaced Config",
                              visibility="personal", group_id=None)
            await db.commit()

        # A stale result (guarded by the pre-replacement version) writes nothing.
        async with session_factory() as db:
            repo = ProviderConfigRepository(db)
            landed = await repo.set_verification_status(
                first.id, "verified", expected_updated_at=version_before)
            await db.commit()
            row = await repo.by_id(first.id)
        assert landed is False
        assert row.verification_status == "unverified"
        assert row.config_ciphertext == "replaced-ciphertext"

        # The current version lands, and only on the requested row.
        async with session_factory() as db:
            repo = ProviderConfigRepository(db)
            current = (await repo.by_id(first.id)).updated_at
            landed = await repo.set_verification_status(
                first.id, "verified", expected_updated_at=current)
            await db.commit()
            row, untouched = await repo.by_id(first.id), await repo.by_id(other.id)
        assert landed is True
        assert row.verification_status == "verified"
        assert untouched.verification_status == "unverified"

        # Unknown ids report that nothing was written.
        async with session_factory() as db:
            repo = ProviderConfigRepository(db)
            assert await repo.set_verification_status(
                str(uuid.uuid4()), "failed") is False

        async with session_factory() as db:
            for config_id in (first.id, other.id):
                row = await ProviderConfigRepository(db).by_id(config_id)
                await db.delete(row)
            for uid in (user_id, other_user_id):
                await db.delete(await db.get(User, uid))
            await db.commit()

    asyncio.run(scenario())
