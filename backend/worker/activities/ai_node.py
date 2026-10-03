"""AI completion validation and correction-cycle orchestration."""

import json
import logging
from pathlib import Path

from temporalio import activity

from shared.agent_events import AgentError, CompletionProposed
from worker.adapters.base import ArtifactContract
from worker.activities.validation import validate_outputs
from worker.activities.artifacts import output_media_type
from shared.paths import safe_path

logger = logging.getLogger(__name__)


async def orchestrate_ai_node(node: dict, adapter, workspace: Path, task_id: str,
                              persist_artifact, write_note, publish_checkpoint, request_input=None) -> dict:
    """Run bounded completion/validation cycles; side effects are injected for tests."""
    contracts = node.get("output_validation")
    if contracts is None:
        # Task snapshots created before per-output validation retain their node-wide contract.
        legacy_contract = node.get("validation")
        contracts = ({name: legacy_contract for name in node.get("outputs", [])}
                     if legacy_contract else {})
    contracts = {name: contracts[name] for name in node.get("outputs", []) if name in contracts}
    first_contract = next(iter(contracts.values()), None)
    fallback_level = ((first_contract or {}).get("levels") or [
        {"name": "completion", "message_key": "errors.node.completion_missing"}
    ])[0]
    expected = [ArtifactContract(logical_name=name) for name in node["outputs"]]
    attempts = min(int(node.get("max_validation_cycles", 3)), 3)
    aggregate = []
    await adapter.start_session(node.get("agent", {}))
    prompt = "\n\n".join(part for part in (
        node.get("agent", {}).get("instructions", ""),
        ("Declared inputs are mounted read-only under /workspace/inputs; read: "
         + ", ".join(f"/workspace/inputs/{Path(name).name}" for name in node.get("inputs", [])))
        if node.get("inputs") else "",
        "Expected artifacts: " + ", ".join(
            f"{name} ({output_media_type(name)})" for name in node["outputs"]
        ),
        "Output validation contracts: " + json.dumps(contracts, sort_keys=True),
        node.get("prompt_template", ""),
        node.get("task_prompt", ""),
    ) if part)
    await adapter.send_prompt(prompt)
    input_request_index = 0
    for attempt in range(1, attempts + 1):
        proposed = False
        async for event in adapter.events():
            if isinstance(event, AgentError):
                break
            from shared.agent_events import InputRequested
            if isinstance(event, InputRequested):
                if request_input is None:
                    raise RuntimeError("Human input handler is not configured")
                request_key = str(event.request_id) if event.request_id is not None else f"notification-{attempt}-{input_request_index}"
                input_request_index += 1
                cancelled = await request_input(event.message_key, event.params, adapter, event.request_id, request_key)
                if cancelled:
                    return {"state": "stopped", "outputs": {}, "error": None}
                continue
            if isinstance(event, CompletionProposed):
                proposed = True
                break
        if not proposed:
            errors = [{"artifact": "", "level": fallback_level["name"],
                       "message_key": fallback_level["message_key"], "params": {"reason": "completion_not_proposed"}}]
        else:
            completion = await adapter.request_completion(expected)
            candidates = completion if isinstance(completion, dict) else getattr(completion, "artifacts", {})
            if isinstance(candidates, list):
                candidates = {item.logical_name: {"path": item.id, "media_type": output_media_type(item.logical_name)}
                              for item in candidates}
            if not isinstance(candidates, dict):
                candidates = {}
            declared = {}
            missing_candidates = []
            for name in node["outputs"]:
                ref = candidates.get(name)
                declared[name] = {"media_type": (ref or {}).get("media_type", "application/octet-stream")}
                if not ref:
                    contract = contracts.get(name)
                    level_data = ((contract or {}).get("levels") or [
                        {"name": "syntax", "message_key": "validation.syntax"}
                    ])[0]
                    missing_candidates.append({"artifact": name, "level": level_data["name"],
                                               "message_key": level_data["message_key"],
                                               "params": {"reason": "missing"}})
            errors = validate_outputs(declared, workspace, contracts, inputs=node.get("inputs", []))
            missing_names = {error["artifact"] for error in missing_candidates}
            errors = [error for error in errors if not (
                error["artifact"] in missing_names and error["params"].get("reason") == "missing"
            )] + missing_candidates
        if errors:
            details = [{**error, "attempt": attempt} for error in errors]
            aggregate.extend(details)
            await adapter.deliver_feedback(details)
            await write_note("tasks.notes.validation_failed", {"attempt": attempt, "level": errors[0]["level"], "details": details})
            continue
        refs = {}
        for name in node["outputs"]:
            refs[name] = await persist_artifact(name, candidates[name], attempt)
        await publish_checkpoint({"node_id": node["id"], "iteration": 0, "attempt": attempt,
                                 "outputs": refs, "artifact_hashes": {key: value["sha256"] for key, value in refs.items()}})
        await write_note("tasks.notes.validation_passed", {"attempt": attempt})
        return {"state": "success", "outputs": refs, "attempt": attempt, "error": None}
    return {"state": "failed", "outputs": {}, "error": {
        "code": "VALIDATION_EXHAUSTED", "message_key": "errors.node.validation_exhausted",
        "params": {"node": node["id"], "attempts": attempts}, "details": aggregate,
    }}


