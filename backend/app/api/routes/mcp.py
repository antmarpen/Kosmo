"""Authenticated MCP-over-HTTP validation tool and compatibility REST route."""

import json
import logging
import os
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.api.deps import bearer, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.domain.tasks.validator_repository import ValidatorRepository
from shared.errors import AuthError, NotFoundError, PermissionDeniedError, ValidationFailedError

router = APIRouter(prefix="/mcp", tags=["mcp"])
logger = logging.getLogger(__name__)


async def _validation_probe(content: bytes, contract: dict, level: int, logical_name: str) -> list[dict]:
    """Stage content outside Temporal history and ask the worker to validate it."""
    from temporalio.client import Client
    from worker.workflows.validation_probe import ValidationProbeWorkflow

    request_id = uuid.uuid4().hex
    root = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks"))
    directory = root / "validation-probes" / request_id
    directory.mkdir(parents=True, exist_ok=False)
    try:
        (directory / "candidate.bin").write_bytes(content)
        (directory / "request.json").write_text(
            json.dumps({"contract": contract, "level": level, "logical_name": logical_name}, allow_nan=False), encoding="utf-8"
        )
        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        result = await client.execute_workflow(
            ValidationProbeWorkflow.run, args=[{"request_id": request_id}],
            id=f"validation-probe-{request_id}", task_queue=settings.temporal_task_queue,
            execution_timeout=timedelta(seconds=25),
        )
        return result["errors"]
    finally:
        shutil.rmtree(directory, ignore_errors=True)
VALIDATOR_ISSUER = "kosmo-agent-validator"
VALIDATOR_AUDIENCE = "kosmo-validator"
VALIDATOR_TOOL = {
    "name": "validate_candidate",
    "description": "Validate candidate output content for the current task and AI node without persisting it.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "minimum": 1, "maximum": 3},
            "logical_name": {"type": "string"},
            "media_type": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["level", "logical_name", "media_type", "content"],
    },
}


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_ref: str | None = Field(default=None, min_length=1, max_length=36)
    task_id: str | None = Field(default=None, min_length=1, max_length=36)
    node_id: str | None = Field(default=None, min_length=1, max_length=200)
    node_execution_id: str | None = Field(default=None, min_length=1, max_length=36)
    level: int = Field(ge=1, le=3)
    logical_name: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=1_000_000)
    media_type: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_artifact_or_candidate(self):
        if self.artifact_ref is None and not all((self.task_id, self.node_id, self.node_execution_id,
                                                   self.logical_name, self.content is not None,
                                                   self.media_type)):
            raise ValueError("Candidate validation requires task, node, execution, logical name, content, and media type")
        return self


@router.post("/validator")
async def validate_artifact(payload: dict[str, Any],
                            credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                            db=Depends(get_db)):
    repository = ValidatorRepository(db)
    auth = await _authorize(credentials, db)
    if "jsonrpc" in payload:
        return await _handle_mcp_request(payload, auth, repository)
    try:
        request = ValidationRequest.model_validate(payload)
    except ValidationError:
        raise ValidationFailedError("errors.validation.invalid_request") from None
    return {"errors": await _validate_request(request, auth, repository)}


async def _authorize(credentials, db):
    if not credentials or not settings.jwt_secret:
        raise AuthError("errors.auth.unauthorized")
    token = credentials.credentials
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.PyJWTError:
        raise AuthError("errors.auth.invalid_token") from None
    if claims.get("purpose") == "agent-validator":
        try:
            scoped = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                                audience=VALIDATOR_AUDIENCE, issuer=VALIDATOR_ISSUER)
        except jwt.PyJWTError:
            raise AuthError("errors.auth.invalid_token") from None
        if scoped.get("scope") != "validator:candidate":
            raise PermissionDeniedError("errors.permission.denied")
        return {"kind": "agent", "claims": scoped}
    user = await get_current_user(credentials, db)
    return {"kind": "user", "user": user}


