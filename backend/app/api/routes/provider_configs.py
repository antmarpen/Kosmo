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
from shared.errors import ErrorDetail, KosmoError, NotFoundError, PermissionDeniedError, ValidationFailedError

router = APIRouter(prefix="/providers", tags=["providers"])
MAX_CONFIG_BYTES = 1_000_000


def get_provider_config_service(db: AsyncSession = Depends(get_db)) -> ProviderConfigService:
    return ProviderConfigService(ProviderConfigRepository(db), settings.config_encryption_key)


class ModelVerificationRequest(BaseModel):
    model: str = Field(min_length=1, max_length=300)
    # The stored configuration the request targets; the caller's list row id.
    config_id: str | None = Field(default=None, max_length=64)


class ConfigVerifyRequest(BaseModel):
    """Metadata-only body naming the stored configuration to probe."""
    config_id: str | None = Field(default=None, max_length=64)


class CandidateConfig(BaseModel):
    model_config = {"extra": "forbid"}
    # The stored instance being edited: present when replacing files of one
    # saved configuration, absent when composing a brand-new pair (create
    # mode, where the full pair is required).
    config_id: str | None = Field(default=None, max_length=64)
    # Both are optional so an edit may replace either file alone: the missing
    # one is overlaid from the stored encrypted files server-side.
    config: dict | None = None
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

    async def list_models(self, user_id: str, config_id: str | None = None) -> list[str]:
        payload = {"user_id": user_id}
        if config_id:
            # Reference only: the worker re-reads the encrypted files itself.
            payload["config_id"] = config_id
        return _discovered_models(await self._execute("list_opencode_models", payload))

    async def verify_model(self, user_id: str, model: str, config_id: str | None = None) -> dict:
        payload = {"user_id": user_id, "model": model}
        if config_id:
            payload["config_id"] = config_id
        return await self._execute("verify_opencode_model", payload)

    async def list_candidate_models(self, user_id: str, config: dict, auth: dict | None) -> list[str]:
        operation_id = await self._create_operation(user_id, config, auth, purpose="discovery")
        try:
            result = await self._execute("list_opencode_candidate_models",
                                         {"operation_id": operation_id, "user_id": user_id})
        except Exception as exc:
            await self._discard_operation(operation_id)
            raise RuntimeError("Candidate model discovery is unavailable") from exc
        if isinstance(result, dict) and isinstance(result.get("error"), dict):
            # A failed discovery run cannot use its operation: release it (a
            # no-op when the activity already consumed it) and surface the
            # stable keyed error instead of any raw failure.
            await self._discard_operation(operation_id)
        # A keyed activity error becomes a keyed HTTP error; the raw container
        # failure never reaches the response.
        return _discovered_models(result)

    async def verify_candidate_model(self, user_id: str, config: dict, auth: dict | None, model: str) -> dict:
        operation_id = await self._create_operation(user_id, config, auth, purpose="verification")
        try:
            result = await self._execute("verify_opencode_candidate_model",
                                         {"operation_id": operation_id, "user_id": user_id,
                                          "model": model, "consume": False})
        except Exception as exc:
            await self._discard_operation(operation_id)
            raise RuntimeError("Candidate verification is unavailable") from exc
        if not (isinstance(result, dict) and result.get("ok")):
            # A failed container test cannot produce a proof; release the row.
            await self._discard_operation(operation_id)
            if isinstance(result, dict) and isinstance(result.get("error"), dict):
                return result
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_FAILED",
                    "message_key": "errors.provider.verification_failed", "params": {}}}
        # Record the success on the operation row: only marked rows are
        # redeemable as single-use proof at save time, so a result that
        # arrives without a recorded success can never brand a configuration.
        remaining = await self._config_service.mark_candidate_operation_verified(operation_id)
        if remaining is None:
            # The proof window closed while the container ran; report the
            # honest result without a redeemable proof.
            return result
        # The operation stays alive for its short TTL and becomes the single-use
        # proof that this exact configuration passed the real container test;
        # the save endpoint redeems it against the uploaded files. The remaining
        # validity lets the client expire its local state honestly.
        return {**result, "verification_id": operation_id, "proof_expires_in_seconds": remaining}

    async def _create_operation(self, user_id: str, config: dict, auth: dict | None,
                                *, purpose: str) -> str:
        # Only the operation id may enter the Temporal payload/history; the
        # credentials travel encrypted through the candidate operation row.
        return await self._config_service.create_candidate_operation(
            user_id, "opencode", config, auth, purpose=purpose)

    async def _discard_operation(self, operation_id: str) -> None:
        try:
            await self._config_service.repository.delete_candidate_operation(operation_id)
        except Exception:
            pass  # best effort; any leaked row expires with the operation TTL


