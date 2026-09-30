from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.domain.identity.repository import IdentityRepository
from app.domain.identity.schemas import Credentials, RefreshRequest, UserResponse
from app.domain.identity.service import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])


def service(db: AsyncSession) -> IdentityService:
    return IdentityService(IdentityRepository(db), token_secret=settings.jwt_secret)


@router.post("/login")
async def login(payload: Credentials, db: AsyncSession = Depends(get_db)):
    return await service(db).login(payload.username, payload.password)


@router.post("/refresh")
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await service(db).refresh(payload.refresh_token)


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service(db).logout(user.id, payload.refresh_token)
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
async def me(user=Depends(get_current_user)):
    return UserResponse(id=user.id, username=user.username, role=user.role.value)
