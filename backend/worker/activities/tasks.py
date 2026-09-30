from temporalio import activity


def _session():
    from app.core.db import AsyncSessionLocal
    return AsyncSessionLocal


@activity.defn
async def start_task(task_id):
    from app.domain.identity.models import User  # Register the FK target in worker metadata.
    from app.domain.tasks.models import Task
    async with _session()() as db:
        task = await db.get(Task, task_id)
        if task and task.state == "queued":
            task.state = "running"
            from app.domain.events.service import publish_event
            await publish_event(db, task_id, "task.state", state="running")
            await db.commit()


@activity.defn
async def completed_nodes(task_id):
    from sqlalchemy import select
    from app.domain.tasks.models import NodeExecution
    async with _session()() as db:
        rows = await db.scalars(select(NodeExecution.node_id).where(NodeExecution.task_id == task_id, NodeExecution.state == "success"))
        return list(rows.all())


@activity.defn
async def ordered_nodes(definition):
    from worker.interpreter import topological_nodes
    return topological_nodes(definition)


@activity.defn
async def begin_node(payload):
    from app.domain.tasks.models import NodeExecution
    task_id, node_id = payload
    async with _session()() as db:
        row = NodeExecution(task_id=task_id, node_id=node_id, iteration=0, attempt=1, state="running")
        db.add(row)
        from app.domain.events.service import publish_event
        await publish_event(db, task_id, "node.state", node_id=node_id, state="running")
        await db.commit()
        return row.id


@activity.defn
async def run_node(payload):
    task_id, node, inputs = payload
    if node.get("type") == "script":
        from worker.activities.sandbox import run_script
        return await run_script({"task_id": task_id, "node": node, "inputs": inputs})
    if node.get("type") == "ai":
        from worker.activities.ai_node import run_ai_node
        from worker.activities.sandbox import TASK_STORAGE_ROOT
        workspace = TASK_STORAGE_ROOT / task_id / "agent" / node["id"]
        workspace.mkdir(parents=True, exist_ok=True)
        return await run_ai_node({"task_id": task_id, "node": node, "task_prompt": inputs.get("prompt", ""),
                                  "workspace": str(workspace)})
    return {"state": "failed", "error": {"code": "EXECUTOR_NOT_REGISTERED", "message_key": "errors.executor.not_registered", "params": {"type": node.get("type")}}}


@activity.defn
async def finish_node(payload):
    from sqlalchemy import select
    from app.domain.tasks.models import NodeExecution
    task_id, node_id, result = payload
    async with _session()() as db:
        row = await db.scalar(select(NodeExecution).where(NodeExecution.task_id == task_id, NodeExecution.node_id == node_id).order_by(NodeExecution.id.desc()))
        if row:
            row.state = result["state"]
            row.error = result.get("error")
            from app.domain.events.service import publish_event
            await publish_event(db, task_id, "node.state", node_id=node_id, state=result["state"])
        await db.commit()


@activity.defn
async def finish_task(payload):
    # A retried workflow may resume on a fresh worker process after start_task
    # was already recorded in history. Re-register FK metadata in that process.
    from app.domain.identity.models import User
    from app.domain.tasks.models import Task
    task_id, state = payload
    async with _session()() as db:
        task = await db.get(Task, task_id)
        if task:
            task.state = state
            from sqlalchemy import delete
            from app.domain.scheduling.models import CapacityClaim
            await db.execute(delete(CapacityClaim).where(CapacityClaim.task_id == task_id, CapacityClaim.kind == "main_task"))
            from app.domain.events.service import publish_event
            await publish_event(db, task_id, "task.state", state=state)
            await db.commit()
    from worker.activities.capacity import admit_queued
    await admit_queued()
