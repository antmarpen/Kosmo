import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.provider_configs import get_provider_config_service, get_provider_handler
from app.main import create_app
from app.domain.provider_configs.service import ProviderConfigService


class MemoryRepository:
    def __init__(self):
        self.rows = []
        self.candidate_operations = {}
        # Stand-in for the database `updated_at` clock: every save strictly
        # bumps the row's version marker so staleness checks are deterministic.
        self._tick = 0

    def _next_updated_at(self):
        self._tick += 1
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=self._tick)

    async def create_candidate_operation(self, user_id, provider, payload_ciphertext, expires_at, purpose="discovery"):
        from types import SimpleNamespace
        operation_id = f"op-{len(self.candidate_operations) + 1}"
        self.candidate_operations[operation_id] = SimpleNamespace(
            id=operation_id, user_id=user_id, provider=provider,
            payload_ciphertext=payload_ciphertext, expires_at=expires_at,
            purpose=purpose, verification_succeeded=False,
        )
        return self.candidate_operations[operation_id]

    async def get_candidate_operation(self, operation_id):
        return self.candidate_operations.get(operation_id)

    async def delete_candidate_operation(self, operation_id):
        return self.candidate_operations.pop(operation_id, None) is not None

    async def mark_candidate_operation_verified(self, operation_id):
        row = self.candidate_operations.get(operation_id)
        if row is None or row.purpose != "verification":
            return None
        remaining = int((row.expires_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            return None
        row.verification_succeeded = True
        return remaining

    def _claim_candidate_operation(self, operation_id, user_id, provider, *, require_redeemable):
        row = self.candidate_operations.get(operation_id)
        if row is None or row.user_id != user_id or row.provider != provider:
            return None
        if row.expires_at <= datetime.now(timezone.utc):
            return None
        if require_redeemable and (row.purpose != "verification" or not row.verification_succeeded):
            return None
        return self.candidate_operations.pop(operation_id)

    async def consume_candidate_operation(self, operation_id, user_id, provider):
        claimed = self._claim_candidate_operation(operation_id, user_id, provider, require_redeemable=False)
        return {"payload_ciphertext": claimed.payload_ciphertext} if claimed else None

    async def redeem_candidate_operation(self, operation_id, user_id, provider):
        claimed = self._claim_candidate_operation(operation_id, user_id, provider, require_redeemable=True)
        return {"payload_ciphertext": claimed.payload_ciphertext} if claimed else None

    async def purge_expired_candidate_operations(self):
        return 0

    async def get(self, user_id, provider):
        # Mirrors the real legacy fallback: the most recently updated row.
        rows = [row for row in self.rows if row.user_id == user_id and row.provider == provider
                and row.visibility == "personal"]
        return max(rows, key=lambda row: (row.updated_at, row.id), default=None)

    async def create(self, user_id, provider, config_ciphertext, auth_ciphertext, visibility="personal", group_id=None, verification_status="unverified", *, display_name):
        from types import SimpleNamespace
        # Mirrors the real functional unique index: a duplicate display name
        # for the same owner and provider can never be stored.
        if await self.name_taken(user_id, provider, display_name):
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("INSERT INTO provider_configs", None,
                                 Exception("uq_provider_config_owner_provider_name_ci"))
        row = SimpleNamespace(id=f"config-{len(self.rows) + 1}", user_id=user_id, provider=provider,
                              visibility=visibility, group_id=group_id,
                              config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                              verification_status=verification_status, display_name=display_name,
                              updated_at=self._next_updated_at())
        self.rows.append(row)
        return row

    async def update(self, row, *, config_ciphertext, auth_ciphertext, verification_status,
                     display_name, visibility, group_id):
        # Mirrors the real repository contract: an update targets one row by
        # id, never duplicates it, and bumps the `updated_at` version marker.
        row.config_ciphertext = config_ciphertext
        row.auth_ciphertext = auth_ciphertext
        row.verification_status = verification_status
        row.display_name = display_name
        row.visibility = visibility
        row.group_id = group_id
        row.updated_at = self._next_updated_at()
        return row

    async def name_taken(self, user_id, provider, display_name, *, exclude_id=None):
        return any(item.user_id == user_id and item.provider == provider
                   and item.display_name.lower() == display_name.lower()
                   and item.id != exclude_id for item in self.rows)

    async def delete(self, user_id, provider):
        row = await self.get(user_id, provider)
        if row is None:
            return False
        self.rows.remove(row)
        return True

    async def candidates(self, user_id, provider, group_ids):
        return [r for r in self.rows if r.provider == provider and
                ((r.visibility == "personal" and r.user_id == user_id) or r.visibility == "global" or
                 (r.visibility == "group" and r.group_id in group_ids))]

    async def get_scoped(self, user_id, provider, visibility, group_id=None):
        return next((r for r in self.rows if r.user_id == user_id and r.provider == provider
                     and r.visibility == visibility and r.group_id == group_id), None)

    async def visible(self, user_id, provider, group_ids):
        return await self.candidates(user_id, provider, group_ids)

    async def memberships(self, user_id):
        return getattr(self, "member_groups", {}).get(user_id, [])

    async def is_member(self, user_id, group_id):
        return group_id in await self.memberships(user_id)

    async def membership_role(self, user_id, group_id):
        return getattr(self, "member_roles", {}).get((user_id, group_id))

    async def delete_scoped(self, config_id):
        row = next((r for r in self.rows if r.id == config_id), None)
        if row:
            self.rows.remove(row)
            return True
        return False

    async def by_id(self, config_id):
        return next((r for r in self.rows if r.id == config_id), None)

    async def set_verification_status(self, config_id, status, expected_updated_at=None):
        row = await self.by_id(config_id)
        if row is None:
            return False
        # Mirrors the real conditional update: a stale result (the files were
        # replaced after the caller read them) writes nothing.
        if expected_updated_at is not None and row.updated_at != expected_updated_at:
            return False
        row.verification_status = status
        return True


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

    # A second upload with a different name is a DISTINCT instance, not an
    # overwrite: both rows coexist with their own ids.
    second = client.put("/providers/opencode/config", data={"name": "Second Config"}, files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/ling-3.0-flash-fin-free","provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}', "application/json"),
    })
    assert second.status_code == 200
    assert second.json()["auth_present"] is False
    listed = client.get("/providers/opencode/config").json()
    assert {row["name"] for row in listed} == {"Personal Config", "Second Config"}
    assert len({row["id"] for row in listed}) == 2

    # Deleting one instance by id leaves the other untouched.
    personal_id = next(row["id"] for row in listed if row["name"] == "Personal Config")
    second_id = next(row["id"] for row in listed if row["name"] == "Second Config")
    deleted = client.delete("/providers/opencode/config", params={"config_id": personal_id})
    assert deleted.status_code == 200
    assert [row["id"] for row in client.get("/providers/opencode/config").json()] == [second_id]

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

    # A different name is a new distinct instance (not a rename): both coexist.
    renamed = client.put("/providers/opencode/config", data={"name": "Renamed Config"}, files=files)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Config"
    names = {row["name"] for row in client.get("/providers/opencode/config").json()}
    assert names == {"Build Config", "Renamed Config"}

    # The same name, even with different case, is rejected with the keyed
    # conflict error instead of overwriting or duplicating the instance.
    duplicate = client.put("/providers/opencode/config", data={"name": "build config"}, files=files)
    assert duplicate.status_code == 409
    assert duplicate.json()["message_key"] == "errors.provider.name_duplicate"
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

    async def list_models(self, user_id, config_id=None):
        return ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]

    async def verify_model(self, user_id, model, config_id=None):
        self.verify_calls.append((user_id, model))
        return {"ok": True, "response_non_empty": True, "latency_ms": 25}


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
    assert verified.json() == {"ok": True, "response_non_empty": True, "latency_ms": 25}
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
    asyncio.run(service.create("user-1", "opencode", b'{"provider":{"opencode":{}}}', None,
                                display_name="Verify Target"))
    client = TestClient(app)

    response = client.post("/providers/opencode/config/verify-model", json={"model": "opencode/big-pickle"})

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.auth_missing"
    client.close()


