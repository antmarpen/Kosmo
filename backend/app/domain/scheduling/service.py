import logging

logger = logging.getLogger(__name__)


class SchedulingService:
    def __init__(self, repository, workflow_starter, max_main_tasks=3, max_agents=2):
        self.repository = repository
        self.workflow_starter = workflow_starter
        self.max_main_tasks = max_main_tasks
        self.max_agents = max_agents

    async def admit_queued(self):
        started = []
        # Running, waiting_for_input, and allocating tasks hold claims; queued
        # tasks do not consume capacity until their workflow is admitted.
        for task in await self.repository.queued_tasks():
            task_id = task["id"] if isinstance(task, dict) else task.id
            if not await self.repository.claim(task_id, "main_task", self.max_main_tasks):
                break
            definition = task.get("definition", task.get("resolved_definition")) if isinstance(task, dict) else task.resolved_definition
            inputs = task.get("input_values", {}) if isinstance(task, dict) else task.input_values
            try:
                await self.workflow_starter.start(task_id, f"task-{task_id}", definition, inputs)
                started.append(task_id)
            except Exception:
                logger.exception("Could not start queued Temporal workflow for task %s; it remains queued for the next admission pass", task_id)
                await self.repository.release(task_id, "main_task")
                break
        return started

    async def acquire_agent(self, task_id):
        await self.repository.queue_agent_waiter(task_id)
        if not await self.repository.is_first_agent_waiter(task_id):
            await self.repository.set_state(task_id, "allocating")
            return "queued"
        if await self.repository.claim(task_id, "agent_slot", self.max_agents):
            await self.repository.remove_agent_waiter(task_id)
            await self.repository.set_state(task_id, "running")
            return "granted"
        await self.repository.set_state(task_id, "allocating")
        return "queued"

    async def set_allocating(self, task_id):
        await self.repository.set_state(task_id, "allocating")

    async def release_agent(self, task_id):
        await self.repository.release(task_id, "agent_slot")

    async def cancel_agent_wait(self, task_id):
        await self.repository.remove_agent_waiter(task_id)
