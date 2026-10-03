import jwt
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.core.config import settings
from app.core.db import get_db
from app.main import create_app
from app.domain.tasks.models import NodeExecution, Task


class ValidatorDb:
    def __init__(self):
        levels = [{"name": f"level-{i}", "message_key": f"validation.level_{i}", "params_schema": {}} for i in range(1, 4)]
        self.task = SimpleNamespace(id="task-1", created_by="owner-1", resolved_definition={"nodes": [
            {"type": "ai", "id": "ai-1", "outputs": ["summary.md", "notes"], "output_validation": {
                "summary.md": {"levels": levels},
                "notes": {"levels": [{**levels[0]}, {**levels[1]}, {**levels[2], "params_schema": {"required_terms": ["secret"]}}]},
            }},
        ]})
        self.node_execution = SimpleNamespace(id="execution-1", task_id="task-1", node_id="ai-1", state="running")

    async def get(self, model, identity):
        if model is Task:
            return self.task if identity == self.task.id else None
        if model is NodeExecution:
            return self.node_execution if identity == self.node_execution.id else None
        return None


def scoped_token(task_id="task-1", node_id="ai-1", execution_id="execution-1"):
    return jwt.encode({
        "iss": "kosmo-agent-validator", "aud": "kosmo-validator", "purpose": "agent-validator",
        "scope": "validator:candidate", "task_id": task_id, "node_id": node_id,
        "node_execution_id": execution_id,
    }, settings.jwt_secret, algorithm="HS256")


def test_scoped_validator_accepts_unpersisted_candidate_content(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-signing-secret-32-bytes")
    async def probe(*args): return []
    monkeypatch.setattr("app.api.routes.mcp._validation_probe", probe)
    token = scoped_token()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: ValidatorDb()
    client = TestClient(app)
    response = client.post("/mcp/validator", headers={"Authorization": f"Bearer {token}"}, json={
        "task_id": "task-1", "node_id": "ai-1", "node_execution_id": "execution-1",
        "level": 1, "logical_name": "summary.md", "media_type": "text/markdown",
        "content": "Draft candidate",
    })
    assert response.status_code == 200
    assert response.json() == {"errors": []}
    client.close()


def test_scoped_validator_selects_contract_by_logical_output(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-signing-secret-32-bytes")
    async def probe(content, contract, level, logical_name):
        assert logical_name == "notes" and contract["levels"][2]["params_schema"]["required_terms"] == ["secret"]
        return [{"artifact": logical_name, "level": "rules", "message_key": "validation.rules",
                 "params": {"reason": "required_terms_missing"}}]
    monkeypatch.setattr("app.api.routes.mcp._validation_probe", probe)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: ValidatorDb()
    client = TestClient(app)
    response = client.post("/mcp/validator", headers={"Authorization": f"Bearer {scoped_token()}"}, json={
        "task_id": "task-1", "node_id": "ai-1", "node_execution_id": "execution-1",
        "level": 3, "logical_name": "notes", "media_type": "text/plain", "content": "ordinary words",
    })
    assert response.status_code == 200
    assert response.json()["errors"][0]["params"]["reason"] == "required_terms_missing"
    client.close()


def test_scoped_validator_rejects_cross_task_candidate_access(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-signing-secret-32-bytes")
    token = scoped_token(task_id="task-1")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: ValidatorDb()
    client = TestClient(app)
    response = client.post("/mcp/validator", headers={"Authorization": f"Bearer {token}"}, json={
        "task_id": "task-other", "node_id": "ai-1", "node_execution_id": "execution-1",
        "level": 1, "logical_name": "summary.md", "media_type": "text/markdown", "content": "draft",
    })
    assert response.status_code == 403
    assert response.json() == {"code": "PERMISSION_DENIED", "message_key": "errors.permission.denied", "params": {}, "details": []}
    client.close()


def test_validator_endpoint_exposes_an_mcp_tool_call_surface(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-signing-secret-32-bytes")
    token = scoped_token()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: ValidatorDb()
    client = TestClient(app)
    response = client.post("/mcp/validator", headers={"Authorization": f"Bearer {token}"}, json={
        "jsonrpc": "2.0", "id": 9, "method": "tools/list",
    })
    assert response.status_code == 200
    assert response.json()["result"]["tools"][0]["name"] == "validate_candidate"
    client.close()


def test_validator_without_auth_returns_keyed_error_envelope(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-signing-secret-32-bytes")
    response = TestClient(create_app()).post("/mcp/validator", json={})
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_ERROR", "message_key": "errors.auth.unauthorized", "params": {}, "details": []}