UPLOAD_FILES = {
    "opencode_json": ("opencode.json", b'{"provider":{"opencode":{"options":{"apiKey":"embedded-test"}}}}', "application/json"),
    "auth_json": ("auth.json", b'{"opencode":{"type":"api","key":"embedded-test"}}', "application/json"),
}


def _two_scope_verification_client():
    """A caller with an own personal config plus a shared group config.

    user-2 owns the group g1 configuration; user-1 is a plain member of g1 and
    owns a personal configuration. Both rows are visible to user-1 with
    distinguishable model lists keyed by the targeted configuration id.
    """
    app = create_app()
    repo = MemoryRepository()
    repo.member_groups = {"user-1": ["g1"]}
    repo.member_roles = {("user-2", "g1"): "group_manager"}
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")

    class TargetedHandler(FakeProviderHandler):
        async def list_models(self, user_id, config_id=None):
            return [f"models-of-{config_id}"]

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-2", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    app.dependency_overrides[get_provider_handler] = lambda: TargetedHandler()
    client = TestClient(app)
    saved = client.put("/providers/opencode/config", data={
        "visibility": "group", "group_id": "g1", "name": "Team Config"}, files=UPLOAD_FILES)
    assert saved.status_code == 200
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    saved = client.put("/providers/opencode/config", data={"name": "Personal Config"}, files=UPLOAD_FILES)
    assert saved.status_code == 200
    return client, repo, service


