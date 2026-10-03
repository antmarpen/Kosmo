import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from worker.validation_runner import run_descriptor, run_rule


@pytest.mark.parametrize(("body", "expected"), [("return True", True), ("return False", False)])
def test_rule_body_returns_exact_boolean(tmp_path, body, expected):
    result = run_descriptor(_descriptor(tmp_path, body))
    assert result == {"passed": expected, "reason": "passed" if expected else "rule_failed"}


@pytest.mark.parametrize("body", ["return 1", "return None", "value == 1"])
def test_invalid_or_missing_return_fails_closed(tmp_path, body):
    result = run_descriptor(_descriptor(tmp_path, body))
    assert result == {"passed": False, "reason": "invalid_result"}


def test_rule_exception_fails_closed_without_traceback(tmp_path):
    result = run_descriptor(_descriptor(tmp_path, "raise RuntimeError('secret traceback')"))
    assert result == {"passed": False, "reason": "execution_error"}
    assert "secret" not in json.dumps(result)


def test_rule_receives_value_and_original_content(tmp_path):
    result = run_descriptor(_descriptor(tmp_path, "return value['answer'] == 42 and content == 'original text'"))
    assert result["passed"] is True


def test_malformed_result_fails_closed(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text('{"passed": "yes"}', encoding="utf-8")
    from worker.validation_runner import read_result
    assert read_result(result_path) == {"passed": False, "reason": "invalid_result"}


def test_missing_fresh_result_fails_closed_even_if_workspace_has_old_result(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "result.json").write_text('{"passed":true,"reason":"passed"}', encoding="utf-8")
    class Container:
        def start(self): pass
        def wait(self, timeout): return {"StatusCode": 0}
        def remove(self, force): pass
    class Client:
        containers = SimpleNamespace(create=lambda *args, **kwargs: Container())
    docker = SimpleNamespace(types=SimpleNamespace(Mount=lambda **kwargs: kwargs))
    result = asyncio.run(run_rule("return True", {}, "", client=Client(), docker_module=docker,
                                  image="test", workspace=tmp_path))
    assert result == {"passed": False, "reason": "invalid_result"}


def test_docker_runner_uses_python_entrypoint_and_restrictive_mounts(tmp_path):
    class Container:
        def start(self): pass
        def wait(self, timeout):
            result_path = tmp_path / "result" / "result.json"
            result_path.write_text('{"passed":true,"reason":"passed"}', encoding="utf-8")
            return {"StatusCode": 0}
        def remove(self, force): self.removed = force
    container = Container()
    class Containers:
        def create(self, image, **kwargs):
            assert kwargs["command"][0] == "/opt/kosmo/validation_runner.py"
            assert "python" not in kwargs["command"]
            assert kwargs["network_mode"] == "none" and kwargs["read_only"] is True
            assert kwargs["user"] == "10001:10001"
            assert len(kwargs["mounts"]) == 2
            return container
    class Client:
        containers = Containers()
    class Mount:
        def __init__(self, **kwargs): self.kwargs = kwargs
    class Docker:
        types = SimpleNamespace(Mount=Mount)
    result = asyncio.run(run_rule("return True", {"n": 1}, "original", client=Client(), docker_module=Docker,
                                  image="test-image", workspace=tmp_path))
    assert result == {"passed": True, "reason": "passed"}
    assert container.removed is True


def test_docker_timeout_kills_and_always_removes_container(tmp_path):
    class Container:
        killed = False
        removed = False
        def start(self): pass
        def wait(self, timeout): raise TimeoutError()
        def kill(self): self.killed = True
        def remove(self, force): self.removed = force
    container = Container()
    class Client:
        containers = SimpleNamespace(create=lambda *args, **kwargs: container)
    class Mount:
        def __init__(self, **kwargs): self.kwargs = kwargs
    docker = SimpleNamespace(types=SimpleNamespace(Mount=Mount))
    result = asyncio.run(run_rule("return True", {}, "text", client=Client(), docker_module=docker,
                                  image="test", workspace=tmp_path))
    assert result == {"passed": False, "reason": "timeout"}
    assert container.killed and container.removed


@pytest.mark.docker
def test_real_sandbox_rule_cannot_access_network_or_unmounted_paths(tmp_path):
    import docker
    client = docker.from_env()
    try:
        client.images.get("kosmo-sandbox:local")
    except docker.errors.ImageNotFound:
        pytest.skip("Build kosmo-sandbox:local to run sandbox proof")
    body = """\
import os
import socket
from pathlib import Path
try:
    Path('/request/forbidden-write').write_text('no')
    return False
except OSError:
    pass
try:
    socket.create_connection(('1.1.1.1', 53), timeout=1)
    return False
except OSError:
    pass
return (os.geteuid() != 0 and not Path('/request/unrelated-task-secret').exists()
        and not Path('/workspace/unrelated-task-secret').exists())
"""
    result = asyncio.run(run_rule(body, {"ok": True}, "content", client=client, image="kosmo-sandbox:local",
                                  workspace=tmp_path))
    assert result == {"passed": True, "reason": "passed"}


def _descriptor(directory: Path, body: str) -> Path:
    descriptor = directory / "descriptor.json"
    descriptor.write_text(json.dumps({"rules": body, "value": {"answer": 42},
                                      "content": "original text", "result_path": str(directory / "result.json")}),
                          encoding="utf-8")
    return descriptor
