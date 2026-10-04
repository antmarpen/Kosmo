from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal
from app.domain.skills.models import Skill
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError

MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 2000
MAX_INSTRUCTIONS_LENGTH = 100000
_NAME_CONSTRAINTS = {"uq_skills_personal_name_ci", "uq_skills_group_name_ci", "uq_skills_global_name_ci"}


def _role(actor) -> str:
    role = getattr(actor, "role", None)
    return str(getattr(role, "value", role))


def _name(value) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value:
        raise ValidationFailedError("errors.skill.name_invalid")
    if len(value) > MAX_NAME_LENGTH:
        raise ValidationFailedError("errors.skill.name_too_long", params={"max_length": MAX_NAME_LENGTH})
    return value


def _safe(row) -> dict:
    return {"id": row.id, "name": row.name, "owner_user_id": row.owner_user_id,
            "visibility": row.visibility, "group_id": row.group_id,
            "description": row.description, "instructions": row.instructions,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


class SkillService:
    def __init__(self, repository):
        self.repository = repository

    async def _actor_with_memberships(self, actor, group_id=None):
        memberships = {}
        if group_id is not None:
            role = await self.repository.membership_role(actor.id, group_id)
            if role:
                memberships[group_id] = role
        return SimpleNamespace(id=actor.id, role=getattr(actor, "role", None), memberships=memberships)

    async def _authorize_scope(self, actor, visibility, group_id):
        if visibility not in {"personal", "group", "global"} or ((visibility == "group") != (group_id is not None)):
            raise ValidationFailedError("errors.skill.scope_invalid")
        scoped_actor = await self._actor_with_memberships(actor, group_id)
        allowed = ((visibility == "personal" and can_create_personal(scoped_actor))
                   or (visibility == "group" and can_create_group(scoped_actor, group_id))
                   or (visibility == "global" and can_create_global(scoped_actor)))
        if not allowed:
            raise PermissionDeniedError("errors.skill.global_admin_only" if visibility == "global"
                                        else "errors.skill.group_forbidden" if visibility == "group"
                                        else "errors.skill.forbidden")

    async def create(self, actor, data: dict) -> dict:
        name = _name(data.get("name"))
        visibility, group_id = data.get("visibility", "personal"), data.get("group_id")
        await self._authorize_scope(actor, visibility, group_id)
        description = data.get("description", "")
        instructions = data.get("instructions", "")
        self._validate_content(description, instructions)
        if await self.repository.name_conflict(actor.id, name, visibility, group_id):
            raise ConflictError("errors.skill.name_duplicate")
        row = Skill(name=name, owner_user_id=actor.id, visibility=visibility, group_id=group_id,
                    description=description, instructions=instructions)
        try:
            row = await self.repository.create(row)
        except IntegrityError as exc:
            if not self._name_race(exc):
                raise
            raise ConflictError("errors.skill.name_duplicate") from None
        return _safe(row)

    async def list_visible(self, user_id: str) -> list[dict]:
        groups = await self.repository.memberships(user_id)
        rows = await self.repository.visible_candidates(user_id, groups)
        priority = {"personal": 0, "group": 1, "global": 2}
        rows.sort(key=lambda row: (priority[row.visibility], row.name.casefold(), row.id))
        return [_safe(row) for row in rows]

    async def get_visible(self, user_id: str, skill_id: str) -> dict:
        row = await self.repository.by_id(skill_id)
        if row is None:
            raise NotFoundError("errors.skill.not_found")
        if row.visibility == "personal" and row.owner_user_id == user_id:
            return _safe(row)
        if row.visibility == "global":
            return _safe(row)
        if row.visibility == "group" and row.group_id in await self.repository.memberships(user_id):
            return _safe(row)
        raise PermissionDeniedError("errors.skill.forbidden")

    async def _mutable(self, actor, skill_id):
        row = await self.repository.by_id(skill_id)
        if row is None:
            raise NotFoundError("errors.skill.not_found")
        await self.get_visible(actor.id, skill_id)
        if _role(actor) != "admin" and row.owner_user_id != actor.id:
            raise PermissionDeniedError("errors.skill.forbidden")
        return row

    async def update(self, actor, skill_id: str, changes: dict) -> dict:
        row = await self._mutable(actor, skill_id)
        values = dict(changes)
        if "name" in values:
            values["name"] = _name(values["name"])
        visibility = values.get("visibility", row.visibility)
        group_id = values.get("group_id", row.group_id if visibility == row.visibility else None)
        await self._authorize_scope(actor, visibility, group_id)
        values["visibility"], values["group_id"] = visibility, group_id
        description = values.get("description", row.description)
        instructions = values.get("instructions", row.instructions)
        self._validate_content(description, instructions)
        name = values.get("name", row.name)
        if await self.repository.name_conflict(row.owner_user_id, name, visibility, group_id, exclude_id=row.id):
            raise ConflictError("errors.skill.name_duplicate")
        try:
            updated = await self.repository.update(row, **values)
        except IntegrityError as exc:
            if not self._name_race(exc):
                raise
            raise ConflictError("errors.skill.name_duplicate") from None
        return _safe(updated)

    async def delete(self, actor, skill_id: str) -> bool:
        await self._mutable(actor, skill_id)
        return await self.repository.delete(skill_id)

    @staticmethod
    def _validate_content(description, instructions):
        if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationFailedError("errors.skill.description_invalid", params={"max_length": MAX_DESCRIPTION_LENGTH})
        if not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS_LENGTH:
            raise ValidationFailedError("errors.skill.instructions_invalid", params={"max_length": MAX_INSTRUCTIONS_LENGTH})

    @staticmethod
    def _name_race(exc: IntegrityError) -> bool:
        cause = exc.orig if exc.orig is not None else exc
        return any(name in str(cause) for name in _NAME_CONSTRAINTS)
