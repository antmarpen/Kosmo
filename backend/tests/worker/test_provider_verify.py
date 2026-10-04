"""Safety contract for the provider probe activities (F5/F6).

Everything an activity returns crosses into Temporal history and the API
response: model names for discovery, a non-empty-response assertion plus
measured latency for verification, and stable keyed errors. Sentinel tests
prove that simulated agent output and external exception text never leak.
"""

import asyncio
import json

import pytest

from shared.agent_events import AgentError, AgentText, CompletionProposed
from shared.errors import NotFoundError
from worker.activities import provider_verify
from worker.activities import agent as agent_module

SENTINEL = "SENTINEL-SECRET-do-not-leak"
AUTH_FILE = b'[{"id":"cred_test","integrationID":"opencode","label":"API key","active":true,"value":{"type":"key","key":"synthetic"}}]'


def _serialized(result) -> str:
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str)
    return str(result)


def test_provider_verification_reports_missing_auth_without_starting_a_container(monkeypatch):
    async def config_files(user_id, config_id=None):
        return {"opencode.json": b'{"providers":{"opencode":{"models":{}}}}'}

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    result = asyncio.run(provider_verify.verify_opencode_model({"user_id": "owner-1", "model": "opencode/big-pickle"}))
    assert result == {"ok": False, "error": {
        "code": "PROVIDER_AUTH_MISSING", "message_key": "errors.provider.auth_missing",
        "params": {"provider": "opencode"},
    }}


def test_saved_config_activities_resolve_files_for_the_targeted_configuration(monkeypatch, tmp_path):
    """The saved-config probe decrypts exactly the targeted configuration's
    files: row A is probed even when other rows exist."""
    class FakeAdapter:
        def __init__(self):
            self.closed = False
            self._adapter = self

        async def start_session(self, cfg):
            pass

        async def send_prompt(self, prompt):
            pass

        async def events(self):
            yield AgentText(delta="ok")
            yield CompletionProposed()

        async def deliver_answer(self, answer, request_id):
            pass

        def list_models(self):
            return ["a/model-a", "a/model-b"]

        async def close(self):
            self.closed = True

    files_by_config = {
        "row-a": {"opencode.json": b'{"providers":{"a":{"options":{"apiKey":"k"}}}}',
                   "auth.json": b'[{"id":"a","integrationID":"a","label":"API key","active":true,"value":{"type":"key","key":"k"}}]'},
        "row-b": {"opencode.json": b'{"providers":{"b":{"options":{"apiKey":"k"}}}}',
                   "auth.json": b'[{"id":"b","integrationID":"b","label":"API key","active":true,"value":{"type":"key","key":"k"}}]'},
    }
    resolved_for = []
    started_files = []
    adapter = FakeAdapter()

    async def config_files(user_id, config_id=None):
        resolved_for.append(config_id)
        return files_by_config[config_id]

    async def start_session(cfg, workspace, **kwargs):
        started_files.append(kwargs["runtime_config_files"])
        return adapter

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_models({"user_id": "owner-1", "config_id": "row-a"}))
    verify_result = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "a/model-a", "config_id": "row-a"}))

    # Both probes resolved row A's files, never another row's.
    assert resolved_for == ["row-a", "row-a"]
    assert started_files == [files_by_config["row-a"], files_by_config["row-a"]]
    assert b'"b"' not in started_files[0] and b'"b"' not in started_files[1]
    assert result == {"models": ["a/model-a", "a/model-b"]}
    assert verify_result["ok"] is True
    assert adapter.closed is True


