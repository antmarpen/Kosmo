"""One-shot OpenCode provider verification activities for builder config flows."""

import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path

from temporalio import activity

from app.integrations.providers.opencode import OpenCodeProviderHandler


async def _config_files(user_id: str):
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        return await ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        ).read_files(user_id, "opencode")


@activity.defn(name="list_opencode_models")
async def list_opencode_models(payload: dict) -> list[str]:
    files = await _config_files(payload["user_id"])
    if files is None:
        return []
    from worker.activities.agent import start_agent_session, TASK_STORAGE_ROOT

    workspace = TASK_STORAGE_ROOT / "provider-verification" / uuid.uuid4().hex
    workspace.mkdir(parents=True, exist_ok=True)
    adapter = None
    try:
        adapter = await start_agent_session(
            {"model": "default"}, str(workspace), runtime_config_files=files,
        )
        await adapter.start_session({"model": "default"})
        return adapter._adapter.list_models()
    finally:
        if adapter is not None:
            await adapter.close()
        await asyncio.to_thread(shutil.rmtree, workspace, True)


@activity.defn(name="verify_opencode_model")
async def verify_opencode_model(payload: dict) -> dict:
    user_id, model = payload["user_id"], payload["model"]
    files = await _config_files(user_id)
    if files is None:
        return _error("PROVIDER_CONFIG_MISSING", "errors.provider.config_not_found")
    config = json.loads(files["opencode.json"])
    auth = json.loads(files["auth.json"]) if "auth.json" in files else None
    violations = OpenCodeProviderHandler(None).validate_config(config, auth)
    if any(item["code"] == "auth_missing" for item in violations):
        return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing", provider="opencode")
    if violations:
        return _error("PROVIDER_CONFIG_INVALID", "errors.provider.config_invalid")

    from worker.activities.agent import start_agent_session, TASK_STORAGE_ROOT

    workspace = TASK_STORAGE_ROOT / "provider-verification" / uuid.uuid4().hex
    workspace.mkdir(parents=True, exist_ok=True)
    adapter = None
    started = time.monotonic()
    try:
        async with asyncio.timeout(60):
            adapter = await start_agent_session({"model": model}, str(workspace), runtime_config_files=files)
            await adapter.start_session({"model": model})
            await adapter.send_prompt("Reply with the word ok.")
            chunks = []
            async for event in adapter.events():
                from shared.agent_events import AgentError, AgentText, CompletionProposed, InputRequested
                if isinstance(event, AgentError):
                    return _error("PROVIDER_VERIFICATION_FAILED", "errors.provider.verification_failed")
                if isinstance(event, InputRequested):
                    await adapter.deliver_answer("cancel", event.request_id)
                if isinstance(event, AgentText):
                    chunks.append(event.delta)
                if isinstance(event, CompletionProposed):
                    break
        response = "".join(chunks).strip()
        latency_ms = int((time.monotonic() - started) * 1000)
        if not response:
            return _error("PROVIDER_EMPTY_RESPONSE", "errors.provider.verification_empty")
        return {"ok": True, "response_snippet": response[:240], "latency_ms": latency_ms}
    except TimeoutError:
        return _error("PROVIDER_VERIFICATION_TIMEOUT", "errors.provider.verification_timeout")
    except Exception as exc:
        if not files and adapter is not None:
            return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing")
        text = str(exc).casefold()
        if any(term in text for term in ("unauthorized", "authentication", "api key", "credential")):
            return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing")
        return _error("PROVIDER_VERIFICATION_FAILED", "errors.provider.verification_failed",
                      reason=type(exc).__name__)
    finally:
        if adapter is not None:
            await adapter.close()
        await asyncio.to_thread(shutil.rmtree, workspace, True)


def _error(code: str, message_key: str, **params) -> dict:
    return {"ok": False, "error": {"code": code, "message_key": message_key, "params": params}}
