"""Targeted provider verification across personal/group/global rows (R9).

Proves the saved-config verification targeting contract on the migrated test
database, resolved exactly as the API routes resolve it
(`_resolve_verification_target` → `ProviderConfigService.visible_row`):

  * an explicit config id targets the caller's personal row, the group row of
    a group the caller belongs to, and the global row for everyone;
  * rows outside the caller's visibility (another user's personal row, a
    group row of a non-member) are forbidden and unknown ids are not found;
  * the visibility listing mirrors the same model per caller;
  * a targeted row decrypts to exactly its own stored files — a probe can
    never run with another row's credentials;
  * the verification-status write lands on the targeted row only, and the
    `expected_updated_at` guard drops stale results instead of branding a
    replaced configuration as verified.

Run inside the backend container (host→localhost:5432 connections reset on
this Windows host, so the tests are skipped off-container):
    docker compose exec -T backend sh -c \\
      "KOSMO_TEST_DATABASE_URL='postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' \\
       uv run pytest tests/api/test_integration_provider_verification_targeting.py -q"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
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

from app.api.routes.provider_configs import _resolve_verification_target
from app.domain.identity.models import (
    Group,
    GroupMembership,
    GroupMembershipRole,
    User,
    UserRole,
)
from app.domain.provider_configs.models import ProviderConfig
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService
from shared.errors import NotFoundError, PermissionDeniedError

ENCRYPTION_KEY = "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc="


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_factory(migrated_test_database):
    """Session factory against the migrated test database (NullPool: each
    test drives async boundaries with its own asyncio.run loop)."""
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _service(session_factory) -> ProviderConfigService:
    return ProviderConfigService(ProviderConfigRepository(session_factory()), ENCRYPTION_KEY)


def _files(key: str, secret: str) -> tuple[bytes, bytes]:
    """A distinct synthetic opencode.json/auth.json pair per row."""
    return (
        json.dumps({"providers": {"opencode": {"options": {"apiKey": key}}}}).encode("utf-8"),
        json.dumps([{"id":"cred_opencode","integrationID":"opencode","label":"API key",
                     "active":True,"value":{"type":"api","key":secret}}]).encode("utf-8"),
    )


async def _seed_rows(session_factory) -> dict:
    """Two group members, an outsider, an admin, and one row per scope."""
    ids = {name: str(uuid.uuid4())
           for name in ("owner_id", "member_id", "outsider_id", "admin_id", "group_id")}
    async with session_factory() as db:
        db.add(User(id=ids["owner_id"], username=f"verify-owner-{uuid.uuid4()}",
                    password_hash="x", role=UserRole.builder))
        db.add(User(id=ids["member_id"], username=f"verify-member-{uuid.uuid4()}",
                    password_hash="x", role=UserRole.builder))
        db.add(User(id=ids["outsider_id"], username=f"verify-outsider-{uuid.uuid4()}",
                    password_hash="x", role=UserRole.builder))
        db.add(User(id=ids["admin_id"], username=f"verify-admin-{uuid.uuid4()}",
                    password_hash="x", role=UserRole.admin))
        db.add(Group(id=ids["group_id"], name=f"verify-group-{uuid.uuid4()}"))
        await db.commit()
        # Memberships land in their own committed unit: the users and the
        # group they reference must exist before the membership rows.
        db.add(GroupMembership(group_id=ids["group_id"], user_id=ids["owner_id"],
                               role=GroupMembershipRole.group_manager))
        db.add(GroupMembership(group_id=ids["group_id"], user_id=ids["member_id"],
                               role=GroupMembershipRole.member))
        await db.commit()

    async with session_factory() as db:
        # One context-managed session owns every seed row: the repository's
        # post-commit refresh() re-opens a transaction, so an unmanaged
        # session would strand its NullPool connection until GC.
        service = ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)
        personal = await service.create(
            ids["owner_id"], "opencode", *_files("sentinel-personal-key", "sentinel-personal-secret"),
            visibility="personal", display_name=f"Personal {uuid.uuid4()}")
        group_row = await service.create(
            ids["owner_id"], "opencode", *_files("sentinel-group-key", "sentinel-group-secret"),
            visibility="group", group_id=ids["group_id"], display_name=f"Group {uuid.uuid4()}")
        global_row = await service.create(
            ids["admin_id"], "opencode", *_files("sentinel-global-key", "sentinel-global-secret"),
            visibility="global", display_name=f"Global {uuid.uuid4()}")
        foreign = await service.create(
            ids["outsider_id"], "opencode", *_files("sentinel-foreign-key", "sentinel-foreign-secret"),
            visibility="personal", display_name=f"Foreign {uuid.uuid4()}")
    return {
        **ids,
        "personal_id": personal["id"],
        "group_row_id": group_row["id"],
        "global_id": global_row["id"],
        "foreign_id": foreign["id"],
    }


async def _cleanup(session_factory, seed: dict) -> None:
    """Group and user deletes cascade to memberships and provider rows."""
    async with session_factory() as db:
        await db.execute(text("DELETE FROM groups WHERE id = :id").bindparams(id=seed["group_id"]))
        stmt = text("DELETE FROM users WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        await db.execute(stmt, {"ids": [seed[name] for name in
                                        ("owner_id", "member_id", "outsider_id", "admin_id")]})
        await db.commit()


def _actor(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


# ---------------------------------------------------------------------------
# Targeting against real PostgreSQL rows
# ---------------------------------------------------------------------------

def test_verification_target_resolves_by_visibility(session_factory):
    """The explicit config id resolves under the list visibility model and is
    denied for rows outside the caller's visibility."""

    async def scenario():
        seed = await _seed_rows(session_factory)
        try:
            # The repository session is context-managed so its NullPool
            # connection is released even though these are read-only calls
            # (they never commit, unlike the sibling redemption tests).
            async with session_factory() as db:
                service = ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)
                owner, member = _actor(seed["owner_id"]), _actor(seed["member_id"])
                outsider, admin = _actor(seed["outsider_id"]), _actor(seed["admin_id"])

                # Own personal row; group row for a member; global row for all.
                assert (await _resolve_verification_target(service, owner, seed["personal_id"])).id \
                    == seed["personal_id"]
                assert (await _resolve_verification_target(service, member, seed["group_row_id"])).id \
                    == seed["group_row_id"]
                assert (await _resolve_verification_target(service, outsider, seed["global_id"])).id \
                    == seed["global_id"]
                assert (await _resolve_verification_target(service, admin, seed["global_id"])).id \
                    == seed["global_id"]

                # Everyone else's personal rows and non-member group rows are
                # forbidden; unknown ids are not found.
                with pytest.raises(PermissionDeniedError):
                    await _resolve_verification_target(service, member, seed["personal_id"])
                with pytest.raises(PermissionDeniedError):
                    await _resolve_verification_target(service, outsider, seed["group_row_id"])
                with pytest.raises(PermissionDeniedError):
                    await _resolve_verification_target(service, owner, seed["foreign_id"])
                with pytest.raises(NotFoundError):
                    await _resolve_verification_target(service, owner, str(uuid.uuid4()))

                # The listing exposes the same model per caller: own personal
                # rows, own groups' rows, and every global row.
                def visible_ids(rows: list[dict]) -> set[str]:
                    return {row["id"] for row in rows}

                assert visible_ids(await service.list_visible(seed["owner_id"], "opencode")) == \
                    {seed["personal_id"], seed["group_row_id"], seed["global_id"]}
                assert visible_ids(await service.list_visible(seed["member_id"], "opencode")) == \
                    {seed["group_row_id"], seed["global_id"]}
                assert visible_ids(await service.list_visible(seed["outsider_id"], "opencode")) == \
                    {seed["foreign_id"], seed["global_id"]}
                assert visible_ids(await service.list_visible(seed["admin_id"], "opencode")) == \
                    {seed["global_id"]}
        finally:
            await _cleanup(session_factory, seed)

    asyncio.run(scenario())


