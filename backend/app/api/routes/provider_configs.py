"""Encrypted user-owned runtime configuration uploads."""

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.db import get_db
from app.domain.provider_configs.repository import ProviderConfigRepository
from app.domain.provider_configs.service import (
    ProviderConfigService,
    ProviderConfigUnavailable,
    normalize_display_name,
)
from app.integrations.providers.opencode import OpenCodeProviderHandler
from shared.errors import ErrorDetail, KosmoError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/providers", tags=["providers"])
MAX_CONFIG_BYTES = 1_000_000


def get_provider_config_service(db: AsyncSession = Depends(get_db)) -> ProviderConfigService:
    return ProviderConfigService(ProviderConfigRepository(db), settings.config_encryption_key)


class ModelVerificationRequest(BaseModel):
    model: str = Field(min_length=1, max_length=300)


class CandidateConfig(BaseModel):
    model_config = {"extra": "forbid"}
    config: dict
    auth: dict | None = None


class CandidateModelVerification(CandidateConfig):
    model: str = Field(min_length=1, max_length=300)


class TemporalOpenCodeRuntime:
    def __init__(self, config_service: ProviderConfigService):
        self._config_service = config_service

    async def _execute(self, activity_name: str, payload: dict):
        from temporalio.client import Client

        # The running Temporal server does not support standalone activities,
        # so the probe runs inside a one-shot workflow (the project's standard
        # execution path).
        from worker.workflows.provider_probe import ProviderProbeWorkflow

        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        return await client.execute_workflow(
            ProviderProbeWorkflow.run,
            args=[activity_name, payload],
            id=f"provider-probe-{uuid.uuid4().hex}",
            task_queue=settings.temporal_task_queue,
        )

    async def list_models(self, user_id: str) -> list[str]:
        return await self._execute("list_opencode_models", {"user_id": user_id})

    async def verify_model(self, user_id: str, model: str) -> dict:
        return await self._execute("verify_opencode_model", {"user_id": user_id, "model": model})

    async def list_candidate_models(self, user_id: str, config: dict, auth: dict | None) -> list[str]:
        operation_id = await self._create_operation(user_id, config, auth)
        try:
            return await self._execute("list_opencode_candidate_models",
                                       {"operation_id": operation_id, "user_id": user_id})
        except Exception as exc:
            await self._discard_operation(operation_id)
            raise RuntimeError("Candidate model discovery is unavailable") from exc

    async def verify_candidate_model(self, user_id: str, config: dict, auth: dict | None, model: str) -> dict:
        operation_id = await self._create_operation(user_id, config, auth)
        try:
            result = await self._execute("verify_opencode_candidate_model",
                                         {"operation_id": operation_id, "user_id": user_id,
                                          "model": model, "consume": False})
        except Exception as exc:
            await self._discard_operation(operation_id)
            raise RuntimeError("Candidate verification is unavailable") from exc
        if not result.get("ok"):
            # A failed container test cannot produce a proof; release the row.
            await self._discard_operation(operation_id)
            return result
        # The operation stays alive for its short TTL and becomes the single-use
        # proof that this exact configuration passed the real container test;
        # the save endpoint redeems it against the uploaded files.
        return {**result, "verification_id": operation_id}

    async def _create_operation(self, user_id: str, config: dict, auth: dict | None) -> str:
        # Only the operation id may enter the Temporal payload/history; the
        # credentials travel encrypted through the candidate operation row.
        return await self._config_service.create_candidate_operation(user_id, "opencode", config, auth)

    async def _discard_operation(self, operation_id: str) -> None:
        try:
            await self._config_service.repository.delete_candidate_operation(operation_id)
        except Exception:
            pass  # best effort; any leaked row expires with the operation TTL


def get_provider_handler(service: ProviderConfigService = Depends(get_provider_config_service)) -> OpenCodeProviderHandler:
    return OpenCodeProviderHandler(TemporalOpenCodeRuntime(service))


