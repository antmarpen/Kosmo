from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workflows.models import Activation, Workflow, WorkflowVersion
from shared.errors import ConflictError


class WorkflowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_name(self, name):
        return await self.db.scalar(select(Workflow).where(Workflow.name == name))

    async def create_workflow(self, name):
        row = Workflow(name=name)
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as error:
            raise ConflictError("errors.workflow.name_conflict") from error
        return row

    async def next_version(self, workflow_id):
        latest = await self.db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow_id))
        return (latest or 0) + 1

    async def create_version(self, workflow_id, version, definition):
        row = WorkflowVersion(workflow_id=workflow_id, version=version, definition=definition)
        self.db.add(row)
        await self.db.flush()
        return row

    async def activate(self, workflow_id, version_id):
        row = await self.db.get(Activation, workflow_id)
        if row is None:
            self.db.add(Activation(workflow_id=workflow_id, version_id=version_id))
        else:
            row.version_id = version_id
        await self.db.flush()

    async def list_workflows(self):
        return list((await self.db.scalars(select(Workflow).order_by(Workflow.name))).all())

    async def get_workflow(self, workflow_id):
        return await self.db.get(Workflow, workflow_id)

    async def get_active_version(self, workflow_id):
        return await self.db.scalar(select(WorkflowVersion).join(Activation, Activation.version_id == WorkflowVersion.id).where(Activation.workflow_id == workflow_id))