@activity.defn
async def run_ai_node(payload: dict) -> dict:
    """Temporal activity binding to the runtime adapter and durable services."""
    from worker.activities.checkpoint import find_durable_artifact_result
    recovered = await find_durable_artifact_result(
        payload["task_id"], payload["node"]["id"], payload.get("iteration", 0), payload["node"]["outputs"],
    )
    if recovered:
        return recovered
    runtime = payload["node"].get("agent", {}).get("runtime")
    if runtime != "opencode":
        return {"state": "failed", "outputs": {}, "error": {
            "code": "EXECUTOR_NOT_SUPPORTED", "message_key": "errors.executor.not_registered",
            "params": {"type": runtime or ""},
        }}
    from worker.activities.agent import start_agent_session, stage_agent_inputs

    task_id, node, task_prompt = payload["task_id"], payload["node"], payload.get("task_prompt", "")
    user_id = payload.get("user_id")
    if not task_prompt or not user_id:
        from app.core.db import AsyncSessionLocal
        from app.domain.tasks.models import Task
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            if task:
                task_prompt = task_prompt or task.prompt or ""
                user_id = user_id or task.created_by
    workspace = payload.get("workspace") or str(Path("/var/lib/kosmo/tasks") / task_id / "agent" / node["id"])
    Path(workspace).mkdir(parents=True, exist_ok=True)
    # The lifecycle activity maintains the ACP session and yields cycle results.
    node = {**node, "task_prompt": task_prompt}
    runtime_environment = {}
    runtime_config_files = {}
    async def persist(name, candidate, attempt):
        return await _persist_artifact(task_id, node["id"], name, candidate, attempt)
    async def note(key, params):
        await _add_task_note(task_id, node["id"], key, params)
    async def checkpoint(record):
        return record
    async def request_input(message_key, params, adapter, request_id, request_key):
        from worker.activities.input import await_human_answer, mark_answer_delivered, pending_answer
        node_execution_id = payload.get("node_execution_id", "")
        answer_text = await await_human_answer(
            task_id, node["id"], message_key, params, node_execution_id, request_id, request_key,
        )
        if answer_text is None:
            return True
        await adapter.deliver_answer(answer_text, request_id)
        answer = await pending_answer(task_id, node_execution_id, request_key)
        if answer:
            await mark_answer_delivered(answer)
        from app.core.db import AsyncSessionLocal
        from app.domain.tasks.models import Task
        from app.domain.events.service import publish_event
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            if task and task.state == "waiting_for_input":
                task.state = "running"
                await publish_event(db, task_id, "task.state", state="running")
                await db.commit()
        return False
    adapter = None
    try:
        from worker.activities.agent import validator_mcp_server
        runtime_config_files = await _load_provider_runtime_config(user_id, runtime) or {}
        from app.core.config import settings
        runtime_environment = stage_agent_inputs(payload.get("inputs", {}), workspace)
        execution_id = payload.get("node_execution_id")
        mcp_servers = ([validator_mcp_server(task_id, node["id"], execution_id, settings.jwt_secret)]
                       if execution_id and settings.jwt_secret else [])
        adapter = await start_agent_session(
            node.get("agent", {}), workspace, runtime_environment=runtime_environment,
            runtime_config_files=runtime_config_files, mcp_servers=mcp_servers,
        )
        return await orchestrate_ai_node(node, adapter, Path(workspace), task_id, persist, note, checkpoint, request_input)
    except Exception as exc:
        logger.exception("AI node infrastructure failure", extra={"task_id": task_id, "node_id": node["id"]})
        # Return a language-independent failure rather than letting infrastructure
        # exceptions trigger Temporal's unbounded default activity retry policy.
        from worker.adapters.opencode_acp import ACPResponseError
        auth_missing = (
            (adapter is not None and not runtime_config_files
             and isinstance(exc, ACPResponseError) and exc.method == "session/prompt")
            or _is_provider_auth_error(exc)
        )
        if auth_missing:
            try:
                await _add_task_note(task_id, node["id"], "tasks.notes.agent_auth_missing", {"provider": "opencode"})
            except Exception:
                pass
        return {
            "state": "failed", "outputs": {},
            "error": {
                "code": "PROVIDER_AUTH_MISSING" if auth_missing else "AGENT_RUNTIME_FAILED",
                "message_key": "errors.provider.auth_missing" if auth_missing else "errors.agent.runtime_failed",
                "params": {"provider": "opencode"} if auth_missing else {"cause": "errors.agent.runtime_failed"},
            },
        }
    finally:
        if adapter is not None:
            await adapter.close()