def test_saved_config_verification_targets_the_requested_configuration():
    client, repo, service = _two_scope_verification_client()

    personal_id = next(row.id for row in repo.rows if row.visibility == "personal")
    group_id = next(row.id for row in repo.rows if row.visibility == "group")

    # Both scopes are listed to the caller; each row probes its own models.
    listed = client.get("/providers/opencode/config")
    assert {row["id"] for row in listed.json()} == {personal_id, group_id}
    probed_personal = client.post("/providers/opencode/config/verify", json={"config_id": personal_id})
    assert probed_personal.status_code == 200
    assert probed_personal.json()["models"] == [f"models-of-{personal_id}"]
    probed_group = client.post("/providers/opencode/config/verify", json={"config_id": group_id})
    assert probed_group.status_code == 200
    assert probed_group.json()["models"] == [f"models-of-{group_id}"]

    # Verifying the group row updates only the group row's stored status.
    verified = client.post("/providers/opencode/config/verify-model",
                           json={"model": "models-of-" + group_id, "config_id": group_id})
    assert verified.status_code == 200
    assert verified.json()["ok"] is True
    statuses = {row.id: row.verification_status for row in repo.rows}
    assert statuses[group_id] == "verified"
    assert statuses[personal_id] == "unverified"
    client.close()


def test_saved_config_verification_rejects_unknown_and_invisible_config_ids():
    client, repo, service = _two_scope_verification_client()
    repo.member_roles[("user-2", "g2")] = "group_manager"
    # A foreign personal row and a group row of a group the caller is not in.
    app_override = client.app.dependency_overrides
    app_override[get_current_user] = lambda: SimpleNamespace(
        id="user-2", role=SimpleNamespace(value="builder"))
    foreign_personal = client.put("/providers/opencode/config", data={"name": "Other Personal"}, files=UPLOAD_FILES)
    assert foreign_personal.status_code == 200
    saved = client.put("/providers/opencode/config", data={
        "visibility": "group", "group_id": "g2", "name": "Other Team"}, files=UPLOAD_FILES)
    assert saved.status_code == 200
    foreign_group_id = next(row.id for row in repo.rows if row.visibility == "group" and row.group_id == "g2")
    foreign_personal_id = next(row.id for row in repo.rows
                               if row.visibility == "personal" and row.user_id == "user-2")
    app_override[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))

    unknown = client.post("/providers/opencode/config/verify", json={"config_id": "missing-id"})
    foreign = client.post("/providers/opencode/config/verify", json={"config_id": foreign_personal_id})
    other_group = client.post("/providers/opencode/config/verify", json={"config_id": foreign_group_id})
    verify_model_foreign = client.post("/providers/opencode/config/verify-model",
                                       json={"model": "m", "config_id": foreign_personal_id})

    assert unknown.status_code == 404
    assert unknown.json()["message_key"] == "errors.provider.config_not_found"
    for response in (foreign, other_group, verify_model_foreign):
        assert response.status_code == 403
        assert response.json()["message_key"] == "errors.provider.forbidden"
    # The stored status of any probed row is untouched by rejected attempts.
    assert all(row.verification_status == "unverified" for row in repo.rows)
    client.close()


def test_verify_model_does_not_mark_a_replaced_configuration_as_verified():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")

    class ReplacingHandler(FakeProviderHandler):
        async def verify_model(self, user_id, model, config_id=None):
            # The targeted configuration is replaced while the container probe
            # runs: an update by id swaps the files and bumps `updated_at`.
            await service.scoped_save(
                SimpleNamespace(id="user-1", role=SimpleNamespace(value="builder")),
                "opencode", b'{"provider":{"opencode":{"options":{"apiKey":"replacement-key"}}}}',
                None, "personal", None, display_name="Replaced Config", config_id=config_id)
            return {"ok": True, "response_non_empty": True, "latency_ms": 5}

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    app.dependency_overrides[get_provider_handler] = lambda: ReplacingHandler()
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Original"}, files=UPLOAD_FILES).status_code == 200
    config_id = repo.rows[0].id

    response = client.post("/providers/opencode/config/verify-model",
                           json={"model": "opencode/big-pickle", "config_id": config_id})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    # The replacement landed on the same row (the files were really swapped).
    assert repo.rows[0].display_name == "Replaced Config"
    # The stale result arrived after the files were replaced: writing it would
    # brand configuration files that were never verified.
    assert repo.rows[0].verification_status == "unverified"
    client.close()


