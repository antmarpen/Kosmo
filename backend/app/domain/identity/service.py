import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import ACCESS_TOKEN_SECONDS, create_access_token, hash_refresh_token, hash_password, verify_password
from app.domain.identity.models import Session
from shared.errors import AuthError


class IdentityService:
    def __init__(self, repository, password_verify=verify_password, password_hash=hash_password, token_secret: str = ""):
        self.repository = repository
        self.password_verify = password_verify
        self.password_hash = password_hash
        self.token_secret = token_secret

    def _pair(self, user, session):
        raw = secrets.token_urlsafe(48)
        session.refresh_hash = hash_refresh_token(raw)
        session.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        return {"access_token": create_access_token(user.id if hasattr(user, "id") else user["id"], user.role.value if hasattr(getattr(user, "role", None), "value") else (user.role if hasattr(user, "role") else user["role"]), self.token_secret), "refresh_token": raw, "token_type": "bearer", "expires_in": ACCESS_TOKEN_SECONDS}

    async def login(self, username, password):
        user = await self.repository.get_user_by_username(username)
        if user is None or not self.password_verify(password, user.password_hash if hasattr(user, "password_hash") else user["password_hash"]):
            raise AuthError("errors.auth.invalid_credentials")
        session = Session(id=str(uuid.uuid4()), user_id=user.id if hasattr(user, "id") else user["id"], refresh_hash="", family_id=str(uuid.uuid4()), expires_at=datetime.now(timezone.utc))
        await self.repository.add_session(session)
        return self._pair(user, session)

    def decode_access_token(self, token):
        from app.core.security import decode_access_token
        claims = decode_access_token(token, self.token_secret)
        return claims["sub"], claims["role"]

    async def refresh(self, token):
        session = await self.repository.get_session_by_hash(hash_refresh_token(token))
        if not session or session.revoked_at or session.expires_at <= datetime.now(timezone.utc):
            if session:
                await self.repository.revoke_family(session.family_id)
            raise AuthError("errors.auth.invalid_refresh_token")
        user = await self.repository.get_user(session.user_id)
        session.revoked_at = datetime.now(timezone.utc)
        await self.repository.save_session(session)
        replacement = Session(id=str(uuid.uuid4()), user_id=session.user_id, refresh_hash="", family_id=session.family_id, expires_at=session.expires_at)
        await self.repository.add_session(replacement)
        return self._pair(user, replacement)

    async def logout(self, user_id, token):
        session = await self.repository.get_session_by_hash(hash_refresh_token(token))
        if session and session.user_id == user_id:
            await self.repository.revoke_family(session.family_id)
