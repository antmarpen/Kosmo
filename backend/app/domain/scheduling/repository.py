from sqlalchemy import func, select, text

from app.domain.scheduling.models import AgentSlotWaiter, CapacityClaim
from app.domain.tasks.models import Task


class SchedulingRepository:
    def __init__(self, db):
        self.db = db

    async def queued_tasks(self):
        claimed = select(CapacityClaim.task_id).where(CapacityClaim.kind == "main_task")
        rows = await self.db.scalars(select(Task).where(Task.state == "queued", Task.id.not_in(claimed)).order_by(Task.created_at, Task.id))
        return list(rows.all())

    async def claim(self, task_id, kind, limit):
        # Serialize capacity checks so concurrent submissions cannot overbook.
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 130013 if kind == "main_task" else 130014})
        existing = await self.db.scalar(select(CapacityClaim.id).where(CapacityClaim.task_id == task_id, CapacityClaim.kind == kind))
        if existing:
            await self.db.commit()
            return kind == "agent_slot"
        if kind == "main_task":
            claimed = select(CapacityClaim.task_id).where(CapacityClaim.kind == "main_task")
            first_waiter = await self.db.scalar(select(Task.id).where(Task.state == "queued", Task.id.not_in(claimed)).order_by(Task.created_at, Task.id).limit(1))
            if first_waiter != task_id:
                await self.db.commit()
                return False
        else:
            first_waiter = await self.db.scalar(select(AgentSlotWaiter.task_id).order_by(AgentSlotWaiter.id).limit(1))
            if first_waiter != task_id:
                await self.db.commit()
                return False
        count = await self.db.scalar(select(func.count()).select_from(CapacityClaim).where(CapacityClaim.kind == kind))
        if count >= limit:
            await self.db.commit()
            return False
        self.db.add(CapacityClaim(task_id=task_id, kind=kind))
        if kind == "agent_slot":
            waiter = await self.db.scalar(select(AgentSlotWaiter).where(AgentSlotWaiter.task_id == task_id))
            if waiter:
                await self.db.delete(waiter)
        await self.db.commit()
        return True

    async def queue_agent_waiter(self, task_id):
        existing = await self.db.scalar(select(AgentSlotWaiter.id).where(AgentSlotWaiter.task_id == task_id))
        claim = await self.db.scalar(select(CapacityClaim.id).where(CapacityClaim.task_id == task_id, CapacityClaim.kind == "agent_slot"))
        if not existing and not claim:
            self.db.add(AgentSlotWaiter(task_id=task_id))
            await self.db.commit()

    async def remove_agent_waiter(self, task_id):
        waiter = await self.db.scalar(select(AgentSlotWaiter).where(AgentSlotWaiter.task_id == task_id))
        if waiter:
            await self.db.delete(waiter)
            await self.db.commit()

    async def is_first_agent_waiter(self, task_id):
        first = await self.db.scalar(select(AgentSlotWaiter.task_id).order_by(AgentSlotWaiter.id).limit(1))
        return first == task_id

    async def release(self, task_id, kind):
        row = await self.db.scalar(select(CapacityClaim).where(CapacityClaim.task_id == task_id, CapacityClaim.kind == kind))
        if row:
            await self.db.delete(row)
            await self.db.commit()

    async def active_claim_count(self, kind):
        return await self.db.scalar(select(func.count()).select_from(CapacityClaim).where(CapacityClaim.kind == kind))

    async def set_state(self, task_id, state):
        task = await self.db.get(Task, task_id)
        if task:
            task.state = state
            from app.domain.tasks.models import NodeExecution
            node = await self.db.scalar(select(NodeExecution).where(
                NodeExecution.task_id == task_id, NodeExecution.state.in_(("running", "allocating"))
            ).order_by(NodeExecution.started_at.desc().nullslast()))
            if node:
                node.state = state
            await self.db.commit()