def _discovered_models(result) -> list[str]:
    """Translate a discovery activity result into model names.

    A keyed error envelope crosses the boundary as a keyed HTTP error; any
    other shape yields plain model names and nothing else.
    """
    if isinstance(result, dict) and isinstance(result.get("error"), dict):
        error = result["error"]
        raise ValidationFailedError(error.get("message_key", "errors.provider.verification_failed"),
                                    params=error.get("params") or {})
    models = result.get("models") if isinstance(result, dict) else result
    return [str(model) for model in models] if models else []


def get_provider_handler(service: ProviderConfigService = Depends(get_provider_config_service)) -> OpenCodeProviderHandler:
    return OpenCodeProviderHandler(TemporalOpenCodeRuntime(service))


def _pair_validator(handler: OpenCodeProviderHandler):
    """Build the save-time validation hook for the create/update endpoints.

    Parses each provided file with the keyed JSON errors and rejects provider
    structure violations with their structured details; returns the parsed
    (config, auth) values so proof redemption compares the same objects the
    container test ran against.
    """
    def validate(config: bytes | None, auth: bytes | None):
        config_value = _json_object(config, "opencode.json") if config is not None else None
        auth_value = _json_object(auth, "auth.json") if auth is not None else None
        violations = handler.validate_config(config_value, auth_value)
        if violations:
            raise ValidationFailedError("errors.provider.config_invalid", details=[
                ErrorDetail(item["message_key"], item.get("params", {})) for item in violations
            ])
        return config_value, auth_value
    return validate


