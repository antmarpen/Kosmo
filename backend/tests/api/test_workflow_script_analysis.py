from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import create_app
from app.domain.identity.models import UserRole


def client_for(role=None):
    app = create_app()
    if role is not None:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id="user-1", username="user", password_hash="x", role=role
        )
    return TestClient(app)


def test_script_analysis_returns_outputs_without_persisting_source():
    client = client_for(UserRole.builder)
    source = "size = 1\ndistance = 2\nreturn size, distance"
    response = client.post("/workflows/script-analysis", json={"code": source, "inputs": ["topic"]})
    assert response.status_code == 200
    assert response.json() == {"outputs": ["size", "distance"], "issues": []}


def test_script_analysis_returns_keyed_issues_for_authored_errors():
    response = client_for(UserRole.builder).post(
        "/workflows/script-analysis", json={"code": "return value + 1", "inputs": []}
    )
    assert response.status_code == 200
    assert response.json()["issues"][0]["message_key"].startswith("errors.script_contract.")


def test_script_analysis_requires_authentication_and_builder_role():
    assert client_for().post("/workflows/script-analysis", json={"code": "pass", "inputs": []}).status_code == 401
    assert client_for(UserRole.runner).post(
        "/workflows/script-analysis", json={"code": "pass", "inputs": []}
    ).status_code == 403


@pytest.mark.parametrize("payload", [
    {"code": "x" * 100001, "inputs": []},
    {"code": "pass", "inputs": [str(index) for index in range(65)]},
])
def test_script_analysis_rejects_oversized_requests(payload):
    assert client_for(UserRole.builder).post("/workflows/script-analysis", json=payload).status_code == 422
