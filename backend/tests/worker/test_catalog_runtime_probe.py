"""Offline ACP delivery probes; live runtime checks are documented separately."""

import asyncio

from worker.adapters.opencode_acp import OpenCodeACPAdapter


class RecordingACP:
    def __init__(self):
        self.calls = []

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": 1, "agentCapabilities": {}}
        if method == "session/new":
            return {"sessionId": "probe-session", "configOptions": [
                {"id": "model", "currentValue": "fixture/model", "options": [
                    {"value": "fixture/model"},
                ]},
            ]}
        if method == "session/prompt":
            return {"stopReason": "end_turn"}
        return {}

    async def receive(self):
        raise StopAsyncIteration

    async def respond(self, request_id, result):
        raise AssertionError("No inbound request expected")

    async def respond_error(self, request_id, code, message):
        raise AssertionError("No inbound request expected")

    async def close(self):
        return None


def test_model_is_selected_before_first_prompt_and_text_is_delivered():
    async def probe():
        transport = RecordingACP()
        adapter = OpenCodeACPAdapter(transport, mcp_servers=[{
            "type": "stdio", "name": "fixture", "command": "fixture-mcp",
            "args": ["--probe"], "env": [{"name": "SYNTHETIC", "value": "not-a-secret"}],
        }, {
            "type": "http", "name": "fixture-http", "url": "http://127.0.0.1:1/mcp",
            "headers": [{"name": "X-Probe", "value": "synthetic"}],
        }])
        await adapter.start_session({"model": "default"})
        text = "<skill name='probe'>synthetic-delivery-marker</skill>\nTask prompt"
        await adapter.send_prompt(text)
        await asyncio.sleep(0)
        calls = transport.calls
        assert [method for method, _ in calls] == [
            "initialize", "session/new", "session/set_config_option", "session/prompt",
        ]
        assert calls[1][1]["mcpServers"] == adapter._mcp_servers
        assert calls[2][1] == {"sessionId": "probe-session", "configId": "model", "value": "fixture/model"}
        assert calls[3][1]["prompt"] == [{"type": "text", "text": text}]

    asyncio.run(probe())
