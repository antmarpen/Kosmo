"""Atomic single-use redemption boundary test for candidate operations (F5).

Proves the real repository conditional claim against the migrated test
database: `redeem_candidate_operation` is a single `DELETE ... RETURNING`
gated on owner, provider, purpose, recorded verification success, and a live
TTL, so two concurrent redemptions can never both land, and discovery-purpose
or failed-verification operations can never be redeemed at all.

NOTE: host→localhost:5432 connections reset on this Windows host (documented
quirk), so run this file inside the backend container where postgres:5432 is
stable: `docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=
'postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' uv run pytest
tests/domain/test_provider_operation_redemption_boundary.py -q"`. Skipped on
the Windows host for that reason.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.identity.models import User, UserRole
from app.domain.provider_configs.models import ProviderCandidateOperation
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)

CONFIG = {"providers": {"x": {"options": {"apiKey": "sentinel-boundary-key"}}}}
AUTH = [{"id":"cred_x","integrationID":"x","label":"API key","active":True,
        "value":{"type":"api","key":"sentinel-boundary-secret"}}]
ENCRYPTION_KEY = "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc="


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


async def _seed_user(session_factory) -> str:
    user_id = str(uuid.uuid4())
    async with session_factory() as db:
        db.add(User(id=user_id, username=f"redeem-{uuid.uuid4()}",
                    password_hash="x", role=UserRole.builder))
        await db.commit()
    return user_id


async def _cleanup_user(session_factory, user_id: str) -> None:
    async with session_factory() as db:
        await db.delete(await db.get(User, user_id))
        await db.commit()


def test_redemption_is_atomic_single_use_under_concurrent_attempts(session_factory):
    async def scenario():
        user_id = await _seed_user(session_factory)
        try:
            service = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            operation_id = await service.create_candidate_operation(
                user_id, "opencode", CONFIG, AUTH, purpose="verification")
            assert await service.mark_candidate_operation_verified(operation_id) is not None

            # Two concurrent redemptions of the same proof: exactly one wins
            # the atomic conditional delete; the loser finds nothing.
            async def redeem(service):
                return await service.redeem_candidate_verification(
                    operation_id, user_id, "opencode", CONFIG, AUTH)

            first = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            second = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            outcomes = await asyncio.gather(redeem(first), redeem(second))
            assert sorted(outcomes, key=str) == [False, True]

            # Single-use: nothing is left to redeem, not even for the winner.
            third = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            assert await redeem(third) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, operation_id) is None
        finally:
            await _cleanup_user(session_factory, user_id)

    asyncio.run(scenario())


def test_wrong_owner_purpose_success_and_expiry_can_never_be_redeemed(session_factory):
    async def scenario():
        owner_id = await _seed_user(session_factory)
        other_id = await _seed_user(session_factory)
        try:
            creator = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)

            # A discovery-purpose operation can never be marked, redeemed, or
            # proven — even if a success flag had been recorded by mistake.
            discovery = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="discovery")
            assert await creator.mark_candidate_operation_verified(discovery) is None
            async with session_factory() as db:
                row = await db.get(ProviderCandidateOperation, discovery)
                row.verification_succeeded = True
                await db.commit()
            redeemer = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            assert await redeemer.redeem_candidate_verification(
                discovery, owner_id, "opencode", CONFIG, AUTH) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, discovery) is not None

            # A verification whose test failed (no recorded success) proves nothing.
            failed = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="verification")
            assert await redeemer.redeem_candidate_verification(
                failed, owner_id, "opencode", CONFIG, AUTH) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, failed) is not None

            # Another actor's operation is neither redeemed nor deleted.
            foreign = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="verification")
            await creator.mark_candidate_operation_verified(foreign)
            assert await redeemer.redeem_candidate_verification(
                foreign, other_id, "opencode", CONFIG, AUTH) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, foreign) is not None

            # A different provider never matches.
            assert await redeemer.redeem_candidate_verification(
                foreign, owner_id, "other-provider", CONFIG, AUTH) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, foreign) is not None

            # Expiry is honoured against the row's stored deadline, frozen by
            # writing a past expires_at (no sleeping): the proof proves nothing
            # and the stale row is cleaned up.
            expired = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="verification")
            await creator.mark_candidate_operation_verified(expired)
            async with session_factory() as db:
                row = await db.get(ProviderCandidateOperation, expired)
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()
            assert await redeemer.redeem_candidate_verification(
                expired, owner_id, "opencode", CONFIG, AUTH) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, expired) is None

            # The redeemable path still works end to end on the real database:
            # the payload must match the uploaded files.
            honest = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="verification")
            await creator.mark_candidate_operation_verified(honest)
            assert await redeemer.redeem_candidate_verification(
                honest, owner_id, "opencode", CONFIG, AUTH) is True
            mismatched = await creator.create_candidate_operation(
                owner_id, "opencode", CONFIG, AUTH, purpose="verification")
            await creator.mark_candidate_operation_verified(mismatched)
            assert await redeemer.redeem_candidate_verification(
                mismatched, owner_id, "opencode", CONFIG, {"x": {"key": "other"}}) is False
            async with session_factory() as db:
                assert await db.get(ProviderCandidateOperation, mismatched) is None
        finally:
            await _cleanup_user(session_factory, owner_id)
            await _cleanup_user(session_factory, other_id)

    asyncio.run(scenario())


def test_candidate_payloads_stay_encrypted_at_rest_and_out_of_results(session_factory):
    async def scenario():
        user_id = await _seed_user(session_factory)
        try:
            service = ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)
            operation_id = await service.create_candidate_operation(
                user_id, "opencode", CONFIG, AUTH, purpose="verification")

            async with session_factory() as db:
                row = await db.get(ProviderCandidateOperation, operation_id)
                stored = json.dumps({
                    "payload_ciphertext": row.payload_ciphertext,
                    "purpose": row.purpose,
                    "verification_succeeded": row.verification_succeeded,
                })
            assert "sentinel-boundary-key" not in stored
            assert "sentinel-boundary-secret" not in stored

            consumed = await service.consume_candidate_operation(operation_id, user_id, "opencode")
            assert consumed == {"format":"v2", "config": CONFIG, "auth": AUTH}
        finally:
            await _cleanup_user(session_factory, user_id)

    asyncio.run(scenario())
