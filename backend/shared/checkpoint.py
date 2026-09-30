from pydantic import BaseModel, ConfigDict, Field


class CompletedExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    outputs: dict[str, dict] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    recorded_at: str


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    version: int = Field(ge=1)
    completed: dict[str, CompletedExecution] = Field(default_factory=dict)


def is_execution_completed(checkpoint: dict, node_id: str, iteration: int = 0) -> bool:
    return f"{node_id}:{iteration}" in checkpoint.get("completed", {})