def test_targeted_row_files_are_the_targeted_ones(session_factory):
    """Resolving a verification target decrypts exactly that row's stored
    files, never another row's credentials."""

    async def scenario():
        seed = await _seed_rows(session_factory)
        try:
            async with session_factory() as db:
                service = ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)

                async def resolved_files(config_id: str, user_id: str) -> dict[str, bytes]:
                    row = await _resolve_verification_target(service, _actor(user_id), config_id)
                    return service.read_row_files(row)

                personal = await resolved_files(seed["personal_id"], seed["owner_id"])
                assert json.loads(personal["opencode.json"]) == \
                    {"providers": {"opencode": {"options": {"apiKey": "sentinel-personal-key"}}}}
                assert json.loads(personal["auth.json"]) == \
                    [{"id":"cred_opencode","integrationID":"opencode","label":"API key","active":True,
                      "value":{"type":"api","key":"sentinel-personal-secret"}}]

                group = await resolved_files(seed["group_row_id"], seed["member_id"])
                assert json.loads(group["opencode.json"]) == \
                    {"providers": {"opencode": {"options": {"apiKey": "sentinel-group-key"}}}}
                assert json.loads(group["auth.json"]) == \
                    [{"id":"cred_opencode","integrationID":"opencode","label":"API key","active":True,
                      "value":{"type":"api","key":"sentinel-group-secret"}}]

                global_files = await resolved_files(seed["global_id"], seed["outsider_id"])
                assert json.loads(global_files["opencode.json"]) == \
                    {"providers": {"opencode": {"options": {"apiKey": "sentinel-global-key"}}}}
                assert json.loads(global_files["auth.json"]) == \
                    [{"id":"cred_opencode","integrationID":"opencode","label":"API key","active":True,
                      "value":{"type":"api","key":"sentinel-global-secret"}}]

                combined = json.dumps(
                    [json.loads(files["opencode.json"]) for files in (personal, group, global_files)]
                    + [json.loads(files["auth.json"]) for files in (personal, group, global_files)])
                for foreign_sentinel in ("sentinel-foreign-key", "sentinel-foreign-secret"):
                    assert foreign_sentinel not in combined
        finally:
            await _cleanup(session_factory, seed)

    asyncio.run(scenario())


