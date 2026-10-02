from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity.models import Group, GroupMembership, Session, User


class IdentityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_username(self, username):
        return await self.db.scalar(select(User).where(User.username == username))

    async def get_user(self, user_id):
        return await self.db.get(User, user_id)

    async def groups_with_membership_roles(self, user_id):
        result = await self.db.execute(select(Group.id, Group.name, GroupMembership.role).join(
            GroupMembership, GroupMembership.group_id == Group.id
        ).where(GroupMembership.user_id == user_id))
        return [{"id": group_id, "name": name, "role": getattr(role, "value", role)}
                for group_id, name, role in result.all()]

    async def add_user(self, user):
        self.db.add(user)
        await self.db.flush()
        return user

    async def add_session(self, session):
        self.db.add(session)
        await self.db.flush()

    async def get_session_by_hash(self, token_hash):
        return await self.db.scalar(select(Session).where(Session.refresh_hash == token_hash).with_for_update())

    async def save_session(self, session):
        await self.db.flush()

    async def revoke_family(self, family_id):
        await self.db.execute(update(Session).where(Session.family_id == family_id, Session.revoked_at.is_(None)).values(revoked_at=func.now()))
        # Reuse detection raises an auth error immediately afterwards; persist
        # revocation independently so request teardown cannot roll it back.
        await self.db.commit()
