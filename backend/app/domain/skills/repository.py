from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity.models import GroupMembership
from app.domain.skills.models import Skill


class SkillRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_id(self, entity_id: str) -> Skill | None:
        return await self.db.get(Skill, entity_id)

    async def memberships(self, user_id: str) -> list[str]:
        return list((await self.db.scalars(select(GroupMembership.group_id).where(GroupMembership.user_id == user_id))).all())

    async def membership_role(self, user_id: str, group_id: str) -> str | None:
        role = await self.db.scalar(select(GroupMembership.role).where(
            GroupMembership.user_id == user_id, GroupMembership.group_id == group_id))
        return getattr(role, "value", role)

    async def visible_candidates(self, user_id: str, group_ids: list[str]) -> list[Skill]:
        clauses = [and_(Skill.visibility == "personal", Skill.owner_user_id == user_id), Skill.visibility == "global"]
        if group_ids:
            clauses.append(and_(Skill.visibility == "group", Skill.group_id.in_(group_ids)))
        return list((await self.db.scalars(select(Skill).where(or_(*clauses)))).all())

    async def name_conflict(self, owner_user_id: str, name: str, visibility: str, group_id: str | None,
                            *, exclude_id: str | None = None) -> bool:
        query = select(Skill.id).where(Skill.visibility == visibility, func.lower(Skill.name) == func.lower(literal(name)))
        query = query.where(Skill.owner_user_id == owner_user_id)
        if visibility == "group": query = query.where(Skill.group_id == group_id)
        if exclude_id: query = query.where(Skill.id != exclude_id)
        return await self.db.scalar(query.limit(1)) is not None

    async def _commit(self):
        try: await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    @staticmethod
    def _validate(row: Skill) -> None:
        row.name = row.name.strip()
        if not 1 <= len(row.name) <= 80 or row.visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid skill name or visibility")
        if (row.visibility == "group") != (row.group_id is not None):
            raise ValueError("Invalid skill group scope")
        if len(row.description) > 2000 or len(row.instructions) > 100000:
            raise ValueError("Skill content exceeds its length limit")

    async def create(self, row: Skill) -> Skill:
        self._validate(row); self.db.add(row); await self._commit(); await self.db.refresh(row); return row

    async def update(self, row: Skill, **changes) -> Skill:
        if "name" in changes: changes["name"] = changes["name"].strip()
        for key, value in changes.items(): setattr(row, key, value)
        self._validate(row)
        await self._commit(); await self.db.refresh(row); return row

    async def delete(self, entity_id: str) -> bool:
        row = await self.by_id(entity_id)
        if row is None: return False
        await self.db.delete(row)
        await self._commit()
        return True
