import asyncio
import os
import pytest

from shared.agent_events import AgentStarted, AgentText, AgentToolUse, CompletionProposed
from worker.adapters.opencode_acp import DockerSocketACPTransport, OpenCodeACPAdapter, normalize_frame


class ScriptedTransport:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.sent = []

    async def request(self, method, params):
        self.sent.append((method, params))
        if method == "initialize":
            return {"protocolVersion": 1, "agentCapabilities": {}}
        if method == "session/new":
            return {"sessionId": "session-1", "configOptions": getattr(self, "config_options", [
                {"id": "model", "currentValue": "provider/current", "options": [{"value": "provider/current"}]}
            ])}
        if method == "session/prompt":
            return {"stopReason": "end_turn"}
        return {}

    async def send(self, method, params):
        self.sent.append((method, params))

    async def respond(self, request_id, result):
        self.sent.append(("response", {"id": request_id, "result": result}))

    async def receive(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)

    async def close(self):
        pass


def test_session_start_and_prompt_speak_acp():
    async def run():
        transport = ScriptedTransport()
        adapter = OpenCodeACPAdapter(transport)
        session = await adapter.start_session({"model": "default", "instructions": "Be useful"})
        await adapter.send_prompt("Hello")
        await asyncio.sleep(0)
        assert session.id == "session-1"
        assert [method for method, _ in transport.sent] == ["initialize", "session/new", "session/set_config_option", "session/prompt"]
    asyncio.run(run())


def test_normalization_maps_acp_updates_to_internal_events():
    events = normalize_frame({"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hi"}}}})
    assert events == [AgentText(delta="Hi")]
    assert normalize_frame({"method": "session/update", "params": {"update": {"sessionUpdate": "tool_call", "title": "Read file"}}}) == [AgentToolUse(name="Read file")]


def test_normalization_surfaces_acp_form_elicitation_request_correlation():
    from shared.agent_events import InputRequested

    events = normalize_frame({"jsonrpc": "2.0", "id": 18, "method": "elicitation/create",
                              "params": {"sessionId": "s1", "mode": "form", "message": "Choose a strategy",
                                         "requestedSchema": {"type": "object"}}})
    assert events == [InputRequested("agent.input.requested", {
        "sessionId": "s1", "mode": "form", "message": "Choose a strategy",
        "requestedSchema": {"type": "object"},
    }, request_id=18, method="elicitation/create")]


def test_synthetic_request_input_update_remains_supported_without_jsonrpc_id():
    from shared.agent_events import InputRequested

    events = normalize_frame({"method": "session/update", "params": {"update": {
        "sessionUpdate": "request_input", "messageKey": "agent.question", "params": {"field": "answer"},
    }}})
    assert events == [InputRequested("agent.question", {"field": "answer"})]


