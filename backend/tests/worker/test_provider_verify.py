import asyncio
import json

import pytest

from shared.agent_events import AgentText, CompletionProposed
from shared.errors import NotFoundError
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


class CandidateOperationStore:
    """Fake of the single-use encrypted candidate operation boundary."""

    def __init__(self):
        self.rows = {}

    async def consume(self, operation_id, user_id):
        row = self.rows.pop(operation_id, None)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        return row


CANDIDATE_CONFIG = {"provider": {"x": {"options": {"apiKey": "candidate-key"}}}}
CANDIDATE_AUTH = {"x": {"key": "candidate-secret"}}


def test_candidate_model_list_activity_consumes_operation_before_container(monkeypatch, tmp_path):
    class FakeAdapter:
        def __init__(self):
            self.closed = False
            self._adapter = self
            self.started_with = []
            self.runtime_files = None

        async def start_session(self, cfg):
            self.started_with.append(cfg)

        def list_models(self):
            return ["candidate/model-a", "candidate/model-b"]

        async def close(self):
            self.closed = True

    adapter = FakeAdapter()
    calls = []
    store = CandidateOperationStore()
    store.rows["op-1"] = {"config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

    async def consume(operation_id, user_id):
        calls.append(("consume", operation_id, user_id))
        return await store.consume(operation_id, user_id)

    async def start_session(cfg, workspace, **kwargs):
        calls.append(("container", cfg))
        adapter.runtime_files = kwargs["runtime_config_files"]
        return adapter

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_candidate_models(
        {"operation_id": "op-1", "user_id": "owner-1"}))

    assert result == ["candidate/model-a", "candidate/model-b"]
    assert calls == [("consume", "op-1", "owner-1"), ("container", {"model": "default"})]
    assert adapter.runtime_files == {
        "opencode.json": json.dumps(CANDIDATE_CONFIG).encode("utf-8"),
        "auth.json": json.dumps(CANDIDATE_AUTH).encode("utf-8"),
    }
    assert adapter.started_with == [{"model": "default"}]
    assert adapter.closed is True
    assert "op-1" not in store.rows


def test_candidate_model_verification_consumes_before_container_and_propagates_result(monkeypatch, tmp_path):
    class FakeAdapter:
        def __init__(self):
            self.closed = False
            self._adapter = self
            self.prompts = []
            self.runtime_files = None

        async def start_session(self, cfg):
            self.model = cfg["model"]

        async def send_prompt(self, prompt):
            self.prompts.append(prompt)

        async def events(self):
            yield AgentText(delta="ok")
            yield CompletionProposed()

        async def deliver_answer(self, answer, request_id):
            pass

        async def close(self):
            self.closed = True

    adapter = FakeAdapter()
    calls = []
    store = CandidateOperationStore()
    store.rows["op-1"] = {"config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

    async def consume(operation_id, user_id):
        calls.append(("consume", operation_id))
        return await store.consume(operation_id, user_id)

    async def start_session(cfg, workspace, **kwargs):
        calls.append(("container", cfg))
        adapter.runtime_files = kwargs["runtime_config_files"]
        return adapter

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.verify_opencode_candidate_model(
        {"operation_id": "op-1", "user_id": "owner-1", "model": "candidate/model-a"}))

    assert result["ok"] is True
    assert result["response_snippet"] == "ok"
    assert result["latency_ms"] >= 0
    assert calls[0] == ("consume", "op-1")
    assert calls[1] == ("container", {"model": "candidate/model-a"})
    assert adapter.runtime_files == {
        "opencode.json": json.dumps(CANDIDATE_CONFIG).encode("utf-8"),
        "auth.json": json.dumps(CANDIDATE_AUTH).encode("utf-8"),
    }
    assert adapter.closed is True
    assert "op-1" not in store.rows


def test_candidate_verification_without_consumption_keeps_operation_as_proof(monkeypatch, tmp_path):
    class FakeAdapter:
        def __init__(self):
            self.closed = False

        async def start_session(self, cfg):
            pass

        async def send_prompt(self, prompt):
            pass

        async def events(self):
            yield AgentText(delta="ok")
            yield CompletionProposed()

        async def deliver_answer(self, answer, request_id):
            pass

        async def close(self):
            self.closed = True

    adapter = FakeAdapter()
    calls = []
    store = CandidateOperationStore()
    store.rows["op-1"] = {"config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

    async def consume(operation_id, user_id):
        calls.append("consume")
        return await store.consume(operation_id, user_id)

    async def load(operation_id, user_id):
        calls.append("load")
        row = store.rows.get(operation_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        return row

    async def start_session(cfg, workspace, **kwargs):
        calls.append("container")
        return adapter

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)
    monkeypatch.setattr(provider_verify, "_load_candidate_operation", load)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.verify_opencode_candidate_model(
        {"operation_id": "op-1", "user_id": "owner-1", "model": "candidate/model-a",
         "consume": False}))

    assert result["ok"] is True
    assert result["response_snippet"] == "ok"
    # The non-consuming variant reads the credentials without consuming the
    # operation so the API can redeem it afterwards as single-use proof.
    assert calls == ["load", "container"]
    assert "op-1" in store.rows
    assert adapter.closed is True


def test_candidate_container_failure_still_leaves_no_operation_row(monkeypatch, tmp_path):
    calls = []
    store = CandidateOperationStore()
    store.rows["op-1"] = {"config": CANDIDATE_CONFIG, "auth": None}

    async def consume(operation_id, user_id):
        calls.append("consume")
        return await store.consume(operation_id, user_id)

    async def start_session(cfg, workspace, **kwargs):
        calls.append("container")
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    with pytest.raises(RuntimeError):
        asyncio.run(provider_verify.list_opencode_candidate_models(
            {"operation_id": "op-1", "user_id": "owner-1"}))

    assert calls == ["consume", "container"]
    assert "op-1" not in store.rows


def test_candidate_verification_with_unknown_operation_returns_structured_error(monkeypatch):
    async def consume(operation_id, user_id):
        raise NotFoundError("errors.provider.config_not_found")

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)

    result = asyncio.run(provider_verify.verify_opencode_candidate_model(
        {"operation_id": "gone", "user_id": "owner-1", "model": "candidate/model-a"}))

    assert result == {"ok": False, "error": {
        "code": "PROVIDER_CONFIG_MISSING", "message_key": "errors.provider.config_not_found",
        "params": {},
    }}


def test_candidate_verification_without_usable_credentials_reports_auth_missing(monkeypatch):
    store = CandidateOperationStore()
    store.rows["op-1"] = {"config": {"provider": {"x": {}}}, "auth": None}

    async def consume(operation_id, user_id):
        return await store.consume(operation_id, user_id)

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)

    result = asyncio.run(provider_verify.verify_opencode_candidate_model(
        {"operation_id": "op-1", "user_id": "owner-1", "model": "candidate/model-a"}))

    assert result == {"ok": False, "error": {
        "code": "PROVIDER_AUTH_MISSING", "message_key": "errors.provider.auth_missing",
        "params": {"provider": "opencode"},
    }}
