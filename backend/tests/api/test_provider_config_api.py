from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.provider_configs import get_provider_config_service, get_provider_handler
from app.main import create_app
from app.domain.provider_configs.service import ProviderConfigService


class MemoryRepository:
    def __init__(self):
        self.rows = []

    async def get(self, user_id, provider):
        return next((row for row in self.rows if row.user_id == user_id and row.provider == provider
                     and row.visibility == "personal"), None)

    async def save(self, user_id, provider, config_ciphertext, auth_ciphertext, visibility="personal", group_id=None):
        from types import SimpleNamespace
        row = SimpleNamespace(id=user_id + provider + str(group_id), user_id=user_id, provider=provider,
                                   visibility=visibility, group_id=group_id,
                                   config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                                   updated_at=None)
        self.rows = [item for item in self.rows if not (item.user_id == user_id and item.provider == provider
                     and item.visibility == visibility and item.group_id == group_id)] + [row]
        return row

    async def delete(self, user_id, provider):
        if await self.get(user_id, provider) is None:
            return False
        self.rows.remove(await self.get(user_id, provider))
        return True

    async def candidates(self, user_id, provider, group_ids):
        return [r for r in self.rows if r.provider == provider and
                ((r.visibility == "personal" and r.user_id == user_id) or r.visibility == "global" or
                 (r.visibility == "group" and r.group_id in group_ids))]

    async def get_scoped(self, user_id, provider, visibility, group_id=None):
        return next((r for r in self.rows if r.user_id == user_id and r.provider == provider
                     and r.visibility == visibility and r.group_id == group_id), None)

    async def get_scope(self, owner_id, provider, visibility, group_id=None):
        candidates = [r for r in self.rows if r.provider == provider and r.visibility == visibility and
                      ((visibility == "personal" and r.user_id == owner_id) or
                       (visibility == "group" and r.group_id == group_id) or visibility == "global")]
        return candidates[0] if candidates else None

    async def visible(self, user_id, provider, group_ids):
        return await self.candidates(user_id, provider, group_ids)

    async def memberships(self, user_id):
        return getattr(self, "member_groups", {}).get(user_id, [])

    async def is_member(self, user_id, group_id):
        return group_id in await self.memberships(user_id)

    async def delete_scoped(self, config_id):
        row = next((r for r in self.rows if r.id == config_id), None)
        if row:
            self.rows.remove(row)
            return True
        return False

    async def by_id(self, config_id):
        return next((r for r in self.rows if r.id == config_id), None)


def test_provider_config_upload_replace_metadata_and_delete_are_role_gated():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)

    upload = client.put("/providers/opencode/config", files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/big-pickle","provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"opencode":{"key":"do-not-return"}}', "application/json"),
    })
    assert upload.status_code == 200
    assert upload.json()["auth_present"] is True
    metadata = client.get("/providers/opencode/config")
    assert metadata.status_code == 200
    assert "config_ciphertext" not in metadata.text
    assert "do-not-return" not in metadata.text

    replaced = client.put("/providers/opencode/config", files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/ling-3.0-flash-fin-free","provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}', "application/json"),
    })
    assert replaced.status_code == 200
    assert replaced.json()["auth_present"] is False
    deleted = client.delete("/providers/opencode/config")
    assert deleted.status_code == 200
    assert client.get("/providers/opencode/config").json() == []

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="viewer-1", role=SimpleNamespace(value="viewer"),
    )
    assert client.get("/providers/opencode/config").status_code == 200
    client.close()


def test_builder_cannot_upload_global_configuration():
    app = create_app()
    service = ProviderConfigService(MemoryRepository(), "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    result = client.put("/providers/opencode/config", data={"visibility": "global"}, files={
        "opencode_json": ("opencode.json", b'{"provider":{"opencode":{"options":{"apiKey":"x"}}}}', "application/json")
    })
    assert result.status_code == 403
    client.close()


