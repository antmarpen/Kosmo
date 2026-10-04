"""Docker SDK lifecycle boundary for one isolated OpenCode ACP session."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from worker.adapters.opencode_acp import DockerSocketACPTransport, OpenCodeACPAdapter


TASK_STORAGE_ROOT = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks"))
TASK_STORAGE_VOLUME = os.getenv("KOSMO_TASK_STORAGE_VOLUME", "task-storage")
AGENT_IMAGE = os.getenv("KOSMO_OPENCODE_IMAGE", "kosmo-opencode:local")
AGENT_NETWORK = os.getenv("KOSMO_AGENT_NETWORK", "kosmo-agent-local")
AGENT_CPU = float(os.getenv("KOSMO_AGENT_CPU", "1.0"))
AGENT_MEMORY = os.getenv("KOSMO_AGENT_MEMORY", "512m")


async def start_agent_session(
    cfg: dict[str, Any],
    workspace: str,
    *,
    docker_client=None,
    transport_factory: Callable | None = None,
    runtime_environment: dict[str, str] | None = None,
    runtime_config_files: dict[str, bytes | str] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
):
    """Start an ACP exec socket inside a fresh, task-scoped agent container."""
    import docker

    client = docker_client or await asyncio.to_thread(docker.from_env)
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace_path.chmod(0o777)
    (workspace_path / "inputs").mkdir(exist_ok=True)
    try:
        subpath = workspace_path.relative_to(TASK_STORAGE_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Agent workspace must be inside the configured task storage root") from exc

    environment = {**(runtime_environment or {})}
    environment["HOME"] = "/home/opencode"
    workspace_mount = docker.types.Mount(
        target="/workspace", source=TASK_STORAGE_VOLUME, type="volume",
        read_only=False, subpath=subpath,
    )
    inputs_mount = docker.types.Mount(
        target="/workspace/inputs", source=TASK_STORAGE_VOLUME, type="volume",
        read_only=True, subpath=f"{subpath}/inputs",
    )
    mounts = [workspace_mount, inputs_mount]
    try:
        container = await asyncio.to_thread(
            client.containers.create,
            AGENT_IMAGE,
            command=["infinity"],
            entrypoint=["sleep"],
            environment=environment,
            network=AGENT_NETWORK,
            mounts=mounts,
            tmpfs={
                "/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777",
                "/home/opencode/.config/opencode": "rw,noexec,nosuid,nodev,size=8m,uid=10001,gid=10001,mode=0700",
                # OpenCode keeps session history and logs under these paths; a
                # few message exchanges can exceed a small tmpfs and surface as
                # "Internal error: OpenCode service failure" mid-session.
                "/home/opencode/.local/share/opencode": "rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001,mode=0700",
                "/home/opencode/.local/state": "rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700",
                "/home/opencode/.cache": "rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001,mode=0700",
            },
            working_dir="/workspace",
            user="10001:10001",
            read_only=True,
            privileged=False,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            nano_cpus=int(AGENT_CPU * 1_000_000_000),
            mem_limit=AGENT_MEMORY,
            detach=True,
        )
    except Exception:
        if docker_client is None:
            await asyncio.to_thread(client.close)
        raise
    transport = None
    try:
        await asyncio.to_thread(container.start)
        await asyncio.to_thread(_inject_runtime_files, client, container, runtime_config_files or {})
        exec_config = await asyncio.to_thread(
            client.api.exec_create,
            container.id,
            ["opencode", "acp"],
            stdin=True,
            stdout=True,
            stderr=False,
            tty=False,
            user="10001:10001",
        )
        exec_socket = await asyncio.to_thread(
            client.api.exec_start,
            exec_config["Id"],
            socket=True,
            tty=False,
        )
        transport = (transport_factory or DockerSocketACPTransport)(exec_socket)
        adapter = OpenCodeACPAdapter(transport, workspace_path, session_cwd="/workspace", mcp_servers=mcp_servers)
        return _ManagedAdapter(adapter, client, container, transport)
    except Exception:
        if transport:
            await transport.close()
        await asyncio.to_thread(container.remove, force=True)
        if docker_client is None:
            await asyncio.to_thread(client.close)
        raise


def stage_agent_inputs(inputs: dict[str, dict], workspace: str | Path) -> dict[str, str]:
    """Copy declared artifact inputs into a Docker-mounted read-only subpath."""
    workspace_path = Path(workspace).resolve()
    input_dir = workspace_path / "inputs"
    if input_dir.is_symlink():
        raise ValueError("Agent input directory must not be a symlink")
    input_dir.mkdir(parents=True, exist_ok=True)
    environment = {}
    used_names = set()
    for logical_name, artifact in inputs.items():
        filename = Path(logical_name).name
        if not filename or filename in {".", ".."} or filename in used_names:
            raise ValueError("Agent input names must have unique safe file names")
        used_names.add(filename)
        target = input_dir / filename
        if target.is_symlink():
            raise ValueError(f"Agent input destination is unsafe: {logical_name}")
        if target.exists():
            target.unlink()
        if isinstance(artifact, dict) and artifact.get("storage_path"):
            source = Path(artifact["storage_path"]).resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Declared agent input is unavailable: {logical_name}")
            shutil.copyfile(source, target)
        else:
            target.write_text(json.dumps(artifact, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        target.chmod(0o444)
        env_name = "KOSMO_INPUT_ARTIFACT_" + logical_name.upper().replace(".", "_").replace("-", "_")
        environment[env_name] = f"/workspace/inputs/{filename}"
    return environment


def _inject_runtime_files(client, container, files: dict[str, bytes | str]) -> None:
    if not files:
        return
    if (files.get("format") != "v2" or set(files) - {"format", "opencode.json", "auth.json"}
            or "opencode.json" not in files):
        raise ValueError("OpenCode runtime bundle must use the v2 format")
    destinations = {
        "opencode.json": "/home/opencode/.config/opencode/opencode.json",
    }
    for filename, target in destinations.items():
        content = files[filename]
        _write_container_file(client, container, target, content, "0400")
    auth = files.get("auth.json")
    if auth is not None:
        # OpenCode v2 accepts the native auth-export array through its supported
        # import command. Never plant auth.json into the persistent store path.
        target = f"/tmp/kosmo-auth-import-{uuid.uuid4().hex}.json"
        try:
            _write_container_file(client, container, target, auth, "0600")
            _run_container_command(client, container, ["opencode", "--version"])
            _run_container_command(client, container, ["opencode", "auth", "import", target])
        except Exception as exc:
            raise ProviderBootstrapError() from exc
        finally:
            try:
                _run_container_command(client, container, ["rm", "-f", target], timeout=5)
            except Exception:
                # Container removal remains the final cleanup boundary.
                pass


class ProviderBootstrapError(RuntimeError):
    """A safe, stable failure raised before ACP starts when auth import fails."""

    code = "PROVIDER_AUTH_BOOTSTRAP_FAILED"
    message_key = "errors.provider.auth_bootstrap_failed"

    def __init__(self):
        super().__init__(self.message_key)


def _write_container_file(client, container, target: str, content: bytes, mode: str) -> None:
    exec_config = client.api.exec_create(
        container.id,
        ["sh", "-c", "umask 077; cat > \"$1\" && chmod \"$2\" \"$1\"", "sh", target, mode],
        stdin=True, stdout=True, stderr=False, tty=False, user="10001:10001",
    )
    stream = client.api.exec_start(exec_config["Id"], socket=True, tty=False)
    sock = getattr(stream, "_sock", stream)
    try:
        _socket_sendall(sock, content)
        sock.shutdown(socket.SHUT_WR)
        while sock.recv(4096):
            pass
    finally:
        response = getattr(stream, "_response", None)
        if response is not None:
            response.close()
        stream.close()
    if client.api.exec_inspect(exec_config["Id"]).get("ExitCode") != 0:
        raise RuntimeError("Could not inject OpenCode runtime file")


def _run_container_command(client, container, command: list[str], timeout: float = 30) -> None:
    exec_config = client.api.exec_create(
        container.id, command, stdout=False, stderr=False, stdin=False,
        tty=False, user="10001:10001",
    )
    client.api.exec_start(exec_config["Id"], detach=True, tty=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.api.exec_inspect(exec_config["Id"])
        if not result.get("Running"):
            if result.get("ExitCode") != 0:
                raise RuntimeError("OpenCode auth command failed")
            return
        time.sleep(0.1)
    raise TimeoutError("OpenCode auth command timed out")


def _socket_sendall(sock, payload: bytes) -> None:
    sendall = getattr(sock, "sendall", None)
    if sendall:
        sendall(payload)
        return
    view = memoryview(payload)
    while view:
        written = sock.write(view)
        if written is None:
            return
        view = view[written:]


def validator_mcp_server(task_id: str, node_id: str, node_execution_id: str,
                         secret: str, url: str | None = None) -> dict[str, Any]:
    from app.domain.tasks.validator_auth import create_validator_token

    token = create_validator_token(secret, task_id, node_id, node_execution_id)
    return {
        "type": "http", "name": "kosmo-validator",
        "url": url or os.getenv("KOSMO_VALIDATOR_MCP_URL", "http://backend:8000/mcp/validator"),
        "headers": [{"name": "Authorization", "value": f"Bearer {token}"}],
    }


async def run_agent(cfg: dict[str, Any], prompt: str, workspace: str) -> dict:
    """One-shot convenience entry point used by the docker integration test."""
    adapter = await start_agent_session(cfg, workspace)
    try:
        await adapter.start_session(cfg)
        await adapter.send_prompt(f"{cfg.get('instructions', '').strip()}\n\n{prompt}".strip())
        async for event in adapter.events():
            from shared.agent_events import AgentError, CompletionProposed
            if isinstance(event, AgentError):
                return {"state": "failed", "error": {"code": "AGENT_RUNTIME_FAILED", "message_key": event.message_key, "params": event.params}}
            if isinstance(event, CompletionProposed):
                break
        return {"state": "success", "artifacts": await adapter.collect_artifacts()}
    finally:
        await adapter.close()


class _ManagedAdapter:
    def __init__(self, adapter, client, container, transport):
        self._adapter = adapter
        self._client = client
        self._container = container
        self._transport = transport
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._adapter, name)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._transport is not None:
                await self._transport.close()
        finally:
            try:
                await asyncio.to_thread(self._container.remove, force=True)
            finally:
                await asyncio.to_thread(self._client.close)
