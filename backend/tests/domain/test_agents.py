import asyncio
from types import SimpleNamespace

import pytest

from app.domain.agents.service import AgentService
from shared.errors import PermissionDeniedError, ValidationFailedError


class Repo:
    def __init__(self):
        self.rows = []
        self.catalog = {"mcp": {}, "skill": {}}
        self.roles = {}

    async def membership_role(self, user_id, group_id):
        return self.roles.get(user_id, {}).get(group_id)

    async def memberships(self, user_id):
        return list(self.roles.get(user_id, {}))

    async def visible_candidates(self, user_id, groups):
        return [r for r in self.rows if r.visibility == "global" or r.owner_user_id == user_id or
                r.visibility == "group" and r.group_id in groups]

    async def by_id(self, entity_id):
        return next((r for r in self.rows if r.id == entity_id), None)

    async def name_conflict(self, *args, **kwargs):
        return False

    async def visible_reference(self, kind, user_id, reference_id):
        row = self.catalog[kind].get(reference_id)
        return row and (row.visibility == "global" or row.owner_user_id == user_id or
                        row.visibility == "group" and row.group_id in await self.memberships(user_id))

    async def create(self, row):
        row.id = f"agent-{len(self.rows) + 1}"
        self.rows.append(row)
        return row

    async def update(self, row, **changes):
        for key, value in changes.items():
            setattr(row, key, value)
        return row

    async def delete(self, entity_id):
        row = await self.by_id(entity_id)
        if row:
            self.rows.remove(row)
            return True
        return False


def actor(uid="u1", role="runner"):
    return SimpleNamespace(id=uid, role=role)


def test_agent_create_validates_unique_ids_and_changed_references():
    async def run():
        repo = Repo()
        service = AgentService(repo)
        with pytest.raises(ValidationFailedError):
            await service.create(actor(), {"name": "a", "model": "m", "mcp_ids": ["x", "x"]})
        with pytest.raises(ValidationFailedError):
            await service.create(actor(), {"name": "a", "model": "m", "mcp_ids": ["hidden"]})
        ref = SimpleNamespace(id="ok", visibility="personal", owner_user_id="u1", group_id=None)
        repo.catalog["mcp"]["ok"] = ref
        created = await service.create(actor(), {"name": "a", "model": "m", "mcp_ids": ["ok"]})
        assert created["mcp_ids"] == ["ok"]
    asyncio.run(run())


def test_agent_patch_preserves_omitted_fields_and_stale_refs_and_delete_does_not_rewrite_node():
    async def run():
        repo = Repo()
        service = AgentService(repo)
        for kind, ref_id in (("mcp", "stale"), ("skill", "gone")):
            repo.catalog[kind][ref_id] = SimpleNamespace(id=ref_id, visibility="personal", owner_user_id="u1", group_id=None)
        created = await service.create(actor(), {"name": "a", "model": "m", "reasoning_effort": "future-value",
                                                  "instructions": "markdown", "mcp_ids": ["stale"], "skill_ids": ["gone"]})
        repo.catalog["mcp"].clear()
        repo.catalog["skill"].clear()
        updated = await service.update(actor(), created["id"], {"instructions": "repaired"})
        assert updated["model"] == "m" and updated["reasoning_effort"] == "future-value"
        assert updated["mcp_ids"] == ["stale"] and updated["skill_ids"] == ["gone"]
        assert await service.delete(actor(), created["id"])
        workflow_node = {"agent_id": created["id"], "mcp_ids": ["stale"]}
        assert workflow_node == {"agent_id": created["id"], "mcp_ids": ["stale"]}
    asyncio.run(run())


def test_agent_scope_policy_requires_group_manager_membership_and_admin_global():
    async def run():
        repo = Repo()
        service = AgentService(repo)
        repo.roles["u1"] = {"g": "member"}
        with pytest.raises(PermissionDeniedError):
            await service.create(actor("u1", "group_manager"), {"name": "g", "model": "m", "visibility": "group", "group_id": "g"})
        repo.roles["u1"]["g"] = "group_manager"
        await service.create(actor(), {"name": "g", "model": "m", "visibility": "group", "group_id": "g"})
        with pytest.raises(PermissionDeniedError):
            await service.create(actor(), {"name": "global", "model": "m", "visibility": "global"})
    asyncio.run(run())
