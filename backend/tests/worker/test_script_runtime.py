"""Behavioral contract for function-body script execution (WP-04)."""

import asyncio
import json
import os
from pathlib import Path

import pytest


class _Container:
    def __init__(self, command, workspace, *, exit_code=0):
        self.command = command
        self.workspace = workspace
        self.exit_code = exit_code
        self.killed = False

    def start(self):
        pass

    def wait(self, timeout):
        if self.command and str(self.command[0]).endswith("script_runner.py"):
            descriptor_path = self.workspace / "descriptor.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["output_dir"] = str(self.workspace / "output")
            for item in descriptor["inputs"].values():
                item["path"] = str(self.workspace / "inputs" / Path(item["path"]).name)
            descriptor_path.write_text(json.dumps(descriptor))
            from worker.script_runner import run_descriptor
            try:
                run_descriptor(descriptor_path)
            except Exception:
                self.exit_code = 1
        if self.exit_code == "timeout":
            raise TimeoutError("container timeout")
        return {"StatusCode": self.exit_code}

    def logs(self):
        return b""

    def kill(self):
        self.killed = True

    def remove(self, force=True):
        pass


class _Mount:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Fake Docker and durable repository boundaries; leave runtime behavior real."""
    import docker
    import worker.activities.checkpoint as checkpoint
    import worker.activities.sandbox as module

    containers = []

    def create(*args, **kwargs):
        mount = kwargs["mounts"][0].kwargs
        container = _Container(kwargs.get("command"), tmp_path / mount["subpath"])
        containers.append(container)
        return container

    client = type("Client", (), {"containers": type("Containers", (), {"create": staticmethod(create)})()})()
    monkeypatch.setattr(docker, "from_env", lambda: client)
    monkeypatch.setattr(docker.types, "Mount", _Mount)
    monkeypatch.setattr(module, "TASK_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(module, "TASK_STORAGE_VOLUME", "test-volume")
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", _missing_result)

    records = []

    class Repo:
        def __init__(self, db):
            pass

        async def create(self, **kwargs):
            records.append(kwargs)
            return type("Artifact", (), {"id": f"artifact-{len(records)}", "sha256": kwargs["sha256"], "media_type": kwargs["media_type"]})()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def commit(self):
            pass

    import app.core.db as db_module
    import app.domain.artifacts.repository as repository

    monkeypatch.setattr(db_module, "AsyncSessionLocal", Session)
    monkeypatch.setattr(repository, "ArtifactRepository", Repo)
    return module.run_script, containers, records


async def _missing_result(*args, **kwargs):
    return None


def _run(sandbox, code, inputs, outputs):
    activity, _, _ = sandbox
    return asyncio.run(activity({
        "task_id": "runtime-test",
        "node": {"id": "script", "type": "script", "code": code, "inputs": list(inputs), "outputs": outputs},
        "inputs": inputs,
        "iteration": 0,
        "attempt": 1,
    }))


def _contract(*, required_terms=None):
    return {"result": {"levels": [
        {"name": "syntax", "message_key": "validation.syntax", "params_schema": {"format": "text"}},
        {"name": "format", "message_key": "validation.format", "params_schema": {}},
        {"name": "rules", "message_key": "validation.rules", "params_schema": {"required_terms": required_terms or []}},
    ]}}


def test_one_invalid_output_blocks_all_artifact_persistence(sandbox):
    activity, containers, records = sandbox
    result = asyncio.run(activity({
        "task_id": "runtime-test",
        "node": {"id": "script", "type": "script", "code": "good = 'safe'\nbad = 'wrong'\nreturn good, bad",
                 "outputs": ["good", "bad"], "output_validation": {
                     "good": _contract()["result"], "bad": _contract(required_terms=["required"])["result"]}},
        "inputs": {}, "iteration": 0, "attempt": 1,
    }))

    assert result == {"state": "failed", "outputs": {}, "error": {
        "code": "OUTPUT_VALIDATION_FAILED", "message_key": "errors.output.validation_failed",
        "params": {}, "details": [{"artifact": "bad", "level": "rules",
                                    "message_key": "validation.rules",
                                    "params": {"reason": "required_terms_missing", "terms": ["required"]}}],
    }}
    assert records == []
    assert len(containers) == 1
    assert not (Path(containers[0].workspace.parent) / "artifacts").exists()


def test_valid_configured_script_outputs_are_persisted(sandbox):
    activity, _, records = sandbox
    result = asyncio.run(activity({
        "task_id": "runtime-test", "node": {"id": "script", "type": "script",
        "code": "result = 'required phrase'\nreturn result", "outputs": ["result"],
        "output_validation": _contract(required_terms=["required"])},
        "inputs": {}, "iteration": 0, "attempt": 1,
    }))

    assert result["state"] == "success"
    assert len(records) == 1


@pytest.mark.docker
def test_real_container_invalid_output_is_not_recorded():
    task_id = os.getenv("KOSMO_DOCKER_TEST_TASK_ID")
    if not task_id:
        pytest.skip("Set KOSMO_DOCKER_TEST_TASK_ID to a disposable task id")

    from sqlalchemy import select
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Artifact
    from worker.activities.sandbox import run_script

    node_id = "script-validation-proof"
    attempt = 987655

    async def exercise():
        result = await run_script({
            "task_id": task_id,
            "node": {"id": node_id, "type": "script", "outputs": ["result"],
                     "code": "result = 'not acceptable'\nreturn result",
                     "output_validation": _contract(required_terms=["required"])},
            "inputs": {}, "iteration": 0, "attempt": attempt,
        })
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Artifact).where(
                Artifact.task_id == task_id, Artifact.node_id == node_id,
                Artifact.attempt == attempt, Artifact.logical_name == "result"))
        return result, row

    result, row = asyncio.run(exercise())
    assert result["state"] == "failed", result
    assert result["outputs"] == {}
    assert result["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
    assert row is None


def test_typed_inputs_return_two_individual_named_artifacts(sandbox):
    result = _run(sandbox, "return size, distance", {"size": 4, "distance": 9}, ["size", "distance"])

    assert result["state"] == "success"
    assert set(result["outputs"]) == {"size", "distance"}
    assert json.loads(Path(result["outputs"]["size"]["storage_path"]).read_text()) == 4
    assert json.loads(Path(result["outputs"]["distance"]["storage_path"]).read_text()) == 9


def test_sandbox_command_uses_the_image_entrypoint_without_duplicating_python(sandbox):
    # The sandbox image's ENTRYPOINT is `python`; the container command must be
    # the runner script only, otherwise the process becomes `python python ...`.
    _run(sandbox, "out = 1\nreturn out", {}, ["out"])
    _, containers, _ = sandbox

    assert containers and containers[0].command[0] == "/opt/kosmo/script_runner.py"


@pytest.mark.parametrize(
    ("value", "media_type", "expected"),
    [("hello", "text/plain", "hello"), ({"ok": True}, "application/json", {"ok": True}),
     ([1, "two"], "application/json", [1, "two"]), (3, "application/json", 3)],
)
def test_returned_values_are_serialized_with_contract_media_type(sandbox, value, media_type, expected):
    name = "result"
    result = _run(sandbox, f"result = {value!r}\nreturn result", {}, [name])

    assert result["state"] == "success"
    artifact = result["outputs"][name]
    assert artifact["media_type"] == media_type
    content = Path(artifact["storage_path"]).read_text(encoding="utf-8")
    assert content == expected if isinstance(expected, str) else json.loads(content) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_return_is_rejected(sandbox, value):
    result = _run(sandbox, f"result = {value!r}\nreturn result", {}, ["result"])
    assert result["state"] == "failed"


@pytest.mark.parametrize(
    ("media_type", "content", "expected_type"),
    [("text/plain", "hello", str), ("text/markdown", "# heading", str),
     ("application/json", '{"a": 1}', dict), ("application/json", '[1, 2]', list)],
)
def test_artifact_input_is_parsed_as_typed_variable(sandbox, tmp_path, media_type, content, expected_type):
    source = tmp_path / "input"
    source.write_text(content, encoding="utf-8")
    result = _run(sandbox, "return value", {"value": {"storage_path": str(source), "media_type": media_type}}, ["value"])
    assert result["state"] == "success"
    assert result["outputs"]["value"]["media_type"] == ("text/plain" if expected_type is str else "application/json")


def test_unsupported_input_media_type_returns_keyed_failure(sandbox, tmp_path):
    source = tmp_path / "input"
    source.write_bytes(b"binary")
    result = _run(sandbox, "return value", {"value": {"storage_path": str(source), "media_type": "image/png"}}, ["value"])
    assert result["state"] == "failed"
    assert result["error"]["params"].get("input") == "value"


def test_returned_artifact_can_be_passed_to_downstream_script(sandbox):
    first = _run(sandbox, "answer = 42\nreturn answer", {}, ["answer"])
    second = _run(sandbox, "return answer", {"answer": first["outputs"]["answer"]}, ["answer"])
    assert second["state"] == "success"
    assert json.loads(Path(second["outputs"]["answer"]["storage_path"]).read_text()) == 42


@pytest.mark.parametrize(
    ("code", "outputs"),
    [("return", ["answer"]), ("return 1", ["answer"]), ("return answer, other", ["answer"]),
     ("answer = 1", ["answer"])],
)
def test_missing_return_values_arity_errors_and_fallthrough_fail(sandbox, code, outputs):
    result = _run(sandbox, code, {}, outputs)
    assert result["state"] == "failed"


def test_wrong_return_type_fails_for_declared_output_contract(sandbox):
    result = _run(sandbox, "answer = object()\nreturn answer", {}, ["answer"])
    assert result["state"] == "failed"


def test_timeout_returns_timeout_failure(sandbox, monkeypatch):
    activity, containers, _ = sandbox
    # Exercise the public activity timeout outcome without substituting its behavior.
    import worker.activities.sandbox as module
    original = module.asyncio.to_thread

    async def timeout_wait(function, *args, **kwargs):
        if getattr(function, "__name__", "") == "wait":
            raise TimeoutError("timeout")
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", timeout_wait)
    result = asyncio.run(activity({"task_id": "runtime-test", "node": {"id": "script", "code": "return x", "outputs": ["x"]}, "inputs": {}}))
    assert result["error"]["code"] == "SCRIPT_TIMEOUT"


def test_retry_recovers_completed_script_without_second_container_execution(sandbox, monkeypatch):
    activity, containers, _ = sandbox
    import worker.activities.checkpoint as checkpoint
    recovered = {"state": "success", "outputs": {"answer": {"id": "a", "storage_path": "/durable/answer", "sha256": "hash", "media_type": "application/json"}}, "error": None}
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", lambda *args, **kwargs: _return(recovered))

    result = asyncio.run(activity({"task_id": "runtime-test", "node": {"id": "script", "code": "raise Exception()", "outputs": ["answer"]}, "inputs": {}}))
    assert result == recovered
    assert containers == []


async def _return(value):
    return value
