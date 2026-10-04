from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.domain.agents.models import Agent
from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError

MAX_NAME_LENGTH = 80
MAX_MODEL_LENGTH = 300
MAX_REASONING_LENGTH = 80
MAX_INSTRUCTIONS_LENGTH = 100000
_NAME_CONSTRAINTS = {"uq_agents_personal_name_ci", "uq_agents_group_name_ci", "uq_agents_global_name_ci"}


def _role(actor):
    role = getattr(actor, "role", None)
    return str(getattr(role, "value", role))


def _safe(row):
    return {"id": row.id, "name": row.name, "owner_user_id": row.owner_user_id,
            "visibility": row.visibility, "group_id": row.group_id, "runtime": row.runtime,
            "model": row.model, "reasoning_effort": row.reasoning_effort,
            "instructions": row.instructions, "mcp_ids": list(row.mcp_ids or []),
            "skill_ids": list(row.skill_ids or []),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


class AgentService:
    def __init__(self, repository):
        self.repository = repository

    async def _authorize_scope(self, actor, visibility, group_id):
        if visibility not in {"personal", "group", "global"} or ((visibility == "group") != (group_id is not None)):
            raise ValidationFailedError("errors.agent.scope_invalid")
        member_role = await self.repository.membership_role(actor.id, group_id) if group_id else None
        scoped = SimpleNamespace(id=actor.id, role=getattr(actor, "role", None),
                                 memberships={group_id: member_role} if member_role else {})
        allowed = ((visibility == "personal" and can_create_personal(scoped)) or
                   (visibility == "group" and can_create_group(scoped, group_id)) or
                   (visibility == "global" and can_create_global(scoped)))
        if not allowed:
            raise PermissionDeniedError("errors.agent.global_admin_only" if visibility == "global" else "errors.agent.scope_forbidden")

    @staticmethod
    def _validate_values(data):
        name = data.get("name")
        model = data.get("model")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME_LENGTH:
            raise ValidationFailedError("errors.agent.name_invalid")
        if not isinstance(model, str) or not model.strip() or len(model) > MAX_MODEL_LENGTH:
            raise ValidationFailedError("errors.agent.model_invalid")
        effort = data.get("reasoning_effort")
        if effort is not None and (not isinstance(effort, str) or len(effort) > MAX_REASONING_LENGTH):
            raise ValidationFailedError("errors.agent.reasoning_effort_invalid", params={"max_length": MAX_REASONING_LENGTH})
        instructions = data.get("instructions", "")
        if not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS_LENGTH:
            raise ValidationFailedError("errors.agent.instructions_invalid", params={"max_length": MAX_INSTRUCTIONS_LENGTH})
        if data.get("runtime", "opencode") != "opencode":
            raise ValidationFailedError("errors.agent.runtime_invalid")
        for field in ("mcp_ids", "skill_ids"):
            ids = data.get(field, [])
            if not isinstance(ids, list) or any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
                raise ValidationFailedError("errors.agent.reference_ids_invalid", params={"field": field})

    async def _validate_references(self, actor, data):
        for field, kind in (("mcp_ids", "mcp"), ("skill_ids", "skill")):
            for ref_id in data.get(field, []):
                if not await self.repository.visible_reference(kind, actor.id, ref_id):
                    raise ValidationFailedError("errors.agent.reference_unavailable", params={"kind": kind})

    async def create(self, actor, data):
        values = dict(data)
        values.setdefault("runtime", "opencode")
        values.setdefault("mcp_ids", [])
        values.setdefault("skill_ids", [])
        values.setdefault("instructions", "")
        self._validate_values(values)
        name = values["name"].strip()
        visibility, group_id = values.get("visibility", "personal"), values.get("group_id")
        await self._authorize_scope(actor, visibility, group_id)
        await self._validate_references(actor, values)
        if await self.repository.name_conflict(actor.id, name, visibility, group_id):
            raise ConflictError("errors.agent.name_duplicate")
        row = Agent(name=name, owner_user_id=actor.id, visibility=visibility, group_id=group_id,
                    runtime=values["runtime"], model=values["model"].strip(),
                    reasoning_effort=values.get("reasoning_effort"), instructions=values["instructions"],
                    mcp_ids=values["mcp_ids"], skill_ids=values["skill_ids"])
        try:
            return _safe(await self.repository.create(row))
        except IntegrityError as exc:
            if self._name_race(exc):
                raise ConflictError("errors.agent.name_duplicate") from None
            raise

    async def list_visible(self, user_id):
        groups = await self.repository.memberships(user_id)
        rows = await self.repository.visible_candidates(user_id, groups)
        priority = {"personal": 0, "group": 1, "global": 2}
        rows.sort(key=lambda row: (priority[row.visibility], row.name.casefold(), row.id))
        return [_safe(row) for row in rows]

    async def get_visible(self, user_id, entity_id):
        row = await self.repository.by_id(entity_id)
        if row is None:
            raise NotFoundError("errors.agent.not_found")
        if row.visibility == "personal" and row.owner_user_id == user_id or row.visibility == "global":
            return _safe(row)
        if row.visibility == "group" and row.group_id in await self.repository.memberships(user_id):
            return _safe(row)
        raise PermissionDeniedError("errors.agent.forbidden")

    async def _mutable(self, actor, entity_id):
        row = await self.repository.by_id(entity_id)
        if row is None:
            raise NotFoundError("errors.agent.not_found")
        await self.get_visible(actor.id, entity_id)
        if _role(actor) != "admin" and row.owner_user_id != actor.id:
            raise PermissionDeniedError("errors.agent.forbidden")
        return row

    async def update(self, actor, entity_id, changes):
        row = await self._mutable(actor, entity_id)
        values = dict(changes)
        visibility = values.get("visibility", row.visibility)
        group_id = values.get("group_id", row.group_id if visibility == row.visibility else None)
        await self._authorize_scope(actor, visibility, group_id)
        candidate = {"name": values.get("name", row.name), "model": values.get("model", row.model),
                     "reasoning_effort": values.get("reasoning_effort", row.reasoning_effort),
                     "instructions": values.get("instructions", row.instructions),
                     "runtime": values.get("runtime", row.runtime),
                     "mcp_ids": values.get("mcp_ids", row.mcp_ids), "skill_ids": values.get("skill_ids", row.skill_ids)}
        self._validate_values(candidate)
        await self._validate_references(actor, {key: values[key] for key in ("mcp_ids", "skill_ids") if key in values})
        name = candidate["name"].strip()
        if await self.repository.name_conflict(row.owner_user_id, name, visibility, group_id, exclude_id=row.id):
            raise ConflictError("errors.agent.name_duplicate")
        values.update(name=name, visibility=visibility, group_id=group_id)
        return _safe(await self.repository.update(row, **values))

    async def delete(self, actor, entity_id):
        await self._mutable(actor, entity_id)
        return await self.repository.delete(entity_id)

    @staticmethod
    def _name_race(exc):
        cause = exc.orig if exc.orig is not None else exc
        return any(name in str(cause) for name in _NAME_CONSTRAINTS)