def test_saved_config_probes_carry_only_the_config_id_reference(monkeypatch):
    """The saved-config probe extends the operation-reference mechanism: the
    Temporal payload names the targeted configuration; credentials stay in the
    encrypted store."""
    captured = []

    async def execute(self, activity_name, payload):
        captured.append((activity_name, dict(payload)))
        if activity_name == "list_opencode_models":
            return ["opencode/big-pickle"]
        return {"ok": True, "response_non_empty": True, "latency_ms": 5}

    from app.api.routes.provider_configs import TemporalOpenCodeRuntime

    monkeypatch.setattr(TemporalOpenCodeRuntime, "_execute", execute)
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Probed Config"}, files=UPLOAD_FILES).status_code == 200
    config_id = repo.rows[0].id

    listed = client.post("/providers/opencode/config/verify", json={"config_id": config_id})
    verified = client.post("/providers/opencode/config/verify-model",
                           json={"model": "opencode/big-pickle", "config_id": config_id})

    assert listed.json()["models"] == ["opencode/big-pickle"]
    assert verified.json()["ok"] is True
    assert captured[0] == ("list_opencode_models", {"user_id": "user-1", "config_id": config_id})
    assert captured[1] == ("verify_opencode_model",
                           {"user_id": "user-1", "model": "opencode/big-pickle", "config_id": config_id})
    serialized = str(captured)
    assert "embedded-test" not in serialized
    client.close()


class NoopRuntime:
    async def list_models(self, user_id, config_id=None):
        return []

    async def verify_model(self, user_id, model, config_id=None):
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


def test_invalid_update_is_rejected_without_overwriting_previous_config():
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
    config_id = repo.rows[0].id
    snapshot = [(row.id, row.config_ciphertext, row.updated_at) for row in repo.rows]

    invalid = client.patch("/providers/opencode/config", data={"config_id": config_id, "name": "Original Config"}, files={
        "opencode_json": ("opencode.json", b'{"model":"opencode/big-pickle","provider":{"opencode":"oops"}}', "application/json"),
        "auth_json": ("auth.json", original_auth, "application/json"),
    })
    assert invalid.status_code == 422
    assert invalid.json()["message_key"] == "errors.provider.config_invalid"
    keys = {detail["message_key"] for detail in invalid.json()["details"]}
    assert keys == {"errors.provider.provider_invalid"}

    # A rejected update leaves the stored row exactly as it was.
    assert [(row.id, row.config_ciphertext, row.updated_at) for row in repo.rows] == snapshot
    stored = asyncio.run(ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=").read_files_by_id(config_id))
    assert stored == {"opencode.json": original_config, "auth.json": original_auth}
    client.close()


def test_patch_updates_one_instance_by_id_and_keeps_the_other_untouched():
    import asyncio

    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200
    assert client.put("/providers/opencode/config", data={"name": "Beta Config"}, files=UPLOAD_FILES).status_code == 200
    alpha_id, beta_id = repo.rows[0].id, repo.rows[1].id
    beta_before = (repo.rows[1].display_name, repo.rows[1].config_ciphertext, repo.rows[1].updated_at)

    # Renaming without uploading files: the id, stored files, and status of
    # the edited instance are preserved, and the sibling is untouched.
    renamed = client.patch("/providers/opencode/config", data={"config_id": alpha_id, "name": "Alpha Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["id"] == alpha_id
    assert renamed.json()["name"] == "Alpha Renamed"
    assert renamed.json()["verification_status"] == "unverified"
    assert repo.rows[0].id == alpha_id
    assert (repo.rows[1].display_name, repo.rows[1].config_ciphertext,
            repo.rows[1].updated_at) == beta_before
    stored = asyncio.run(service.read_files_by_id(alpha_id))
    assert stored == {"opencode.json": UPLOAD_FILES["opencode_json"][1],
                      "auth.json": UPLOAD_FILES["auth_json"][1]}
    listed = client.get("/providers/opencode/config").json()
    assert {row["name"] for row in listed} == {"Alpha Renamed", "Beta Config"}
    assert {row["id"] for row in listed} == {alpha_id, beta_id}

    # Uploading a replacement file updates that exact instance: the stored
    # auth file is preserved and the honest status without a proof is
    # unverified.
    replaced = client.patch("/providers/opencode/config", data={"config_id": alpha_id, "name": "Alpha Renamed"}, files={
        "opencode_json": ("opencode.json", b'{"provider":{"opencode":{"options":{"apiKey":"new-embedded-key"}}}}', "application/json"),
    })
    assert replaced.status_code == 200
    assert replaced.json()["id"] == alpha_id
    assert replaced.json()["verification_status"] == "unverified"
    assert replaced.json()["auth_present"] is True
    stored = asyncio.run(service.read_files_by_id(alpha_id))
    assert stored["opencode.json"] == b'{"provider":{"opencode":{"options":{"apiKey":"new-embedded-key"}}}}'
    assert stored["auth.json"] == UPLOAD_FILES["auth_json"][1]
    # The sibling instance never moved.
    assert (repo.rows[1].display_name, repo.rows[1].config_ciphertext,
            repo.rows[1].updated_at) == beta_before
    client.close()


def test_patch_rejects_unknown_and_foreign_config_ids():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    overrides = app.dependency_overrides
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200

    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-2", role=SimpleNamespace(value="builder"))
    assert client.put("/providers/opencode/config", data={"name": "Gamma Config"}, files=UPLOAD_FILES).status_code == 200
    foreign_id = next(row.id for row in repo.rows if row.user_id == "user-2")
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))

    unknown = client.patch("/providers/opencode/config", data={"config_id": "missing-id", "name": "X"})
    foreign = client.patch("/providers/opencode/config", data={"config_id": foreign_id, "name": "X"})

    assert unknown.status_code == 404
    assert unknown.json()["message_key"] == "errors.provider.config_not_found"
    assert foreign.status_code == 403
    assert foreign.json()["message_key"] == "errors.provider.forbidden"
    assert all(row.display_name != "X" for row in repo.rows)
    client.close()


def test_patch_without_file_changes_preserves_the_verification_status():
    import asyncio

    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    asyncio.run(service.create("user-1", "opencode", UPLOAD_FILES["opencode_json"][1],
                               UPLOAD_FILES["auth_json"][1],
                               verification_status="verified", display_name="Verified Config"))
    config_id = repo.rows[0].id

    renamed = client.patch("/providers/opencode/config", data={"config_id": config_id, "name": "Still Verified"})

    assert renamed.status_code == 200
    # Nothing about the credentials changed, so the recorded status is kept.
    assert renamed.json()["verification_status"] == "verified"
    assert renamed.json()["id"] == config_id
    client.close()


def test_patch_with_matching_verification_id_records_verified(monkeypatch):
    async def execute(self, activity_name, payload):
        return {"ok": True, "response_non_empty": True, "latency_ms": 12}

    from app.api.routes.provider_configs import TemporalOpenCodeRuntime

    monkeypatch.setattr(TemporalOpenCodeRuntime, "_execute", execute)
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Original"}, files=UPLOAD_FILES).status_code == 200
    config_id = repo.rows[0].id
    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**VERIFY_BODY, "model": "candidate/model-a"})
    verification_id = verified.json()["verification_id"]

    saved = client.patch("/providers/opencode/config", data={
        "config_id": config_id, "name": "Original", "verification_id": verification_id,
    }, files={
        "opencode_json": ("opencode.json", b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"secret-key"}}}}', "application/json"),
        "auth_json": ("auth.json", b'{"x":{"key":"auth-secret","type":"api"}}', "application/json"),
    })

    assert saved.status_code == 200
    assert saved.json()["id"] == config_id
    assert saved.json()["verification_status"] == "verified"
    # The proof is single-use: the update consumed the operation.
    assert repo.candidate_operations == {}
    client.close()


