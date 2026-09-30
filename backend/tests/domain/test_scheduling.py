import asyncio
from datetime import datetime, timedelta, timezone

from app.domain.scheduling.service import SchedulingService


class Repo:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.tasks = {str(i): {"id": str(i), "state": "queued", "created_at": now + timedelta(seconds=i), "definition": {}, "input_values": {}} for i in range(4)}
        self.claims = set()
        self.agent_waiters = []

    async def queued_tasks(self):
        return sorted((t for t in self.tasks.values() if t["state"] == "queued" and (t["id"], "main_task") not in self.claims), key=lambda t: t["created_at"])

    async def claim(self, task_id, kind, limit):
        count = sum(1 for _, k in self.claims if k == kind)
        if (task_id, kind) in self.claims:
            return True
        if count >= limit:
            return False
        self.claims.add((task_id, kind))
        return True

    async def release(self, task_id, kind):
        self.claims.discard((task_id, kind))

    async def active_claim_count(self, kind):
        return sum(1 for _, k in self.claims if k == kind)

    async def set_state(self, task_id, state):
        self.tasks[task_id]["state"] = state

    async def queue_agent_waiter(self, task_id):
        if task_id not in self.agent_waiters and (task_id, "agent_slot") not in self.claims:
            self.agent_waiters.append(task_id)

    async def remove_agent_waiter(self, task_id):
        if task_id in self.agent_waiters:
            self.agent_waiters.remove(task_id)

    async def is_first_agent_waiter(self, task_id):
        return bool(self.agent_waiters and self.agent_waiters[0] == task_id)



class Starter:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    async def start(self, task_id, workflow_id, definition, inputs):
        self.calls.append(task_id)
        if task_id in self.fail:
            raise RuntimeError("Temporal unavailable")


def test_admission_is_fifo_and_respects_zero_and_one_limits():
    repo, starter = Repo(), Starter()
    service = SchedulingService(repo, starter, max_main_tasks=1, max_agents=0)
    assert asyncio.run(service.admit_queued()) == ["0"]
    assert asyncio.run(service.admit_queued()) == []
    asyncio.run(repo.release("0", "main_task"))
    repo.tasks["0"]["state"] = "success"
    assert asyncio.run(service.admit_queued()) == ["1"]


def test_admission_retries_workflow_start_failure_on_next_pass():
    repo, starter = Repo(), Starter(fail={"0"})
    service = SchedulingService(repo, starter, max_main_tasks=1, max_agents=1)
    assert asyncio.run(service.admit_queued()) == []
    starter.fail.clear()
    assert asyncio.run(service.admit_queued()) == ["0"]


def test_zero_main_task_limit_admits_nothing():
    repo, starter = Repo(), Starter()
    assert asyncio.run(SchedulingService(repo, starter, max_main_tasks=0).admit_queued()) == []
    assert starter.calls == []


def test_agent_release_frees_exactly_one_slot():
    repo, starter = Repo(), Starter()
    service = SchedulingService(repo, starter, max_main_tasks=0, max_agents=1)
    assert asyncio.run(service.acquire_agent("0")) == "granted"
    assert repo.tasks["0"]["state"] == "running"
    assert asyncio.run(service.acquire_agent("1")) == "queued"
    assert repo.tasks["1"]["state"] == "allocating"
    asyncio.run(service.release_agent("0"))
    assert asyncio.run(service.acquire_agent("1")) == "granted"
    assert repo.tasks["1"]["state"] == "running"


def test_agent_slots_are_granted_to_waiters_in_fifo_order():
    repo, starter = Repo(), Starter()
    service = SchedulingService(repo, starter, max_main_tasks=0, max_agents=1)
    async def scenario():
        assert await service.acquire_agent("0") == "granted"
        assert await service.acquire_agent("1") == "queued"
        assert await service.acquire_agent("2") == "queued"
        await service.release_agent("0")
        assert await service.acquire_agent("2") == "queued"
        assert await service.acquire_agent("1") == "granted"
        await service.release_agent("1")
        assert await service.acquire_agent("2") == "granted"
    asyncio.run(scenario())
