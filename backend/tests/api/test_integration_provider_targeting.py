"""Backend integration tests for concurrent single-use proof redemption against
a real PostgreSQL instance.

Run inside the backend container:
    docker compose exec -T backend sh -c \
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \
       uv run pytest tests/api/test_integration_provider_targeting.py -q"

Skipped on the Windows host because host-to-container DB connections are unstable.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.domain.identity.models import Group, GroupMembership, User, UserRole
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService
from app.domain.provider_configs.models import ProviderCandidateOperation

ENCRYPTION_KEY = "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc="
TEST_CONFIG = {"provider": {"x": {"options": {"apiKey": "sentinel-concurrent-key"}}}}
TEST_AUTH = {"x": {"key": "sentinel-concurrent-secret"}}


@pytest.fixture(scope="module")
def session_factory(migrated_test_database):
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


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


@pytest.fixture
def test_user(session_factory):
    """Create a test user and clean up after the test.

    Sync fixture on purpose: the tests are sync (they drive async boundaries
    with `asyncio.run`), and pytest-asyncio does not serve async fixtures to
    sync tests. Each phase opens its own loop; NullPool keeps that safe.
    """
    user_id = str(uuid.uuid4())

    async def create() -> None:
        async with session_factory() as db:
            db.add(User(id=user_id, username=f"concurrent-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            await db.commit()

    asyncio.run(create())
    yield user_id

    async def cleanup() -> None:
        async with session_factory() as db:
            stmt = text("DELETE FROM users WHERE id = :id").bindparams(id=user_id)
            await db.execute(stmt)
            await db.commit()

    asyncio.run(cleanup())


def test_concurrent_single_use_proof_redemption(session_factory, test_user, migrated_test_database):
    """Two concurrent redemption attempts of the same verification proof must
    resolve to [True, False] — exactly one lands.  This is the key concurrency
    guarantee of the `DELETE ... RETURNING WHERE` clause in the real database.

    NOTE: Because the asyncpg test client shares state within a single
    asyncio.run loop, true concurrent coroutines are simulated by launching
    two coroutines via asyncio.gather within the same event loop.  The
    underlying database still sees them as separate transactions (different
    AsyncSession instances) and the conditional delete gate fires correctly.
    """

    async def scenario():
        async with service_session(session_factory) as svc1:
            operation_id = await svc1.create_candidate_operation(
                test_user, "opencode", TEST_CONFIG, TEST_AUTH, purpose="verification")
            remaining = await svc1.mark_candidate_operation_verified(operation_id)
            assert 0 < remaining <= 120  # proof is live

        # Two concurrent redemptions: exactly one wins.  Each attempt runs on
        # its own session (separate transactions), so the context managers
        # stay nested for the duration of the gather.
        async def try_redeem(svc):
            return await svc.redeem_candidate_verification(
                operation_id, test_user, "opencode", TEST_CONFIG, TEST_AUTH)

        async with service_session(session_factory) as svc1:
            async with service_session(session_factory) as svc2:
                outcomes = await asyncio.gather(try_redeem(svc1), try_redeem(svc2))
        assert sorted(outcomes) == [False, True], f"Expected exactly one True, got {outcomes}"

        # The proof is single-use: third attempt finds nothing.
        async with service_session(session_factory) as svc3:
            assert await svc3.redeem_candidate_verification(
                operation_id, test_user, "opencode", TEST_CONFIG, TEST_AUTH) is False

        # Verify the operation row is gone from the database.
        async with session_factory() as db:
            row = await db.get(ProviderCandidateOperation, operation_id)
            assert row is None

    asyncio.run(scenario())


def test_discovery_purpose_never_redeemable(session_factory, test_user, migrated_test_database):
    """Discovery-purpose operations can never be redeemed — even if
    verification_succeeded were set by mistake.  This is enforced by the
    WHERE clause in the conditional delete."""

    async def scenario():
        async with service_session(session_factory) as svc:
            discovery = await svc.create_candidate_operation(
                test_user, "opencode", TEST_CONFIG, TEST_AUTH, purpose="discovery")
            assert await svc.mark_candidate_operation_verified(discovery) is None  # purpose guard

            result = await svc.redeem_candidate_verification(
                discovery, test_user, "opencode", TEST_CONFIG, TEST_AUTH)
            assert result is False

        # Row must still exist (not consumed).
        async with session_factory() as db:
            row = await db.get(ProviderCandidateOperation, discovery)
            assert row is not None

    asyncio.run(scenario())


def test_wrong_owner_cannot_redeem_foreign_proof(session_factory, migrated_test_database):
    """Another user's verification proof must be rejected — and the row must
    remain untouched (foreign rows are never modified by the claim gate)."""

    async def scenario():
        # Create two users.
        from sqlalchemy import text

        user_id_a = str(uuid.uuid4())
        user_id_b = str(uuid.uuid4())
        async with session_factory() as db:
            db.add(User(id=user_id_a, username=f"owner-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            db.add(User(id=user_id_b, username=f"other-{uuid.uuid4()}",
                        password_hash="x", role=UserRole.builder))
            await db.commit()

        try:
            async with service_session(session_factory) as svc_a:
                operation_id = await svc_a.create_candidate_operation(
                    user_id_a, "opencode", TEST_CONFIG, TEST_AUTH, purpose="verification")
                await svc_a.mark_candidate_operation_verified(operation_id)

            async with service_session(session_factory) as svc_b:
                # User B tries to redeem user A's proof.
                result = await svc_b.redeem_candidate_verification(
                    operation_id, user_id_b, "opencode", TEST_CONFIG, TEST_AUTH)
                assert result is False

            # The row must still exist (not consumed by foreign claim).
            async with session_factory() as db:
                row = await db.get(ProviderCandidateOperation, operation_id)
                assert row is not None

            # Also test wrong provider.
            async with service_session(session_factory) as svc_a2:
                result2 = await svc_a2.redeem_candidate_verification(
                    operation_id, user_id_a, "other-provider", TEST_CONFIG, TEST_AUTH)
                assert result2 is False
        finally:
            async with session_factory() as db:
                await db.execute(text("DELETE FROM users WHERE id IN (:a, :b)").bindparams(a=user_id_a, b=user_id_b))
                await db.commit()

    asyncio.run(scenario())


def test_mismatched_credentials_consume_the_operation(session_factory, test_user, migrated_test_database):
    """A mismatched config/auth pair consumes the operation row (untrusted
    reuse) but returns False — the proof was used but not honored."""

    async def scenario():
        async with service_session(session_factory) as svc:
            operation_id = await svc.create_candidate_operation(
                test_user, "opencode", TEST_CONFIG, TEST_AUTH, purpose="verification")
            await svc.mark_candidate_operation_verified(operation_id)

            # Different credentials: should return False.
            result = await svc.redeem_candidate_verification(
                operation_id, test_user, "opencode",
                {"provider": {"x": {"options": {"apiKey": "different-key"}}}},
                TEST_AUTH)
            assert result is False

        # The operation must have been consumed (deleted by the conditional claim).
        async with session_factory() as db:
            row = await db.get(ProviderCandidateOperation, operation_id)
            assert row is None

    asyncio.run(scenario())