def test_patch_with_a_name_taken_by_a_sibling_instance_is_a_keyed_conflict():
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200
    assert client.put("/providers/opencode/config", data={"name": "Beta Config"}, files=UPLOAD_FILES).status_code == 200
    beta_id = repo.rows[1].id

    conflict = client.patch("/providers/opencode/config", data={"config_id": beta_id, "name": "alpha config"})

    assert conflict.status_code == 409
    assert conflict.json()["message_key"] == "errors.provider.name_duplicate"
    assert repo.rows[1].display_name == "Beta Config"
    client.close()


class ConflictingUpdateRepository(MemoryRepository):
    """MemoryRepository whose update commit always loses at a database index.

    Stands in for the commit-time `IntegrityError` the functional unique index
    raises when two updates race to the same case-insensitive name (the
    application pre-check cannot see that race coming).
    """

    def __init__(self, constraint: str):
        super().__init__()
        self._constraint = constraint

    async def update(self, row, *, config_ciphertext, auth_ciphertext, verification_status,
                     display_name, visibility, group_id):
        from sqlalchemy.exc import IntegrityError
        raise IntegrityError("UPDATE provider_configs", None, Exception(self._constraint))


def test_update_losing_a_name_race_at_the_index_is_a_keyed_conflict():
    """A lost update race — the unique index rejected the commit — surfaces as
    the keyed conflict error, matching the create path, and the rejected
    rename never reaches the stored row."""
    app = create_app()
    repo = ConflictingUpdateRepository("uq_provider_config_owner_provider_name_ci")
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200
    alpha_id = repo.rows[0].id

    response = client.patch("/providers/opencode/config", data={"config_id": alpha_id, "name": "Alpha Renamed"})

    assert response.status_code == 409
    assert response.json()["message_key"] == "errors.provider.name_duplicate"
    assert response.json()["params"] == {"name": "Alpha Renamed"}
    assert repo.rows[0].display_name == "Alpha Config"
    client.close()


