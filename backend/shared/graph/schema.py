from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SAFE_IDENTIFIER = r"^[a-zA-Z0-9._-]{1,64}$"
SafeIdentifier = Annotated[str, Field(pattern=SAFE_IDENTIFIER)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormField(ContractModel):
    name: str = Field(pattern=SAFE_IDENTIFIER)
    type: Literal["string", "number", "boolean"]
    required: bool
    label_message_key: str


class StartNode(ContractModel):
    type: Literal["start"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    input_form: list[FormField]


class ScriptNode(ContractModel):
    type: Literal["script"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    code: str
    inputs: list[SafeIdentifier]
    outputs: list[SafeIdentifier]


class HttpNode(ContractModel):
    type: Literal["http"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    method: str
    url: str
    outputs: list[str] = Field(pattern=SAFE_IDENTIFIER)


class AgentConfig(ContractModel):
    runtime: Literal["opencode"]
    model: str
    instructions: str


class ValidationLevel(ContractModel):
    name: str
    message_key: str
    params_schema: dict


class ValidationContract(ContractModel):
    levels: list[ValidationLevel] = Field(min_length=3, max_length=3)


class AiNode(ContractModel):
    type: Literal["ai"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    agent: AgentConfig
    prompt_template: str
    inputs: list[SafeIdentifier]
    outputs: list[SafeIdentifier]
    validation: ValidationContract
    max_validation_cycles: int = 3


class EndNode(ContractModel):
    type: Literal["end"]
    id: str = Field(pattern=SAFE_IDENTIFIER)


class DecisionNode(ContractModel):
    type: Literal["decision"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    selected_next_node_id: str


class WorkflowNode(ContractModel):
    type: Literal["workflow"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    workflow_id: str


Node = Annotated[StartNode | ScriptNode | HttpNode | AiNode | EndNode | DecisionNode | WorkflowNode, Field(discriminator="type")]


class Edge(ContractModel):
    from_node: str = Field(alias="from", pattern=SAFE_IDENTIFIER)
    to: str = Field(pattern=SAFE_IDENTIFIER)


class LoopPolicy(ContractModel):
    target_node_id: str
    max_iterations: int


class Phase(ContractModel):
    id: str
    node_ids: list[str]
    loop: LoopPolicy | None = None


class WorkflowDefinition(ContractModel):
    schema_version: Literal["v1"]
    name: str
    nodes: list[Node]
    edges: list[Edge]
    phases: list[Phase] | None = None
