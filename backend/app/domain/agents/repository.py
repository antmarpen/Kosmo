from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agents.models import Agent
from app.domain.identity.models import GroupMembership
from app.domain.mcp_servers.models import McpServer
from app.domain.skills.models import Skill


class AgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_id(self, entity_id: str) -> Agent | None:
        return await self.db.get(Agent, entity_id)

    async def memberships(self, user_id: str) -> list[str]:
        return list((await self.db.scalars(select(GroupMembership.group_id).where(GroupMembership.user_id == user_id))).all())

    async def visible_reference(self, kind: str, user_id: str, reference_id: str) -> bool:
        model = {"mcp": McpServer, "skill": Skill}.get(kind)
        if model is None:
            return False
        row = await self.db.get(model, reference_id)
        if row is None or row.visibility == "personal" and row.owner_user_id != user_id:
            return False
        if row.visibility == "group":
            groups = await self.memberships(user_id)
            return row.group_id in groups
        return row.visibility == "global" or row.visibility == "personal"

    async def visible_candidates(self, user_id: str, group_ids: list[str]) -> list[Agent]:
        clauses = [and_(Agent.visibility == "personal", Agent.owner_user_id == user_id), Agent.visibility == "global"]
        if group_ids:
            clauses.append(and_(Agent.visibility == "group", Agent.group_id.in_(group_ids)))
        return list((await self.db.scalars(select(Agent).where(or_(*clauses)))).all())

    async def name_conflict(self, owner_user_id: str, name: str, visibility: str, group_id: str | None,
                            *, exclude_id: str | None = None) -> bool:
        query = select(Agent.id).where(Agent.visibility == visibility, func.lower(Agent.name) == func.lower(literal(name)))
        query = query.where(Agent.owner_user_id == owner_user_id)
        query = query.where(Agent.group_id == group_id) if visibility == "group" else query
        if exclude_id:
            query = query.where(Agent.id != exclude_id)
        return await self.db.scalar(query.limit(1)) is not None

    async def _commit(self):
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    @staticmethod
    def _validate(row: Agent) -> None:
        row.name = row.name.strip()
        if not 1 <= len(row.name) <= 80:
            raise ValueError("Agent name must contain 1 to 80 characters")
        if row.visibility not in {"personal", "group", "global"} or ((row.visibility == "group") != (row.group_id is not None)):
            raise ValueError("Invalid agent scope")
        if row.runtime != "opencode" or not row.model:
            raise ValueError("Agent runtime and model are required")
        if len(set(row.mcp_ids or [])) != len(row.mcp_ids or []) or len(set(row.skill_ids or [])) != len(row.skill_ids or []):
            raise ValueError("Agent reference IDs must be unique")

    async def create(self, row: Agent) -> Agent:
        self._validate(row)
        self.db.add(row)
        await self._commit()
        await self.db.refresh(row)
        return row

    async def update(self, row: Agent, **changes) -> Agent:
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        for key, value in changes.items():
            setattr(row, key, value)
        self._validate(row)
        await self._commit()
        await self.db.refresh(row)
        return row

    async def delete(self, entity_id: str) -> bool:
        row = await self.by_id(entity_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self._commit()
        return True
