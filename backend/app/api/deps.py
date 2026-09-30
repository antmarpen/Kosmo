from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.domain.identity.models import User
from app.domain.identity.repository import IdentityRepository
from app.domain.identity.service import IdentityService
from shared.errors import AuthError, PermissionDeniedError

bearer = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)):
    if not credentials or not settings.jwt_secret:
        raise AuthError("errors.auth.invalid_token")
    try:
        claims = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user = await IdentityRepository(db).get_user(claims["sub"])
    except (jwt.PyJWTError, KeyError):
        raise AuthError("errors.auth.invalid_token") from None
    if user is None or user.role.value != claims.get("role"):
        raise AuthError("errors.auth.invalid_token")
    return user


def require_roles(*roles: str) -> Callable:
    async def dependency(user=Depends(get_current_user)):
        if user.role.value not in roles:
            raise PermissionDeniedError("errors.auth.forbidden")
        return user
    return dependency
