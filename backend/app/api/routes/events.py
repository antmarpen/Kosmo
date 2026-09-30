import asyncio

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.db import AsyncSessionLocal
from app.domain.events.repository import TaskEventRepository
from app.domain.events.service import event_data, filter_aggregate_events, format_sse
from app.domain.tasks.models import Task
from shared.errors import KosmoError, NotFoundError, PermissionDeniedError

router = APIRouter(tags=["events"])


def _last_id(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except ValueError:
        raise KosmoError("errors.events.invalid_cursor", code="VALIDATION_FAILED", http_status=400) from None
    if parsed < 0:
        raise KosmoError("errors.events.invalid_cursor", code="VALIDATION_FAILED", http_status=400)
    return parsed


async def _stream(request: Request, user, task_id: str | None, cursor: int):
    last_id = cursor
    last_heartbeat = asyncio.get_running_loop().time()
    while not await request.is_disconnected():
        async with AsyncSessionLocal() as db:
            events = await TaskEventRepository(db).replay(last_id, task_id)
        if events:
            if task_id is None:
                events = await filter_aggregate_events(db, events, user)
            for event in events:
                last_id = max(last_id, event.id)
                yield format_sse(event_data(event))
            continue
        now = asyncio.get_running_loop().time()
        if now - last_heartbeat >= 15:
            yield ": heartbeat\n\n"
            last_heartbeat = now
        await asyncio.sleep(0.5)


def _response(request: Request, user, task_id: str | None, cursor: int):
    return StreamingResponse(
        _stream(request, user, task_id, cursor), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/tasks/events")
async def stream_task_events(request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID"),
                             user=Depends(get_current_user)):
    return _response(request, user, None, _last_id(last_event_id))


@router.get("/tasks/{task_id}/events")
async def stream_detail_events(task_id: str, request: Request,
                               last_event_id: str | None = Header(None, alias="Last-Event-ID"),
                               user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("errors.task.not_found")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "admin" and task.created_by != user.id:
        raise PermissionDeniedError("errors.permission.denied")
    return _response(request, user, task_id, _last_id(last_event_id))