def test_update_with_files_losing_a_name_race_is_a_keyed_conflict():
    """The file-replacing update branch translates a lost name race into the
    keyed conflict too, and stores nothing on the rejected row."""
    app = create_app()
    repo = ConflictingUpdateRepository("uq_provider_config_owner_provider_name_ci")
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200
    alpha_id = repo.rows[0].id
    stored = repo.rows[0].config_ciphertext

    response = client.patch("/providers/opencode/config", data={"config_id": alpha_id, "name": "Alpha Renamed"}, files=UPLOAD_FILES)

    assert response.status_code == 409
    assert response.json()["message_key"] == "errors.provider.name_duplicate"
    # The failed save stored nothing: the row keeps its previous ciphertext.
    assert repo.rows[0].display_name == "Alpha Config"
    assert repo.rows[0].config_ciphertext == stored
    client.close()


def test_update_unrelated_database_failure_is_not_translated():
    """Only the name-index violation is translated: any other database failure
    propagates unchanged to the unhandled-error path instead of masquerading
    as a name conflict."""
    app = create_app()
    repo = ConflictingUpdateRepository("provider_configs_user_id_fkey")
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    assert client.put("/providers/opencode/config", data={"name": "Alpha Config"}, files=UPLOAD_FILES).status_code == 200
    alpha_id = repo.rows[0].id

    response = client.patch("/providers/opencode/config", data={"config_id": alpha_id, "name": "Alpha Renamed"})

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["message_key"] == "errors.internal"
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
            return {"ok": model == "candidate/model", "response_non_empty": True, "latency_ms": 1}
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
        return {"ok": True, "response_non_empty": True, "latency_ms": 12}

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
    operation = next(iter(repo.candidate_operations.values()))
    assert response.json()["verification_id"] == operation.id
    # The success was recorded on the row and the remaining validity is
    # exposed so the client can act before the proof window closes.
    assert operation.verification_succeeded is True
    assert operation.purpose == "verification"
    proof = response.json()["proof_expires_in_seconds"]
    assert 0 < proof <= 120
    assert "response_snippet" not in response.json()
    client.close()


def test_verification_success_after_proof_expiry_returns_no_proof(monkeypatch):
    """When the proof window closed while the container ran, the honest result
    carries no verification_id: nothing redeemable may be handed out."""
    from datetime import datetime, timedelta, timezone

    async def execute(self, activity_name, payload):
        return {"ok": True, "response_non_empty": True, "latency_ms": 12}

    client, repo = _candidate_client(monkeypatch, execute)

    async def expire_mark(operation_id):
        return None

    # The row expires between activity success and the marking step.
    import app.domain.provider_configs.service as service_module

    original_mark = service_module.ProviderConfigService.mark_candidate_operation_verified

    async def expired_mark(self, operation_id):
        row = await self.repository.get_candidate_operation(operation_id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        return await original_mark(self, operation_id)

    monkeypatch.setattr(service_module.ProviderConfigService,
                        "mark_candidate_operation_verified", expired_mark)
    response = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**CANDIDATE_BODY, "model": "candidate/model-a"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "verification_id" not in response.json()
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
        return {"ok": True, "response_non_empty": True, "latency_ms": 12}
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


DISCOVERY_ERROR_RESULT = {"ok": False, "error": {
    "code": "PROVIDER_DISCOVERY_FAILED",
    "message_key": "errors.provider.verification_failed", "params": {},
}}


def test_candidate_model_discovery_translates_keyed_activity_errors(monkeypatch):
    """A failed discovery container run returns the stable keyed error and
    releases the candidate operation; no activity text reaches the response."""

    async def execute(self, activity_name, payload):
        assert activity_name == "list_opencode_candidate_models"
        return DISCOVERY_ERROR_RESULT

    client, repo = _candidate_client(monkeypatch, execute)
    response = client.post("/providers/opencode/config/candidate/models", json=CANDIDATE_BODY)

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.verification_failed"
    assert repo.candidate_operations == {}
    client.close()


def test_saved_config_discovery_failure_surfaces_only_the_keyed_error(monkeypatch):
    async def execute(self, activity_name, payload):
        return DISCOVERY_ERROR_RESULT

    from app.api.routes.provider_configs import TemporalOpenCodeRuntime

    monkeypatch.setattr(TemporalOpenCodeRuntime, "_execute", execute)
    app = create_app()
    repo = MemoryRepository()
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="builder"))
    app.dependency_overrides[get_provider_config_service] = lambda: service
    client = TestClient(app)
    assert client.put("/providers/opencode/config", data={"name": "Probed Config"}, files=UPLOAD_FILES).status_code == 200

    response = client.post("/providers/opencode/config/verify", json={"config_id": repo.rows[0].id})

    assert response.status_code == 422
    assert response.json()["message_key"] == "errors.provider.verification_failed"
    client.close()


