"""ACP JSON-RPC adapter. Protocol frame normalization is pure for easy testing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
import threading
from typing import Any, AsyncIterator, Protocol

from shared.agent_events import AgentError, AgentEvent, AgentStarted, AgentText, AgentToolUse, CompletionProposed, InputRequested
from shared.execution import ArtifactRef
from .base import ArtifactContract, CompletionResult, SessionHandle
from shared.paths import safe_path


class ACPTransport(Protocol):
    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...
    async def send(self, method: str, params: dict[str, Any]) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None: ...
    async def respond_error(self, request_id: str | int, code: int, message: str) -> None: ...
    async def close(self) -> None: ...


class ACPResponseError(RuntimeError):
    """A JSON-RPC server error with method metadata for bounded classification."""

    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.code = error.get("code")
        self.data = error.get("data")
        self.message = str(error.get("message", "ACP request failed"))
        super().__init__(self.message)


def normalize_frame(frame: dict[str, Any]) -> list[AgentEvent]:
    method, params = frame.get("method"), frame.get("params", {})
    if method == "session/request_permission":
        return [InputRequested("agent.permission.requested", params, frame.get("id"), method)]
    if method == "elicitation/create":
        return [InputRequested("agent.input.requested", params, frame.get("id"), method)]
    update = params.get("update", {})
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        content = update.get("content", {})
        return [AgentText(content["text"])] if content.get("type") == "text" else []
    if kind == "tool_call":
        return [AgentToolUse(update.get("title") or update.get("toolCallId", "tool"))]
    if kind == "request_input":
        return [InputRequested(update.get("messageKey", "agent.input.requested"), update.get("params", {}))]
    if kind == "agent_turn_complete":
        return [CompletionProposed([])]
    if method == "session/update" and kind == "session_info_update":
        return []
    if method == "session/update" and kind:
        return []
    if frame.get("error"):
        return [AgentError("agent.runtime.error", {"message": str(frame["error"])})]
    return []


class OpenCodeACPAdapter:
    def __init__(self, transport: ACPTransport, output_dir: str | Path | None = None,
                 session_cwd: str = "/workspace", mcp_servers: list[dict[str, Any]] | None = None):
        self._transport = transport
        self._output_dir = Path(output_dir) if output_dir else None
        self._session_cwd = session_cwd
        self._mcp_servers = mcp_servers or []
        self._session_id: str | None = None
        self._completion_ready = False
        self._prompt_task: asyncio.Task | None = None
        self._pending_requests: dict[str | int, dict[str, Any]] = {}
        self._available_models: list[str] = []

    async def start_session(self, cfg: Any) -> SessionHandle:
        await self._transport.request("initialize", {
            "protocolVersion": 1,
            "clientInfo": {"name": "kosmo", "version": "1"},
            "clientCapabilities": {"elicitation": {"form": {}}},
        })
        result = await self._transport.request("session/new", {"cwd": self._session_cwd, "mcpServers": self._mcp_servers})
        self._session_id = result["sessionId"]
        model_option = next((option for option in result.get("configOptions", []) if option.get("id") == "model"), None)
        self._available_models = [option["value"] for option in (model_option or {}).get("options", [])
                                  if isinstance(option, dict) and isinstance(option.get("value"), str)]
        model = cfg.get("model", "default") if isinstance(cfg, dict) else "default"
        if not isinstance(model, str) or not model.strip() or model == "default":
            if model_option is None:
                raise ValueError("workflow.agent.model_default_unavailable")
            model = model_option.get("currentValue")
            allowed = {option.get("value") for option in (model_option.get("options") or []) if isinstance(option, dict)}
            if not isinstance(model, str) or not model.strip() or model not in allowed:
                raise ValueError("workflow.agent.model_default_unavailable")
            await self._transport.request("session/set_config_option", {
                "sessionId": self._session_id, "configId": model_option["id"], "value": model,
            })
        else:
            if model_option is None:
                raise RuntimeError("OpenCode ACP session does not advertise model selection")
            allowed = {option.get("value") for option in (model_option.get("options") or [])}
            if model not in allowed:
                raise ValueError("Configured model is not available in the OpenCode ACP session")
            await self._transport.request("session/set_config_option", {
                "sessionId": self._session_id, "configId": model_option["id"], "value": model,
            })
        return SessionHandle(self._session_id)

    def list_models(self) -> list[str]:
        return list(self._available_models)

    async def send_prompt(self, text: str) -> None:
        self._require_session()
        if self._prompt_task and not self._prompt_task.done():
            raise RuntimeError("An ACP prompt is already in progress")
        self._completion_ready = False
        self._prompt_task = asyncio.create_task(self._transport.request(
            "session/prompt", {"sessionId": self._session_id, "prompt": [{"type": "text", "text": text}]},
        ))

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._session_id:
            raise RuntimeError("ACP session has not started")
        yield AgentStarted(self._session_id)
        while True:
            frame = None
            if self._prompt_task and self._prompt_task.done():
                if hasattr(self._transport, "receive_nowait"):
                    try:
                        frame = self._transport.receive_nowait()
                    except (asyncio.QueueEmpty, StopAsyncIteration):
                        frame = None
                if frame is None:
                    result = await self._prompt_task
                    self._prompt_task = None
                    self._completion_ready = result.get("stopReason") == "end_turn"
                    if self._completion_ready:
                        yield CompletionProposed([])
                    return
            elif self._prompt_task:
                receive_task = asyncio.create_task(self._transport.receive())
                done, _ = await asyncio.wait({receive_task, self._prompt_task}, return_when=asyncio.FIRST_COMPLETED)
                if receive_task in done:
                    try:
                        frame = receive_task.result()
                    except StopAsyncIteration:
                        if not self._prompt_task.done():
                            return
                        result = await self._prompt_task
                        self._prompt_task = None
                        self._completion_ready = result.get("stopReason") == "end_turn"
                        if self._completion_ready:
                            yield CompletionProposed([])
                        return
                else:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
                    continue
            else:
                try:
                    frame = await self._transport.receive()
                except StopAsyncIteration:
                    return
            if frame is None:
                continue
            normalized = normalize_frame(frame)
            if frame.get("id") is not None and frame.get("method") and not normalized:
                await self._transport.respond_error(frame["id"], -32601, "Method not supported")
                continue
            if frame.get("method") == "elicitation/create" and frame.get("params", {}).get("mode") != "form":
                await self._transport.respond_error(frame["id"], -32602, "Only form elicitation is supported")
                continue
            for event in normalized:
                if isinstance(event, InputRequested):
                    if event.request_id is not None:
                        self._pending_requests[event.request_id] = frame
                yield event
                if isinstance(event, (CompletionProposed, AgentError)):
                    return

    async def request_completion(self, expected_artifacts: list[ArtifactContract]) -> CompletionResult:
        # ACP has no separate completion RPC: the prompt's end_turn is the
        # completion proposal. Report only expected files actually present.
        available = await self.collect_artifacts()
        return CompletionResult([available[item.logical_name] for item in expected_artifacts if item.logical_name in available])

    async def deliver_feedback(self, errors: list[Any]) -> None:
        text = "Validation feedback (correct the artifacts and try again):\n" + "\n".join(
            json.dumps(error, sort_keys=True, ensure_ascii=False) if isinstance(error, dict) else str(error)
            for error in errors
        )
        await self.send_prompt(text)

    async def deliver_answer(self, text: str, request_id: str | int | None = None) -> None:
        if request_id is None and len(self._pending_requests) == 1:
            request_id = next(iter(self._pending_requests))
        if request_id is not None and request_id in self._pending_requests:
            frame = self._pending_requests.pop(request_id)
            method = frame["method"]
            params = frame.get("params", {})
            if method == "session/request_permission":
                options = params.get("options", [])
                selected = next((option for option in options if option.get("optionId") == text), None)
                if selected:
                    result = {"outcome": {"outcome": "selected", "optionId": selected["optionId"]}}
                else:
                    rejected = next((option for option in options if option.get("kind") == "reject_once"), None)
                    result = ({"outcome": {"outcome": "selected", "optionId": rejected["optionId"]}}
                              if rejected else {"outcome": {"outcome": "cancelled"}})
            elif method == "elicitation/create":
                if params.get("mode") == "form":
                    content = _parse_form_answer(text, params.get("requestedSchema", {}))
                    result = {"action": "accept", "content": content} if content is not None else {"action": "cancel"}
                else:
                    result = {"action": "accept"} if text == "accept" else {"action": "decline" if text == "decline" else "cancel"}
            else:
                result = {"answer": text}
            await self._transport.respond(request_id, result)
            return
        if self._prompt_task and not self._prompt_task.done():
            # Legacy/synthetic input updates have no JSON-RPC request id to
            # answer. Best-effort fallback is a second user prompt on the same
            # session; OpenCode 1.18.33 uses request_permission/elicitation instead.
            await self._transport.request("session/prompt", {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": text}],
            })
            return
        await self.send_prompt(text)

    async def collect_artifacts(self) -> dict[str, ArtifactRef]:
        if not self._output_dir or not self._output_dir.exists():
            return {}
        root = self._output_dir.resolve()
        artifacts = {}
        for path in root.iterdir():
            try:
                resolved = safe_path(root, path.name)
            except (ValueError, OSError):
                continue
            if resolved.is_file():
                artifacts[path.name] = ArtifactRef(id=str(resolved), logical_name=path.name)
        return artifacts

    def _require_session(self) -> None:
        if not self._session_id:
            raise RuntimeError("ACP session has not started")


def _parse_form_answer(answer: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    try:
        decoded = json.loads(answer)
        return decoded if isinstance(decoded, dict) else None
    except json.JSONDecodeError:
        properties = schema.get("properties", {})
        if len(properties) == 1:
            key, definition = next(iter(properties.items()))
            if definition.get("type") == "string":
                return {key: answer}
        return None


class StdioACPTransport:
    """Newline-delimited JSON-RPC over a Docker exec stream."""
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._pending_methods: dict[int, str] = {}
        self._reader_task = asyncio.create_task(self._read_frames())

    async def _read_frames(self) -> None:
        while line := await self.reader.readline():
            frame = json.loads(line)
            if frame.get("method"):
                await self._notifications.put(frame)
                continue
            future = self._pending.pop(frame.get("id"), None)
            if future:
                if "error" in frame:
                    method = self._pending_methods.pop(frame.get("id"), "unknown")
                    future.set_exception(ACPResponseError(method, frame["error"]))
                else:
                    self._pending_methods.pop(frame.get("id"), None)
                    future.set_result(frame.get("result", {}))
            else:
                await self._notifications.put(frame)

    @property
    def _notifications(self):
        if not hasattr(self, "__notifications"):
            self.__notifications = asyncio.Queue()
        return self.__notifications

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = future
        self._pending_methods[self._next_id] = method
        self.writer.write((json.dumps({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}) + "\n").encode())
        await self.writer.drain()
        return await future

    async def send(self, method: str, params: dict[str, Any]) -> None:
        self.writer.write((json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode())
        await self.writer.drain()

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        await self._write_frame({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def respond_error(self, request_id: str | int, code: int, message: str) -> None:
        await self._write_frame({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    async def _write_frame(self, frame: dict[str, Any]) -> None:
        self.writer.write((json.dumps(frame) + "\n").encode())
        await self.writer.drain()

    async def receive(self) -> dict[str, Any]:
        return await self._notifications.get()

    def receive_nowait(self) -> dict[str, Any]:
        return self._notifications.get_nowait()

    async def close(self) -> None:
        self._reader_task.cancel()
        await asyncio.gather(self._reader_task, return_exceptions=True)
        self.writer.close()


class DockerSocketACPTransport:
    """ACP over Docker exec's raw socket (demultiplexing Docker stdout frames)."""

    def __init__(self, sock):
        self._response_socket = sock
        # docker-py's unix transport returns a read-only SocketIO wrapper whose
        # private underlying socket is nevertheless the full-duplex hijack.
        self._socket = getattr(sock, "_sock", sock)
        self._loop = asyncio.get_running_loop()
        self._pending: dict[int, asyncio.Future] = {}
        self._pending_methods: dict[int, str] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._next_id = 0
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_frames, daemon=True)
        self._reader.start()

    def _read_exact(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            read = getattr(self._socket, "recv", None) or self._socket.read
            chunk = read(count - len(chunks))
            if not chunk:
                raise EOFError("Docker exec socket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _read_frames(self) -> None:
        buffered = bytearray()
        try:
            while True:
                header = self._read_exact(8)
                stream_type, length = header[0], struct.unpack(">I", header[4:])[0]
                payload = self._read_exact(length)
                if stream_type != 1:
                    continue
                buffered.extend(payload)
                while b"\n" in buffered:
                    line, _, remaining = buffered.partition(b"\n")
                    buffered = bytearray(remaining)
                    if line:
                        self._dispatch(json.loads(line))
        except Exception as exc:
            self._loop.call_soon_threadsafe(self._fail_pending, exc)

    def _dispatch(self, frame: dict[str, Any]) -> None:
        if frame.get("method"):
            self._loop.call_soon_threadsafe(self._notifications.put_nowait, frame)
            return
        response_id = frame.get("id")
        future = self._pending.pop(response_id, None) if response_id is not None else None
        if future:
            if "error" in frame:
                method = self._pending_methods.pop(response_id, "unknown")
                self._loop.call_soon_threadsafe(future.set_exception, ACPResponseError(method, frame["error"]))
            else:
                self._pending_methods.pop(response_id, None)
                self._loop.call_soon_threadsafe(future.set_result, frame.get("result", {}))
        else:
            self._loop.call_soon_threadsafe(self._notifications.put_nowait, frame)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError(f"Docker exec ACP stream closed: {exc}"))
        self._pending.clear()
        self._pending_methods.clear()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        future = self._loop.create_future()
        self._pending[self._next_id] = future
        self._pending_methods[self._next_id] = method
        try:
            await self._write({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        except Exception:
            self._pending.pop(self._next_id, None)
            self._pending_methods.pop(self._next_id, None)
            future.cancel()
            raise
        return await future

    async def send(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def respond_error(self, request_id: str | int, code: int, message: str) -> None:
        await self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    async def _write(self, frame: dict[str, Any]) -> None:
        payload = (json.dumps(frame) + "\n").encode()
        await asyncio.to_thread(self._sendall, payload)

    def _sendall(self, payload: bytes) -> None:
        with self._write_lock:
            sendall = getattr(self._socket, "sendall", None)
            if sendall:
                sendall(payload)
                return
            view = memoryview(payload)
            while view:
                written = self._socket.write(view)
                if written is None:
                    return
                view = view[written:]

    async def receive(self) -> dict[str, Any]:
        return await self._notifications.get()

    def receive_nowait(self) -> dict[str, Any]:
        return self._notifications.get_nowait()

    async def close(self) -> None:
        response = getattr(self._response_socket, "_response", None)
        if response is not None:
            response.close()
        self._response_socket.close()
        await asyncio.to_thread(self._reader.join, 1)
