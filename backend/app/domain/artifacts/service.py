from shared.errors import NotFoundError, PermissionDeniedError


class ArtifactService:
    def __init__(self, repository):
        self.repository = repository

    async def _authorize(self, task_id, user):
        task = await self.repository.get_task(task_id)
        if task is None:
            raise NotFoundError("errors.task.not_found")
        if user.role.value != "admin" and task.created_by != user.id:
            raise PermissionDeniedError("errors.auth.forbidden")

    async def list_for_task(self, task_id, user):
        await self._authorize(task_id, user)
        return await self.repository.list_for_task(task_id)

    async def get_download(self, task_id, artifact_id, user):
        await self._authorize(task_id, user)
        artifact = await self.repository.get(artifact_id)
        if artifact is None or artifact.task_id != task_id:
            raise NotFoundError("errors.artifact.not_found")
        return artifact
