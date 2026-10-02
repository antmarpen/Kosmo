"""One-shot OpenCode provider verification activities for builder config flows.

Everything an activity returns crosses into Temporal history and from there
into API responses, so the result contract is deliberately narrow:

- discovery returns model names, or a keyed error envelope;
- verification returns only the non-empty-response assertion (boolean) and
  the measured latency, or a keyed error envelope.

Raw agent output, container/ACP exception text, and credentials never cross
the activity boundary: every failure path is normalized into stable keyed
errors (``errors.provider.*``) before the result exists.
"""

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


async def _config_files(user_id: str, config_id: str | None = None):
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        service = ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        )
        if config_id:
            # The payload names the targeted configuration by reference; the
            # credentials are decrypted here, never carried through Temporal.
            return await service.read_files_by_id(config_id)
        return await service.read_files(user_id, "opencode")


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
    marks it as a succeeded verification and its id becomes the single-use
    verification_id that the save endpoint redeems against the uploaded files.
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


def _error(code: str, message_key: str, **params) -> dict:
    return {"ok": False, "error": {"code": code, "message_key": message_key, "params": params}}


_DISCOVERY_FAILED = ("PROVIDER_DISCOVERY_FAILED", "errors.provider.verification_failed")
_VERIFICATION_FAILED = ("PROVIDER_VERIFICATION_FAILED", "errors.provider.verification_failed")


def _remove_workspace(workspace: Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)


async def _close_quietly(adapter) -> None:
    if adapter is None:
        return
    try:
        await adapter.close()
    except Exception:
        pass  # cleanup must never mask the probe result or leak its text


@activity.defn(name="list_opencode_models")
async def list_opencode_models(payload: dict) -> dict:
    try:
        files = await _config_files(payload["user_id"], payload.get("config_id"))
        if files is None:
            return {"models": []}
        return await _discover_models(files)
    except Exception:
        return _error(*_DISCOVERY_FAILED)


@activity.defn(name="verify_opencode_model")
async def verify_opencode_model(payload: dict) -> dict:
    try:
        return await _verify_saved_model(payload)
    except Exception:
        return _error(*_VERIFICATION_FAILED)


async def _verify_saved_model(payload: dict) -> dict:
    files = await _config_files(payload["user_id"], payload.get("config_id"))
    if files is None:
        return _error("PROVIDER_CONFIG_MISSING", "errors.provider.config_not_found")
    config = json.loads(files["opencode.json"])
    auth = json.loads(files["auth.json"]) if "auth.json" in files else None
    violations = OpenCodeProviderHandler(None).validate_config(config, auth)
    if any(item["code"] == "auth_missing" for item in violations):
        return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing", provider="opencode")
    if violations:
        return _error("PROVIDER_CONFIG_INVALID", "errors.provider.config_invalid")
    return await _verify_model_with_container(files, payload["model"])


@activity.defn(name="list_opencode_candidate_models")
async def list_opencode_candidate_models(payload: dict) -> dict:
    try:
        return await _list_candidate_models(payload)
    except NotFoundError:
        return _error("PROVIDER_CONFIG_MISSING", "errors.provider.config_not_found")
    except Exception:
        return _error(*_DISCOVERY_FAILED)


async def _list_candidate_models(payload: dict) -> dict:
    # The operation (and with it the credentials) is consumed before any
    # container work starts; a failed container can never re-read it.
    resolved = await _consume_candidate_operation(payload["operation_id"], payload["user_id"])
    return await _discover_models(_candidate_files(resolved))


@activity.defn(name="verify_opencode_candidate_model")
async def verify_opencode_candidate_model(payload: dict) -> dict:
    try:
        return await _verify_candidate_model(payload)
    except NotFoundError:
        return _error("PROVIDER_CONFIG_MISSING", "errors.provider.config_not_found")
    except Exception:
        return _error(*_VERIFICATION_FAILED)


async def _verify_candidate_model(payload: dict) -> dict:
    # Verification defaults to the legacy consuming behavior for in-flight
    # payloads; the API always sends "consume": False so the operation survives
    # as the single-use proof redeemed by the save endpoint.
    if payload.get("consume", True):
        resolved = await _consume_candidate_operation(payload["operation_id"], payload["user_id"])
    else:
        resolved = await _load_candidate_operation(payload["operation_id"], payload["user_id"])
    config, auth = resolved["config"], resolved.get("auth")
    violations = OpenCodeProviderHandler(None).validate_config(config, auth)
    if any(item["code"] == "auth_missing" for item in violations):
        return _error("PROVIDER_AUTH_MISSING", "errors.provider.auth_missing", provider="opencode")
    if violations:
        return _error("PROVIDER_CONFIG_INVALID", "errors.provider.config_invalid")
    return await _verify_model_with_container(_candidate_files(resolved), payload["model"])


async def _discover_models(files: dict[str, bytes]) -> dict:
    from worker.activities.agent import start_agent_session, TASK_STORAGE_ROOT

    workspace = TASK_STORAGE_ROOT / "provider-verification" / uuid.uuid4().hex
    workspace.mkdir(parents=True, exist_ok=True)
    adapter = None
    try:
        adapter = await start_agent_session(
            {"model": "default"}, str(workspace), runtime_config_files=files,
        )
        await adapter.start_session({"model": "default"})
        models = adapter._adapter.list_models()
        return {"models": [str(model) for model in models]}
    finally:
        await _close_quietly(adapter)
        _remove_workspace(workspace)


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
            received_text = False
            async for event in adapter.events():
                from shared.agent_events import AgentError, AgentText, CompletionProposed, InputRequested
                if isinstance(event, AgentError):
                    return _error("PROVIDER_VERIFICATION_FAILED", "errors.provider.verification_failed")
                if isinstance(event, InputRequested):
                    await adapter.deliver_answer("cancel", event.request_id)
                if isinstance(event, AgentText) and event.delta.strip():
                    # The assertion is recorded while the agent's words stay in
                    # the container: no text ever enters the activity result.
                    received_text = True
                if isinstance(event, CompletionProposed):
                    break
        latency_ms = int((time.monotonic() - started) * 1000)
        if not received_text:
            return _error("PROVIDER_EMPTY_RESPONSE", "errors.provider.verification_empty")
        return {"ok": True, "response_non_empty": True, "latency_ms": latency_ms}
    except TimeoutError:
        return _error("PROVIDER_VERIFICATION_TIMEOUT", "errors.provider.verification_timeout")
    finally:
        await _close_quietly(adapter)
        _remove_workspace(workspace)
