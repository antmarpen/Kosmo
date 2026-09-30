import json
import os
import re
import tempfile
import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from temporalio import activity

from shared.checkpoint import Checkpoint, CompletedExecution

TASK_STORAGE_ROOT = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks"))
_checkpoint_locks: dict[str, threading.RLock] = {}
_checkpoint_locks_guard = threading.Lock()


def checkpoint_path(task_id: str, storage_root: Path = TASK_STORAGE_ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ValueError("Invalid task id")
    return storage_root / task_id / "checkpoint.json"


def write_checkpoint(path: Path, checkpoint: Checkpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(checkpoint.model_dump(mode="json"), stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Directory fsync persists the rename on POSIX filesystems. Windows/Docker
        # Desktop may not expose directory handles; file contents were fsynced above.
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _completion_key(record: dict) -> str:
    return f"{record['node_id']}:{record.get('iteration', 0)}"


def _apply_completion(checkpoint: Checkpoint, record: dict) -> Checkpoint:
    key = _completion_key(record)
    value = CompletedExecution.model_validate({
        "attempt": record["attempt"],
        "outputs": record.get("outputs", {}),
        "artifact_hashes": record.get("artifact_hashes", {}),
        "recorded_at": record.get("recorded_at") or datetime.now(timezone.utc).isoformat(),
    })
    existing = checkpoint.completed.get(key)
    if existing is not None:
        if existing.artifact_hashes != value.artifact_hashes:
            raise ValueError(f"Conflicting completion for {key}")
        return checkpoint
    checkpoint.completed[key] = value
    checkpoint.version += 1
    return checkpoint


def reconcile_artifact_completions(checkpoint: Checkpoint, records: list[dict]) -> Checkpoint:
    """Merge durable artifact rows into the checkpoint, keyed by execution/hash."""
    for record in records:
        _apply_completion(checkpoint, record)
    return checkpoint


def valid_artifact_group(outputs: dict, declared_outputs: list[str]) -> bool:
    """Only accept the exact declared set with files matching their recorded digest."""
    if set(outputs) != set(declared_outputs):
        return False
    for ref in outputs.values():
        path = Path(ref["storage_path"])
        if not path.is_file():
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ref.get("sha256"):
            return False
    return True


def validate_checkpoint_references(checkpoint: Checkpoint) -> Checkpoint:
    """Drop invalid completion claims so workflow recovery re-executes those nodes."""
    invalid = [key for key, item in checkpoint.completed.items()
               if not valid_artifact_group(item.outputs, list(item.outputs))]
    for key in invalid:
        del checkpoint.completed[key]
    if invalid:
        checkpoint.version += 1
    return checkpoint


def read_checkpoint(path: Path) -> Checkpoint:
    if not path.exists():
        raise FileNotFoundError(path)
    return Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))


@contextmanager
def _cross_process_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            if stream.tell() == 0 and lock_path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def publish_completion_if_current(path: Path, expected: Checkpoint, record: dict) -> Checkpoint:
    """Serialize in-process writers and fence activity attempts by checkpoint revision."""
    with _checkpoint_locks_guard:
        lock = _checkpoint_locks.setdefault(str(path.resolve()), threading.RLock())
    with lock, _cross_process_lock(path):
        current = read_checkpoint(path) if path.exists() else Checkpoint(task_id=expected.task_id, version=1)
        key = _completion_key(record)
        if current.version != expected.version:
            existing = current.completed.get(key)
            candidate = CompletedExecution.model_validate({
                "attempt": record["attempt"], "outputs": record.get("outputs", {}),
                "artifact_hashes": record.get("artifact_hashes", {}),
                "recorded_at": record.get("recorded_at") or datetime.now(timezone.utc).isoformat(),
            })
            if (existing is not None and existing.attempt == candidate.attempt and existing.outputs == candidate.outputs
                    and existing.artifact_hashes == candidate.artifact_hashes):
                return current
            raise ValueError("Stale checkpoint writer")
        _apply_completion(current, record)
        write_checkpoint(path, current)
        return current


def durable_execution_result(outputs: dict, declared_outputs: list[str]) -> dict | None:
    if valid_artifact_group(outputs, declared_outputs):
        return {"state": "success", "outputs": outputs, "error": None}
    return None


async def find_durable_artifact_result(task_id: str, node_id: str, iteration: int, declared: list[str]) -> dict | None:
    """Return a persisted complete output set, if one is already durable."""
    if not declared:
        return None
    from sqlalchemy import select
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Artifact
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(Artifact).where(
            Artifact.task_id == task_id, Artifact.node_id == node_id,
            Artifact.iteration == iteration,
        ).order_by(Artifact.attempt.desc()))).all()
    attempts = sorted({row.attempt for row in rows}, reverse=True)
    for attempt in attempts:
        group = {row.logical_name: {"id": row.id, "storage_path": row.storage_path,
                                   "sha256": row.sha256, "media_type": row.media_type}
                 for row in rows if row.attempt == attempt}
        result = durable_execution_result(group, declared)
        if result:
            result["attempt"] = attempt
            return result
    return None


