"""D9 proof through the production resolver and real PostgreSQL catalog rows.

The model/runtime is deliberately not started: failure must occur during live
catalog resolution, before the external model boundary is reachable.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.agents.models import Agent
from app.domain.agents.resolution import AgentCatalogResolver, SqlCatalogResolutionRepository
from app.domain.identity.models import Group, GroupMembership, GroupMembershipRole, User, UserRole
from app.domain.mcp_servers.models import McpServer
from app.domain.skills.models import Skill
from shared.errors import KosmoError

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Run DB-backed integration journey in backend container")


@pytest.fixture(scope="module")
def sessions(migrated_test_database):
    engine = create_async_engine(migrated_test_database, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


_EN = "The referenced {kind} entry is unavailable. It may have been deleted or you may no longer have access to it."
_ES = "La entrada de tipo {kind} referenciada no está disponible. Puede que se haya eliminado o que ya no tengas acceso a ella."


@pytest.mark.parametrize("kind", ["agent", "mcp", "skill"])
@pytest.mark.parametrize("case", ["missing", "invisible", "revoked"])
def test_d9_resolution_blocks_missing_invisible_and_revoked_references(sessions, kind, case):
    consumer, owner, group_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    target_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4())
    actor_id_for_target = consumer if case == "revoked" else owner
    visibility = "group" if case == "revoked" else "personal"
    node = {"agent_id": target_id if kind == "agent" else agent_id}
    async def seed_and_resolve():
        async with sessions() as db:
            db.add_all([
                User(id=consumer, username=f"d9-c-{consumer}", password_hash="x", role=UserRole.runner),
                User(id=owner, username=f"d9-o-{owner}", password_hash="x", role=UserRole.runner),
            ])
            await db.flush()
            if case == "revoked":
                db.add(Group(id=group_id, name=f"d9-{group_id}"))
                db.add(GroupMembership(group_id=group_id, user_id=consumer, role=GroupMembershipRole.member))
            if kind != "agent":
                db.add(Agent(id=agent_id, name=f"d9-agent-{agent_id}", owner_user_id=consumer,
                             visibility="personal", model="provider/model", instructions="",
                             mcp_ids=[target_id] if kind == "mcp" else [],
                             skill_ids=[target_id] if kind == "skill" else []))
            if kind == "agent" and case != "missing":
                db.add(Agent(id=target_id, name=f"target-{target_id}", owner_user_id=actor_id_for_target,
                             visibility=visibility, group_id=group_id if visibility == "group" else None,
                             model="provider/model", instructions="", mcp_ids=[], skill_ids=[]))
            if kind == "mcp" and case != "missing":
                db.add(McpServer(id=target_id, name=f"target-{target_id}", owner_user_id=actor_id_for_target,
                                 visibility=visibility, group_id=group_id if visibility == "group" else None,
                                 transport_type="stdio", safe_config={"type": "stdio", "command": "tool", "args": [], "env": []},
                                 secret_ciphertext={}))
            if kind == "skill" and case != "missing":
                db.add(Skill(id=target_id, name=f"target-{target_id}", owner_user_id=actor_id_for_target,
                             visibility=visibility, group_id=group_id if visibility == "group" else None,
                             description="", instructions=""))
            await db.commit()
            if case == "revoked":
                # Selection happened while membership existed; resolution is live.
                await db.execute(delete(GroupMembership).where(
                    GroupMembership.user_id == consumer, GroupMembership.group_id == group_id))
                await db.commit()
            try:
                await AgentCatalogResolver(SqlCatalogResolutionRepository(db)).resolve(
                    created_by=consumer, node=node)
            except KosmoError as error:
                observed = (error.message_key, error.params, error.code)
            else:
                observed = ("resolved", {}, "")
            await db.execute(delete(Agent).where(Agent.id.in_([agent_id, target_id])))
            await db.execute(delete(McpServer).where(McpServer.id == target_id))
            await db.execute(delete(Skill).where(Skill.id == target_id))
            await db.execute(delete(Group).where(Group.id == group_id))
            await db.execute(delete(User).where(User.id.in_([consumer, owner])))
            await db.commit()
            return observed
    observed = asyncio.run(seed_and_resolve())
    assert observed == ("errors.catalog.reference_unavailable", {"kind": kind, "id": target_id},
                        "CATALOG_REFERENCE_UNAVAILABLE")
    # The public keyed failure and parameters are identical for a missing id,
    # an existing-but-invisible id and a reference revoked after authoring.
    assert _EN.format(kind=kind) and _ES.format(kind=kind)


@pytest.mark.parametrize("kind", ["agent", "mcp", "skill"])
def test_d9_unknown_and_forbidden_have_identical_caller_error(sessions, kind):
    """Compare a nonexistent UUID against an existing personal item owned elsewhere."""
    consumer, owner = str(uuid.uuid4()), str(uuid.uuid4())
    hidden_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4())
    async def run_case(existing):
        async with sessions() as db:
            if existing:
                if kind == "agent":
                    db.add(Agent(id=hidden_id, name=f"hidden-{hidden_id}", owner_user_id=owner,
                                 visibility="personal", model="provider/model", instructions="", mcp_ids=[], skill_ids=[]))
                elif kind == "mcp":
                    db.add(McpServer(id=hidden_id, name=f"hidden-{hidden_id}", owner_user_id=owner,
                                     visibility="personal", transport_type="stdio", safe_config={"type":"stdio", "command":"tool", "args":[], "env":[]}, secret_ciphertext={}))
                else:
                    db.add(Skill(id=hidden_id, name=f"hidden-{hidden_id}", owner_user_id=owner,
                                 visibility="personal", description="", instructions=""))
                await db.commit()
            if kind != "agent":
                db.add(Agent(id=agent_id, name=f"consumer-{agent_id}", owner_user_id=consumer,
                             visibility="personal", model="provider/model", instructions="",
                             mcp_ids=[hidden_id] if kind == "mcp" else [], skill_ids=[hidden_id] if kind == "skill" else []))
                await db.commit()
            try:
                await AgentCatalogResolver(SqlCatalogResolutionRepository(db)).resolve(
                    created_by=consumer, node={"agent_id": hidden_id if kind == "agent" else agent_id})
            except KosmoError as error:
                result = (error.message_key, error.params, error.code)
            else:
                result = ("resolved", {}, "")
            await db.execute(delete(Agent).where(Agent.id.in_([agent_id, hidden_id])))
            await db.execute(delete(McpServer).where(McpServer.id == hidden_id))
            await db.execute(delete(Skill).where(Skill.id == hidden_id))
            await db.commit()
            return result
    # Set up users for catalog FK ownership. Resolution itself needs no user row.
    async def seed_users():
        async with sessions() as db:
            db.add_all([User(id=consumer, username=f"d9-c-{consumer}", password_hash="x", role=UserRole.runner),
                        User(id=owner, username=f"d9-o-{owner}", password_hash="x", role=UserRole.runner)])
            await db.commit()
    asyncio.run(seed_users())
    missing = asyncio.run(run_case(False))
    forbidden = asyncio.run(run_case(True))
    async def cleanup_users():
        async with sessions() as db:
            await db.execute(delete(User).where(User.id.in_([consumer, owner])))
            await db.commit()
    asyncio.run(cleanup_users())
    expected = ("errors.catalog.reference_unavailable", {"kind": kind, "id": hidden_id},
                "CATALOG_REFERENCE_UNAVAILABLE")
    assert missing == forbidden == expected
    assert _EN.format(kind=kind) == {
        "agent": "The referenced agent entry is unavailable. It may have been deleted or you may no longer have access to it.",
        "mcp": "The referenced mcp entry is unavailable. It may have been deleted or you may no longer have access to it.",
        "skill": "The referenced skill entry is unavailable. It may have been deleted or you may no longer have access to it.",
    }[kind]
    assert _ES.format(kind=kind) == {
        "agent": "La entrada de tipo agent referenciada no está disponible. Puede que se haya eliminado o que ya no tengas acceso a ella.",
        "mcp": "La entrada de tipo mcp referenciada no está disponible. Puede que se haya eliminado o que ya no tengas acceso a ella.",
        "skill": "La entrada de tipo skill referenciada no está disponible. Puede que se haya eliminado o que ya no tengas acceso a ella.",
    }[kind]
