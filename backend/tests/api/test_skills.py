from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.skills import get_skill_service
from app.main import create_app
from app.domain.skills.service import SkillService


class Repo:
    def __init__(self):
        self.rows = []

    async def memberships(self, user_id):
        return []

    async def membership_role(self, user_id, group_id):
        return None

    async def visible_candidates(self, user_id, group_ids):
        return [r for r in self.rows if r.visibility == "personal" and r.owner_user_id == user_id]

    async def by_id(self, entity_id):
        return next((r for r in self.rows if r.id == entity_id), None)

    async def name_conflict(self, *args, **kwargs):
        return False

    async def create(self, row):
        row.id = f"skill-{len(self.rows) + 1}"
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


def test_skills_api_crud_and_invalid_body_does_not_echo_instructions():
    app = create_app()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="runner"))
    service = SkillService(Repo())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_skill_service] = lambda: service
    client = TestClient(app)
    created = client.post("/skills", json={"name": "Notes", "instructions": "Keep me"})
    assert created.status_code == 201
    skill_id = created.json()["id"]
    assert client.get("/skills/" + skill_id).json()["instructions"] == "Keep me"
    assert client.patch("/skills/" + skill_id, json={"description": "Updated"}).json()["instructions"] == "Keep me"
    assert client.delete("/skills/" + skill_id).status_code == 204
    sentinel = "SENSITIVE-CANDIDATE-" + "x" * 100001
    invalid = client.post("/skills", content=(('{"name":"n","instructions":"' + sentinel + '"}').encode()),
                          headers={"content-type": "application/json"})
    assert invalid.status_code == 422
    assert sentinel not in invalid.text
    assert "input" not in invalid.text
    client.close()
