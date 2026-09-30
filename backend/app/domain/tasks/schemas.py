from pydantic import BaseModel, ConfigDict


class TaskSubmission(BaseModel):
    workflow_id: str
    input_values: dict
    prompt: str | None = None


class TaskCreated(BaseModel):
    id: str
    state: str


class TaskListItem(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    state: str
    created_at: object
    updated_at: object


class TaskDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    version_id: str
    state: str
    prompt: str | None
    input_values: dict
    resolved_definition: dict
    created_by: str
    created_at: object
    updated_at: object
    nodes: list[dict] = []
    notes: list[dict] = []
    artifacts: list[dict] = []
