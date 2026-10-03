"""Worker-side entry point for shared output validation and rule sandboxing."""

import json
import os
import shutil
import uuid
from pathlib import Path

from temporalio import activity

from app.domain.workflows.output_validation import validate_content, validate_outputs_async as shared_validate_outputs_async
from app.domain.workflows.validation_logic import validate_outputs as validate_outputs_legacy
from worker.validation_runner import run_rule
from shared.paths import safe_path
from app.domain.tasks.service import validate_start_inputs as _validate_start_inputs

validate_outputs = validate_outputs_legacy


async def validate_outputs_async(outputs, workspace, contracts, level=None, inputs=None):
    """Worker facade; sandbox access stays in the worker process only."""
    if level is not None and not any(
        isinstance(contract, dict) and "format" in contract for contract in (contracts or {}).values()
    ):
        return validate_outputs_legacy(outputs, workspace, contracts, level, inputs)

    async def sandbox(rules, value, text):
        return await run_rule(rules, value, text)

    return await shared_validate_outputs_async(outputs, workspace, contracts, sandbox, inputs=inputs)


@activity.defn(name="validate_start_inputs")
async def validate_start_inputs(payload: dict) -> list[dict]:
    async def validate_rule(name, submitted, contract):
        failures = await validate_content(submitted.encode("utf-8"), contract, 3, _run_sandbox_rule)
        for failure in failures:
            failure["artifact"] = name
        return failures
    errors = await _validate_start_inputs(payload["start"], payload["input_values"], validate_rule)
    return [{"message_key": error.message_key, "params": error.params} for error in errors]


@activity.defn(name="validate_persisted_start_inputs")
async def validate_persisted_start_inputs(task_id: str) -> list[dict]:
    """Validate stored Start data in-worker; only diagnostics cross the boundary."""
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Task
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None:
            raise ValueError("Task no longer exists")
        definition, values = task.resolved_definition, task.input_values or {}
    return await validate_start_inputs({"start": next(
        (node for node in definition["nodes"] if node.get("type") == "start"),
        {"input_form": []},
    ), "input_values": values})


def _probe_directory(request_id: str) -> Path:
    # UUID parsing prevents a Temporal payload from selecting arbitrary files.
    canonical_id = uuid.UUID(request_id).hex
    root = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks"))
    return root / "validation-probes" / canonical_id


@activity.defn(name="validate_staged_candidate")
async def validate_staged_candidate(payload: dict) -> dict:
    """Read only the API-staged probe, execute a rule in Docker, return errors."""
    request_id = payload.get("request_id")
    directory = _probe_directory(request_id)
    if set(payload) != {"request_id"}:
        raise ValueError("Validation probe accepts only an opaque request reference")
    try:
        descriptor = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        content = (directory / "candidate.bin").read_bytes()
        contract = descriptor["contract"]
        if "levels" in contract:
            candidate = safe_path(directory, descriptor["logical_name"])
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(content)
            return {"errors": validate_outputs_legacy(
                {descriptor["logical_name"]: {}}, directory, contract, descriptor["level"]
            )}
        errors = await validate_content(content, contract, descriptor["level"], _run_sandbox_rule)
        for error in errors:
            error["artifact"] = descriptor["logical_name"]
        return {"errors": errors}
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def _run_sandbox_rule(rules, value, text):
    return await run_rule(rules, value, text)


__all__ = ["validate_outputs", "validate_outputs_async", "validate_staged_candidate", "validate_start_inputs"]

import json
import os
import re
from pathlib import Path
from shared.paths import safe_path
