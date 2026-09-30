import json
from datetime import datetime, timezone


async def publish_event(db, task_id: str, kind: str, state: str | None = None,
                        node_id: str | None = None, note: dict | None = None):
    from app.domain.events.repository import TaskEventRepository

    payload = {"state": state, "note": note}
    return await TaskEventRepository(db).publish(task_id, node_id, kind, payload)


def event_data(event) -> dict:
    payload = event.payload
    return {
        "id": event.id,
        "kind": event.kind,
        "task_id": event.task_id,
        "node_id": event.node_id,
        "state": payload.get("state"),
        "note": payload.get("note"),
        "at": (event.created_at or datetime.now(timezone.utc)).isoformat(),
    }


def format_sse(event: dict) -> str:
    data = {key: event[key] for key in ("task_id", "node_id", "state", "note", "at")}
    return f"id: {event['id']}\nevent: {event['kind']}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def aggregate_event_visible(event: dict, user, submitter_id: str | None) -> bool:
    """Aggregate streams expose notes only to the task submitter and admins."""
    if event["kind"] != "task.note":
        return True
    role = user["role"] if isinstance(user, dict) else user.role
    role = role.value if hasattr(role, "value") else str(role)
    user_id = user["id"] if isinstance(user, dict) else user.id
    return role == "admin" or user_id == submitter_id


async def filter_aggregate_events(db, events, user):
    """Keep aggregate state summaries; note payloads require submitter/admin access."""
    from app.domain.tasks.models import Task

    visible = []
    for event in events:
        if event.kind == "task.note":
            task = await db.get(Task, event.task_id)
            submitter_id = task.created_by if task is not None else None
            if not aggregate_event_visible({"kind": event.kind, "task_id": event.task_id}, user, submitter_id):
                continue
        visible.append(event)
    return visible