@router.post("/opencode/config/candidate/validate")
async def validate_candidate(body: CandidateConfig, user=Depends(get_current_user),
                             handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    del user
    violations = handler.validate_config(body.config, body.auth)
    return {"valid": not violations, "violations": violations}


@router.post("/opencode/config/candidate/models")
async def candidate_models(body: CandidateConfig, user=Depends(get_current_user),
                           handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    violations = handler.validate_config(body.config, body.auth)
    if violations:
        return {"valid": False, "violations": violations, "models": []}
    try:
        models = await handler.list_candidate_models(user.id, body.config, body.auth)
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc
    except RuntimeError:
        raise ValidationFailedError("errors.provider.candidate_operation_unavailable") from None
    return {"valid": True, "violations": [], "models": models}


@router.post("/opencode/config/candidate/verify-model")
async def verify_candidate_model(body: CandidateModelVerification, user=Depends(get_current_user),
                                 handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    violations = handler.validate_config(body.config, body.auth)
    if violations:
        return {"ok": False, "error": {"code": "PROVIDER_CONFIG_INVALID",
                "message_key": "errors.provider.config_invalid", "details": violations}}
    try:
        return await handler.verify_candidate_model(user.id, body.config, body.auth, body.model)
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc
    except RuntimeError:
        raise ValidationFailedError("errors.provider.candidate_operation_unavailable") from None


@router.put("/opencode/config")
async def replace_opencode_config(
    opencode_json: UploadFile = File(...),
    auth_json: UploadFile | None = File(default=None),
    name: str | None = Form(default=None),
    visibility: str = Form(default="personal"),
    group_id: str | None = Form(default=None),
    verification_id: str | None = Form(default=None, max_length=64),
    user=Depends(get_current_user),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    # The display name is mandatory and user-entered: absent, empty, and
    # whitespace-only values are rejected, never defaulted to the provider type.
    display_name = normalize_display_name(name or "")
    config = await _read_upload(opencode_json, "opencode.json")
    auth = await _read_upload(auth_json, "auth.json") if auth_json is not None else None
    try:
        config_value, auth_value = _json_object(config, "opencode.json"), _json_object(auth, "auth.json") if auth else None
        violations = handler.validate_config(config_value, auth_value)
        if violations:
            raise ValidationFailedError("errors.provider.config_invalid", details=[
                ErrorDetail(item["message_key"], item.get("params", {})) for item in violations
            ])
        # verification_id is the single-use proof from a successful candidate
        # model verification; the save records "verified" only when the uploaded
        # files match the exact configuration the container test ran against.
        return await service.scoped_replace(user, "opencode", config, auth, visibility, group_id,
                                            verification_id=verification_id, display_name=display_name)
    except ValueError as exc:
        raise ValidationFailedError("errors.provider.config_invalid") from exc
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc


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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    row = await service.repository.get(user.id, "opencode")
    if row is not None:
        await service.set_verification_status(row.id, "verified" if result.get("ok") else "failed")
    if not result.get("ok") and result.get("error", {}).get("code") == "PROVIDER_AUTH_MISSING":
        raise ValidationFailedError("errors.provider.auth_missing", params={"provider": "opencode"})
    return result


async def _read_upload(upload: UploadFile, expected_filename: str) -> bytes:
    if upload.filename and upload.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] != expected_filename:
        raise ValidationFailedError("errors.provider.upload_filename_invalid", params={"filename": expected_filename})
    try:
        contents = await upload.read(MAX_CONFIG_BYTES + 1)
    except Exception as exc:
        raise ValidationFailedError("errors.provider.upload_failed") from exc
    if len(contents) > MAX_CONFIG_BYTES:
        raise KosmoError("errors.provider.upload_too_large", params={"filename": expected_filename}, http_status=413)
    return contents


async def _read_config_files(service: ProviderConfigService, user_id: str) -> dict[str, bytes]:
    try:
        files = await service.read_files(user_id, "opencode")
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc
    if files is None:
        raise NotFoundError("errors.provider.config_not_found")
    return files


def _json_object(contents: bytes | None, filename: str):
    if contents is None:
        return None
    try:
        result = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationFailedError("errors.provider.json_invalid", params={"filename": filename}) from None
    if not isinstance(result, dict):
        raise ValidationFailedError("errors.provider.json_object_required", params={"filename": filename})
    return result
