from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events.models import TaskEvent


class TaskEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def publish(self, task_id: str, node_id: str | None, kind: str, payload: dict) -> TaskEvent:
        row = TaskEvent(task_id=task_id, node_id=node_id, kind=kind, payload=payload)
        self.db.add(row)
        await self.db.flush()
        return row

    async def replay(self, after_id: int, task_id: str | None = None) -> list[TaskEvent]:
        query = select(TaskEvent).where(TaskEvent.id > after_id).order_by(TaskEvent.id)
        if task_id is not None:
            query = query.where(TaskEvent.task_id == task_id)
        return list((await self.db.scalars(query)).all())
