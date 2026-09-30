import pytest
from pydantic import ValidationError

from shared.graph.schema import WorkflowDefinition


def valid_definition():
    return {
        "schema_version": "v1", "name": "example", "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "label_message_key": "workflow.topic.label"}]},
            {"type": "script", "id": "script", "code": "pass", "inputs": ["topic"], "outputs": ["report"]},
            {"type": "end", "id": "end"},
        ], "edges": [{"from": "start", "to": "script"}, {"from": "script", "to": "end"}],
    }


def test_schema_parses_v1_with_discriminated_node_types_and_edge_aliases():
    definition = WorkflowDefinition.model_validate(valid_definition())
    assert definition.schema_version == "v1"
    assert definition.edges[0].from_node == "start"
    assert definition.nodes[0].type == "start"


def test_schema_rejects_unknown_version():
    value = valid_definition()
    value["schema_version"] = "v2"
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_schema_rejects_unknown_node_discriminator():
    value = valid_definition()
    value["nodes"][1]["type"] = "unknown"
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_schema_requires_exactly_three_ai_validation_levels():
    value = valid_definition()
    value["nodes"][1] = {"type": "ai", "id": "ai", "agent": {"runtime": "opencode", "model": "m", "instructions": "i"}, "prompt_template": "p", "inputs": ["topic"], "outputs": [], "validation": {"levels": []}}
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_schema_carries_optional_bounded_loop_phase():
    value = valid_definition()
    value["phases"] = [{"id": "phase-1", "node_ids": ["start", "script", "end"], "loop": {"target_node_id": "script", "max_iterations": 2}}]
    assert WorkflowDefinition.model_validate(value).phases[0].loop.max_iterations == 2


@pytest.mark.parametrize("location,value", [
    ("node", "/etc/passwd"), ("node", "../escape"), ("node", "bad/name"),
    ("node", "x" * 65), ("node", ""), ("field", "../escape"),
    ("artifact", "nested/file"),
])
def test_schema_rejects_invalid_path_identifiers(location, value):
    definition = valid_definition()
    if location == "node":
        definition["nodes"][1]["id"] = value
    elif location == "field":
        definition["nodes"][0]["input_form"][0]["name"] = value
    else:
        definition["nodes"][1]["outputs"] = [value]
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition)
