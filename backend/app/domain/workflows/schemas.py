from datetime import datetime

from pydantic import BaseModel, Field


class PublishDraftRequest(BaseModel):
    expected_pub_revision: int = Field(ge=0)
    confirm_overwrite: bool = False


class ActivateWorkflowRequest(BaseModel):
    version_id: str
    expected_active_revision: int = Field(ge=0)
    confirm_stale_base: bool = False


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
    publication_revision: int
    active_version: ActiveVersionResponse | None


class WorkflowDraftSave(BaseModel):
    definition: dict
    layout: dict = Field(default_factory=dict)
    expected_revision: int = Field(ge=1)


class WorkflowDraftResponse(BaseModel):
    id: str
    revision: int
    definition: dict
    layout: dict


class WorkflowDraftMetadata(BaseModel):
    id: str
    revision: int
    updated_at: datetime