def test_builder_cannot_upload_to_group_they_do_not_belong_to():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    result = client.put("/providers/opencode/config", data={"visibility": "group", "group_id": "not-member"}, files={
        "opencode_json": ("opencode.json", b'{"provider":{"opencode":{"options":{"apiKey":"x"}}}}', "application/json")
    })
    assert result.status_code == 403
    client.close()


def test_provider_config_list_exposes_only_personal_configs_owned_by_requester_and_global():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    admin = SimpleNamespace(id="admin", role=SimpleNamespace(value="admin"))
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    body = b'{"provider":{"opencode":{"options":{"apiKey":"private"}}}}'
    assert client.put("/providers/opencode/config", data={"visibility": "global"}, files={
        "opencode_json": ("opencode.json", body, "application/json")
    }).status_code == 200
    assert client.put("/providers/opencode/config", files={
        "opencode_json": ("opencode.json", body, "application/json")
    }).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="reader", role=SimpleNamespace(value="viewer"))
    rows = client.get("/providers/opencode/config").json()
    assert [row["visibility"] for row in rows] == ["global"]
    assert "config_ciphertext" not in str(rows) and "private" not in str(rows)
    client.close()


class FakeProviderHandler:
    def __init__(self):
        self.config = None
        self.auth = None
        self.verify_calls = []

    def validate_config(self, config, auth):
        self.config, self.auth = config, auth
        providers = config.get("provider", {})
        inline = any(provider.get("options", {}).get("apiKey") for provider in providers.values() if isinstance(provider, dict))
        return [] if auth or inline else [{"code": "auth_missing", "message_key": "errors.provider.auth_missing"}]

    async def list_models(self, user_id):
        return ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]

    async def verify_model(self, user_id, model):
        self.verify_calls.append((user_id, model))
        return {"ok": True, "response_snippet": "ok", "latency_ms": 25}


def test_provider_verify_lists_models_and_real_model_verify_is_scoped_and_structured():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    handler = FakeProviderHandler()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="admin"))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: service
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    uploaded = client.put("/providers/opencode/config", files={
        "opencode_json": ("opencode.json", b'{"provider":{"opencode":{"options":{"apiKey":"fake"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"opencode":{"type":"api","key":"fake"}}', "application/json"),
    })
    assert uploaded.status_code == 200

    models = client.post("/providers/opencode/config/verify")
    assert models.status_code == 200
    assert models.json() == {"valid": True, "violations": [],
                             "models": ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]}
    verified = client.post("/providers/opencode/config/verify-model", json={"model": "opencode/big-pickle"})
    assert verified.json() == {"ok": True, "response_snippet": "ok", "latency_ms": 25}
    assert handler.verify_calls == [("user-1", "opencode/big-pickle")]
    assert "fake" not in models.text and "fake" not in verified.text
    client.close()


def test_model_verify_reports_missing_auth_as_a_structured_error():
    import asyncio

    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    handler = FakeProviderHandler()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    app.dependency_overrides[get_provider_handler] = lambda: handler
    asyncio.run(service.replace("user-1", "opencode", b'{"provider":{"opencode":{}}}', None))
    client = TestClient(app)

    response = client.post("/providers/opencode/config/verify-model", json={"model": "opencode/big-pickle"})

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.auth_missing"
    client.close()


def test_upload_rejects_missing_provider_and_auth_sections_with_specific_violations():
    from app.integrations.providers.opencode import OpenCodeProviderHandler

    class NoopRuntime:
        async def list_models(self, user_id):
            return []

        async def verify_model(self, user_id, model):
            return {"ok": False}

    app = create_app()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    handler = OpenCodeProviderHandler(NoopRuntime())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(
        MemoryRepository(), "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=",
    )
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    response = client.put("/providers/opencode/config", files={
        "opencode_json": ("opencode.json", b'{"mcp":{},"skills":[]}', "application/json"),
    })
    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.config_invalid"
    keys = {detail["message_key"] for detail in response.json()["details"]}
    assert keys == {"errors.provider.providers_missing", "errors.provider.auth_missing"}
    client.close()