@activity.defn
async def load_checkpoint(task_id: str) -> dict:
    path = checkpoint_path(task_id)
    if not path.exists():
        return Checkpoint(task_id=task_id, version=1).model_dump(mode="json")
    checkpoint = Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
    if checkpoint.task_id != task_id:
        raise ValueError("Checkpoint task id mismatch")
    return checkpoint.model_dump(mode="json")


@activity.defn
async def publish_completion(payload: dict, storage_root: Path = TASK_STORAGE_ROOT) -> dict:
    task_id = payload["task_id"]
    path = checkpoint_path(task_id, storage_root)
    checkpoint = Checkpoint.model_validate(payload["expected_checkpoint"]) if payload.get("expected_checkpoint") else (
        read_checkpoint(path) if path.exists() else Checkpoint(task_id=task_id, version=1)
    )
    if checkpoint.task_id != task_id:
        raise ValueError("Checkpoint task id mismatch")
    checkpoint = publish_completion_if_current(path, checkpoint, payload["completion"])
    return checkpoint.model_dump(mode="json")


@activity.defn
async def reconcile_checkpoint(task_id: str) -> dict:
    from sqlalchemy import select
    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Artifact, NodeExecution, Task

    path = checkpoint_path(task_id)
    checkpoint = Checkpoint.model_validate(await load_checkpoint(task_id))
    original_version = checkpoint.version
    validate_checkpoint_references(checkpoint)
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        rows = (await db.scalars(select(Artifact).where(Artifact.task_id == task_id))).all()
        executions = (await db.scalars(select(NodeExecution).where(
            NodeExecution.task_id == task_id, NodeExecution.state == "success"
        ))).all()
    declared = {node["id"]: node.get("outputs", []) for node in (task.resolved_definition.get("nodes", []) if task else [])}
    successful = {(row.node_id, row.iteration, row.attempt) for row in executions}
    groups = {}
    for row in rows:
        artifact_path = Path(row.storage_path)
        if (row.node_id, row.iteration, row.attempt) in successful:
            groups.setdefault((row.node_id, row.iteration, row.attempt), {})[row.logical_name] = {
                "id": row.id, "storage_path": row.storage_path, "sha256": row.sha256,
                "media_type": row.media_type,
            }
    changed = False
    records = []
    for (node_id, iteration, attempt), outputs in groups.items():
        if not valid_artifact_group(outputs, declared.get(node_id, [])):
            continue
        records.append({"node_id": node_id, "iteration": iteration, "attempt": attempt,
                        "outputs": outputs, "artifact_hashes": {name: ref["sha256"] for name, ref in outputs.items()}})
    before_version = checkpoint.version
    reconcile_artifact_completions(checkpoint, records)
    changed = checkpoint.version != before_version or checkpoint.version != original_version
    if changed:
        write_checkpoint(path, checkpoint)
    return checkpoint.model_dump(mode="json")
