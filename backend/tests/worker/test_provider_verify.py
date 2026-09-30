import asyncio

from worker.activities import provider_verify
from worker.activities import agent as agent_module


def test_provider_verification_reports_missing_auth_without_starting_a_container(monkeypatch):
    async def config_files(user_id):
        return {"opencode.json": b'{"provider":{"opencode":{"models":{}}}}'}

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    result = asyncio.run(provider_verify.verify_opencode_model({"user_id": "owner-1", "model": "opencode/big-pickle"}))
    assert result == {"ok": False, "error": {
        "code": "PROVIDER_AUTH_MISSING", "message_key": "errors.provider.auth_missing",
        "params": {"provider": "opencode"},
    }}


def test_model_list_activity_uses_acp_session_model_options(monkeypatch, tmp_path):
    class FakeAdapter:
        def __init__(self):
            self.closed = False
            self._adapter = self
            self.started_with = []

        async def start_session(self, cfg):
            self.started_with.append(cfg)

        def list_models(self):
            return ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]

        async def close(self):
            self.closed = True

    adapter = FakeAdapter()
    async def config_files(user_id):
        return {"opencode.json": b'{"provider":{"opencode":{"options":{"apiKey":"test"}}}}'}
    async def start_session(*args, **kwargs):
        return adapter

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_models({"user_id": "owner-1"}))

    assert result == ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]
    assert adapter.started_with == [{"model": "default"}]
    assert adapter.closed is True
