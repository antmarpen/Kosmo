"""Provider update name-conflict race against real PostgreSQL (RR-F5).

Proves the update-path contract on the migrated test database: two concurrent
updates selecting the same case-insensitive display name end with exactly one
success and one localized 409 (`errors.provider.name_duplicate`) — never an
unlocalized 500 — the losing row is left unchanged, and the losing connection
stays usable. The application pre-check cannot decide this race (both saves
pass it before either commits), so the functional unique index is the
authoritative gate, mirroring the create path.

Failed-save lifecycle (documented here and in the service): the single-use
proof redemption commits separately from the save, so a save that fails at
commit leaves the configuration row exactly unchanged (never marked verified)
while the spent proof stays spent — redemption is single-use and cannot be
replayed.

Run inside the backend container:
    docker compose exec -T backend sh -c \\
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \\
       uv run pytest tests/api/test_integration_provider_update_conflict.py -q"

Skipped on the Windows host because host-to-container DB connections are
unstable (documented quirk).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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

from app.api.deps import get_current_user
from app.api.routes.provider_configs import get_provider_config_service
from app.core.db import get_db
from app.domain.identity.models import User, UserRole
from app.domain.provider_configs.models import ProviderConfig
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService
from app.main import create_app

ENCRYPTION_KEY = "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc="
CONFIG_JSON = b'{"providers":{"x":{"options":{"apiKey":"update-conflict-key"}}}}'
AUTH_JSON = b'[{"id":"cred_x","integrationID":"x","label":"API key","active":true,"value":{"type":"api","key":"update-conflict-secret"}}]'
CONFIG = {"providers": {"x": {"options": {"apiKey": "update-conflict-key"}}}}
AUTH = [{"id":"cred_x","integrationID":"x","label":"API key","active":True,
         "value":{"type":"api","key":"update-conflict-secret"}}]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_factory(migrated_test_database):
    """Session factory against the migrated test database.

    NullPool on purpose: async boundaries run via asyncio.run per test, and
    pooled connections cannot survive loop changes. Every session below is
    scoped with `async with` so no connection stays checked out when a loop
    closes (NullPool closes the raw connection when the session ends).
    """
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture
def test_user(session_factory):
    """Sync fixture (asyncio.run convention): seeds one builder user."""
    user_id = str(uuid.uuid4())

    async def create() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"upd-conflict-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            await db.commit()

    asyncio.run(create())
    yield user_id

    async def cleanup() -> None:
        async with session_factory() as db:
            await db.execute(text("DELETE FROM users WHERE id = :id").bindparams(id=user_id))
            await db.commit()

    asyncio.run(cleanup())


def _service(db) -> ProviderConfigService:
    return ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)


class _RendezvousRepository(ProviderConfigRepository):
    """Real repository whose update() waits for its sibling before committing.

    Pure test orchestration: both concurrent saves must have passed their
    application pre-checks before either commit runs, so the unique index —
    not the pre-check — decides the race. With a plain gather, whichever
    request pre-checks after the other committed would be rejected early and
    the commit-time path under test would never run.
    """

    def __init__(self, db: AsyncSession, barrier: asyncio.Barrier):
        super().__init__(db)
        self._barrier = barrier

    async def update(self, row, **fields):
        await self._barrier.wait()
        return await super().update(row, **fields)


def _test_app(session_factory, user_id: str, barrier: asyncio.Barrier | None):
    """The real app wired to the migrated test database through overrides."""
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_service(db: AsyncSession = Depends(get_db)) -> ProviderConfigService:
        repository = (_RendezvousRepository(db, barrier) if barrier is not None
                      else ProviderConfigRepository(db))
        return ProviderConfigService(repository, ENCRYPTION_KEY)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider_config_service] = override_service
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, username=f"user-{user_id}", password_hash="x", role=UserRole.builder)
    return app


# ---------------------------------------------------------------------------
# Commit-time name race
# ---------------------------------------------------------------------------

def test_concurrent_case_variant_updates_yield_one_success_and_one_keyed_409(
        session_factory, test_user):
    """Two concurrent case-variant PATCHes selecting the same case-insensitive
    name race at the database index: exactly one succeeds, the loser gets the
    localized 409 (never a 500), its row is unchanged, and the API keeps
    working afterwards."""
    async def scenario():
        async with session_factory() as seed_db:
            seed = _service(seed_db)
            first = await seed.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                      display_name="Other One")
            second = await seed.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                       display_name="Other Two")
        async with session_factory() as db:
            snapshot = {row.id: (row.display_name, row.verification_status, row.updated_at)
                        for row in await db.scalars(select(ProviderConfig).where(
                            ProviderConfig.user_id == test_user))}

        app = _test_app(session_factory, test_user, barrier=asyncio.Barrier(2))
        transport = ASGITransport(app=app, raise_app_exceptions=False)

        async def patch(config_id: str, name: str):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.patch("/providers/opencode/config",
                                          data={"config_id": config_id, "name": name})

        responses = await asyncio.gather(patch(first["id"], "Shared Name"),
                                         patch(second["id"], "SHARED NAME"))
        outcomes = [("Shared Name", first["id"], responses[0]),
                    ("SHARED NAME", second["id"], responses[1])]

        statuses = sorted(response.status_code for response in responses)
        assert statuses == [200, 409], [response.text for response in responses]
        winner_name, winner_id = next((name, config_id) for name, config_id, response
                                      in outcomes if response.status_code == 200)
        loser_name, loser_id = next((name, config_id) for name, config_id, response
                                    in outcomes if response.status_code == 409)
        loser = next(response for response in responses if response.status_code == 409)
        assert loser.json()["message_key"] == "errors.provider.name_duplicate"
        assert loser.json()["params"] == {"name": loser_name}

        async with session_factory() as db:
            rows = list(await db.scalars(select(ProviderConfig).where(
                ProviderConfig.user_id == test_user)))
        by_id = {row.id: row for row in rows}
        # The race never duplicated the row: exactly two rows remain.
        assert len(rows) == 2
        # The losing row is unchanged: its pre-race name, status, and version
        # marker survived; the losing variant never landed.
        assert (by_id[loser_id].display_name, by_id[loser_id].verification_status,
                by_id[loser_id].updated_at) == snapshot[loser_id]
        assert by_id[loser_id].display_name.lower() != "shared name"
        # The winner's variant is the only one persisted.
        assert by_id[winner_id].display_name == winner_name
        assert sum(1 for row in rows
                   if row.display_name.lower() == "shared name") == 1

        # The API is healthy after the race: a follow-up request succeeds.
        plain_app = _test_app(session_factory, test_user, barrier=None)
        async with AsyncClient(transport=ASGITransport(app=plain_app, raise_app_exceptions=False),
                               base_url="http://test") as client:
            followup = await client.patch("/providers/opencode/config",
                                          data={"config_id": loser_id,
                                                "name": "Renamed After Race"})
        assert followup.status_code == 200
        assert followup.json()["name"] == "Renamed After Race"

    asyncio.run(scenario())


def test_lost_name_index_commit_is_rolled_back_and_the_session_stays_usable(
        session_factory, test_user):
    """The repository rolls the lost update back and re-raises: the very same
    session remains usable afterwards (no PendingRollbackError) and sees the
    persisted, unchanged row."""
    async def scenario():
        async with session_factory() as seed_db:
            seed = _service(seed_db)
            first = await seed.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                      display_name="Alpha")
            second = await seed.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                       display_name="Beta")

        # The winner commits its rename first.
        async with session_factory() as winner_db:
            winner_row = await winner_db.get(ProviderConfig, first["id"])
            await ProviderConfigRepository(winner_db).update(
                winner_row, config_ciphertext=winner_row.config_ciphertext,
                auth_ciphertext=winner_row.auth_ciphertext,
                verification_status=winner_row.verification_status,
                display_name="Shared Name", visibility=winner_row.visibility,
                group_id=winner_row.group_id)

        # The loser's conflicting rename then loses at the functional index.
        async with session_factory() as loser_db:
            loser_row = await loser_db.get(ProviderConfig, second["id"])
            with pytest.raises(IntegrityError):
                await ProviderConfigRepository(loser_db).update(
                    loser_row, config_ciphertext=loser_row.config_ciphertext,
                    auth_ciphertext=loser_row.auth_ciphertext,
                    verification_status=loser_row.verification_status,
                    display_name="SHARED NAME", visibility=loser_row.visibility,
                    group_id=loser_row.group_id)
            # The same session still works: the failed commit was rolled back,
            # and the persisted row is unchanged.
            reloaded = await loser_db.get(ProviderConfig, second["id"])
            assert reloaded.display_name == "Beta"
            assert reloaded.verification_status == "unverified"

        # A fresh session sees the persisted state: the loser never landed and
        # the winner's variant is the only 'shared name'.
        async with session_factory() as db:
            names = [row.display_name for row in await db.scalars(select(ProviderConfig).where(
                ProviderConfig.user_id == test_user))]
        assert sorted(names) == ["Beta", "Shared Name"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Failed-save lifecycle after proof redemption
# ---------------------------------------------------------------------------

def test_failed_save_after_proof_redemption_leaves_the_row_unchanged_and_unverified(
        session_factory, test_user):
    """Failed-save lifecycle: the single-use proof redemption commits
    separately from the save, so when the save itself loses the name race the
    configuration row is rolled back unchanged and the redeemed proof never
    marks it verified; the spent proof stays spent (single-use)."""
    async def scenario():
        actor = SimpleNamespace(id=test_user, role="builder")
        async with session_factory() as service_db, session_factory() as racer_db:
            service = _service(service_db)
            original = await service.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                            display_name="Original")
            holder = await service.create(test_user, "opencode", CONFIG_JSON, AUTH_JSON,
                                          display_name="Holder")

            operation_id = await service.create_candidate_operation(
                test_user, "opencode", CONFIG, AUTH, purpose="verification")
            assert await service.mark_candidate_operation_verified(operation_id) is not None

            # Deterministic interleaving: the save passes its pre-check,
            # redeems the proof, and only then the racer renames the sibling to
            # the same case-insensitive name, so the save's own commit loses at
            # the index.
            racer = _service(racer_db)
            original_redeem = service.redeem_candidate_verification

            async def redeem_then_racer(operation, owner, provider, config, auth):
                redeemed = await original_redeem(operation, owner, provider, config, auth)
                assert redeemed is True
                await racer.scoped_save(actor, "opencode", None, None, "personal", None,
                                        display_name="Shared Name", config_id=holder["id"])
                return redeemed

            service.redeem_candidate_verification = redeem_then_racer

            with pytest.raises(ConflictError) as excinfo:
                await service.scoped_save(actor, "opencode", CONFIG_JSON, AUTH_JSON,
                                          "personal", None, verification_id=operation_id,
                                          display_name="Shared Name", config_id=original["id"])
            assert excinfo.value.message_key == "errors.provider.name_duplicate"
            assert excinfo.value.params == {"name": "Shared Name"}

        async with session_factory() as fresh_db:
            fresh = _service(fresh_db)
            # The redemption committed separately: the proof is spent even
            # though the save failed, and can never be redeemed twice.
            assert await fresh.repository.get_candidate_operation(operation_id) is None
            # The failed save left the row exactly as it was — the redeemed
            # proof did not mark the stored configuration verified.
            row = await fresh.repository.by_id(original["id"])
            assert row.display_name == "Original"
            assert row.verification_status == "unverified"
            assert await fresh.read_files_by_id(original["id"]) == {
                "format":"v2", "opencode.json": CONFIG_JSON, "auth.json": AUTH_JSON}
            # The racer's legitimate rename landed; the loser never duplicated it.
            holder_row = await fresh.repository.by_id(holder["id"])
            assert holder_row.display_name == "Shared Name"

    asyncio.run(scenario())
