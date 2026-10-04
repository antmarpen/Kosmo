"""Live, consumer-authorized agent catalog resolution for worker-local use."""

from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.agents.models import Agent
from app.domain.identity.models import GroupMembership
from app.domain.mcp_servers.models import McpServer
from app.domain.skills.models import Skill
from shared.errors import KosmoError


def apply_reference_deltas(agent_ids, added_ids=(), removed_ids=()):
    removed = set(removed_ids or ())
    result = []
    seen = set()
    for entity_id in (*list(agent_ids or ()), *list(added_ids or ())):
        if entity_id not in seen and entity_id not in removed:
            result.append(entity_id)
            seen.add(entity_id)
    return result


@dataclass(frozen=True)
class EffectiveAgent:
    id: str
    runtime: str
    model: str
    reasoning_effort: str | None
    instructions: str


@dataclass(frozen=True)
class EffectiveMcp:
    id: str
    name: str
    transport: dict
    # Excluded from repr by design; runtime config must remain worker-local.
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    env: tuple[tuple[str, str], ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class EffectiveSkill:
    id: str
    name: str
    description: str
    instructions: str


@dataclass(frozen=True)
class EffectiveCatalog:
    agent: EffectiveAgent
    mcps: tuple[EffectiveMcp, ...]
    skills: tuple[EffectiveSkill, ...]

    def to_safe_dict(self):
        return {"agent": {"id": self.agent.id, "runtime": self.agent.runtime, "model": self.agent.model,
                          "reasoning_effort": self.agent.reasoning_effort, "instructions": self.agent.instructions},
                "mcps": [{"id": mcp.id, "name": mcp.name, "transport": mcp.transport} for mcp in self.mcps],
                "skills": [{"id": skill.id, "name": skill.name, "description": skill.description,
                            "instructions": skill.instructions} for skill in self.skills]}


def _value(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _blocked(kind, entity_id):
    return KosmoError("errors.catalog.reference_unavailable", {"kind": kind, "id": entity_id},
                      code="CATALOG_REFERENCE_UNAVAILABLE", http_status=409)


class SqlCatalogResolutionRepository:
    """Minimal query boundary; permissions and secret reads are separate operations."""
    def __init__(self, db: AsyncSession): self.db = db
    async def memberships(self, user_id):
        return list((await self.db.scalars(select(GroupMembership.group_id).where(GroupMembership.user_id == user_id))).all())
    async def agent_by_id(self, entity_id): return await self.db.get(Agent, entity_id)
    async def mcp_by_id(self, entity_id): return await self.db.get(McpServer, entity_id)
    async def skill_by_id(self, entity_id): return await self.db.get(Skill, entity_id)
    @staticmethod
    def decrypt(ciphertext):
        if not ciphertext: return {}
        if not settings.config_encryption_key: raise ValueError("encryption unavailable")
        cipher = Fernet(settings.config_encryption_key.encode())
        return {name: cipher.decrypt(value.encode()).decode() for name, value in ciphertext.items()}


class AgentCatalogResolver:
    def __init__(self, repository): self.repository = repository

    @staticmethod
    def _visible(row, user_id, groups):
        visibility = _value(row, "visibility")
        return ((visibility == "personal" and _value(row, "owner_user_id") == user_id)
                or visibility == "global"
                or (visibility == "group" and _value(row, "group_id") in groups))

    async def resolve(self, *, created_by: str, node: dict) -> EffectiveCatalog:
        groups = set(await self.repository.memberships(created_by))
        agent_id = node.get("agent_id")
        agent = await self.repository.agent_by_id(agent_id) if agent_id else None
        if agent is None or not self._visible(agent, created_by, groups): raise _blocked("agent", agent_id)
        mcp_ids = apply_reference_deltas(_value(agent, "mcp_ids", []), node.get("added_mcp_ids", []), node.get("removed_mcp_ids", []))
        skill_ids = apply_reference_deltas(_value(agent, "skill_ids", []), node.get("added_skill_ids", []), node.get("removed_skill_ids", []))
        mcps = []
        for entity_id in mcp_ids:
            row = await self.repository.mcp_by_id(entity_id)
            if row is None or not self._visible(row, created_by, groups): raise _blocked("mcp", entity_id)
            config = _value(row, "safe_config", {})
            secret = _value(row, "secret_ciphertext", {})
            try:
                decrypted = self.repository.decrypt(secret)
            except Exception:
                raise KosmoError("errors.mcp_server.encryption_unavailable", {"kind":"mcp", "id":entity_id},
                                 code="CATALOG_DECRYPTION_UNAVAILABLE", http_status=409) from None
            coll = "headers" if _value(row, "transport_type", config.get("type")) == "http" else "env"
            entries = tuple((item["name"], decrypted[item["name"]] if item.get("secret") else item.get("value", ""))
                            for item in config.get(coll, []))
            mcps.append(EffectiveMcp(_value(row,"id"), _value(row,"name"), config,
                                     headers=entries if coll == "headers" else (), env=entries if coll == "env" else ()))
        skills = []
        for entity_id in skill_ids:
            row = await self.repository.skill_by_id(entity_id)
            if row is None or not self._visible(row, created_by, groups): raise _blocked("skill", entity_id)
            skills.append(EffectiveSkill(_value(row,"id"), _value(row,"name"), _value(row,"description", ""), _value(row,"instructions", "")))
        effective_agent = EffectiveAgent(_value(agent,"id"), _value(agent,"runtime"), _value(agent,"model"),
                                         _value(agent,"reasoning_effort"), _value(agent,"instructions", ""))
        return EffectiveCatalog(effective_agent, tuple(mcps), tuple(skills))