def test_temporal_outage_responses_never_carry_exception_text(monkeypatch):
    """The worker/API failure text (which could embed external details) never
    reaches the response; only the stable keyed error does."""
    sentinel = "SENTINEL-API-LEAK-CHECK"

    async def execute(self, activity_name, payload):
        raise RuntimeError(f"temporal unavailable: {sentinel}")

    client, repo = _candidate_client(monkeypatch, execute)
    models = client.post("/providers/opencode/config/candidate/models", json=CANDIDATE_BODY)
    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={**CANDIDATE_BODY, "model": "candidate/model-a"})

    for response in (models, verified):
        assert response.status_code == 422
        assert response.json()["message_key"] == "errors.provider.candidate_operation_unavailable"
        assert sentinel not in response.text
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


EDIT_CONFIG_BYTES = b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"new-config-key"}}}}'
EDIT_CONFIG_OBJECT = json.loads(EDIT_CONFIG_BYTES)
STORED_CONFIG_OBJECT = json.loads(UPLOAD_FILES["opencode_json"][1])
STORED_AUTH_OBJECT = json.loads(UPLOAD_FILES["auth_json"][1])


def _models_execute():
    async def execute(self, activity_name, payload):
        return ["candidate/model-a", "candidate/model-b"]
    return execute


def _edit_target_client(monkeypatch, execute):
    """A candidate client with one stored config+auth row owned by user-1."""
    client, repo = _candidate_client(monkeypatch, execute)
    service = ProviderConfigService(repo, "p9N0DDs9ZxgKYBEYEBEQzsSk0kjV3xCuQx0TLTPrgrc=")
    assert client.put("/providers/opencode/config", data={"name": "Stored Config"}, files=UPLOAD_FILES).status_code == 200
    return client, repo, service, repo.rows[0].id


def _operation_payload(service, operation_id):
    """Decrypt the live candidate operation payload (no consumption)."""
    import asyncio

    return asyncio.run(service.read_candidate_operation(operation_id, "user-1", "opencode"))


def test_edit_mode_candidate_verify_with_config_only_uses_the_stored_auth(monkeypatch):
    """Replacing only opencode.json of a stored instance must attest the
    EFFECTIVE pair — the uploaded configuration over the STORED credentials —
    so the proof matches exactly the pair the save will store."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _ok_verification_execute())

    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={"config_id": config_id, "config": EDIT_CONFIG_OBJECT, "model": "candidate/model-a"})

    assert verified.status_code == 200
    assert verified.json()["ok"] is True
    verification_id = verified.json()["verification_id"]
    # The operation carries the effective pair: uploaded config, stored auth.
    assert _operation_payload(service, verification_id) == {
        "config": EDIT_CONFIG_OBJECT, "auth": STORED_AUTH_OBJECT}

    saved = client.patch("/providers/opencode/config", data={
        "config_id": config_id, "name": "Stored Config", "verification_id": verification_id,
    }, files={"opencode_json": ("opencode.json", EDIT_CONFIG_BYTES, "application/json")})

    assert saved.status_code == 200
    # The saved pair equals the tested pair, so the proof redeems as verified.
    assert saved.json()["verification_status"] == "verified"
    assert repo.candidate_operations == {}
    client.close()


def test_edit_mode_candidate_verify_with_auth_only_uses_the_stored_config(monkeypatch):
    """Replacing only auth.json of a stored instance must attest the uploaded
    credentials over the STORED configuration, and the proof must redeem when
    the save stores exactly that effective pair."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _ok_verification_execute())

    rotated_auth = {"opencode": {"type": "api", "key": "rotated-key"}}
    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={"config_id": config_id, "auth": rotated_auth, "model": "candidate/model-a"})

    assert verified.status_code == 200
    assert verified.json()["ok"] is True
    verification_id = verified.json()["verification_id"]
    # The operation carries the effective pair: stored config, uploaded auth.
    assert _operation_payload(service, verification_id) == {
        "config": STORED_CONFIG_OBJECT, "auth": rotated_auth}

    saved = client.patch("/providers/opencode/config", data={
        "config_id": config_id, "name": "Stored Config", "verification_id": verification_id,
    }, files={"auth_json": ("auth.json", json.dumps(rotated_auth).encode(), "application/json")})

    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "verified"
    assert repo.candidate_operations == {}
    client.close()


