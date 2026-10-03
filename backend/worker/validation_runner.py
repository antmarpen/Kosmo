"""Isolated execution harness for optional authored Python validation rules."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

_REASONS = {"passed", "rule_failed", "invalid_result", "execution_error", "timeout"}
_MAX_RESULT_BYTES = 256
_TIMEOUT_SECONDS = 5


def run_descriptor(descriptor_path: str | Path) -> dict[str, bool | str]:
    """Execute a descriptor in the sandbox process and return only bounded status."""
    try:
        descriptor = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
        body, value, content = descriptor["rules"], descriptor["value"], descriptor["content"]
        if not isinstance(body, str) or not isinstance(content, str):
            return _result(False, "invalid_result")
        namespace: dict[str, Any] = {}
        wrapped = "def __kosmo_rule(value, content):\n" + "\n".join(
            "    " + line for line in body.splitlines()
        )
        if not body.strip():
            return _result(False, "invalid_result")
        exec(compile(wrapped, "<validation-rule>", "exec"), {"__builtins__": __builtins__}, namespace)
        passed = namespace["__kosmo_rule"](value, content)
        if type(passed) is not bool:
            return _result(False, "invalid_result")
        return _result(passed, "passed" if passed else "rule_failed")
    except BaseException:
        return _result(False, "execution_error")


def _result(passed: bool, reason: str) -> dict[str, bool | str]:
    return {"passed": passed, "reason": reason if reason in _REASONS else "invalid_result"}


def read_result(path: str | Path) -> dict[str, bool | str]:
    """Read and strictly validate a bounded result; malformed data fails closed."""
    try:
        encoded = Path(path).read_bytes()
        if len(encoded) > _MAX_RESULT_BYTES:
            return _result(False, "invalid_result")
        data = json.loads(encoded)
        if (not isinstance(data, dict) or set(data) != {"passed", "reason"}
                or type(data["passed"]) is not bool or data["reason"] not in _REASONS
                or data["passed"] != (data["reason"] == "passed")):
            return _result(False, "invalid_result")
        return data
    except Exception:
        return _result(False, "invalid_result")


async def run_rule(
    rules: str, value: Any, content: str, *, client: Any = None, docker_module: Any = None,
    image: str | None = None, workspace: str | Path | None = None,
    timeout_seconds: int = _TIMEOUT_SECONDS,
) -> dict[str, bool | str]:
    """Run one rule body with only read-only request and writable result mounts."""
    import docker

    docker_module = docker_module or docker
    client = client or await asyncio.to_thread(docker_module.from_env)
    image = image or os.getenv("KOSMO_SANDBOX_IMAGE", "kosmo-sandbox:local")
    storage_root = Path(workspace or os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks")).resolve()
    root = storage_root / "validation" / uuid.uuid4().hex
    request, result_dir = root / "request", root / "result"
    request.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    descriptor = request / "descriptor.json"
    result_path = result_dir / "result.json"
    result_path.unlink(missing_ok=True)
    os.chmod(result_dir, 0o777)
    descriptor.write_text(json.dumps({"rules": rules, "value": value, "content": content,
                                     "result_path": "/result/result.json"}, allow_nan=False), encoding="utf-8")
    os.chmod(request, 0o555)
    os.chmod(descriptor, 0o444)
    container = None
    try:
        mounts = [
            docker_module.types.Mount(target="/request", source=os.getenv("KOSMO_TASK_STORAGE_VOLUME", "task-storage"),
                                      type="volume", read_only=True, subpath=f"validation/{root.name}/request"),
            docker_module.types.Mount(target="/result", source=os.getenv("KOSMO_TASK_STORAGE_VOLUME", "task-storage"),
                                      type="volume", read_only=False, subpath=f"validation/{root.name}/result"),
        ]
        container = client.containers.create(
            image, command=["/opt/kosmo/validation_runner.py", "/request/descriptor.json"],
            network_mode="none", user="10001:10001", mem_limit="128m", nano_cpus=500_000_000,
            read_only=True, tmpfs={"/tmp": "rw,noexec,nosuid,size=8m"}, mounts=mounts,
            working_dir="/request",
        )
        await asyncio.to_thread(container.start)
        try:
            result = await asyncio.to_thread(container.wait, timeout=timeout_seconds)
        except Exception:
            await asyncio.to_thread(container.kill)
            return _result(False, "timeout")
        if result.get("StatusCode") != 0:
            return _result(False, "execution_error")
        return read_result(result_path)
    except Exception:
        return _result(False, "execution_error")
    finally:
        if container is not None:
            try:
                await asyncio.to_thread(container.remove, force=True)
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(2)
    descriptor = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run_descriptor(sys.argv[1])
    Path(descriptor["result_path"]).write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