def test_saved_config_activities_report_a_missing_targeted_configuration(monkeypatch):
    async def config_files(user_id, config_id=None):
        return None

    monkeypatch.setattr(provider_verify, "_config_files", config_files)

    assert asyncio.run(provider_verify.list_opencode_models(
        {"user_id": "owner-1", "config_id": "gone"})) == {"models": []}
    result = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "m", "config_id": "gone"}))
    assert result == {"ok": False, "error": {
        "code": "PROVIDER_CONFIG_MISSING", "message_key": "errors.provider.config_not_found",
        "params": {},
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
    async def config_files(user_id, config_id=None):
        return {"opencode.json": b'{"providers":{"opencode":{"models":{}}}}', "auth.json": AUTH_FILE}
    async def start_session(*args, **kwargs):
        return adapter

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_models({"user_id": "owner-1"}))

    assert result == {"models": ["opencode/big-pickle", "opencode/ling-3.0-flash-fin-free"]}
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


CANDIDATE_CONFIG = {"providers": {"x": {"options": {"apiKey": "candidate-key"}}}}
CANDIDATE_AUTH = [{"id":"cred_x","integrationID":"x","label":"API key","active":True,
                   "value":{"type":"key","key":"candidate-secret"}}]


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
    store.rows["op-1"] = {"format":"v2", "config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

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

    assert result == {"models": ["candidate/model-a", "candidate/model-b"]}
    assert calls == [("consume", "op-1", "owner-1"), ("container", {"model": "default"})]
    assert adapter.runtime_files == {
        "format": "v2",
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
    store.rows["op-1"] = {"format":"v2", "config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

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
    # Only the non-empty-response assertion and latency cross the boundary:
    # no agent text may enter Temporal history or the API response.
    assert result["response_non_empty"] is True
    assert result["latency_ms"] >= 0
    assert "response_snippet" not in result
    assert calls[0] == ("consume", "op-1")
    assert calls[1] == ("container", {"model": "candidate/model-a"})
    assert adapter.runtime_files == {
        "format": "v2",
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
    store.rows["op-1"] = {"format":"v2", "config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

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
    assert result["response_non_empty"] is True
    assert "response_snippet" not in result
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
        raise RuntimeError(f"docker unavailable: {SENTINEL}")

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_candidate_models(
        {"operation_id": "op-1", "user_id": "owner-1"}))

    # Container/ACP failures normalize into the stable keyed error before the
    # activity boundary: no raw exception text reaches Temporal.
    assert result == {"ok": False, "error": {
        "code": "PROVIDER_DISCOVERY_FAILED",
        "message_key": "errors.provider.verification_failed", "params": {},
    }}
    assert SENTINEL not in _serialized(result)
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
    store.rows["op-1"] = {"format":"v2", "config": {"providers": {"x": {}}}, "auth": None}

    async def consume(operation_id, user_id):
        return await store.consume(operation_id, user_id)

    monkeypatch.setattr(provider_verify, "_consume_candidate_operation", consume)

    result = asyncio.run(provider_verify.verify_opencode_candidate_model(
        {"operation_id": "op-1", "user_id": "owner-1", "model": "candidate/model-a"}))

    assert result == {"ok": False, "error": {
        "code": "PROVIDER_AUTH_MISSING", "message_key": "errors.provider.auth_missing",
        "params": {"provider": "opencode"},
    }}


def test_candidate_runtime_bundle_marks_native_v2_format():
    resolved = {"format": "v2", "config": CANDIDATE_CONFIG, "auth": CANDIDATE_AUTH}

    files = provider_verify._candidate_files(resolved)

    assert files["format"] == "v2"
    assert json.loads(files["opencode.json"]) == CANDIDATE_CONFIG
    assert json.loads(files["auth.json"]) == CANDIDATE_AUTH


def test_unavailable_configured_model_blocks_provider_prompt(monkeypatch, tmp_path):
    class MissingModelAdapter:
        prompted = False
        async def start_session(self, cfg):
            raise ValueError("Configured model is not available in the OpenCode ACP session")
        async def send_prompt(self, prompt):
            self.prompted = True
        async def close(self):
            pass

    adapter = MissingModelAdapter()
    async def config_files(user_id, config_id=None):
        return {"format": "v2", "opencode.json": b'{"providers":{}}', "auth.json": AUTH_FILE}
    async def start_session(*args, **kwargs):
        return adapter

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)
    result = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "private/missing"}))

    assert result["ok"] is False
    assert result["error"]["message_key"] == "errors.provider.verification_failed"
    assert adapter.prompted is False


def test_verification_result_never_carries_simulated_agent_text(monkeypatch, tmp_path):
    """F6: agent output must not enter the activity result (Temporal history
    and the API response are downstream of it)."""

    class LeakyAdapter:
        def __init__(self):
            self.closed = False

        async def start_session(self, cfg):
            pass

        async def send_prompt(self, prompt):
            pass

        async def events(self):
            yield AgentText(delta=f"all ok. credentials: {SENTINEL}")
            yield CompletionProposed()

        async def deliver_answer(self, answer, request_id):
            pass

        async def close(self):
            self.closed = True

    adapter = LeakyAdapter()

    async def config_files(user_id, config_id=None):
        return {"opencode.json": b'{"providers":{"opencode":{"models":{}}}}', "auth.json": AUTH_FILE}

    async def start_session(cfg, workspace, **kwargs):
        return adapter

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "candidate/model-a"}))

    assert result["ok"] is True
    assert result["response_non_empty"] is True
    assert isinstance(result["latency_ms"], int)
    assert set(result) == {"ok", "response_non_empty", "latency_ms"}
    assert SENTINEL not in _serialized(result)


