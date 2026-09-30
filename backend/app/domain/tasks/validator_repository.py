"""Persistence queries required by the task-scoped validator API."""

from app.domain.artifacts.repository import ArtifactRepository
from app.domain.tasks.models import NodeExecution
from app.domain.tasks.repository import TaskRepository


class ValidatorRepository:
    def __init__(self, db):
        self.tasks = TaskRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.db = db

    async def get_task(self, task_id):
        return await self.tasks.get_task(task_id)

    async def get_artifact(self, artifact_id):
        return await self.artifacts.get(artifact_id)

    async def get_node_execution(self, execution_id):
        return await self.db.get(NodeExecution, execution_id)