def test_status_write_targets_only_the_targeted_row(session_factory):
    """A verification result updates exactly the row it targeted, and the
    expected_updated_at guard drops stale results."""

    async def scenario():
        seed = await _seed_rows(session_factory)
        try:
            # One context-managed service session for the whole scenario: the
            # status writes commit (releasing the NullPool connection) and the
            # context exit releases any residual transaction.
            async with session_factory() as db:
                service = ProviderConfigService(ProviderConfigRepository(db), ENCRYPTION_KEY)

                # Status reads use their own fresh session: the Core UPDATE
                # does not refresh the shared session's identity map.
                async def status_of(config_id: str) -> str:
                    async with session_factory() as read_db:
                        row = await read_db.get(ProviderConfig, config_id)
                        assert row is not None
                        return row.verification_status

                # Marking the personal row verified touches only that row.
                assert await service.set_verification_status(seed["personal_id"], "verified") is True
                assert await status_of(seed["personal_id"]) == "verified"
                assert await status_of(seed["group_row_id"]) == "unverified"
                assert await status_of(seed["global_id"]) == "unverified"
                assert await status_of(seed["foreign_id"]) == "unverified"

                # A result carrying a stale version marker updates nothing: the
                # configuration was replaced (updated_at moved) after the probe
                # started, so the new files must not be branded verified.
                async with session_factory() as read_db:
                    group_row = await read_db.get(ProviderConfig, seed["group_row_id"])
                    assert group_row is not None
                    expected_updated_at = group_row.updated_at
                stale = await service.set_verification_status(
                    seed["group_row_id"], "verified",
                    expected_updated_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
                assert stale is False
                assert await status_of(seed["group_row_id"]) == "unverified"

                # The live version marker lands the write.
                fresh = await service.set_verification_status(
                    seed["group_row_id"], "verified", expected_updated_at=expected_updated_at)
                assert fresh is True
                assert await status_of(seed["group_row_id"]) == "verified"
                assert await status_of(seed["global_id"]) == "unverified"
        finally:
            await _cleanup(session_factory, seed)

    asyncio.run(scenario())
