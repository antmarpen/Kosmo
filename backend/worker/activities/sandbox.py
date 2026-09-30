import asyncio
import logging
import os
from pathlib import Path

from temporalio import activity
from shared.paths import safe_path

from worker.activities.artifacts import artifact_digest, output_media_type, validate_output

TASK_STORAGE_ROOT = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks"))
SANDBOX_IMAGE = os.getenv("KOSMO_SANDBOX_IMAGE", "kosmo-sandbox:local")
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("KOSMO_SANDBOX_TIMEOUT_SECONDS", "60"))
TASK_STORAGE_VOLUME = os.getenv("KOSMO_TASK_STORAGE_VOLUME", "task-storage")
logger = logging.getLogger(__name__)


def script_failure(exit_code: int | None) -> dict:
    return {"state": "failed", "error": {"code": "SCRIPT_FAILED", "message_key": "errors.script.failed",
                                             "params": {"exit_code": exit_code}}}


@activity.defn
async def run_script(payload):
    import docker
    node = payload["node"]
    task_id = payload["task_id"]
    from worker.activities.checkpoint import find_durable_artifact_result
    recovered = await find_durable_artifact_result(task_id, node["id"], payload.get("iteration", 0), node["outputs"])
    if recovered:
        return recovered
    inputs = payload.get("inputs", {})
    base = safe_path(TASK_STORAGE_ROOT, task_id)
    workspace = safe_path(base, f'sandbox/{node["id"]}') / f'{payload.get("iteration", 0)}-{payload.get("attempt", 1)}'
    workspace = safe_path(base, workspace)
    output = safe_path(workspace, "output")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o777)
    input_dir = workspace / "inputs"
    input_dir.mkdir(exist_ok=True)
    env = {}
    for key, value in inputs.items():
        if key == "topic":
            env["KOSMO_INPUT_TOPIC"] = str(value)
        elif isinstance(value, dict) and value.get("storage_path"):
            source = safe_path(base, value["storage_path"])
            target = input_dir / source.name
            target.write_bytes(source.read_bytes())
            env[f"KOSMO_INPUT_ARTIFACT_{key.upper().replace('-', '_')}"] = f"/workspace/inputs/{target.name}"
    env.update({f"KOSMO_OUTPUT_{name.upper().replace('.', '_').replace('-', '_')}": f"/workspace/output/{name}" for name in node["outputs"]})
    env["KOSMO_OUTPUT_DIR"] = "/workspace/output"
    client = docker.from_env()
    container = None
    try:
        mounts = [
            docker.types.Mount(target="/workspace", source=TASK_STORAGE_VOLUME, type="volume", read_only=True,
                               subpath=f"{task_id}/sandbox/{node['id']}/{payload.get('iteration', 0)}-{payload.get('attempt', 1)}"),
            docker.types.Mount(target="/workspace/output", source=TASK_STORAGE_VOLUME, type="volume", read_only=False,
                               subpath=f"{task_id}/sandbox/{node['id']}/{payload.get('iteration', 0)}-{payload.get('attempt', 1)}/output"),
        ]
        container = client.containers.create(
            SANDBOX_IMAGE, command=["-c", node["code"]], environment=env,
            network_mode="none", user="10001:10001", mem_limit="256m", nano_cpus=1_000_000_000,
            read_only=True, tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
            mounts=mounts,
            working_dir="/workspace",
        )
        container.start()
        try:
            result = await asyncio.to_thread(container.wait, timeout=SANDBOX_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("Sandbox execution timed out", exc_info=True, extra={"task_id": task_id, "node_id": node["id"]})
            await asyncio.to_thread(container.kill)
            return {"state": "failed", "error": {"code": "SCRIPT_TIMEOUT", "message_key": "errors.script.timeout", "params": {"seconds": SANDBOX_TIMEOUT_SECONDS}}}
        if result.get("StatusCode") != 0:
            logger.error("Sandbox script exited unsuccessfully", extra={"task_id": task_id, "node_id": node["id"], "exit_code": result.get("StatusCode"), "output": (await asyncio.to_thread(container.logs)).decode("utf-8", errors="replace")[-300:]})
            return script_failure(result.get("StatusCode"))
        for name in node["outputs"]:
            validate_output(safe_path(output, name), output_media_type(name))
        from app.core.db import AsyncSessionLocal
        from app.domain.artifacts.repository import ArtifactRepository
        artifact_dir = safe_path(base, f'artifacts/{node["id"]}') / f'{payload.get("iteration", 0)}-{payload.get("attempt", 1)}'
        artifact_dir = safe_path(base, artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        async with AsyncSessionLocal() as db:
            repo = ArtifactRepository(db)
            refs = {}
            for name in node["outputs"]:
                source = safe_path(output, name)
                target = artifact_dir / Path(name).name
                target.write_bytes(source.read_bytes())
                row = await repo.create(task_id=task_id, node_id=node["id"], logical_name=name,
                    iteration=payload.get("iteration", 0), attempt=payload.get("attempt", 1),
                    media_type=output_media_type(name), size=target.stat().st_size,
                    sha256=artifact_digest(target), storage_path=str(target))
                refs[name] = {"id": row.id, "storage_path": str(target), "sha256": row.sha256, "media_type": row.media_type}
            await db.commit()
        return {"state": "success", "outputs": refs, "error": None}
    except (ValueError, docker.errors.DockerException) as exc:
        logger.exception("Sandbox execution failed", extra={"task_id": task_id, "node_id": node["id"]})
        return {"state": "failed", "error": {"code": "SCRIPT_EXECUTION_FAILED", "message_key": "errors.script.failed", "params": {}}}
    finally:
        if container is not None:
            await asyncio.to_thread(container.remove, force=True)