async def _handle_mcp_request(payload, auth, repository):
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        version = params.get("protocolVersion", "2025-06-18")
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "kosmo-validator", "version": "1"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [VALIDATOR_TOOL]}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found"}}
    if params.get("name") != VALIDATOR_TOOL["name"]:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32602, "message": "Unknown validator tool"}}
    arguments = params.get("arguments") or {}
    claims = auth.get("claims", {})
    tool_request = {
        "task_id": claims.get("task_id"), "node_id": claims.get("node_id"),
        "node_execution_id": claims.get("node_execution_id"), **arguments,
    }
    try:
        request = ValidationRequest.model_validate(tool_request)
        errors = await _validate_request(request, auth, repository)
    except ValidationError:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32602, "message": "Invalid validator arguments"} }
    except PermissionDeniedError:
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"isError": True, "content": [{"type": "text", "text": "Candidate access denied"}]}}
    result = {"errors": errors}
    return {"jsonrpc": "2.0", "id": request_id, "result": {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "structuredContent": result,
        "isError": False,
    }}


async def _validate_request(request: ValidationRequest, auth, repository: ValidatorRepository):
    if request.artifact_ref:
        artifact = await repository.get_artifact(request.artifact_ref)
        if artifact is None:
            raise NotFoundError("errors.artifact.not_found")
        task_id, node_id = artifact.task_id, artifact.node_id
        logical_name, media_type = artifact.logical_name, artifact.media_type
        workspace = Path(artifact.storage_path).parent
        execution_id = auth.get("claims", {}).get("node_execution_id") if auth["kind"] == "agent" else None
        await _authorize_task_scope(auth, repository, task_id, node_id, execution_id)
        task = await repository.get_task(task_id)
        ai_node = _ai_node(task, node_id)
        source = safe_candidate_path(workspace, logical_name)
        return await _validation_probe(source.read_bytes(), _contract(ai_node, logical_name), request.level, logical_name)

    task_id, node_id = request.task_id, request.node_id
    await _authorize_task_scope(auth, repository, task_id, node_id, request.node_execution_id)
    task = await repository.get_task(task_id)
    ai_node = _ai_node(task, node_id)
    if request.logical_name not in ai_node.get("outputs", []):
        raise PermissionDeniedError("errors.permission.denied")
    logical_path = Path(request.logical_name)
    if logical_path.is_absolute() or ".." in logical_path.parts:
        raise ValidationFailedError("errors.artifact.invalid_path")
    return await _validation_probe((request.content or "").encode("utf-8"),
                                   _contract(ai_node, request.logical_name), request.level, request.logical_name)


def safe_candidate_path(workspace: Path, logical_name: str) -> Path:
    from shared.paths import safe_path
    return safe_path(workspace, logical_name)


def _contract(node: dict, logical_name: str) -> dict:
    contracts = _contracts(node)
    contract = contracts.get(logical_name, {})
    return contract if isinstance(contract, dict) else {}


async def _authorize_task_scope(auth, repository: ValidatorRepository, task_id: str, node_id: str, node_execution_id: str | None = None):
    if auth["kind"] == "agent":
        claims = auth["claims"]
        if claims.get("task_id") != task_id or claims.get("node_id") != node_id:
            raise PermissionDeniedError("errors.permission.denied")
        if node_execution_id is not None and claims.get("node_execution_id") != node_execution_id:
            raise PermissionDeniedError("errors.permission.denied")
    task = await repository.get_task(task_id)
    if task is None:
        raise NotFoundError("errors.task.not_found")
    if auth["kind"] == "agent":
        claims = auth["claims"]
        if node_execution_id:
            execution = await repository.get_node_execution(node_execution_id)
            if (execution is None or execution.task_id != task_id or execution.node_id != node_id
                    or execution.state != "running"):
                raise PermissionDeniedError("errors.permission.denied")
        return
    user = auth["user"]
    if task.created_by != user.id and user.role.value != "admin":
        raise PermissionDeniedError("errors.permission.denied")


def _contracts(node):
    contracts = node.get("output_validation") or {}
    if contracts:
        return contracts
    legacy = node.get("validation")
    return {name: legacy for name in node.get("outputs", [])} if legacy else {}


def _ai_node(task, node_id):
    if task is None:
        raise NotFoundError("errors.task.not_found")
    return next((node for node in task.resolved_definition["nodes"]
                 if node["id"] == node_id and node["type"] in {"ai", "script", "http", "workflow"}), None) or _missing_ai_node()


def _missing_ai_node():
    raise NotFoundError("errors.node.not_found")
