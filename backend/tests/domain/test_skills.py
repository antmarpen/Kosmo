import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.skills.service import SkillService
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError


class Repo:
    def __init__(self):
        self.rows = []
        self.roles = {}

    async def memberships(self, user_id):
        return list(self.roles.get(user_id, {}).keys())

    async def membership_role(self, user_id, group_id):
        return self.roles.get(user_id, {}).get(group_id)

    async def visible_candidates(self, user_id, groups):
        return [r for r in self.rows if (r.visibility == "personal" and r.owner_user_id == user_id)
                or (r.visibility == "group" and r.group_id in groups) or r.visibility == "global"]

    async def by_id(self, entity_id):
        return next((r for r in self.rows if r.id == entity_id), None)

    async def name_conflict(self, owner, name, visibility, group_id, *, exclude_id=None):
        return any(r.owner_user_id == owner and r.visibility == visibility
                   and (visibility != "group" or r.group_id == group_id)
                   and r.name.casefold() == name.casefold() and r.id != exclude_id for r in self.rows)

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


def actor(user_id="u1", role="runner"):
    return SimpleNamespace(id=user_id, role=role)


def test_skill_crud_visibility_and_partial_update():
    async def run():
        repo = Repo()
        service = SkillService(repo)
        created = await service.create(actor(), {"name": "  Research ", "instructions": "First"})
        assert created["name"] == "Research"
        assert created["instructions"] == "First"
        await service.update(actor(), created["id"], {"description": "Changed"})
        detail = await service.get_visible("u1", created["id"])
        assert detail["instructions"] == "First"
        assert detail["description"] == "Changed"
        assert await service.delete(actor(), created["id"]) is True
    asyncio.run(run())


def test_skill_group_create_requires_group_manager_membership_not_platform_role():
    async def run():
        repo = Repo()
        service = SkillService(repo)
        repo.roles["u1"] = {"g1": "member"}
        with pytest.raises(PermissionDeniedError):
            await service.create(actor(role="group_manager"), {"name": "No", "visibility": "group", "group_id": "g1"})
        repo.roles["u1"] = {"g1": "group_manager"}
        await service.create(actor(), {"name": "Yes", "visibility": "group", "group_id": "g1"})
    asyncio.run(run())


def test_skill_duplicate_conflict_is_keyed():
    async def run():
        service = SkillService(Repo())
        await service.create(actor(), {"name": "Research"})
        with pytest.raises(ConflictError) as error:
            await service.create(actor(), {"name": " research "})
        assert error.value.message_key == "errors.skill.name_duplicate"
    asyncio.run(run())


def test_skill_invisible_ids_and_read_visibility_do_not_grant_mutation():
    async def run():
        repo = Repo()
        service = SkillService(repo)
        # Seed a group-visible record as its owner; a member may read, but not edit it.
        row = await SkillService(repo).create(actor("owner"), {"name": "Shared"})
        repo.rows[0].visibility = "group"
        repo.rows[0].group_id = "g1"
        repo.roles["reader"] = {"g1": "member"}
        assert (await service.get_visible("reader", row["id"]))["name"] == "Shared"
        with pytest.raises(PermissionDeniedError):
            await service.update(actor("reader"), row["id"], {"name": "Changed"})
        with pytest.raises(NotFoundError):
            await service.get_visible("reader", "missing")
    asyncio.run(run())


def test_skill_scope_change_requires_new_target_scope_permission():
    async def run():
        repo = Repo()
        service = SkillService(repo)
        created = await service.create(actor(), {"name": "Move"})
        with pytest.raises(PermissionDeniedError):
            await service.update(actor(), created["id"], {"visibility": "group", "group_id": "g1"})
        repo.roles["u1"] = {"g1": "group_manager"}
        moved = await service.update(actor(), created["id"], {"visibility": "group", "group_id": "g1"})
        assert (moved["visibility"], moved["group_id"]) == ("group", "g1")
    asyncio.run(run())


def test_skill_commit_time_name_race_becomes_keyed_conflict():
    class RacingRepo(Repo):
        async def create(self, row):
            raise IntegrityError("insert", {}, Exception("uq_skills_personal_name_ci"))

    async def run():
        with pytest.raises(ConflictError) as error:
            await SkillService(RacingRepo()).create(actor(), {"name": "Race"})
        assert error.value.message_key == "errors.skill.name_duplicate"
        assert "uq_skills" not in str(error.value)
    asyncio.run(run())
