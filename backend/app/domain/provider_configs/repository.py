from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.provider_configs.models import ProviderCandidateOperation, ProviderConfig


class ProviderConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: str, provider: str):
        return await self.db.scalar(select(ProviderConfig).where(
            ProviderConfig.user_id == user_id, ProviderConfig.provider == provider,
        ))

    async def get_scoped(self, owner_id: str | None, provider: str, visibility: str, group_id: str | None = None):
        return await self.db.scalar(select(ProviderConfig).where(
            ProviderConfig.user_id == owner_id, ProviderConfig.provider == provider,
            ProviderConfig.visibility == visibility, ProviderConfig.group_id == group_id,
        ))

    async def get_scope(self, owner_id: str, provider: str, visibility: str, group_id: str | None = None):
        query = select(ProviderConfig).where(
            ProviderConfig.provider == provider, ProviderConfig.visibility == visibility,
        )
        if visibility == "personal":
            query = query.where(ProviderConfig.user_id == owner_id)
        elif visibility == "group":
            query = query.where(ProviderConfig.group_id == group_id)
        return await self.db.scalar(query)

    async def candidates(self, user_id: str, provider: str, group_ids: list[str]):
        conditions = [(ProviderConfig.visibility == "personal", ProviderConfig.user_id == user_id),
                      (ProviderConfig.visibility == "global",)]
        from sqlalchemy import and_, or_
        filters = [and_(*condition) for condition in conditions]
        if group_ids:
            filters.append(and_(ProviderConfig.visibility == "group", ProviderConfig.group_id.in_(group_ids)))
        return list((await self.db.scalars(select(ProviderConfig).where(
            ProviderConfig.provider == provider, or_(*filters)
        ))).all())

    async def memberships(self, user_id: str) -> list[str]:
        from app.domain.identity.models import GroupMembership
        return list((await self.db.scalars(select(GroupMembership.group_id).where(
            GroupMembership.user_id == user_id
        ))).all())

    async def is_member(self, user_id: str, group_id: str) -> bool:
        return group_id in await self.memberships(user_id)

    async def membership_role(self, user_id: str, group_id: str) -> str | None:
        from app.domain.identity.models import GroupMembership
        role = await self.db.scalar(select(GroupMembership.role).where(
            GroupMembership.user_id == user_id, GroupMembership.group_id == group_id
        ))
        return getattr(role, "value", role)

    async def visible(self, user_id: str, provider: str, group_ids: list[str]):
        return await self.candidates(user_id, provider, group_ids)

    async def by_id(self, config_id: str):
        return await self.db.get(ProviderConfig, config_id)

    async def delete_scoped(self, config_id: str) -> bool:
        row = await self.by_id(config_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def save(self, user_id: str, provider: str, config_ciphertext: str, auth_ciphertext: str | None,
                   visibility: str = "personal", group_id: str | None = None,
                   verification_status: str = "unverified", *, display_name: str):
        row = await self.get_scoped(user_id, provider, visibility, group_id)
        if row is None:
            row = ProviderConfig(user_id=user_id, provider=provider, visibility=visibility, group_id=group_id,
                                 config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                                 verification_status=verification_status, display_name=display_name)
            self.db.add(row)
        else:
            row.config_ciphertext = config_ciphertext
            row.auth_ciphertext = auth_ciphertext
            row.verification_status = verification_status
            # Replacing a scoped configuration also replaces its display name.
            row.display_name = display_name
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def set_verification_status(self, config_id: str, status: str):
        row = await self.by_id(config_id)
        if row is not None:
            row.verification_status = status
            await self.db.commit()

    async def delete(self, user_id: str, provider: str) -> bool:
        row = await self.get(user_id, provider)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def create_candidate_operation(self, user_id: str, provider: str,
                                         payload_ciphertext: str, expires_at):
        row = ProviderCandidateOperation(user_id=user_id, provider=provider,
                                         payload_ciphertext=payload_ciphertext, expires_at=expires_at)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get_candidate_operation(self, operation_id: str):
        return await self.db.get(ProviderCandidateOperation, operation_id)

    async def delete_candidate_operation(self, operation_id: str) -> bool:
        row = await self.get_candidate_operation(operation_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def purge_expired_candidate_operations(self) -> int:
        result = await self.db.execute(
            delete(ProviderCandidateOperation).where(
                ProviderCandidateOperation.expires_at <= func.now(),
            )
        )
        await self.db.commit()
        return result.rowcount
