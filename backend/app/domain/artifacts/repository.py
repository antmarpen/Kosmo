from sqlalchemy import select

from app.domain.tasks.models import Artifact


class ArtifactRepository:
    def __init__(self, db):
        self.db = db

    async def list_for_task(self, task_id):
        return list((await self.db.scalars(select(Artifact).where(Artifact.task_id == task_id).order_by(Artifact.created_at))).all())

    async def get(self, artifact_id):
        return await self.db.get(Artifact, artifact_id)

    async def create(self, **values):
        existing = await self.db.scalar(select(Artifact).where(
            Artifact.task_id == values["task_id"], Artifact.node_id == values["node_id"],
            Artifact.logical_name == values["logical_name"], Artifact.iteration == values["iteration"],
            Artifact.attempt == values["attempt"],
        ))
        if existing is not None:
            if existing.sha256 != values["sha256"]:
                raise ValueError("Conflicting artifact for completed execution output")
            return existing
        row = Artifact(**values)
        self.db.add(row)
        await self.db.flush()
        return row
