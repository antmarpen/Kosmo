from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.skills.repository import SkillRepository
from app.domain.skills.service import SkillService
from shared.errors import ValidationFailedError

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillResponse(BaseModel):
    id: str
    name: str
    owner_user_id: str
    visibility: str
    group_id: str | None
    description: str
    instructions: str
    updated_at: str | None


def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(SkillRepository(db))


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    visibility: str = Field(default="personal", pattern="^(personal|group|global)$")
    group_id: str | None = Field(default=None, max_length=36)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=100000)


class SkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    visibility: str | None = Field(default=None, pattern="^(personal|group|global)$")
    group_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=100000)


def _patch_values(body: SkillPatch) -> dict:
    values = body.model_dump(exclude_unset=True)
    for field in ("name", "visibility", "description", "instructions"):
        if field in values and values[field] is None:
            raise ValidationFailedError("errors.skill.field_required")
    return values


@router.get("", response_model=list[SkillResponse])
async def list_skills(user=Depends(get_current_user), service: SkillService = Depends(get_skill_service)):
    return await service.list_visible(user.id)


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, user=Depends(get_current_user), service: SkillService = Depends(get_skill_service)):
    return await service.get_visible(user.id, skill_id)


@router.post("", status_code=201, response_model=SkillResponse)
async def create_skill(body: SkillCreate, user=Depends(get_current_user), service: SkillService = Depends(get_skill_service)):
    return await service.create(user, body.model_dump())


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: str, body: SkillPatch, user=Depends(get_current_user), service: SkillService = Depends(get_skill_service)):
    return await service.update(user, skill_id, _patch_values(body))


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, user=Depends(get_current_user), service: SkillService = Depends(get_skill_service)):
    await service.delete(user, skill_id)
