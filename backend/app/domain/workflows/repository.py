from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workflows.models import Activation, Workflow, WorkflowDraft, WorkflowVersion
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

    async def get_latest_version(self, workflow_id):
        return await self.db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version.desc()).limit(1))

    async def create_version(self, workflow_id, version, definition, published_by=None):
        row = WorkflowVersion(workflow_id=workflow_id, version=version, definition=definition, published_by=published_by)
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

    async def lock_workflow(self, workflow_id):
        return await self.db.scalar(select(Workflow).where(Workflow.id == workflow_id).with_for_update())

    async def increment_publication_revision(self, workflow):
        workflow.publication_revision += 1
        await self.db.flush()
        return workflow.publication_revision

    async def get_version(self, version_id):
        return await self.db.get(WorkflowVersion, version_id)

    async def get_active_version(self, workflow_id):
        return await self.db.scalar(select(WorkflowVersion).join(Activation, Activation.version_id == WorkflowVersion.id).where(Activation.workflow_id == workflow_id))

    async def create_draft(self, workflow_id, author_id, base_version_id, definition, layout):
        row = WorkflowDraft(workflow_id=workflow_id, author_id=author_id, base_version_id=base_version_id,
                            definition=definition, layout=layout, revision=1)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_drafts(self, workflow_id, author_id):
        query = select(WorkflowDraft).where(WorkflowDraft.author_id == author_id)
        query = query.where(WorkflowDraft.workflow_id == workflow_id) if workflow_id else query
        return list((await self.db.scalars(query.order_by(WorkflowDraft.updated_at.desc()))).all())

    async def get_draft(self, workflow_id, draft_id):
        return await self.db.scalar(select(WorkflowDraft).where(WorkflowDraft.id == draft_id, WorkflowDraft.workflow_id == workflow_id))

    async def save_draft(self, draft_id, author_id, expected_revision, definition, layout):
        statement = update(WorkflowDraft).where(
            WorkflowDraft.id == draft_id, WorkflowDraft.author_id == author_id,
            WorkflowDraft.revision == expected_revision,
        ).values(definition=definition, layout=layout, revision=WorkflowDraft.revision + 1,
                 updated_at=func.now()).returning(WorkflowDraft)
        row = (await self.db.execute(statement)).scalar_one_or_none()
        if row is not None:
            return row
        current = await self.db.scalar(select(WorkflowDraft).where(WorkflowDraft.id == draft_id, WorkflowDraft.author_id == author_id))
        if current is None:
            return None
        raise ConflictError("errors.workflow.draft_revision_conflict", {"current_revision": current.revision})
