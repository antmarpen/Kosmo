from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.agents import get_agent_service
from app.domain.agents.service import AgentService
from app.main import create_app


class Repo:
    def __init__(self):
        self.rows = []

    async def memberships(self, user_id): return []
    async def membership_role(self, user_id, group_id): return None
    async def visible_candidates(self, user_id, groups): return [r for r in self.rows if r.owner_user_id == user_id]
    async def by_id(self, entity_id): return next((r for r in self.rows if r.id == entity_id), None)
    async def name_conflict(self, *args, **kwargs): return False
    async def visible_reference(self, *args): return True
    async def create(self, row):
        row.id = "agent-1"
        self.rows.append(row)
        return row
    async def update(self, row, **changes):
        for key, value in changes.items(): setattr(row, key, value)
        return row
    async def delete(self, entity_id):
        row = await self.by_id(entity_id)
        if row: self.rows.remove(row); return True
        return False


def test_agents_api_crud_nullable_patch_and_extra_fields_rejected():
    app = create_app()
    user = SimpleNamespace(id="u1", role=SimpleNamespace(value="runner"))
    service = AgentService(Repo())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_agent_service] = lambda: service
    client = TestClient(app)
    created = client.post("/agents", json={"name": "Agent", "model": "provider/model", "reasoning_effort": "effort-x", "instructions": "Markdown"})
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    assert client.patch(f"/agents/{agent_id}", json={"reasoning_effort": None}).json()["reasoning_effort"] is None
    assert client.get(f"/agents/{agent_id}").json()["instructions"] == "Markdown"
    assert client.post("/agents", json={"name": "No", "model": "m", "agent": {}}).status_code == 422
    assert client.delete(f"/agents/{agent_id}").status_code == 204
    client.close()
