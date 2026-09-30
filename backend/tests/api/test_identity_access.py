import asyncio
from types import SimpleNamespace

import pytest

from app.api.deps import require_roles
from app.api.deps import get_current_user
from app.main import create_app
from shared.errors import PermissionDeniedError
from fastapi.testclient import TestClient


def test_runner_role_dependency_rejects_viewer():
    dependency = require_roles("runner")
    viewer = SimpleNamespace(role=SimpleNamespace(value="viewer"))

    async def act():
        with pytest.raises(PermissionDeniedError):
            await dependency(viewer)

    asyncio.run(act())


def test_me_requires_a_valid_bearer_user():
    client = TestClient(create_app())
    assert client.get("/auth/me").status_code == 401
    client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="u1", username="alice", role=SimpleNamespace(value="runner")
    )
    response = client.get("/auth/me", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json() == {"id": "u1", "username": "alice", "role": "runner"}
