from pydantic import BaseModel


class WorkflowVersionResponse(BaseModel):
    id: str
    workflow_id: str
    version: int
    definition: dict


class ActiveVersionResponse(BaseModel):
    id: str
    version: int
    definition: dict


class WorkflowResponse(BaseModel):
    id: str
    name: str
    active_version: ActiveVersionResponse | None
