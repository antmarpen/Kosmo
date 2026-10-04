from cryptography.fernet import Fernet
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.identity.models import GroupMembership
from app.domain.mcp_servers.models import McpServer


class McpServerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def encrypt_secrets(secrets: dict[str, str]) -> dict[str, str]:
        if not secrets:
            return {}
        if not settings.config_encryption_key:
            raise RuntimeError("MCP encryption key is not configured")
        cipher = Fernet(settings.config_encryption_key.encode())
        return {key: cipher.encrypt(value.encode()).decode() for key, value in secrets.items()}

    async def by_id(self, entity_id: str) -> McpServer | None:
        return await self.db.get(McpServer, entity_id)

    async def memberships(self, user_id: str) -> list[str]:
        return list((await self.db.scalars(select(GroupMembership.group_id).where(GroupMembership.user_id == user_id))).all())

    async def membership_role(self, user_id: str, group_id: str) -> str | None:
        role = await self.db.scalar(select(GroupMembership.role).where(
            GroupMembership.user_id == user_id, GroupMembership.group_id == group_id))
        return getattr(role, "value", role)

    async def visible_candidates(self, user_id: str, group_ids: list[str]) -> list[McpServer]:
        clauses = [and_(McpServer.visibility == "personal", McpServer.owner_user_id == user_id), McpServer.visibility == "global"]
        if group_ids: clauses.append(and_(McpServer.visibility == "group", McpServer.group_id.in_(group_ids)))
        return list((await self.db.scalars(select(McpServer).where(or_(*clauses)))).all())

    async def name_conflict(self, owner_user_id: str, name: str, visibility: str, group_id: str | None,
                            *, exclude_id: str | None = None) -> bool:
        query = select(McpServer.id).where(McpServer.visibility == visibility,
                                           func.lower(McpServer.name) == func.lower(literal(name)))
        query = query.where(McpServer.owner_user_id == owner_user_id)
        if visibility == "group": query = query.where(McpServer.group_id == group_id)
        if exclude_id: query = query.where(McpServer.id != exclude_id)
        return await self.db.scalar(query.limit(1)) is not None

    async def _commit(self):
        try: await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    @staticmethod
    def _validate(row: McpServer) -> None:
        row.name = row.name.strip()
        if not 1 <= len(row.name) <= 80 or row.visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid MCP server name or visibility")
        if (row.visibility == "group") != (row.group_id is not None):
            raise ValueError("Invalid MCP server group scope")
        if row.transport_type not in {"stdio", "http"}:
            raise ValueError("Invalid MCP transport")

    async def create(self, row: McpServer, *, secret_values: dict[str, str] | None = None) -> McpServer:
        self._validate(row)
        row.secret_ciphertext = self.encrypt_secrets(secret_values or {})
        self.db.add(row)
        await self._commit()
        await self.db.refresh(row)
        return row

    async def update(self, row: McpServer, *, secret_values: dict[str, str] | None = None,
                     retained_ciphertext: dict[str, str] | None = None, **changes) -> McpServer:
        if "name" in changes: changes["name"] = changes["name"].strip()
        if secret_values is not None:
            changes["secret_ciphertext"] = {**(retained_ciphertext or {}), **self.encrypt_secrets(secret_values)}
        for key, value in changes.items(): setattr(row, key, value)
        self._validate(row)
        await self._commit()
        await self.db.refresh(row)
        return row

    async def delete(self, entity_id: str) -> bool:
        row = await self.by_id(entity_id)
        if row is None: return False
        await self.db.delete(row)
        await self._commit()
        return True
