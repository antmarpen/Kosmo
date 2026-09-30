from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.domain.workflows.repository import WorkflowRepository
from app.domain.workflows.schemas import WorkflowResponse, WorkflowVersionResponse
from app.domain.workflows.service import WorkflowService
from shared.graph.schema import WorkflowDefinition

router = APIRouter(prefix="/workflows", tags=["workflows"])


def service(db: AsyncSession) -> WorkflowService:
    return WorkflowService(WorkflowRepository(db))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkflowVersionResponse, dependencies=[Depends(require_roles("admin", "builder"))])
async def publish(definition: WorkflowDefinition, db: AsyncSession = Depends(get_db)):
    return await service(db).publish(definition)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).list_workflows()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, _user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).get_workflow(workflow_id)
