from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.agents.repository import AgentRepository
from app.domain.agents.service import AgentService
from shared.errors import ValidationFailedError

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentResponse(BaseModel):
    id: str
    name: str
    owner_user_id: str
    visibility: str
    group_id: str | None
    runtime: str
    model: str
    reasoning_effort: str | None
    instructions: str
    mcp_ids: list[str]
    skill_ids: list[str]
    updated_at: str | None


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(AgentRepository(db))


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    visibility: str = Field(default="personal", pattern="^(personal|group|global)$")
    group_id: str | None = Field(default=None, max_length=36)
    runtime: str = Field(default="opencode", pattern="^opencode$")
    model: str = Field(min_length=1, max_length=300)
    reasoning_effort: str | None = Field(default=None, max_length=80)
    instructions: str = Field(default="", max_length=100000)
    mcp_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    visibility: str | None = Field(default=None, pattern="^(personal|group|global)$")
    group_id: str | None = Field(default=None, max_length=36)
    runtime: str | None = Field(default=None, pattern="^opencode$")
    model: str | None = Field(default=None, min_length=1, max_length=300)
    reasoning_effort: str | None = Field(default=None, max_length=80)
    instructions: str | None = Field(default=None, max_length=100000)
    mcp_ids: list[str] | None = None
    skill_ids: list[str] | None = None


def _patch_values(body: AgentPatch) -> dict:
    values = body.model_dump(exclude_unset=True)
    for field in ("name", "visibility", "runtime", "model", "instructions", "mcp_ids", "skill_ids"):
        if field in values and values[field] is None:
            raise ValidationFailedError("errors.agent.field_required")
    return values


@router.get("", response_model=list[AgentResponse])
async def list_agents(user=Depends(get_current_user), service: AgentService = Depends(get_agent_service)):
    return await service.list_visible(user.id)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, user=Depends(get_current_user), service: AgentService = Depends(get_agent_service)):
    return await service.get_visible(user.id, agent_id)


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(body: AgentCreate, user=Depends(get_current_user), service: AgentService = Depends(get_agent_service)):
    return await service.create(user, body.model_dump(exclude_none=True))


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, body: AgentPatch, user=Depends(get_current_user), service: AgentService = Depends(get_agent_service)):
    return await service.update(user, agent_id, _patch_values(body))


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user=Depends(get_current_user), service: AgentService = Depends(get_agent_service)):
    await service.delete(user, agent_id)
