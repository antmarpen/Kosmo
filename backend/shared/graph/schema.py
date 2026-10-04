from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

SAFE_IDENTIFIER = r"^[a-zA-Z0-9._-]{1,64}$"
SafeIdentifier = Annotated[str, Field(pattern=SAFE_IDENTIFIER)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormField(ContractModel):
    name: str = Field(pattern=SAFE_IDENTIFIER)
    type: Literal["string", "number", "boolean"]
    required: bool
    validation: "ValidationContract | None" = None


class StartNode(ContractModel):
    type: Literal["start"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    input_form: list[FormField]


class LegacyValidationLevel(ContractModel):
    name: str
    message_key: str
    params_schema: dict


class ValidationContract(ContractModel):
    """Canonical validation configuration. Legacy ``levels`` are read separately."""
    format: Literal["text", "markdown", "json", "yaml"]
    json_schema: bool | dict | None = None
    rules_code: str | None = None

    @model_validator(mode="after")
    def validate_format_options(self):
        if self.format in {"text", "markdown"} and (self.json_schema is not None or self.rules_code is not None):
            raise ValueError("text and markdown validation are parse-only")
        if self.format == "yaml" and self.json_schema is not None:
            raise ValueError("YAML does not support JSON Schema")
        return self


class LegacyValidationContract(ContractModel):
    """Isolated shape for reading historical C3 contracts only."""
    levels: list[LegacyValidationLevel] = Field(min_length=3, max_length=3)


class ScriptNode(ContractModel):
    type: Literal["script"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    code: str
    inputs: list[SafeIdentifier]
    outputs: list[SafeIdentifier]
    output_validation: dict[str, ValidationContract] | None = None


class HttpNode(ContractModel):
    type: Literal["http"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    method: str
    url: str
    inputs: list[SafeIdentifier] = Field(default_factory=list)
    outputs: list[Literal["response"]] = Field(default_factory=lambda: ["response"], min_length=1, max_length=1)
    output_validation: dict[str, ValidationContract] | None = None


class AiNode(ContractModel):
    type: Literal["ai"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    agent_id: UUID | None = None
    model: str | None = Field(default=None, min_length=1, max_length=300)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=80)
    added_mcp_ids: list[UUID] = Field(default_factory=list)
    removed_mcp_ids: list[UUID] = Field(default_factory=list)
    added_skill_ids: list[UUID] = Field(default_factory=list)
    removed_skill_ids: list[UUID] = Field(default_factory=list)
    prompt_template: str
    inputs: list[SafeIdentifier]
    outputs: list[SafeIdentifier]
    output_validation: dict[str, ValidationContract] | None = None
    # Parsing-only compatibility for old persisted AI definitions. Excluded from
    # serialization; callers normalize before storing canonical definitions.
    validation: ValidationContract | dict | None = Field(default=None, exclude=True)
    max_validation_cycles: int = 3

    @model_validator(mode="before")
    @classmethod
    def trim_overrides(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            for field in ("model", "reasoning_effort"):
                if isinstance(value.get(field), str):
                    value[field] = value[field].strip()
        return value

    @model_validator(mode="after")
    def validate_reference_deltas(self):
        for kind in ("mcp", "skill"):
            added = getattr(self, f"added_{kind}_ids")
            removed = getattr(self, f"removed_{kind}_ids")
            if len(added) != len(set(added)) or len(removed) != len(set(removed)):
                raise ValueError(f"{kind} reference deltas must be unique")
            if set(added) & set(removed):
                raise ValueError(f"{kind} reference deltas must be disjoint")
        return self

    @model_serializer(mode="wrap")
    def omit_inherited_values(self, handler):
        result = handler(self)
        for field in ("agent_id", "model", "reasoning_effort", "added_mcp_ids", "removed_mcp_ids",
                      "added_skill_ids", "removed_skill_ids"):
            value = result.get(field)
            if value is None or value == []:
                result.pop(field, None)
        return result


class EndNode(ContractModel):
    type: Literal["end"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    inputs: list[SafeIdentifier] = Field(default_factory=list)


class DecisionNode(ContractModel):
    type: Literal["decision"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    selected_next_node_id: str


class WorkflowNode(ContractModel):
    type: Literal["workflow"]
    id: str = Field(pattern=SAFE_IDENTIFIER)
    workflow_id: str
    inputs: list[SafeIdentifier] = Field(default_factory=list)
    output_validation: dict[str, ValidationContract] | None = None


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
