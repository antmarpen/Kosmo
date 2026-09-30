"""Encrypted user-owned runtime configuration uploads."""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.common import RetryPolicy

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.db import get_db
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import ProviderConfigService, ProviderConfigUnavailable
from app.integrations.providers.opencode import OpenCodeProviderHandler
from shared.errors import ErrorDetail, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/providers", tags=["providers"])
MAX_CONFIG_BYTES = 1_000_000


def get_provider_config_service(db: AsyncSession = Depends(get_db)) -> ProviderConfigService:
    return ProviderConfigService(ProviderConfigRepository(db), settings.config_encryption_key)


class ModelVerificationRequest(BaseModel):
    model: str = Field(min_length=1, max_length=300)


class TemporalOpenCodeRuntime:
    async def _execute(self, activity_name: str, payload: dict):
        from temporalio.client import Client

        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        try:
            return await client.execute_activity(
                activity_name, payload, task_queue=settings.temporal_task_queue,
                start_to_close_timeout=timedelta(seconds=75),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        finally:
            await client.close()

    async def list_models(self, user_id: str) -> list[str]:
        return await self._execute("list_opencode_models", {"user_id": user_id})

    async def verify_model(self, user_id: str, model: str) -> dict:
        return await self._execute("verify_opencode_model", {"user_id": user_id, "model": model})


def get_provider_handler() -> OpenCodeProviderHandler:
    return OpenCodeProviderHandler(TemporalOpenCodeRuntime())


@router.put("/opencode/config")
async def replace_opencode_config(
    opencode_json: UploadFile = File(...),
    auth_json: UploadFile | None = File(default=None),
    visibility: str = Form(default="personal"),
    group_id: str | None = Form(default=None),
    user=Depends(require_roles("builder", "admin")),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    config = await _read_upload(opencode_json, "opencode.json")
    auth = await _read_upload(auth_json, "auth.json") if auth_json is not None else None
    try:
        config_value, auth_value = _json_object(config, "opencode.json"), _json_object(auth, "auth.json") if auth else None
        violations = handler.validate_config(config_value, auth_value)
        if violations:
            raise ValidationFailedError("errors.provider.config_invalid", details=[
                ErrorDetail(item["message_key"], item.get("params", {})) for item in violations
            ])
        return await service.scoped_replace(user, "opencode", config, auth, visibility, group_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ProviderConfigUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/opencode/config")
async def get_opencode_config_metadata(
    user=Depends(get_current_user),
    service: ProviderConfigService = Depends(get_provider_config_service),
):
    try:
        return await service.list_visible(user.id, "opencode")
    except ProviderConfigUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.delete("/opencode/config")
async def delete_opencode_config(
    config_id: str | None = Query(default=None),
    user=Depends(require_roles("builder", "admin")),
    service: ProviderConfigService = Depends(get_provider_config_service),
):
    if config_id is None:
        # Backwards-compatible personal scope delete; never delete another owner's row.
        row = await service.repository.get_scoped(user.id, "opencode", "personal")
        deleted = await service.delete_owned(user, row.id) if row else False
    else:
        deleted = await service.delete_owned(user, config_id)
    return {"provider": "opencode", "deleted": deleted, "configured": False}


@router.post("/opencode/config/verify")
async def verify_opencode_config(
    user=Depends(require_roles("builder", "admin")),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    files = await _read_config_files(service, user.id)
    config = _json_object(files["opencode.json"], "opencode.json")
    auth = _json_object(files["auth.json"], "auth.json") if "auth.json" in files else None
    violations = handler.validate_config(config, auth)
    if violations:
        return {"valid": False, "violations": violations, "models": []}
    models = await handler.list_models(user.id)
    return {"valid": True, "violations": [], "models": models}


@router.post("/opencode/config/verify-model")
async def verify_opencode_model(
    body: ModelVerificationRequest,
    user=Depends(require_roles("builder", "admin")),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    files = await _read_config_files(service, user.id)
    config = _json_object(files["opencode.json"], "opencode.json")
    auth = _json_object(files["auth.json"], "auth.json") if "auth.json" in files else None
    violations = handler.validate_config(config, auth)
    auth_missing = next((item for item in violations if item["code"] == "auth_missing"), None)
    if auth_missing:
        raise ValidationFailedError("errors.provider.auth_missing", params={"provider": "opencode"})
    if violations:
        raise ValidationFailedError("errors.provider.config_invalid", details=[
            ErrorDetail(item["message_key"], item.get("params", {})) for item in violations
        ])
    result = await handler.verify_model(user.id, body.model)
    if not result.get("ok") and result.get("error", {}).get("code") == "PROVIDER_AUTH_MISSING":
        raise ValidationFailedError("errors.provider.auth_missing", params={"provider": "opencode"})
    return result


async def _read_upload(upload: UploadFile, expected_filename: str) -> bytes:
    if upload.filename and upload.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] != expected_filename:
        raise HTTPException(status_code=422, detail=f"Expected {expected_filename}")
    contents = await upload.read(MAX_CONFIG_BYTES + 1)
    if len(contents) > MAX_CONFIG_BYTES:
        raise HTTPException(status_code=413, detail=f"{expected_filename} exceeds the upload limit")
    return contents


async def _read_config_files(service: ProviderConfigService, user_id: str) -> dict[str, bytes]:
    try:
        files = await service.read_files(user_id, "opencode")
    except ProviderConfigUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if files is None:
        raise NotFoundError("errors.provider.config_not_found")
    return files


def _json_object(contents: bytes | None, filename: str):
    if contents is None:
        return None
    try:
        result = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail=f"{filename} must contain valid JSON") from None
    if not isinstance(result, dict):
        raise HTTPException(status_code=422, detail=f"{filename} must contain a JSON object")
    return result