def test_edit_mode_candidate_models_discovery_uses_the_effective_pair(monkeypatch):
    """Candidate model discovery in edit mode runs against the same effective
    pair the later verification and the save will use."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _models_execute())

    response = client.post("/providers/opencode/config/candidate/models",
                           json={"config_id": config_id, "config": EDIT_CONFIG_OBJECT})

    assert response.status_code == 200
    assert response.json() == {"valid": True, "violations": [],
                               "models": ["candidate/model-a", "candidate/model-b"]}
    operation = next(iter(repo.candidate_operations.values()))
    assert operation.purpose == "discovery"
    # The discovery operation also attests the effective pair: uploaded
    # config over the stored auth.
    assert _operation_payload(service, operation.id) == {
        "config": EDIT_CONFIG_OBJECT, "auth": STORED_AUTH_OBJECT}
    client.close()


def test_edit_mode_candidate_verification_rejects_unknown_and_foreign_config_ids(monkeypatch):
    """The edit-mode candidate flow resolves the targeted configuration under
    the same visibility model as the rest of the API and never stores
    credentials for a rejected target."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _ok_verification_execute())
    overrides = client.app.dependency_overrides
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-2", role=SimpleNamespace(value="runner"))
    assert client.put("/providers/opencode/config", data={"name": "Foreign Config"}, files=UPLOAD_FILES).status_code == 200
    foreign_id = next(row.id for row in repo.rows if row.user_id == "user-2")
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", role=SimpleNamespace(value="runner"))

    body = {"config": EDIT_CONFIG_OBJECT, "model": "candidate/model-a"}
    unknown = client.post("/providers/opencode/config/candidate/verify-model",
                          json={**body, "config_id": "missing-id"})
    foreign = client.post("/providers/opencode/config/candidate/verify-model",
                          json={**body, "config_id": foreign_id})

    assert unknown.status_code == 404
    assert unknown.json()["message_key"] == "errors.provider.config_not_found"
    assert foreign.status_code == 403
    assert foreign.json()["message_key"] == "errors.provider.forbidden"
    # A rejected target never reaches candidate-operation creation.
    assert repo.candidate_operations == {}
    client.close()


def test_edit_mode_candidate_requires_owner_or_admin_for_visible_shared_rows(monkeypatch):
    """A non-owner who can merely SEE a shared row (group/global) must not run
    an edit-mode candidate against it: the operation overlays caller-supplied
    files on the owner's stored credentials, so it could exfiltrate them."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _ok_verification_execute())
    overrides = client.app.dependency_overrides
    body = {"config": EDIT_CONFIG_OBJECT, "model": "candidate/model-a"}
    row = repo.rows[0]

    # Global row: visible to any authenticated caller, still owned by user-1.
    row.visibility = "global"
    row.group_id = None
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-2", role=SimpleNamespace(value="runner"))
    global_response = client.post("/providers/opencode/config/candidate/verify-model",
                                  json={**body, "config_id": config_id})
    assert global_response.status_code == 403
    assert global_response.json()["message_key"] == "errors.provider.forbidden"
    assert repo.candidate_operations == {}

    # Group row the caller belongs to: visible, still not owned.
    row.visibility = "group"
    row.group_id = "g1"
    repo.member_groups = {"user-2": ["g1"]}
    group_response = client.post("/providers/opencode/config/candidate/verify-model",
                                 json={**body, "config_id": config_id})
    assert group_response.status_code == 403
    assert group_response.json()["message_key"] == "errors.provider.forbidden"
    assert repo.candidate_operations == {}

    # An admin (non-owner) may target a visible row, matching the save path.
    row.visibility = "global"
    row.group_id = None
    overrides[get_current_user] = lambda: SimpleNamespace(
        id="admin-1", role=SimpleNamespace(value="admin"))
    admin_response = client.post("/providers/opencode/config/candidate/verify-model",
                                 json={**body, "config_id": config_id})
    assert admin_response.status_code == 200
    assert admin_response.json()["ok"] is True
    client.close()


def test_edit_mode_save_with_a_pair_different_from_the_proof_records_unverified(monkeypatch):
    """A proof earned for one effective pair proves nothing about a save that
    stores different files: the row is recorded honestly as unverified."""
    client, repo, service, config_id = _edit_target_client(monkeypatch, _ok_verification_execute())

    verified = client.post("/providers/opencode/config/candidate/verify-model",
                           json={"config_id": config_id, "config": EDIT_CONFIG_OBJECT, "model": "candidate/model-a"})
    verification_id = verified.json()["verification_id"]

    other_bytes = b'{"mcp":{},"provider":{"x":{"options":{"apiKey":"different-key"}}}}'
    saved = client.patch("/providers/opencode/config", data={
        "config_id": config_id, "name": "Stored Config", "verification_id": verification_id,
    }, files={"opencode_json": ("opencode.json", other_bytes, "application/json")})

    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "unverified"
    client.close()
