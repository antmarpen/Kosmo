"""One-shot OpenCode provider verification activities for builder config flows."""

import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path

from temporalio import activity

from app.integrations.providers.opencode import OpenCodeProviderHandler
from shared.errors import NotFoundError

CANDIDATE_PROVIDER = "opencode"


async def _config_files(user_id: str):
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        return await ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        ).read_files(user_id, "opencode")


async def _consume_candidate_operation(operation_id: str, user_id: str) -> dict:
    """Resolve and delete the single-use candidate operation (worker side)."""
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        return await ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        ).consume_candidate_operation(operation_id, user_id, CANDIDATE_PROVIDER)


async def _load_candidate_operation(operation_id: str, user_id: str) -> dict:
    """Resolve the candidate operation WITHOUT consuming it (verification proof).

    Model verification must leave the operation alive: on success the API
    returns its id as a single-use verification_id that the save endpoint
    redeems against the uploaded files.
    """
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        return await ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        ).read_candidate_operation(operation_id, user_id, CANDIDATE_PROVIDER)


def _candidate_files(resolved: dict) -> dict[str, bytes]:
    files = {"opencode.json": json.dumps(resolved["config"]).encode("utf-8")}
    if resolved.get("auth"):
        files["auth.json"] = json.dumps(resolved["auth"]).encode("utf-8")
    return files


@activity.defn(name="list_opencode_models")
async def list_opencode_models(payload: dict) -> list[str]:
    files = await _config_files(payload["user_id"])
    if files is None:
        return []
    return await _list_models_with_container(files)


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
    return await _verify_model_with_container(files, model)


@activity.defn(name="list_opencode_candidate_models")
async def list_opencode_candidate_models(payload: dict) -> list[str]:
    # The operation (and with it the credentials) is consumed before any
    # container work starts; a failed container can never re-read it.
    resolved = await _consume_candidate_operation(payload["operation_id"], payload["user_id"])
    return await _list_models_with_container(_candidate_files(resolved))


@activity.defn(name="verify_opencode_candidate_model")
async def verify_opencode_candidate_model(payload: dict) -> dict:
    # Verification defaults to the legacy consuming behavior for in-flight
    # payloads; the API always sends "consume": False so the operation survives
    # as the single-use proof redeemed by the save endpoint.
    try:
        if payload.get("consume", True):
            resolved = await _consume_candidate_operation(payload["operation_id"], payload["user_id"])
        else:
            resolved = await _load_candidate_operation(payload["operation_id"], payload["user_id"])
    except NotFoundError:
        return _error("PROVIDER_CONFIG_MISSING", "errors.provider.config_not_found")
    config, auth = resolved["config"], resolved.get("auth")
    violations = OpenCodeProviderHandler(None).validate_config(config, auth)
    if any(item["code"] == "auth_missing" for item in violations):
        return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing", provider="opencode")
    if violations:
        return _error("PROVIDER_CONFIG_INVALID", "errors.provider.config_invalid")
    return await _verify_model_with_container(_candidate_files(resolved), payload["model"])


async def _list_models_with_container(files: dict[str, bytes]) -> list[str]:
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


async def _verify_model_with_container(files: dict[str, bytes], model: str) -> dict:
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
