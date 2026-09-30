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

    without_provider = handler.validate_config({"model": "opencode/big-pickle"}, None)
    assert {item["code"] for item in without_provider} == {"auth_missing", "providers_missing"}

    ignored_only = {**VALID_CONFIG, "mcp": {"malformed": "ignored"}, "skills": ["also ignored"]}
    assert handler.validate_config(ignored_only, VALID_AUTH) == []


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
