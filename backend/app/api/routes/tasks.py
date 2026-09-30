from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.domain.tasks.repository import TaskRepository
from app.domain.tasks.schemas import TaskCreated, TaskListItem, TaskSubmission
from app.domain.tasks.service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


class HumanInput(BaseModel):
    answer: str = Field(min_length=1, max_length=10000)
    node_execution_id: str = Field(min_length=1, max_length=36)
    request_id: str | int


def service(db: AsyncSession) -> TaskService:
    return TaskService(TaskRepository(db))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskCreated)
async def submit(body: TaskSubmission, user=Depends(require_roles("runner", "admin")), db: AsyncSession = Depends(get_db)):
    return await service(db).submit(body.workflow_id, body.input_values, body.prompt, user.id)


@router.get("")
async def list_tasks(_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[TaskListItem]:
    return await service(db).list_tasks(_user)


@router.get("/{task_id}")
async def get_task(task_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).get_task(task_id, user)


@router.post("/{task_id}/input")
async def answer_task(task_id: str, body: HumanInput, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).record_answer(task_id, body.answer, user, body.node_execution_id, body.request_id)


@router.post("/{task_id}/stop")
async def stop_task(task_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service(db).request_stop(task_id, user)
