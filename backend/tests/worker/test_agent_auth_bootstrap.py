import json
import os
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from worker.activities import agent


AUTH = json.dumps([{
    "id": "cred_fixture", "integrationID": "fixture", "label": "API key",
    "active": True, "value": {"type": "key", "key": "WP24-SENTINEL-NEVER-LOG"},
}]).encode()


def test_runtime_bundle_imports_v2_auth_before_acp_and_removes_import_file(monkeypatch):
    events = []

    def write(client, container, target, content, mode):
        events.append(("write", target, content, mode))

    def command(client, container, argv, timeout=30):
        events.append(("command", argv))

    monkeypatch.setattr(agent, "_write_container_file", write)
    monkeypatch.setattr(agent, "_run_container_command", command)
    agent._inject_runtime_files(object(), object(), {
        "format": "v2", "opencode.json": b'{"providers":{}}', "auth.json": AUTH,
    })

    assert events[0] == ("write", "/home/opencode/.config/opencode/opencode.json",
                         b'{"providers":{}}', "0400")
    auth_path = events[1][1]
    assert auth_path.startswith("/tmp/kosmo-auth-import-")
    assert events[1][2:] == (AUTH, "0600")
    assert events[2] == ("command", ["opencode", "--version"])
    assert events[3] == ("command", ["opencode", "auth", "import", auth_path])
    assert events[4] == ("command", ["rm", "-f", auth_path])
    assert "auth.json" not in [event[1] for event in events if event[0] == "write"]


def test_failed_auth_import_is_safe_and_tempfile_cleanup_is_attempted(monkeypatch):
    writes, commands = [], []

    def write(client, container, target, content, mode):
        writes.append((target, content, mode))

    def command(client, container, argv, timeout=30):
        commands.append(argv)
        if argv[:3] == ["opencode", "auth", "import"]:
            raise RuntimeError("private importer output WP24-SENTINEL-NEVER-LOG")

    monkeypatch.setattr(agent, "_write_container_file", write)
    monkeypatch.setattr(agent, "_run_container_command", command)
    with pytest.raises(agent.ProviderBootstrapError) as error:
        agent._inject_runtime_files(object(), object(), {
            "format": "v2", "opencode.json": b'{"providers":{}}', "auth.json": AUTH,
        })

    assert str(error.value) == "errors.provider.auth_bootstrap_failed"
    assert commands[0] == ["opencode", "--version"]
    assert commands[1][:3] == ["opencode", "auth", "import"]
    assert commands[2] == ["rm", "-f", writes[1][0]]
    assert "WP24-SENTINEL-NEVER-LOG" not in str(error.value)


def test_runtime_bundle_rejects_unversioned_or_legacy_auth_planting(monkeypatch):
    writes = []
    monkeypatch.setattr(agent, "_write_container_file", lambda *args: writes.append(args))
    with pytest.raises(ValueError, match="v2"):
        agent._inject_runtime_files(object(), object(), {
            "opencode.json": b'{"providers":{}}', "auth.json": AUTH,
        })
    assert writes == []


@pytest.mark.skipif(os.getenv("KOSMO_OPENCODE_V2_INTEGRATION") != "1",
                    reason="requires Docker socket and the pinned OpenCode v2 image")
def test_v2_auth_import_authenticates_fixture_api_before_acp_prompt(tmp_path, monkeypatch):
    import docker

    docker_client = docker.from_env()
    network = docker_client.networks.create(f"wp24-fixture-{uuid.uuid4().hex[:12]}")
    worker_container = docker_client.containers.get(os.environ["HOSTNAME"])
    network.connect(worker_container, aliases=["wp24-fixture-worker"])
    monkeypatch.setattr(agent, "AGENT_NETWORK", network.name)
    requests = []

    class FixtureAPI(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, self.headers.get("Authorization"), None))
            body = json.dumps({"data": [{"id": "fixture-model", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.command, self.path, self.headers.get("Authorization"), payload))
            chunks = [
                {"id": "chatcmpl-fixture", "object": "chat.completion.chunk", "created": 1,
                 "model": "qwen3.6", "choices": [{"index": 0,
                                                     "delta": {"role": "assistant", "content": "fixture-reply"},
                                                     "finish_reason": None}]},
                {"id": "chatcmpl-fixture", "object": "chat.completion.chunk", "created": 1,
                 "model": "qwen3.6", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            body = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", 0), FixtureAPI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    key = "WP24-LIVE-FIXTURE-SENTINEL"
    provider_config = {
        "providers": {"nan": {
            "package": "aisdk:@ai-sdk/openai-compatible",
            "settings": {"baseURL": f"http://wp24-fixture-worker:{server.server_port}/v1"},
            "models": {"qwen3.6": {"name": "Fixture Model"}},
        }},
    }
    auth = json.dumps([{
        "id": "cred_fixture", "integrationID": "nan", "label": "API key",
        "active": True, "value": {"type": "key", "key": key},
    }]).encode()
    workspace = agent.TASK_STORAGE_ROOT / "wp24-auth-fixture" / str(os.getpid())
    try:
        async def exercise():
            adapter = await agent.start_agent_session(
                {"model": "nan/qwen3.6"}, str(workspace),
                runtime_config_files={"format": "v2", "opencode.json": json.dumps(provider_config).encode(),
                                      "auth.json": auth},
            )
            try:
                exit_code, _output = adapter._container.exec_run(
                    ["sh", "-c", "test -z \"$(find /tmp -maxdepth 1 -name 'kosmo-auth-import-*' -print -quit)\" "
                     "&& test ! -e /home/opencode/.local/share/opencode/auth.json"],
                    user="10001:10001",
                )
                assert exit_code == 0, "temporary import file remained or legacy auth.json was planted"
                try:
                    await adapter.start_session({"model": "nan/qwen3.6"})
                except ValueError as exc:
                    pytest.fail(f"Configured fixture model unavailable; ACP advertised {adapter._adapter.list_models()!r}: {exc}")
                await adapter.send_prompt("fixture-prompt")
                output = []
                async for _event in adapter.events():
                    from shared.agent_events import AgentText
                    if isinstance(_event, AgentText):
                        output.append(_event.delta)
                assert "fixture-reply" in "".join(output)
                assert key not in "".join(output)
            finally:
                await adapter.close()
        __import__("asyncio").run(exercise())
        assert any(row[0] == "POST" and row[3] and "fixture-prompt" in str(row[3]) for row in requests)
        post_requests = [row for row in requests if row[0] == "POST"]
        assert post_requests
        assert all(row[2] == f"Bearer {key}" for row in post_requests)
        assert all(row[3]["model"] == "qwen3.6" for row in post_requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        network.disconnect(worker_container, force=True)
        network.remove()
        docker_client.close()
        assert all(key.encode() not in path.read_bytes()
                   for path in workspace.rglob("*") if path.is_file())
        shutil.rmtree(workspace, ignore_errors=True)
