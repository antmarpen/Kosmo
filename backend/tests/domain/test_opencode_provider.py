import asyncio

from app.integrations.providers.opencode import OpenCodeProviderHandler


VALID_CONFIG = {
    "model": "opencode/big-pickle",
    "provider": {"opencode": {"name": "OpenCode Zen", "options": {"baseURL": "https://opencode.ai/zen/v1"},
                                "models": {"big-pickle": {"name": "Big Pickle"}}}},
    "mcp": {"ignored": {"type": "local"}},
    "skills": {"ignored": True},
}
VALID_AUTH = {"opencode": {"type": "api", "key": "synthetic-test-key"}}
NATIVE_CONFIG = {"$schema": "https://opencode.ai/config.json", "model": "anthropic/claude-sonnet-4-5"}
NATIVE_AUTH_API = {"anthropic": {"type": "api", "key": "synthetic-native-key"}}
NATIVE_AUTH_OAUTH = {"anthropic": {"type": "oauth", "access": "synthetic-access", "refresh": "synthetic-refresh"}}


class FakeRuntime:
    def __init__(self, models=None, verification=None):
        self.models = models or ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]
        self.verification = verification or {"ok": True, "response_snippet": "ok", "latency_ms": 12}
        self.calls = []

    async def list_models(self, user_id):
        self.calls.append(("list", user_id))
        return self.models

    async def verify_model(self, user_id, model):
        self.calls.append(("verify", user_id, model))
        if isinstance(self.verification, Exception):
            raise self.verification
        if asyncio.iscoroutine(self.verification):
            return await self.verification
        return self.verification


def test_opencode_validation_checks_provider_auth_and_model_subset_only():
    handler = OpenCodeProviderHandler(FakeRuntime())
    assert handler.validate_config(VALID_CONFIG, VALID_AUTH) == []

    without_auth = handler.validate_config(VALID_CONFIG, None)
    assert {item["code"] for item in without_auth} == {"auth_missing"}

    ignored_only = {**VALID_CONFIG, "mcp": {"malformed": "ignored"}, "skills": ["also ignored"]}
    assert handler.validate_config(ignored_only, VALID_AUTH) == []


def test_native_config_without_custom_provider_map_validates_with_separate_auth():
    handler = OpenCodeProviderHandler(FakeRuntime())
    assert handler.validate_config(NATIVE_CONFIG, NATIVE_AUTH_API) == []
    assert handler.validate_config(NATIVE_CONFIG, NATIVE_AUTH_OAUTH) == []
    assert handler.validate_config({**NATIVE_CONFIG, "provider": {}}, NATIVE_AUTH_API) == []
    multi_provider_auth = {**NATIVE_AUTH_API, "openai": {"type": "api", "key": "synthetic-openai"}}
    assert handler.validate_config(NATIVE_CONFIG, multi_provider_auth) == []


def test_native_config_without_custom_provider_map_still_requires_credentials():
    handler = OpenCodeProviderHandler(FakeRuntime())
    without_any = handler.validate_config(NATIVE_CONFIG, None)
    assert {item["code"] for item in without_any} == {"auth_missing"}

    empty_auth = handler.validate_config(NATIVE_CONFIG, {})
    assert {item["code"] for item in empty_auth} == {"auth_missing"}

    credential_less = handler.validate_config(NATIVE_CONFIG, {"anthropic": {"type": "oauth"}})
    assert {item["code"] for item in credential_less} == {"auth_missing"}


def test_supplied_malformed_provider_and_auth_entries_are_rejected():
    handler = OpenCodeProviderHandler(FakeRuntime())
    not_an_object = handler.validate_config({**NATIVE_CONFIG, "provider": "anthropic"}, NATIVE_AUTH_API)
    assert {item["code"] for item in not_an_object} == {"providers_missing"}

    bad_entries = handler.validate_config(
        {**NATIVE_CONFIG, "provider": {"anthropic": {"options": "oops", "models": ["x"]}}},
        NATIVE_AUTH_API)
    assert {item["code"] for item in bad_entries} == {"provider_options_invalid", "models_invalid"}

    bad_model = handler.validate_config({**NATIVE_CONFIG, "model": "   "}, NATIVE_AUTH_API)
    assert {item["code"] for item in bad_model} == {"model_invalid"}

    auth_not_object = handler.validate_config(VALID_CONFIG, ["anthropic"])
    assert {item["code"] for item in auth_not_object} == {"auth_invalid"}


def test_violations_are_structured_without_credential_material_or_file_reads(monkeypatch):
    def forbidden_open(*args, **kwargs):
        raise AssertionError("validate_config must not read the filesystem or home credentials")

    monkeypatch.setattr("builtins.open", forbidden_open)
    handler = OpenCodeProviderHandler(FakeRuntime())
    secret = "sk-synthetic-secret-value"
    violations = handler.validate_config(
        {"provider": {"anthropic": "oops", "openai": {"options": {"apiKey": secret}, "models": ["x"]}}},
        {"anthropic": {"type": "api", "key": secret}},
    )
    assert {item["code"] for item in violations} == {"provider_invalid", "models_invalid"}
    for item in violations:
        assert set(item) == {"code", "message_key", "params"}
        assert item["params"] == {}
        assert secret not in repr(item)
    assert handler.validate_config(NATIVE_CONFIG, NATIVE_AUTH_API) == []


def test_provider_handler_lists_runtime_models_and_verifies_selected_model():
    runtime = FakeRuntime()
    handler = OpenCodeProviderHandler(runtime, verify_timeout_seconds=1)
    models = asyncio.run(handler.list_models("user-1"))
    verification = asyncio.run(handler.verify_model("user-1", "opencode/big-pickle"))
    assert models == runtime.models
    assert verification["ok"] is True
    assert runtime.calls == [("list", "user-1"), ("verify", "user-1", "opencode/big-pickle")]


def test_provider_handler_structures_verification_failure_and_timeout():
    failed = OpenCodeProviderHandler(FakeRuntime(verification={"ok": False, "error": {"code": "MODEL_AUTH"}}))
    result = asyncio.run(failed.verify_model("user-1", "opencode/big-pickle"))
    assert result["ok"] is False
    assert result["error"]["code"] == "MODEL_AUTH"

    async def never_finishes():
        await asyncio.Event().wait()

    timed = OpenCodeProviderHandler(FakeRuntime(verification=never_finishes()), verify_timeout_seconds=0.01)
    result = asyncio.run(timed.verify_model("user-1", "opencode/big-pickle"))
    assert result["ok"] is False
    assert result["error"]["message_key"] == "errors.provider.verification_timeout"
