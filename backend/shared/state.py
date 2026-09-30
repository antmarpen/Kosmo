from enum import StrEnum


class TaskState(StrEnum):
    queued = "queued"
    running = "running"
    waiting_for_input = "waiting_for_input"
    stopping = "stopping"
    stopped = "stopped"
    failed = "failed"
    success = "success"
    allocating = "allocating"