def test_external_exception_text_never_reaches_activity_results(monkeypatch, tmp_path):
    """F6: container/ACP failures normalize into the stable keyed errors."""

    class ExplodingAdapter:
        async def start_session(self, cfg):
            pass

        async def send_prompt(self, prompt):
            raise RuntimeError(f"ACP transport died: {SENTINEL}")

        async def events(self):
            yield AgentText(delta="ok")
            yield CompletionProposed()

        async def deliver_answer(self, answer, request_id):
            pass

        async def close(self):
            pass

    async def config_files(user_id, config_id=None):
        return {"opencode.json": b'{"providers":{"opencode":{"models":{}}}}', "auth.json": AUTH_FILE}

    async def start_session(cfg, workspace, **kwargs):
        return ExplodingAdapter()

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "candidate/model-a"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "PROVIDER_VERIFICATION_FAILED"
    assert result["error"]["message_key"] == "errors.provider.verification_failed"
    assert SENTINEL not in _serialized(result)


def test_discovery_container_failure_normalizes_into_keyed_error(monkeypatch, tmp_path):
    """F6: model discovery wraps container/ACP failures in the stable keyed
    error instead of letting the exception escape into Temporal."""

    async def config_files(user_id, config_id=None):
        return {"opencode.json": b'{"providers":{"opencode":{"models":{}}}}', "auth.json": AUTH_FILE}

    async def start_session(cfg, workspace, **kwargs):
        raise RuntimeError(f"container start failed: {SENTINEL}")

    monkeypatch.setattr(provider_verify, "_config_files", config_files)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    result = asyncio.run(provider_verify.list_opencode_models({"user_id": "owner-1"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "PROVIDER_DISCOVERY_FAILED"
    assert result["error"]["message_key"] == "errors.provider.verification_failed"
    assert SENTINEL not in _serialized(result)


def test_database_failures_normalize_into_keyed_errors(monkeypatch):
    """Even storage-layer exceptions (whose text can carry SQL details) are
    normalized before crossing the activity boundary."""

    async def config_files(user_id, config_id=None):
        raise RuntimeError(f"asyncpg: constraint violated: {SENTINEL}")

    monkeypatch.setattr(provider_verify, "_config_files", config_files)

    discovered = asyncio.run(provider_verify.list_opencode_models({"user_id": "owner-1"}))
    verified = asyncio.run(provider_verify.verify_opencode_model(
        {"user_id": "owner-1", "model": "m"}))

    for result in (discovered, verified):
        assert result["ok"] is False
        assert result["error"]["message_key"] == "errors.provider.verification_failed"
        assert SENTINEL not in _serialized(result)