async def _load_provider_runtime_config(user_id: str | None, provider_type: str = "opencode") -> dict[str, bytes] | None:
    if not user_id:
        return None
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from sqlalchemy import select
    from app.domain.provider_configs.repository import ProviderConfigRepository
    from app.domain.provider_configs.service import ProviderConfigService

    async with AsyncSessionLocal() as db:
        from app.domain.identity.models import GroupMembership
        group_ids = list((await db.scalars(select(GroupMembership.group_id).where(
            GroupMembership.user_id == user_id
        ))).all())
        return await ProviderConfigService(
            ProviderConfigRepository(db), settings.config_encryption_key,
        ).resolve_files(user_id, provider_type, group_ids)


def _is_provider_auth_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(marker in message for marker in ("unauthorized", "authentication failed", "invalid api key",
                                                 "missing api key", "credentials are missing"))


async def _persist_artifact(task_id: str, node_id: str, name: str, candidate: dict, attempt: int) -> dict:
    import shutil
    from worker.activities.artifacts import artifact_digest, output_media_type
    from app.core.db import AsyncSessionLocal
    from app.domain.artifacts.repository import ArtifactRepository

    task_root = Path("/var/lib/kosmo/tasks") / task_id
    workspace = Path("/var/lib/kosmo/tasks") / task_id / "agent" / node_id
    source = safe_path(workspace, candidate.get("path", ""))
    if not source.is_file():
        raise ValueError(f"Declared output missing: {name}")
    target = safe_path(task_root, f"artifacts/{node_id}/0-{attempt}/{name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    async with AsyncSessionLocal() as db:
        row = await ArtifactRepository(db).create(task_id=task_id, node_id=node_id, logical_name=name,
            iteration=0, attempt=attempt, media_type=candidate.get("media_type", output_media_type(name)),
            size=target.stat().st_size, sha256=artifact_digest(target), storage_path=str(target))
        result = {"id": row.id, "storage_path": str(target), "sha256": row.sha256, "media_type": row.media_type}
        await db.commit()
    return result


async def _add_task_note(task_id: str, node_id: str, message_key: str, params: dict) -> None:
    from sqlalchemy import func, select
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import TaskNote
    from app.domain.events.service import publish_event

    async with AsyncSessionLocal() as db:
        revision = (await db.scalar(select(func.max(TaskNote.revision)).where(TaskNote.task_id == task_id)) or 0) + 1
        note = TaskNote(task_id=task_id, revision=revision, message_key=message_key,
                        params={"node": node_id, **params})
        db.add(note)
        await publish_event(db, task_id, "task.note", node_id=node_id,
                            note={"revision": revision, "message_key": message_key, "params": note.params})
        await db.commit()