@router.post("/opencode/config/candidate/validate")
async def validate_candidate(body: CandidateConfig, user=Depends(get_current_user),
                             service: ProviderConfigService = Depends(get_provider_config_service),
                             handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    config, auth = await _effective_candidate_pair(service, user, body)
    violations = handler.validate_config(config, auth)
    return {"valid": not violations, "violations": violations}


@router.post("/opencode/config/candidate/models")
async def candidate_models(body: CandidateConfig, user=Depends(get_current_user),
                           service: ProviderConfigService = Depends(get_provider_config_service),
                           handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    config, auth = await _effective_candidate_pair(service, user, body)
    violations = handler.validate_config(config, auth)
    if violations:
        return {"valid": False, "violations": violations, "models": []}
    try:
        models = await handler.list_candidate_models(user.id, config, auth)
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc
    except RuntimeError:
        raise ValidationFailedError("errors.provider.candidate_operation_unavailable") from None
    return {"valid": True, "violations": [], "models": models}


@router.post("/opencode/config/candidate/verify-model")
async def verify_candidate_model(body: CandidateModelVerification, user=Depends(get_current_user),
                                 service: ProviderConfigService = Depends(get_provider_config_service),
                                 handler: OpenCodeProviderHandler = Depends(get_provider_handler)):
    config, auth = await _effective_candidate_pair(service, user, body)
    violations = handler.validate_config(config, auth)
    if violations:
        return {"ok": False, "error": {"code": "PROVIDER_CONFIG_INVALID",
                "message_key": "errors.provider.config_invalid", "details": violations}}
    try:
        return await handler.verify_candidate_model(user.id, config, auth, body.model)
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
    # Every call creates a DISTINCT instance; updating one is the PATCH route.
    display_name = normalize_display_name(name or "")
    config = await _read_upload(opencode_json, "opencode.json")
    auth = await _read_upload(auth_json, "auth.json") if auth_json is not None else None
    try:
        # verification_id is the single-use proof from a successful candidate
        # model verification; the save records "verified" only when the uploaded
        # files match the exact configuration the container test ran against.
        return await service.scoped_save(user, "opencode", config, auth, visibility, group_id,
                                         verification_id=verification_id, display_name=display_name,
                                         validate_pair=_pair_validator(handler))
    except ValueError as exc:
        raise ValidationFailedError("errors.provider.config_invalid") from exc
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc


@router.patch("/opencode/config")
async def update_opencode_config(
    config_id: str = Form(..., max_length=64),
    opencode_json: UploadFile | None = File(default=None),
    auth_json: UploadFile | None = File(default=None),
    name: str | None = Form(default=None),
    visibility: str = Form(default="personal"),
    group_id: str | None = Form(default=None),
    verification_id: str | None = Form(default=None, max_length=64),
    user=Depends(get_current_user),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    # Update one stored instance by id (owner or admin): the same id always
    # comes back. Files are optional — an absent upload keeps the stored
    # encrypted file, so decrypted secrets never travel through the client —
    # and an update that replaces no file needs no new verification proof.
    display_name = normalize_display_name(name or "")
    config = await _read_optional_upload(opencode_json, "opencode.json")
    auth = await _read_optional_upload(auth_json, "auth.json")
    try:
        return await service.scoped_save(user, "opencode", config, auth, visibility, group_id,
                                         verification_id=verification_id, display_name=display_name,
                                         config_id=config_id, validate_pair=_pair_validator(handler))
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
        row = await service.repository.get(user.id, "opencode")
        deleted = await service.delete_owned(user, row.id) if row else False
    else:
        deleted = await service.delete_owned(user, config_id)
    return {"provider": "opencode", "deleted": deleted, "configured": False}


async def _resolve_verification_target(service: ProviderConfigService, user, config_id: str | None):
    """Resolve the exact configuration a saved-config verification targets.

    An explicit id must name an existing configuration visible to the caller
    (same visibility model as the list endpoint). Without one, the caller's
    personal scope is the only unambiguous legacy fallback.
    """
    if config_id is not None:
        return await service.visible_row(user.id, config_id)
    row = await service.repository.get(user.id, "opencode")
    if row is None:
        raise NotFoundError("errors.provider.config_not_found")
    return row


async def _read_row_files(service: ProviderConfigService, row) -> dict[str, bytes]:
    try:
        return service.read_row_files(row)
    except ProviderConfigUnavailable as exc:
        raise KosmoError("errors.provider.storage_unavailable", http_status=503) from exc


async def _effective_candidate_pair(service: ProviderConfigService, user, body: CandidateConfig):
    """Resolve the exact pair a candidate operation will attest.

    With `config_id` the request edits one stored instance: the replaced
    files from the body are overlaid on the stored encrypted files (decrypted
    server-side, never returned to the client), so the candidate proof attests
    exactly the effective pair a save of this request would store. Without
    one, the body must carry the full pair (create mode, unchanged).
    """
    if body.config_id is None:
        if body.config is None:
            raise ValidationFailedError("errors.provider.config_invalid")
        return body.config, body.auth
    row = await service.visible_row(user.id, body.config_id)
    # Edit-mode candidates overlay caller-supplied files on the stored
    # (decrypted) credentials, so only the owner or an admin may target a row.
    # Merely seeing a shared group/global row must never let a non-owner
    # inherit its secrets or launch a probe with them; this mirrors the save
    # path's authorization rule.
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if role != "admin" and row.user_id != user.id:
        raise PermissionDeniedError("errors.provider.forbidden")
    stored = await _read_row_files(service, row)
    config = body.config if body.config is not None else _json_object(stored["opencode.json"], "opencode.json")
    auth = body.auth if body.auth is not None else (
        _json_object(stored["auth.json"], "auth.json") if "auth.json" in stored else None)
    return config, auth


@router.post("/opencode/config/verify")
async def verify_opencode_config(
    body: ConfigVerifyRequest | None = None,
    user=Depends(get_current_user),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    row = await _resolve_verification_target(service, user, body.config_id if body else None)
    files = await _read_row_files(service, row)
    config = _json_object(files["opencode.json"], "opencode.json")
    auth = _json_object(files["auth.json"], "auth.json") if "auth.json" in files else None
    violations = handler.validate_config(config, auth)
    if violations:
        return {"valid": False, "violations": violations, "models": []}
    models = await handler.list_models(user.id, config_id=row.id)
    return {"valid": True, "violations": [], "models": models}


@router.post("/opencode/config/verify-model")
async def verify_opencode_model(
    body: ModelVerificationRequest,
    user=Depends(get_current_user),
    service: ProviderConfigService = Depends(get_provider_config_service),
    handler: OpenCodeProviderHandler = Depends(get_provider_handler),
):
    row = await _resolve_verification_target(service, user, body.config_id)
    files = await _read_row_files(service, row)
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
    # The row version is captured before the probe: the status write is
    # guarded by it, so a result that arrives after the files were replaced
    # updates nothing instead of branding the replacement as verified.
    target_id, target_updated_at = row.id, row.updated_at
    result = await handler.verify_model(user.id, body.model, config_id=row.id)
    await service.set_verification_status(
        target_id, "verified" if result.get("ok") else "failed",
        expected_updated_at=target_updated_at)
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


async def _read_optional_upload(upload: UploadFile | None, expected_filename: str) -> bytes | None:
    """Read an update upload that may be absent (keep the stored file)."""
    if upload is None or not upload.filename:
        return None
    return await _read_upload(upload, expected_filename)


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
