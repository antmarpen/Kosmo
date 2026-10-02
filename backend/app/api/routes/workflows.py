from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.domain.workflows.repository import WorkflowRepository
from app.domain.workflows.schemas import ActivateWorkflowRequest, PublishDraftRequest, WorkflowDraftMetadata, WorkflowDraftResponse, WorkflowDraftSave, WorkflowResponse, WorkflowVersionResponse
from app.domain.workflows.service import WorkflowService
from shared.graph.schema import WorkflowDefinition

router = APIRouter(prefix="/workflows", tags=["workflows"])


def service(db: AsyncSession) -> WorkflowService:
    return WorkflowService(WorkflowRepository(db))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkflowVersionResponse, dependencies=[Depends(require_roles("admin", "builder"))])
async def publish(definition: WorkflowDefinition, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).publish(definition, user.id)


@router.post("/{workflow_id}/drafts/{draft_id}/publish", status_code=status.HTTP_201_CREATED, response_model=WorkflowVersionResponse, dependencies=[Depends(require_roles("admin", "builder"))])
async def publish_draft(workflow_id: str, draft_id: str, body: PublishDraftRequest, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).publish_draft(workflow_id, draft_id, user, body.expected_pub_revision, body.confirm_overwrite)


@router.post("/{workflow_id}/activate", dependencies=[Depends(require_roles("admin", "builder"))])
async def activate_version(workflow_id: str, body: ActivateWorkflowRequest, db: AsyncSession = Depends(get_db)):
    version = await service(db).activate_version(workflow_id, body.version_id, body.expected_active_revision, body.confirm_stale_base)
    return {"version_id": _value(version, "id"), "active_revision": _value(version, "version")}


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).list_workflows()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, _user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).get_workflow(workflow_id)


@router.post("/{workflow_id}/drafts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("admin", "builder"))])
async def create_draft(workflow_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    draft = await service(db).create_draft(workflow_id, user.id)
    return {"draft_id": _value(draft, "id"), "revision": _value(draft, "revision")}


@router.get("/{workflow_id}/drafts", response_model=list[WorkflowDraftMetadata])
async def list_drafts(workflow_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).list_drafts(workflow_id, user.id)


@router.get("/{workflow_id}/drafts/{draft_id}", response_model=WorkflowDraftResponse)
async def get_draft(workflow_id: str, draft_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).get_draft(workflow_id, draft_id, user)


@router.put("/{workflow_id}/drafts/{draft_id}")
async def save_draft(workflow_id: str, draft_id: str, body: WorkflowDraftSave,
                     validate: bool = Query(False), user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    draft = await service(db).save_draft(workflow_id, draft_id, user, body.expected_revision, body.definition, body.layout)
    result = {"revision": _value(draft, "revision")}
    if validate:
        result["issues"] = await service(db).validate_draft(workflow_id, draft_id, user)
    return result


@router.post("/{workflow_id}/drafts/{draft_id}/validate")
async def validate_draft(workflow_id: str, draft_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"issues": await service(db).validate_draft(workflow_id, draft_id, user)}


def _value(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)
