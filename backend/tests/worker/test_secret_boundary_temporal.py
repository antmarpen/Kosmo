"""WP-R2: catalog secrets reach the runtime but never cross Temporal boundaries.

Opt-in (run in the worker container, which has the Docker socket):
    KOSMO_SECRET_BOUNDARY_INTEGRATION=1 uv run pytest tests/worker/test_secret_boundary_temporal.py

Flow: seed a synthetic agent + HTTP MCP whose secret is a sentinel (encrypted)
in the test DB, then run a Temporal workflow whose activity uses the *production*
resolver and v2 bootstrap against a local fixture model API. The fixture MCP
receiver proves the sentinel reached the runtime; the recorded history, the
activity result and the safe DTO must not contain it.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from temporalio import activity as tactivity, workflow as tworkflow

from app.core.config import settings
from app.domain.agents.models import Agent
from app.domain.agents.resolution import AgentCatalogResolver, SqlCatalogResolutionRepository
from app.domain.identity.models import User, UserRole
from app.domain.mcp_servers.models import McpServer
from worker.activities import agent
from worker.activities.ai_node import _mcp_runtime_config

pytestmark = pytest.mark.skipif(
    os.name == "nt" or os.getenv("KOSMO_SECRET_BOUNDARY_INTEGRATION") != "1",
    reason="Requires the Docker socket + a migrated test DB; set KOSMO_SECRET_BOUNDARY_INTEGRATION=1.",
)

SENTINEL = "MCP-BOUNDARY-SENTINEL-9f23c6"
FIXTURE_KEY = "WP-R2-FIXTURE-KEY"

_ENGINE = None
_PROVIDER_FILES = None
_MCP_RUNTIME = []


def _make_http_fixture(handler_cls):
    server = ThreadingHTTPServer(("0.0.0.0", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class _ModelFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": [{"id": "qwen3.6", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        chunks = [
            {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "qwen3.6",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "fixture-reply"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "qwen3.6",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, *args):
        return


class _McpFixture(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "replace")
        _McpFixture.received.append((self.headers.get("Authorization"), body))
        request = json.loads(body) if body else {}
        method = request.get("method")
        result = {}
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": []}
        data = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

    def log_message(self, *args):
        return


def _seed(sessions, creator):
    agent_id, mcp_id = str(uuid.uuid4()), str(uuid.uuid4())
    cipher = Fernet(settings.config_encryption_key.encode())
    safe_config = {"type": "http", "url": _MCP_RUNTIME[0], "headers": [{"name": "Authorization", "secret": True}]}

    async def seed():
        async with sessions() as db:
            db.add(User(id=creator, username=f"wp-r2-{creator}", password_hash="x", role=UserRole.runner))
            await db.flush()
            db.add(McpServer(id=mcp_id, name=f"mcp-{mcp_id}", owner_user_id=creator, visibility="personal",
                             transport_type="http", safe_config=safe_config,
                             secret_ciphertext={"Authorization": cipher.encrypt(SENTINEL.encode()).decode()}))
            db.add(Agent(id=agent_id, name=f"agent-{agent_id}", owner_user_id=creator, visibility="personal",
                         runtime="opencode", model="nan/qwen3.6", reasoning_effort=None, instructions="",
                         mcp_ids=[mcp_id], skill_ids=[]))
            await db.commit()

    asyncio.run(seed())
    return agent_id, mcp_id


@tactivity.defn(name="wp_r2_secret_probe")
async def probe(payload: dict) -> dict:
    async with _ENGINE() as db:
        effective = await AgentCatalogResolver(SqlCatalogResolutionRepository(db)).resolve(
            created_by=payload["created_by"], node={"agent_id": payload["agent_id"]})
    safe = json.dumps(effective.to_safe_dict())
    assert SENTINEL not in safe, "safe DTO leaked the MCP secret"
    mcp_servers = [_mcp_runtime_config(mcp) for mcp in effective.mcps]
    workspace = agent.TASK_STORAGE_ROOT / "wp-r2" / str(uuid.uuid4())
    adapter = await agent.start_agent_session(
        {"model": effective.agent.model, "reasoning_effort": effective.agent.reasoning_effort},
        str(workspace), runtime_config_files=_PROVIDER_FILES, mcp_servers=mcp_servers,
    )
    try:
        await adapter.start_session({"model": effective.agent.model})
        await adapter.send_prompt("fixture-prompt")
        async for _event in adapter.events():
            pass
    finally:
        await adapter.close()
        shutil.rmtree(workspace, ignore_errors=True)
    return {"status": "success"}


@tworkflow.defn(sandboxed=False)
class ProbeWorkflow:
    @tworkflow.run
    async def run(self, payload: dict) -> dict:
        return await tworkflow.execute_activity(
            "wp_r2_secret_probe", payload, start_to_close_timeout=timedelta(minutes=5))


def test_catalog_secret_reaches_runtime_but_not_temporal(tmp_path, monkeypatch):
    import docker
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    global _ENGINE, _PROVIDER_FILES
    database_url = os.environ["KOSMO_TEST_DATABASE_URL"]

    docker_client = docker.from_env()
    network = docker_client.networks.create(f"wp-r2-{uuid.uuid4().hex[:12]}")
    worker_container = docker_client.containers.get(os.environ["HOSTNAME"])
    network.connect(worker_container, aliases=["wp-r2-fixture"])
    monkeypatch.setattr(agent, "AGENT_NETWORK", network.name)

    model_server, model_thread = _make_http_fixture(_ModelFixture)
    mcp_server, mcp_thread = _make_http_fixture(_McpFixture)
    _MCP_RUNTIME[:] = [f"http://wp-r2-fixture:{mcp_server.server_port}/mcp"]
    _McpFixture.received = []

    provider_config = {"providers": {"nan": {
        "package": "aisdk:@ai-sdk/openai-compatible",
        "settings": {"baseURL": f"http://wp-r2-fixture:{model_server.server_port}/v1"},
        "models": {"qwen3.6": {"name": "Fixture"}},
    }}}
    auth = json.dumps([{"id": "cred_fixture", "integrationID": "nan", "label": "API key",
                        "active": True, "value": {"type": "key", "key": FIXTURE_KEY}}]).encode()
    _PROVIDER_FILES = {"format": "v2", "opencode.json": json.dumps(provider_config).encode(), "auth.json": auth}

    engine = create_async_engine(database_url, poolclass=NullPool)
    _ENGINE = async_sessionmaker(engine, expire_on_commit=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    creator = str(uuid.uuid4())
    agent_id, mcp_id = _seed(sessions, creator)

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue="wp-r2", workflows=[ProbeWorkflow], activities=[probe]):
                handle = await env.client.start_workflow(
                    ProbeWorkflow.run, {"created_by": creator, "agent_id": agent_id},
                    id="wp-r2", task_queue="wp-r2")
                result = await handle.result()
                history = await handle.fetch_history()
        return result, history

    try:
        result, history = asyncio.run(run())
        history_text = json.dumps(history, default=str)
        assert result == {"status": "success"}
        assert SENTINEL not in json.dumps(result)
        assert SENTINEL not in history_text, "sentinel leaked into the Temporal history"
        assert any(SENTINEL in (auth_header or "") for auth_header, _ in _McpFixture.received), \
            "fixture MCP never received the sentinel (delivery not proven)"
    finally:
        model_server.shutdown(); model_server.server_close(); model_thread.join(timeout=2)
        mcp_server.shutdown(); mcp_server.server_close(); mcp_thread.join(timeout=2)
        network.disconnect(worker_container, force=True)
        network.remove()
        docker_client.close()

        async def cleanup():
            async with sessions() as db:
                await db.execute(delete(Agent).where(Agent.id == agent_id))
                await db.execute(delete(McpServer).where(McpServer.id == mcp_id))
                await db.execute(delete(User).where(User.id == creator))
                await db.commit()
        asyncio.run(cleanup())
        asyncio.run(engine.dispose())
