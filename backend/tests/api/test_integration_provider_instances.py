"""Multiple named provider configuration instances against real PostgreSQL.

Proves the R6 contract on the migrated test database: two same-scope
instances coexist with distinct ids, the case-insensitive per-owner name
uniqueness is enforced at the database level (functional unique index), and
updates target one row by id without touching its siblings.

Run inside the backend container:
    docker compose exec -T backend sh -c \\
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \\
       uv run pytest tests/api/test_integration_provider_instances.py -q"

Skipped on the Windows host because host-to-container DB connections are
unstable (documented quirk).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from shared.errors import ConflictError

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.domain.identity.models import User, UserRole
from app.domain.provider_configs.models import ProviderConfig
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService

ENCRYPTION_KEY = "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc="
FILES = (b'{"providers":{"x":{"options":{"apiKey":"instance-test-key"}}}}',
         b'[{"id":"cred_x","integrationID":"x","label":"API key","active":true,"value":{"type":"key","key":"instance-test-secret"}}]')


@pytest.fixture(scope="module")
def session_factory(migrated_test_database):
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture
def test_user(session_factory):
    """Sync fixture (see the targeting module note): the tests are sync."""
    user_id = str(uuid.uuid4())

    async def create() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"instances-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            await db.commit()

    asyncio.run(create())
    yield user_id

    async def cleanup() -> None:
        async with session_factory() as db:
            await db.execute(text("DELETE FROM users WHERE id = :id").bindparams(id=user_id))
            await db.commit()

    asyncio.run(cleanup())


@asynccontextmanager
async def service_session(session_factory):
    """One context-managed service interaction.

    The service session must be entered and closed explicitly: the
    repository's post-commit refresh() re-opens a transaction, so an
    unmanaged `session_factory()` call strands its NullPool connection until
    GC (SAWarning at collection, "Event loop is closed" at shutdown) — the
    same defect the acceptance tests fixed in
    test_integration_provider_verification_targeting.py.
    """
    async with session_factory() as db:
        yield ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)


def test_two_same_scope_instances_coexist_with_distinct_ids(session_factory, test_user):
    async def scenario():
        async with service_session(session_factory) as service:
            first = await service.create(test_user, "opencode", *FILES, display_name="Alpha")
            second = await service.create(test_user, "opencode", *FILES, display_name="Beta")

            assert first["format"] == second["format"] == "v2"
            assert first["id"] != second["id"]
            rows = (await service.list_visible(test_user, "opencode"))
            assert {row["id"] for row in rows} == {first["id"], second["id"]}
            assert {row["name"] for row in rows} == {"Alpha", "Beta"}
            # Metadata only: no response carries ciphertext or file contents.
            assert all("config_ciphertext" not in row and "auth_ciphertext" not in row
                       for row in rows)

    asyncio.run(scenario())


def test_duplicate_name_is_rejected_by_the_database_index(session_factory, test_user):
    async def scenario():
        async with service_session(session_factory) as service:
            await service.create(test_user, "opencode", *FILES, display_name="Team Config")

            # The application pre-check rejects the keyed conflict first.
            with pytest.raises(ConflictError) as excinfo:
                await service.create(test_user, "opencode", *FILES, display_name="team config")
            assert excinfo.value.message_key == "errors.provider.name_duplicate"

        # The functional unique index is the backstop: a raw insert bypassing
        # the service cannot store a case-insensitive duplicate either.
        async with session_factory() as db:
            db.add(ProviderConfig(user_id=test_user, provider="opencode",
                                  config_ciphertext="raw-cipher", display_name="TEAM CONFIG"))
            with pytest.raises(Exception) as raw:
                await db.commit()
        assert "uq_provider_config_owner_provider_name_ci" in str(raw.value)

    asyncio.run(scenario())


def test_update_by_id_preserves_files_and_keeps_siblings_untouched(session_factory, test_user):
    async def scenario():
        async with service_session(session_factory) as service:
            first = await service.create(test_user, "opencode", *FILES, display_name="Alpha")
            second = await service.create(test_user, "opencode", *FILES, display_name="Beta")
            original = await service.read_files_by_id(first["id"])

            renamed = await service.scoped_save(
                type("Actor", (), {"id": test_user, "role": "builder"})(),
                "opencode", None, None, "personal", None,
                display_name="Alpha Renamed", config_id=first["id"])

            assert renamed["id"] == first["id"]
            assert renamed["name"] == "Alpha Renamed"
            # The untouched files decrypt to the originals; the sibling row is
            # exactly as it was.
            assert await service.read_files_by_id(first["id"]) == original
            untouched = await service.repository.by_id(second["id"])
            assert untouched.display_name == "Beta"
            assert untouched.verification_status == "unverified"

    asyncio.run(scenario())
