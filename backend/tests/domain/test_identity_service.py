import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.identity.service import IdentityService
from shared.errors import AuthError


class FakeRepository:
    def __init__(self):
        self.users = {"alice": {"id": "u1", "username": "alice", "password_hash": "hashed", "role": "runner"}}
        self.sessions = {}

    async def get_user_by_username(self, username):
        return self.users.get(username)

    async def get_user(self, user_id):
        return next((user for user in self.users.values() if user["id"] == user_id), None)

    async def add_session(self, session):
        self.sessions[session.id] = session

    async def get_session_by_hash(self, token_hash):
        return next((s for s in self.sessions.values() if s.refresh_hash == token_hash), None)

    async def save_session(self, session):
        self.sessions[session.id] = session

    async def revoke_family(self, family_id):
        for session in self.sessions.values():
            if session.family_id == family_id:
                session.revoked_at = datetime.now(timezone.utc)


def make_service(repo):
    return IdentityService(repo, password_verify=lambda password, hashed: password == "correct", password_hash=lambda _: "hashed", token_secret="test-secret-long-enough-for-hs256-32bytes")


def test_login_issues_tokens():
    result = asyncio.run(make_service(FakeRepository()).login("alice", "correct"))
    assert result["token_type"] == "bearer"
    assert result["expires_in"] == 900
    assert result["access_token"] and result["refresh_token"]


def test_login_wrong_password_has_localizable_auth_error():
    async def act():
        with pytest.raises(AuthError) as error:
            await make_service(FakeRepository()).login("alice", "wrong")
        assert error.value.message_key == "errors.auth.invalid_credentials"
    asyncio.run(act())


def test_refresh_rotates_and_reuse_revokes_family():
    async def act():
        service = make_service(FakeRepository())
        first = await service.login("alice", "correct")
        second = await service.refresh(first["refresh_token"])
        with pytest.raises(AuthError):
            await service.refresh(first["refresh_token"])
        with pytest.raises(AuthError):
            await service.refresh(second["refresh_token"])
    asyncio.run(act())


def test_logout_revokes_family():
    async def act():
        service = make_service(FakeRepository())
        tokens = await service.login("alice", "correct")
        user, _ = service.decode_access_token(tokens["access_token"])
        await service.logout(user, tokens["refresh_token"])
        with pytest.raises(AuthError):
            await service.refresh(tokens["refresh_token"])
    asyncio.run(act())