def test_events_yield_start_text_and_completion_proposal():
    async def run():
        transport = ScriptedTransport([
            {"method": "session/update", "params": {"sessionId": "session-1", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Done"}}}},
            {"method": "session/update", "params": {"sessionId": "session-1", "update": {"sessionUpdate": "agent_turn_complete"}}},
        ])
        adapter = OpenCodeACPAdapter(transport)
        await adapter.start_session({"model": "default", "instructions": ""})
        events = [event async for event in adapter.events()]
        assert isinstance(events[0], AgentStarted)
        assert events[1] == AgentText(delta="Done")
        assert events[2] == CompletionProposed(artifacts=[])
    asyncio.run(run())


def test_completion_and_feedback_use_adapter_frames():
    async def run():
        transport = ScriptedTransport()
        adapter = OpenCodeACPAdapter(transport)
        await adapter.start_session({"model": "default", "instructions": ""})
        result = await adapter.request_completion([])
        await adapter.deliver_feedback([{"artifact": "summary.md", "level": "required_sections", "message_key": "validation.failed", "params": {"reason": "missing"}}])
        await asyncio.sleep(0)
        assert result.artifacts == []
        text = transport.sent[-1][1]["prompt"][0]["text"]
        assert transport.sent[-1][0] == "session/prompt"
        assert '"artifact": "summary.md"' in text
        assert '"message_key": "validation.failed"' in text
    asyncio.run(run())


def test_acp_end_turn_becomes_completion_proposal_without_private_rpc():
    async def run():
        adapter = OpenCodeACPAdapter(ScriptedTransport())
        await adapter.start_session({"model": "default", "instructions": ""})
        await adapter.send_prompt("Finish")
        events = [event async for event in adapter.events()]
        assert isinstance(events[-1], CompletionProposed)
    asyncio.run(run())


def test_docker_socket_transport_demultiplexes_jsonrpc_stdout():
    import socket
    import struct
    import threading

    client_sock, daemon_sock = socket.socketpair()
    def fake_daemon():
        request = daemon_sock.recv(4096)
        request_id = __import__("json").loads(request.split(b"\n", 1)[0])["id"]
        response = (__import__("json").dumps({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1}}) + "\n").encode()
        daemon_sock.sendall(b"\x01\0\0\0" + struct.pack(">I", len(response)) + response)

    thread = threading.Thread(target=fake_daemon)
    thread.start()

    async def exercise():
        transport = DockerSocketACPTransport(client_sock)
        assert await transport.request("initialize", {}) == {"protocolVersion": 1}
        await transport.close()

    asyncio.run(exercise())
    thread.join(timeout=1)
    daemon_sock.close()


def test_docker_socket_transport_accepts_docker_sdk_socketio(monkeypatch):
    import socket
    import struct
    import threading

    client_sock, daemon_sock = socket.socketpair()

    class SocketIO:
        def __init__(self, sock):
            self.sock = sock
            self._sock = sock

        def read(self, length):
            return self.sock.recv(length)

        def write(self, payload):
            self.sock.sendall(payload)
            return len(payload)

        def close(self):
            self.sock.close()

    def fake_daemon():
        request = daemon_sock.recv(4096)
        request_id = __import__("json").loads(request.split(b"\n", 1)[0])["id"]
        response = (__import__("json").dumps({"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}) + "\n").encode()
        daemon_sock.sendall(b"\x01\0\0\0" + struct.pack(">I", len(response)) + response)

    thread = threading.Thread(target=fake_daemon)
    thread.start()

    async def exercise():
        transport = DockerSocketACPTransport(SocketIO(client_sock))
        response = await transport.request("initialize", {})
        await transport.close()
        return response

    assert asyncio.run(exercise()) == {"ok": True}
    thread.join(timeout=1)
    daemon_sock.close()


def test_docker_socket_transport_closes_docker_socketio_once():
    class RawSocket:
        def __init__(self):
            self.close_count = 0

        def recv(self, size):
            return b""

        def close(self):
            self.close_count += 1

    class SocketIO:
        def __init__(self, raw):
            self._sock = raw

        def close(self):
            self._sock.close()

    raw = RawSocket()

    async def exercise():
        transport = DockerSocketACPTransport(SocketIO(raw))
        await asyncio.sleep(0)
        await transport.close()

    asyncio.run(exercise())
    assert raw.close_count == 1


def test_docker_socket_transport_returns_server_request_response_with_original_id():
    import json
    import socket
    import struct
    import threading

    client_sock, daemon_sock = socket.socketpair()
    replies = []

    def fake_daemon():
        request = {"jsonrpc": "2.0", "id": 123, "method": "session/request_permission", "params": {}}
        payload = (json.dumps(request) + "\n").encode()
        daemon_sock.sendall(b"\x01\0\0\0" + struct.pack(">I", len(payload)) + payload)
        response = bytearray()
        while not response.endswith(b"\n"):
            response.extend(daemon_sock.recv(4096))
        replies.append(json.loads(response))

    thread = threading.Thread(target=fake_daemon)
    thread.start()

    async def exercise():
        transport = DockerSocketACPTransport(client_sock)
        inbound = await transport.receive()
        assert inbound["id"] == 123
        await transport.respond(123, {"outcome": {"outcome": "selected", "optionId": "allow-once"}})
        await transport.close()

    asyncio.run(exercise())
    thread.join(timeout=1)
    daemon_sock.close()
    assert replies == [{"jsonrpc": "2.0", "id": 123,
                        "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}}]


def test_agent_session_uses_docker_sdk_mount_network_and_exec_socket(monkeypatch, tmp_path):
    from worker.activities.agent import start_agent_session

    class FakeExecAPI:
        def exec_create(self, container_id, command, **kwargs):
            self.create = (container_id, command, kwargs)
            return {"Id": "exec-1"}

        def exec_start(self, exec_id, **kwargs):
            self.start = (exec_id, kwargs)
            return object()

    class FakeContainer:
        id = "container-1"

        def start(self):
            self.started = True

        def remove(self, force=False):
            self.removed = force

    class FakeContainers:
        def create(self, image, **kwargs):
            self.created = (image, kwargs)
            return container

    class FakeClient:
        def __init__(self):
            self.api = FakeExecAPI()
            self.containers = FakeContainers()

        def close(self):
            pass

    container = FakeContainer()
    client = FakeClient()
    import worker.activities.agent as agent_module
    monkeypatch.setattr(agent_module, "TASK_STORAGE_VOLUME", "task-storage")
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)

    async def exercise():
        managed = await start_agent_session({"model": "provider/model"}, str(tmp_path / "task" / "agent"), docker_client=client,
                                            transport_factory=lambda _sock: ScriptedTransport(),
                                            runtime_environment={"KOSMO_INPUT_ARTIFACT_REPORT_MD": "/workspace/inputs/report.md"})
        assert managed._adapter._session_id is None
        await managed.close()

    asyncio.run(exercise())
    image, options = client.containers.created
    assert image == "kosmo-opencode:local"
    assert options["network"] == "kosmo-agent-local"
    assert options["mounts"][0]["Source"] == "task-storage"
    assert options["mounts"][1]["ReadOnly"] is True
    assert options["environment"]["KOSMO_INPUT_ARTIFACT_REPORT_MD"] == "/workspace/inputs/report.md"
    assert "OPENCODE_API_KEY" not in options["environment"]
    assert "OPENCODE_MODEL" not in options["environment"]
    assert client.api.start == ("exec-1", {"socket": True, "tty": False})
    assert container.removed is True


def test_agent_session_injects_config_files_into_container_before_acp_start(monkeypatch, tmp_path):
    from worker.activities.agent import start_agent_session

    class FakeExecAPI:
        def __init__(self):
            self.calls = []
            self.sockets = []

        def exec_create(self, container_id, command, **kwargs):
            self.calls.append((command, kwargs))
            return {"Id": f"exec-{len(self.calls)}"}

        def exec_start(self, exec_id, **kwargs):
            if kwargs.get("detach"):
                return None
            sock = FakeDuplexSocket()
            self.sockets.append(sock)
            return sock

        def exec_inspect(self, exec_id):
            return {"ExitCode": 0}

    class FakeDuplexSocket:
        def __init__(self):
            self.written = bytearray()

        def sendall(self, data):
            self.written.extend(data)

        def shutdown(self, direction):
            pass

        def recv(self, size):
            return b""

        def close(self):
            pass

    class FakeContainer:
        id = "container-config"

        def start(self):
            pass

        def remove(self, force=False):
            pass

    class FakeContainers:
        def create(self, image, **kwargs):
            self.options = kwargs
            return container

    class FakeClient:
        def __init__(self):
            self.api, self.containers = FakeExecAPI(), FakeContainers()

        def close(self):
            pass

    container, client = FakeContainer(), FakeClient()
    import worker.activities.agent as agent_module
    monkeypatch.setattr(agent_module, "TASK_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(agent_module, "TASK_STORAGE_VOLUME", "task-storage")

    async def exercise():
        managed = await start_agent_session(
            {"model": "default"}, str(tmp_path / "task" / "agent"), docker_client=client,
            transport_factory=lambda _sock: ScriptedTransport(),
            runtime_config_files={"format": "v2", "opencode.json": b'{"providers":{}}',
                                  "auth.json": b'[{"id":"cred","integrationID":"p","label":"API key","active":true,"value":{"type":"key","key":"private"}}]'},
        )
        mounts = {mount["Target"]: mount for mount in client.containers.options["mounts"]}
        assert "/home/opencode/.config/opencode" in client.containers.options["tmpfs"]
        assert "/home/opencode/.local/share/opencode" in client.containers.options["tmpfs"]
        # OpenCode also writes state and cache; without writable mounts it dies
        # with EROFS on startup and the ACP stream closes immediately.
        assert "/home/opencode/.local/state" in client.containers.options["tmpfs"]
        assert "/home/opencode/.cache" in client.containers.options["tmpfs"]
        assert "/home/opencode/.config/opencode" not in mounts
        assert client.api.sockets[0].written == b'{"providers":{}}'
        assert b'"key":"private"' in client.api.sockets[1].written
        assert all("private" not in " ".join(call[0]) for call in client.api.calls)
        assert all(call[1]["user"] == "10001:10001" for call in client.api.calls)
        assert client.api.calls[2][0] == ["opencode", "--version"]
        assert client.api.calls[3][0][:3] == ["opencode", "auth", "import"]
        assert client.api.calls[4][0][:2] == ["rm", "-f"]
        await managed.close()

    asyncio.run(exercise())
    assert "OPENCODE_API_KEY" not in client.containers.options["environment"]
    assert client.api.calls[-1][0] == ["opencode", "acp"]


def test_stage_agent_inputs_copies_readonly_files_and_exports_existing_input_convention(tmp_path):
    import stat
    from worker.activities.agent import stage_agent_inputs

    source = tmp_path / "artifacts" / "report.md"
    source.parent.mkdir()
    source.write_text("# Findings", encoding="utf-8")
    workspace = tmp_path / "agent"

    env = stage_agent_inputs({"report.md": {"storage_path": str(source)}}, workspace)

    assert (workspace / "inputs" / "report.md").read_text(encoding="utf-8") == "# Findings"
    assert stat.S_IMODE((workspace / "inputs" / "report.md").stat().st_mode) == 0o444
    assert env == {"KOSMO_INPUT_ARTIFACT_REPORT_MD": "/workspace/inputs/report.md"}


def test_session_new_uses_container_path_and_applies_model_config_option():
    async def run():
        transport = ScriptedTransport()
        transport.config_options = [{"id": "model", "currentValue": "old/model", "options": [{"value": "provider/model"}]}]
        adapter = OpenCodeACPAdapter(transport, output_dir="/var/lib/kosmo/tasks/task/agent", session_cwd="/workspace")
        await adapter.start_session({"model": "provider/model"})
        session_params = next(params for method, params in transport.sent if method == "session/new")
        assert session_params["cwd"] == "/workspace"
        assert transport.sent[-1] == ("session/set_config_option", {"sessionId": "session-1", "configId": "model", "value": "provider/model"})
    asyncio.run(run())


def test_default_model_explicitly_selects_advertised_current_model():
    async def run():
        transport = ScriptedTransport()
        transport.config_options = [{"id": "model", "currentValue": "provider/current", "options": [{"value": "provider/current"}]}]
        adapter = OpenCodeACPAdapter(transport, output_dir="/host/path", session_cwd="/workspace")
        await adapter.start_session({"model": "default"})
        assert transport.sent[-1] == ("session/set_config_option", {"sessionId": "session-1", "configId": "model", "value": "provider/current"})
    asyncio.run(run())


def test_explicit_model_is_rejected_when_auth_import_did_not_make_it_available():
    async def run():
        transport = ScriptedTransport()
        transport.config_options = [{"id": "model", "currentValue": "other/model", "options": []}]
        with pytest.raises(ValueError, match="Configured model is not available"):
            await OpenCodeACPAdapter(transport).start_session({"model": "private/model"})
    asyncio.run(run())


@pytest.mark.parametrize("current_value, options", [(None, []), ("", [{"value": "provider/model"}]), ("not-listed", [{"value": "provider/model"}])])
def test_default_model_fails_when_current_model_is_missing_or_unusable(current_value, options):
    async def run():
        transport = ScriptedTransport()
        transport.config_options = [{"id": "model", "currentValue": current_value, "options": options}]
        with pytest.raises(ValueError, match="workflow.agent.model_default_unavailable"):
            await OpenCodeACPAdapter(transport).start_session({"model": "default"})
    asyncio.run(run())


def test_session_new_receives_task_scoped_validator_mcp_server():
    async def run():
        server = {"type": "http", "name": "kosmo-validator", "url": "http://backend:8000/mcp/validator",
                  "headers": [{"name": "Authorization", "value": "Bearer scoped-token"}]}
        transport = ScriptedTransport()
        adapter = OpenCodeACPAdapter(transport, mcp_servers=[server])
        await adapter.start_session({"model": "default"})
        params = next(params for method, params in transport.sent if method == "session/new")
        assert params["mcpServers"] == [server]
    asyncio.run(run())


def test_validator_mcp_configuration_contains_execution_scoped_bearer():
    import jwt
    from worker.activities.agent import validator_mcp_server

    secret = "validator-signing-secret-with-at-least-32-bytes"
    server = validator_mcp_server("task-1", "ai-1", "exec-1", secret)
    bearer = next(header["value"] for header in server["headers"] if header["name"] == "Authorization")
    claims = jwt.decode(bearer.removeprefix("Bearer "), secret, algorithms=["HS256"], audience="kosmo-validator")
    assert server["type"] == "http"
    assert server["url"] == "http://backend:8000/mcp/validator"
    assert claims["task_id"] == "task-1" and claims["node_id"] == "ai-1"
    assert claims["node_execution_id"] == "exec-1"


def test_ai_activity_returns_structured_failure_when_agent_infrastructure_fails(monkeypatch, tmp_path, caplog):
    from worker.activities import agent as agent_module
    from worker.activities import ai_node as ai_node_module
    from worker.activities.ai_node import run_ai_node

    async def unavailable(*args, **kwargs):
        raise RuntimeError("docker socket unavailable")

    monkeypatch.setattr(agent_module, "start_agent_session", unavailable)
    async def no_provider_config(user_id, provider_type):
        return None
    monkeypatch.setattr(ai_node_module, "_load_provider_runtime_config", no_provider_config)
    result = asyncio.run(run_ai_node({
        "task_id": "task-1", "task_prompt": "work", "user_id": "user-1", "workspace": str(tmp_path),
        "node": {"id": "ai-1", "agent": {"runtime": "opencode"}, "outputs": [], "validation": {"levels": []}},
    }))
    assert result["state"] == "failed"
    assert result["error"]["code"] == "AGENT_RUNTIME_FAILED"
    assert result["error"]["message_key"] == "errors.agent.runtime_failed"
    assert result["error"]["params"] == {"cause": "errors.agent.runtime_failed"}
    assert "AI node infrastructure failure" in caplog.text
    assert "Traceback" in caplog.text
    assert "docker socket unavailable" in caplog.text


def test_missing_provider_config_turns_runtime_failure_into_auth_error_and_note(monkeypatch, tmp_path):
    from worker.activities import agent as agent_module
    from worker.activities import ai_node as ai_node_module
    from worker.activities.ai_node import run_ai_node

    notes = []

    class Adapter:
        async def close(self):
            pass

    async def no_config(user_id, provider_type):
        return None

    async def start_session(*args, **kwargs):
        return Adapter()

    from worker.adapters.opencode_acp import ACPResponseError
    async def fail_prompt(*args, **kwargs):
        raise ACPResponseError("session/prompt", {"code": -32603, "message": "OpenCode service failure"})

    async def save_note(task_id, node_id, key, params):
        notes.append((task_id, node_id, key, params))

    monkeypatch.setattr(ai_node_module, "_load_provider_runtime_config", no_config)
    monkeypatch.setattr(ai_node_module, "orchestrate_ai_node", fail_prompt)
    monkeypatch.setattr(ai_node_module, "_add_task_note", save_note)
    monkeypatch.setattr(agent_module, "start_agent_session", start_session)
    result = asyncio.run(run_ai_node({
        "task_id": "task-1", "user_id": "owner-1", "task_prompt": "work", "workspace": str(tmp_path),
        "node": {"id": "ai-1", "agent": {"runtime": "opencode"}, "outputs": [], "validation": {"levels": []}},
    }))
    assert result["error"]["code"] == "PROVIDER_AUTH_MISSING"
    assert result["error"]["message_key"] == "errors.provider.auth_missing"
    assert notes == [("task-1", "ai-1", "tasks.notes.agent_auth_missing", {"provider": "opencode"})]


def test_permission_request_is_serviced_while_prompt_is_pending():
    from shared.agent_events import InputRequested

    class InteractiveTransport(ScriptedTransport):
        def __init__(self):
            super().__init__()
            self.inbound = asyncio.Queue()
            self.permission_answered = asyncio.Event()

        async def request(self, method, params):
            self.sent.append((method, params))
            if method == "initialize":
                return {"protocolVersion": 1}
            if method == "session/new":
                return {"sessionId": "interactive-session", "configOptions": [
                    {"id": "model", "currentValue": "provider/current", "options": [{"value": "provider/current"}]}
                ]}
            if method == "session/prompt":
                await self.inbound.put({
                    "jsonrpc": "2.0", "id": 47, "method": "session/request_permission",
                    "params": {"sessionId": "interactive-session", "toolCall": {"toolCallId": "tc-1"},
                               "options": [{"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                                           {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]},
                })
                await self.permission_answered.wait()
                return {"stopReason": "end_turn"}
            return {}

        async def receive(self):
            return await self.inbound.get()

        async def respond(self, request_id, result):
            self.sent.append(("response", {"id": request_id, "result": result}))
            self.permission_answered.set()

    async def run():
        transport = InteractiveTransport()
        adapter = OpenCodeACPAdapter(transport)
        await adapter.start_session({"model": "default"})
        await asyncio.wait_for(adapter.send_prompt("Do a protected action"), timeout=0.1)
        events = adapter.events()
        assert isinstance(await anext(events), AgentStarted)
        request = await asyncio.wait_for(anext(events), timeout=0.1)
        assert isinstance(request, InputRequested)
        assert request.request_id == 47
        assert request.method == "session/request_permission"
        await adapter.deliver_answer("allow-once")
        await asyncio.sleep(0)
        assert transport.permission_answered.is_set()
        assert adapter._prompt_task.done()
        assert transport.sent[-1] == ("response", {"id": 47, "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}})
        assert isinstance(await asyncio.wait_for(anext(events), timeout=1), CompletionProposed)
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("KOSMO_PROVIDER_CONFIG_USER_ID"), reason="No uploaded encrypted OpenCode provider config selected for live test")
@pytest.mark.docker
def test_real_opencode_container_round_trip():
    from worker.activities.provider_verify import verify_opencode_model

    result = asyncio.run(verify_opencode_model({
        "user_id": os.environ["KOSMO_PROVIDER_CONFIG_USER_ID"],
        "model": os.getenv("KOSMO_PROVIDER_TEST_MODEL", "opencode/big-pickle"),
    }))
    assert result["ok"] is True
    # The result carries only the non-empty-response assertion and latency;
    # the agent's words never leave the container.
    assert result["response_non_empty"] is True
    assert "response_snippet" not in result
