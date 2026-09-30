from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.artifacts.repository import ArtifactRepository
from app.domain.artifacts.service import ArtifactService
from app.domain.tasks.models import Task

router = APIRouter(prefix="/tasks/{task_id}/artifacts", tags=["artifacts"])


class TaskArtifactRepository(ArtifactRepository):
    def __init__(self, db):
        super().__init__(db)
        self.db = db

    async def get_task(self, task_id):
        return await self.db.get(Task, task_id)


def service(db):
    return ArtifactService(TaskArtifactRepository(db))


def serialize(row):
    return {"id": row.id, "task_id": row.task_id, "node_id": row.node_id,
            "logical_name": row.logical_name, "iteration": row.iteration,
            "attempt": row.attempt, "media_type": row.media_type, "size": row.size,
            "sha256": row.sha256, "created_at": row.created_at}


@router.get("")
async def list_artifacts(task_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [serialize(row) for row in await service(db).list_for_task(task_id, user)]


@router.get("/{artifact_id}/download")
async def download_artifact(task_id: str, artifact_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await service(db).get_download(task_id, artifact_id, user)
    path = Path(row.storage_path).resolve()
    if not path.is_file():
        from shared.errors import NotFoundError
        raise NotFoundError("errors.artifact.not_found")
    return FileResponse(path, media_type=row.media_type, filename=row.logical_name)
