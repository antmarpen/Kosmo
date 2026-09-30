from temporalio import activity


@activity.defn
async def acquire_agent(task_id):
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.scheduling.repository import SchedulingRepository
    from app.domain.scheduling.service import SchedulingService
    async with AsyncSessionLocal() as db:
        service = SchedulingService(SchedulingRepository(db), None, settings.max_main_tasks, settings.max_agents)
        return await service.acquire_agent(task_id) == "granted"


@activity.defn
async def release_agent(task_id):
    from app.core.db import AsyncSessionLocal
    from app.domain.scheduling.repository import SchedulingRepository
    async with AsyncSessionLocal() as db:
        await SchedulingRepository(db).release(task_id, "agent_slot")


@activity.defn
async def cancel_agent_wait(task_id):
    from app.core.db import AsyncSessionLocal
    from app.domain.scheduling.repository import SchedulingRepository
    async with AsyncSessionLocal() as db:
        await SchedulingRepository(db).remove_agent_waiter(task_id)


@activity.defn
async def admit_queued():
    from app.core.config import settings
    from app.core.db import AsyncSessionLocal
    from app.domain.scheduling.repository import SchedulingRepository
    from app.domain.scheduling.service import SchedulingService
    from app.domain.tasks.service import TemporalWorkflowStarter
    async with AsyncSessionLocal() as db:
        await SchedulingService(SchedulingRepository(db), TemporalWorkflowStarter(), settings.max_main_tasks,
                               settings.max_agents).admit_queued()
