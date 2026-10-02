from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.provider_configs import get_provider_config_service, get_provider_handler
from app.main import create_app
from app.domain.provider_configs.service import ProviderConfigService


class MemoryRepository:
    def __init__(self):
        self.rows = []
        self.candidate_operations = {}

    async def create_candidate_operation(self, user_id, provider, payload_ciphertext, expires_at):
        from types import SimpleNamespace
        operation_id = f"op-{len(self.candidate_operations) + 1}"
        self.candidate_operations[operation_id] = SimpleNamespace(
            id=operation_id, user_id=user_id, provider=provider,
            payload_ciphertext=payload_ciphertext, expires_at=expires_at,
        )
        return self.candidate_operations[operation_id]

    async def get_candidate_operation(self, operation_id):
        return self.candidate_operations.get(operation_id)

    async def delete_candidate_operation(self, operation_id):
        return self.candidate_operations.pop(operation_id, None) is not None

    async def purge_expired_candidate_operations(self):
        return 0

    async def get(self, user_id, provider):
        return next((row for row in self.rows if row.user_id == user_id and row.provider == provider
                     and row.visibility == "personal"), None)

    async def save(self, user_id, provider, config_ciphertext, auth_ciphertext, visibility="personal", group_id=None, verification_status="unverified", *, display_name):
        from types import SimpleNamespace
        # Mirrors the real repository contract: an existing scoped row is
        # updated in place (including the display name), never duplicated.
        existing = next((item for item in self.rows if item.user_id == user_id and item.provider == provider
                         and item.visibility == visibility and item.group_id == group_id), None)
        if existing is not None:
            existing.config_ciphertext = config_ciphertext
            existing.auth_ciphertext = auth_ciphertext
            existing.verification_status = verification_status
            existing.display_name = display_name
            return existing
        row = SimpleNamespace(id=user_id + provider + str(group_id), user_id=user_id, provider=provider,
                                   visibility=visibility, group_id=group_id,
                                    config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                                    verification_status=verification_status, display_name=display_name,
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

    async def set_verification_status(self, config_id, status):
        row = await self.by_id(config_id)
        if row:
            row.verification_status = status


def test_provider_config_upload_replace_metadata_and_delete_are_role_gated():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)

    upload = client.put("/providers/opencode/config", data={"name": "Personal Config"}, files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/big-pickle","provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"opencode":{"key":"do-not-return"}}', "application/json"),
    })
    assert upload.status_code == 200
    assert upload.json()["auth_present"] is True
    # A provider configuration never stores a model: neither the save response
    # nor the metadata list may carry selected_model or a model-derived count.
    assert "selected_model" not in upload.json() and "model_count" not in upload.json()
    metadata = client.get("/providers/opencode/config")
    assert metadata.status_code == 200
    for row in metadata.json():
        assert "selected_model" not in row and "model_count" not in row
    assert "config_ciphertext" not in metadata.text
    assert "do-not-return" not in metadata.text

    replaced = client.put("/providers/opencode/config", data={"name": "Replaced Config"}, files={
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


def test_upload_requires_a_user_entered_name_that_is_stored_listed_and_replaced():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    files = {"opencode_json": ("opencode.json",
                               b'{"provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}',
                               "application/json")}

    # The name is mandatory: absent, empty, and whitespace-only values are all
    # rejected with the localized key — never defaulted to the provider type.
    missing = client.put("/providers/opencode/config", files=files)
    empty = client.put("/providers/opencode/config", data={"name": ""}, files=files)
    whitespace = client.put("/providers/opencode/config", data={"name": "   "}, files=files)
    for response in (missing, empty, whitespace):
        assert response.status_code == 422
        assert response.json()["message_key"] == "errors.provider.name_invalid"
    too_long = client.put("/providers/opencode/config", data={"name": "x" * 81}, files=files)
    assert too_long.status_code == 422
    assert too_long.json()["message_key"] == "errors.provider.name_too_long"
    assert repo.rows == []

    saved = client.put("/providers/opencode/config", data={"name": "  Build Config  "}, files=files)
    assert saved.status_code == 200
    assert saved.json()["name"] == "Build Config"
    assert repo.rows[0].display_name == "Build Config"

    listed = client.get("/providers/opencode/config")
    assert listed.json()[0]["name"] == "Build Config"
    # `provider_type` still reports the type: it is not the display name.
    assert listed.json()[0]["provider_type"] == "opencode"

    renamed = client.put("/providers/opencode/config", data={"name": "Renamed Config"}, files=files)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Config"
    assert client.get("/providers/opencode/config").json()[0]["name"] == "Renamed Config"
    client.close()


def test_builder_cannot_upload_global_configuration():
    app = create_app()
    service = ProviderConfigService(MemoryRepository(), "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    result = client.put("/providers/opencode/config", data={"visibility": "global", "name": "Global Attempt"}, files={
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
    result = client.put("/providers/opencode/config", data={"visibility": "group", "group_id": "not-member", "name": "Group Attempt"}, files={
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
    assert client.put("/providers/opencode/config", data={"visibility": "global", "name": "Global Config"}, files={
        "opencode_json": ("opencode.json", body, "application/json")
    }).status_code == 200
    assert client.put("/providers/opencode/config", data={"name": "Personal Config"}, files={
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
    uploaded = client.put("/providers/opencode/config", data={"name": "Verified Config"}, files={
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
    asyncio.run(service.replace("user-1", "opencode", b'{"provider":{"opencode":{}}}', None,
                                display_name="Verify Target"))
    client = TestClient(app)

    response = client.post("/providers/opencode/config/verify-model", json={"model": "opencode/big-pickle"})

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.auth_missing"
    client.close()


class NoopRuntime:
    async def list_models(self, user_id):
        return []

    async def verify_model(self, user_id, model):
        return {"ok": False}


def test_upload_without_any_credentials_is_rejected_with_auth_missing():
    from app.integrations.providers.opencode import OpenCodeProviderHandler

    app = create_app()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    handler = OpenCodeProviderHandler(NoopRuntime())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(
        MemoryRepository(), "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=",
    )
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    response = client.put("/providers/opencode/config", data={"name": "No Auth Config"}, files={
        "opencode_json": ("opencode.json", b'{"mcp":{},"skills":[]}', "application/json"),
    })
    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.config_invalid"
    keys = {detail["message_key"] for detail in response.json()["details"]}
    assert keys == {"errors.provider.auth_missing"}
    client.close()


def test_upload_rejects_supplied_malformed_provider_section():
    from app.integrations.providers.opencode import OpenCodeProviderHandler

    app = create_app()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    handler = OpenCodeProviderHandler(NoopRuntime())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(
        MemoryRepository(), "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=",
    )
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    response = client.put("/providers/opencode/config", data={"name": "Malformed Config"}, files={
        "opencode_json": ("opencode.json", b'{"provider":"anthropic"}', "application/json"),
        "auth_json": ("auth.json", b'{"anthropic":{"type":"api","key":"embedded-test"}}', "application/json"),
    })
    assert response.status_code == 422
    keys = {detail["message_key"] for detail in response.json()["details"]}
    assert keys == {"errors.provider.providers_missing"}
    client.close()


def test_native_opencode_config_with_separate_auth_upload_and_verify_succeed():
    from app.integrations.providers.opencode import OpenCodeProviderHandler

    app = create_app()
    repo = MemoryRepository()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    handler = OpenCodeProviderHandler(NoopRuntime())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(
        repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=",
    )
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    upload = client.put("/providers/opencode/config", data={"name": "Native Config"}, files={
        "opencode_json": ("opencode.json", b'{"$schema":"https://opencode.ai/config.json","model":"anthropic/claude-sonnet-4-5"}', "application/json"),
        "auth_json": ("auth.json", b'{"anthropic":{"type":"api","key":"synthetic-native-key"}}', "application/json"),
    })
    assert upload.status_code == 200
    assert upload.json()["auth_present"] is True
    assert [row.user_id for row in repo.rows] == ["user-1"]
    assert "synthetic-native-key" not in upload.text

    verified = client.post("/providers/opencode/config/verify")
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert "synthetic-native-key" not in verified.text
    client.close()


def test_invalid_replacement_is_rejected_without_overwriting_previous_config():
    import asyncio

    from app.integrations.providers.opencode import OpenCodeProviderHandler

    app = create_app()
    repo = MemoryRepository()
    user = SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder"))
    handler = OpenCodeProviderHandler(NoopRuntime())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(
        repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=",
    )
    app.dependency_overrides[get_provider_handler] = lambda: handler
    client = TestClient(app)
    original_config = b'{"model":"opencode/big-pickle","provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}'
    original_auth = b'{"opencode":{"type":"api","key":"embedded-test"}}'
    assert client.put("/providers/opencode/config", data={"name": "Original Config"}, files={
        "opencode_json": ("opencode.json", original_config, "application/json"),
        "auth_json": ("auth.json", original_auth, "application/json"),
    }).status_code == 200
    snapshot = list(repo.rows)

    invalid = client.put("/providers/opencode/config", data={"name": "Original Config"}, files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/big-pickle","provider":{"opencode":"oops"}}', "application/json"),
        "auth_json": ("auth.json", original_auth, "application/json"),
    })
    assert invalid.status_code == 422
    assert invalid.json()["message_key"] == "errors.provider.config_invalid"
    keys = {detail["message_key"] for detail in invalid.json()["details"]}
    assert keys == {"errors.provider.provider_invalid"}

    assert repo.rows == snapshot
    stored = asyncio.run(ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=").read_files("user-1", "opencode"))
    assert stored == {"opencode.json": original_config, "auth.json": original_auth}
    client.close()


def test_candidate_validation_never_persists_candidate_credentials():
    app = create_app()
    repo = MemoryRepository()
    class Handler(FakeProviderHandler):
        pass
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u", role=SimpleNamespace(value="runner"))
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_provider_handler] = Handler
    client = TestClient(app)
    body = {"config": {"provider": {"x": {"options": {"apiKey": "secret"}}}}, "auth": None}
    assert client.post("/providers/opencode/config/candidate/validate", json=body).json() == {"valid": True, "violations": []}
    invalid = client.post("/providers/opencode/config/candidate/validate", json={"config": {}, "auth": None})
    assert invalid.json()["valid"] is False and invalid.json()["violations"]
    assert repo.rows == [] and "secret" not in invalid.text
    client.close()


def test_candidate_models_and_verify_use_candidate_handler_methods_without_storage():
    app = create_app()
    repo = MemoryRepository()
    class Handler(FakeProviderHandler):
        async def list_candidate_models(self, user_id, config, auth):
            assert config["provider"]
            return ["candidate/model"]
        async def verify_candidate_model(self, user_id, config, auth, model):
            return {"ok": model == "candidate/model", "response_snippet": "ok", "latency_ms": 1}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u", role=SimpleNamespace(value="runner"))
    app.dependency_overrides[get_provider_config_service] = lambda: ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_provider_handler] = Handler
    client = TestClient(app)
    body = {"config": {"provider": {"x": {"options": {"apiKey": "secret"}}}}, "auth": None}
    assert client.post("/providers/opencode/config/candidate/models", json=body).json()["models"] == ["candidate/model"]
    assert client.post("/providers/opencode/config/candidate/verify-model", json={**body, "model": "candidate/model"}).json()["ok"]
    assert not repo.rows
    client.close()


CANDIDATE_BODY = {"config": {"provider": {"x": {"options": {"apiKey": "secret-key"}}}},
                  "auth": {"x": {"key": "auth-secret"}}}


def _candidate_client(monkeypatch, execute):
    """Real handler + real runtime with the Temporal execution seam faked."""
    from app.api.routes.provider_configs import TemporalOpenCodeRuntime

    monkeypatch.setattr(TemporalOpenCodeRuntime, "_execute", execute)
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="runner"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    return TestClient(app), repo


def test_candidate_models_executes_activity_with_operation_id_only(monkeypatch):
    captured = {}

    async def execute(self, activity_name, payload):
        captured["activity"] = activity_name
        captured["payload"] = payload
        return ["candidate/model-a", "candidate/model-b"]

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/models", json=CANDIDATE_BODY)

    assert response.status_code == 200
    assert response.json() == {"valid": True, "violations": [],
                               "models": ["candidate/model-a", "candidate/model-b"]}
    assert captured["activity"] == "list_opencode_candidate_models"
    assert set(captured["payload"]) == {"operation_id", "user_id"}
    assert captured["payload"]["user_id"] == "user-1"
    serialized = str(captured["payload"])
    assert "secret-key" not in serialized and "auth-secret" not in serialized
    # The operation itself carries the credentials encrypted, never as a config row.
    assert len(repo.candidate_operations) == 1
    operation = next(iter(repo.candidate_operations.values()))
    assert captured["payload"]["operation_id"] == operation.id
    assert "secret-key" not in operation.payload_ciphertext and "auth-secret" not in operation.payload_ciphertext
    assert repo.rows == []
    client.close()


def test_candidate_model_verification_executes_activity_with_operation_id_only(monkeypatch):
    captured = {}

    async def execute(self, activity_name, payload):
        captured["activity"] = activity_name
        captured["payload"] = payload
        return {"ok": True, "response_snippet": "ok", "latency_ms": 12}

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**CANDIDATE_BODY, "model": "candidate/model-a"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["activity"] == "verify_opencode_candidate_model"
    assert captured["payload"] == {"operation_id": next(iter(repo.candidate_operations)),
                                   "user_id": "user-1", "model": "candidate/model-a", "consume": False}
    serialized = str(captured["payload"])
    assert "secret-key" not in serialized and "auth-secret" not in serialized
    # Verification never consumes the operation: the still-live row becomes the
    # single-use proof returned to the client as verification_id.
    assert len(repo.candidate_operations) == 1
    assert response.json()["verification_id"] == next(iter(repo.candidate_operations))
    client.close()


def test_failed_candidate_verification_returns_no_proof_and_discards_operation(monkeypatch):
    async def execute(self, activity_name, payload):
        return {"ok": False, "error": {"code": "PROVIDER_AUTH_MISSING",
                "message_key": "errors.provider.auth_missing", "params": {"provider": "opencode"}}}

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**CANDIDATE_BODY, "model": "candidate/model-a"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    # A failed test can never produce a proof.
    assert "verification_id" not in response.json()
    assert repo.candidate_operations == {}
    client.close()


VERIFY_BODY = {"config": {"provider": {"x": {"options": {"apiKey": "secret-key"}}}, "mcp": {}},
               "auth": {"x": {"type": "api", "key": "auth-secret"}}}


def _ok_verification_execute(captured=None):
    async def execute(self, activity_name, payload):
        if captured is not None:
            captured["payload"] = payload
        return {"ok": True, "response_snippet": "ok", "latency_ms": 12}
    return execute


def test_upload_with_matching_verification_id_records_verified_and_consumes_it(monkeypatch):
    client, repo = _candidate_client(monkeypatch, _ok_verification_execute())
    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**VERIFY_BODY, "model": "candidate/model-a"})
    verification_id = verified.json()["verification_id"]

    # The uploaded files carry the same parsed objects with reordered keys:
    # the proof matches configurations, not byte-for-byte payloads.
    saved = client.put("/providers/opencode/config", data={"verification_id": verification_id, "name": "Verified Config"}, files={
        "opencode_json": ("opencode.json", b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"secret-key"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"x":{"key":"auth-secret","type":"api"}}', "application/json"),
    })

    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "verified"
    assert repo.rows and repo.rows[0].verification_status == "verified"
    # The proof is single-use: saving consumed the operation.
    assert repo.candidate_operations == {}
    client.close()


def test_upload_with_mismatched_verification_id_records_unverified_and_untrusts_operation(monkeypatch):
    client, repo = _candidate_client(monkeypatch, _ok_verification_execute())
    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**VERIFY_BODY, "model": "candidate/model-a"})
    verification_id = verified.json()["verification_id"]

    saved = client.put("/providers/opencode/config", data={"verification_id": verification_id, "name": "Mismatched Config"}, files={
        "opencode_json": ("opencode.json", b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"different-key"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"x":{"key":"auth-secret","type":"api"}}', "application/json"),
    })

    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "unverified"
    # A mismatched reuse untrusting the operation: it must not be redeemable afterwards.
    assert repo.candidate_operations == {}
    client.close()


def test_upload_with_missing_expired_or_absent_verification_id_records_unverified(monkeypatch):
    client, repo = _candidate_client(monkeypatch, _ok_verification_execute())
    from datetime import datetime, timedelta, timezone

    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**VERIFY_BODY, "model": "candidate/model-a"})
    verification_id = verified.json()["verification_id"]
    repo.candidate_operations[verification_id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    files = {
        "opencode_json": ("opencode.json", b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"secret-key"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"x":{"key":"auth-secret","type":"api"}}', "application/json"),
    }

    expired = client.put("/providers/opencode/config", data={"verification_id": verification_id, "name": "Expired Proof Config"}, files=files)
    unknown = client.put("/providers/opencode/config", data={"verification_id": "missing-op", "name": "Unknown Proof Config"}, files=files)
    absent = client.put("/providers/opencode/config", data={"name": "Absent Proof Config"}, files=files)

    for response in (expired, unknown, absent):
        assert response.status_code == 200
        assert response.json()["verification_status"] == "unverified"
    assert repo.rows and all(row.verification_status == "unverified" for row in repo.rows)
    client.close()


def test_candidate_operation_is_deleted_and_structured_error_returned_on_activity_failure(monkeypatch):
    captured = {}

    async def execute(self, activity_name, payload):
        captured["payload"] = payload
        raise RuntimeError("temporal unavailable")

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/models", json=CANDIDATE_BODY)

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.candidate_operation_unavailable"
    # The activity really ran with a live operation before the failure.
    assert captured["payload"]["user_id"] == "user-1"
    assert repo.candidate_operations == {}
    client.close()


def test_candidate_model_verification_failure_deletes_operation_and_returns_structured_error(monkeypatch):
    captured = {}

    async def execute(self, activity_name, payload):
        captured["called"] = True
        raise RuntimeError("temporal unavailable")

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**CANDIDATE_BODY, "model": "candidate/model-a"})

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.candidate_operation_unavailable"
    assert captured["called"] is True
    assert repo.candidate_operations == {}
    client.close()


def test_execute_runs_the_probe_workflow(monkeypatch):
    """Standalone activities are unsupported by the running Temporal server, so
    probes must execute inside the workflow (regression: execute_activity raised
    TypeError/RPCError and every provider verification failed)."""
    import asyncio

    import temporalio.client as temporal_client

    from app.api.routes.provider_configs import TemporalOpenCodeRuntime

    calls = []

    class FakeClient:
        async def execute_workflow(self, workflow_run, *, args, id, task_queue):
            calls.append({"workflow": workflow_run, "args": args, "id": id, "task_queue": task_queue})
            return ["model-a"]

    async def fake_connect(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(temporal_client.Client, "connect", staticmethod(fake_connect))
    runtime = TemporalOpenCodeRuntime(config_service=None)

    result = asyncio.run(runtime._execute("list_opencode_models", {"user_id": "user-1"}))

    assert result == ["model-a"]
    assert calls[0]["workflow"].__qualname__.endswith("ProviderProbeWorkflow.run")
    assert calls[0]["args"][0] == "list_opencode_models"
    assert calls[0]["args"][1] == {"user_id": "user-1"}
    assert calls[0]["id"].startswith("provider-probe-")
