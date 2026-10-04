import pytest

from app.domain.agents.resolution import AgentCatalogResolver, apply_reference_deltas
from shared.errors import KosmoError


def test_deltas_dedupe_preserve_agent_order_and_apply_removal_before_addition():
    assert apply_reference_deltas(["a", "b", "a", "c"], ["b", "d", "a"], ["b", "c"]) == ["a", "d"]


@pytest.mark.parametrize("added,removed,expected", [
    (["x", "x", "y"], [], ["base", "x", "y"]),
    ([], ["absent"], ["base"]),
    (["base", "new"], [], ["base", "new"]),
])
def test_delta_edge_cases(added, removed, expected):
    assert apply_reference_deltas(["base"], added, removed) == expected


class Repo:
    def __init__(self):
        self.agent = dict(id="selected", visibility="global", owner_user_id="owner", mcp_ids=["shared"], skill_ids=["skill"])
        self.mcps = {"shared": dict(id="shared", visibility="group", group_id="g", safe_config={"type": "http", "url": "https://example.test", "headers":[{"name":"X-Key","secret":True,"is_set":True}]}, secret_ciphertext={"X-Key":"cipher"})}
        self.skills = {"skill": dict(id="skill", visibility="global", name="S", description="", instructions="full")}
        self.groups = {"creator": ["g"], "owner": []}
        self.decrypt_called = False

    async def memberships(self, user): return self.groups[user]
    async def agent_by_id(self, entity_id): return self.agent if entity_id == self.agent["id"] else None
    async def mcp_by_id(self, entity_id): return self.mcps.get(entity_id)
    async def skill_by_id(self, entity_id): return self.skills.get(entity_id)
    def decrypt(self, ciphertext):
        self.decrypt_called = True
        return {"X-Key": "SYNTHETIC_SECRET"}


@pytest.mark.asyncio
async def test_resolution_uses_task_creator_live_visibility_and_keeps_secret_runtime_local():
    repo = Repo()
    resolver = AgentCatalogResolver(repo)
    result = await resolver.resolve(created_by="creator", node={"agent_id":"selected", "added_mcp_ids":[], "removed_mcp_ids":[], "added_skill_ids":[], "removed_skill_ids":[]})
    assert result.mcps[0].headers == (("X-Key", "SYNTHETIC_SECRET"),)
    assert result.skills[0].instructions == "full"
    assert "SYNTHETIC_SECRET" not in repr(result)
    assert "SYNTHETIC_SECRET" not in repr(result.to_safe_dict())
    assert repo.decrypt_called


@pytest.mark.asyncio
async def test_membership_revocation_blocks_before_secret_decryption():
    repo = Repo()
    repo.groups["creator"] = []
    with pytest.raises(KosmoError) as error:
        await AgentCatalogResolver(repo).resolve(created_by="creator", node={"agent_id":"selected"})
    assert error.value.code == "CATALOG_REFERENCE_UNAVAILABLE"
    assert error.value.params == {"kind":"mcp", "id":"shared"}
    assert not repo.decrypt_called


@pytest.mark.asyncio
async def test_removed_missing_id_is_not_resolved_and_agent_is_live():
    repo = Repo()
    repo.agent["mcp_ids"] = ["gone"]
    result = await AgentCatalogResolver(repo).resolve(created_by="creator", node={"agent_id":"selected", "removed_mcp_ids":["gone"]})
    assert result.mcps == ()
    repo.agent.update(model="changed", mcp_ids=[])
    result = await AgentCatalogResolver(repo).resolve(created_by="creator", node={"agent_id":"selected"})
    assert result.agent.model == "changed"
