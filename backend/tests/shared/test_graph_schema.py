import pytest
from pydantic import ValidationError

from shared.graph.schema import WorkflowDefinition
from shared.graph.output_contract import normalize_output_validation, normalize_validation_contracts


def valid_definition():
    return {
        "schema_version": "v1", "name": "example", "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
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


def test_form_field_rejects_removed_label_message_key():
    value = valid_definition()
    value["nodes"][0]["input_form"][0]["label_message_key"] = "workflow.topic.label"
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_schema_rejects_unknown_node_discriminator():
    value = valid_definition()
    value["nodes"][1]["type"] = "unknown"
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_schema_requires_exactly_three_output_validation_levels():
    value = valid_definition()
    value["nodes"][1] = {"type": "ai", "id": "ai", "agent_id": "00000000-0000-0000-0000-000000000001", "prompt_template": "p", "inputs": ["topic"], "outputs": ["result"], "output_validation": {"result": {"levels": []}}}
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def test_legacy_ai_contract_is_copied_to_each_output_without_aliasing():
    value = valid_definition()
    legacy = {"levels": [
        {"name": "parse", "message_key": "x", "params_schema": {"format": "json"}},
        {"name": "structure", "message_key": "x", "params_schema": {"required_keys": ["id"]}},
        {"name": "rules", "message_key": "x", "params_schema": {}},
    ]}
    value["nodes"][1] = {"type": "ai", "id": "ai", "agent_id": "00000000-0000-0000-0000-000000000001", "prompt_template": "p", "inputs": [], "outputs": ["a", "b"], "validation": legacy}
    normalized = normalize_output_validation(value)
    normalized["nodes"][1]["output_validation"]["a"]["json_schema"]["required"].append("changed")
    assert normalized["nodes"][1]["output_validation"]["b"]["json_schema"]["required"] == ["id"]
    assert "validation" not in normalized["nodes"][1]


def test_legacy_ai_without_outputs_is_preserved_as_draft_extension():
    value = valid_definition()
    legacy = {"levels": []}
    value["nodes"][1] = {"type": "ai", "id": "ai", "agent_id": "00000000-0000-0000-0000-000000000001", "prompt_template": "p", "inputs": [], "outputs": [], "validation": legacy}
    normalized = normalize_output_validation(value)
    assert normalized["nodes"][1]["validation"] == legacy
    assert WorkflowDefinition.model_validate(normalized).model_dump(mode="json")["nodes"][1].get("validation") is None


def test_legacy_and_new_contract_conflict_returns_keyed_issue():
    value = valid_definition()
    value["nodes"][1] = {"type": "ai", "id": "ai", "agent_id": "00000000-0000-0000-0000-000000000001", "prompt_template": "p", "inputs": [], "outputs": ["a"], "validation": {}, "output_validation": {}}
    _, issues = normalize_validation_contracts(value)
    assert issues[0]["key"] == "errors.graph.output_validation_conflict"


def test_schema_has_output_validation_only_on_contract_output_nodes():
    value = valid_definition()
    value["nodes"][1]["output_validation"] = {}
    parsed = WorkflowDefinition.model_validate(value)
    dumped = parsed.model_dump(mode="json")
    assert "validation" not in dumped["nodes"][1]
    for node in [
        {"type": "script", "id": "s", "code": "pass", "inputs": [], "outputs": []},
        {"type": "http", "id": "h", "method": "GET", "url": "https://example.invalid"},
        {"type": "ai", "id": "a", "agent_id": "00000000-0000-0000-0000-000000000001", "prompt_template": "p", "inputs": [], "outputs": []},
        {"type": "workflow", "id": "w", "workflow_id": "child"},
    ]:
        value = valid_definition(); value["nodes"][1] = node
        assert "output_validation" in WorkflowDefinition.model_validate(value).model_dump(mode="json")["nodes"][1]
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({**valid_definition(), "nodes": [{"type": "start", "id": "start", "input_form": [], "output_validation": {}}]})


def test_schema_carries_optional_bounded_loop_phase():
    value = valid_definition()
    value["phases"] = [{"id": "phase-1", "node_ids": ["start", "script", "end"], "loop": {"target_node_id": "script", "max_iterations": 2}}]
    assert WorkflowDefinition.model_validate(value).phases[0].loop.max_iterations == 2


@pytest.mark.parametrize("node", [
    {"type": "decision", "id": "decision", "selected_next_node_id": "end"},
    {"type": "workflow", "id": "invoke", "workflow_id": "child-workflow", "inputs": []},
])
def test_schema_round_trips_decision_and_workflow_nodes(node):
    value = valid_definition()
    value["nodes"].insert(1, node)
    parsed = WorkflowDefinition.model_validate(value)
    dumped = parsed.model_dump(mode="json", by_alias=True)
    assert {key: value for key, value in dumped["nodes"][1].items() if key != "output_validation"} == node
    if node["type"] == "workflow":
        assert dumped["nodes"][1]["output_validation"] is None
    else:
        assert "output_validation" not in dumped["nodes"][1]
    assert type(WorkflowDefinition.model_validate(dumped).nodes[1]).__name__ == ("DecisionNode" if node["type"] == "decision" else "WorkflowNode")


def test_new_node_variants_reject_extra_fields():
    value = valid_definition()
    value["nodes"].insert(1, {"type": "decision", "id": "decision", "selected_next_node_id": "end", "extra": True})
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(value)


def http_definition(outputs):
    value = valid_definition()
    value["nodes"][1] = {"type": "http", "id": "http", "method": "GET", "url": "https://example.invalid", "outputs": outputs}
    return value


def test_http_node_defaults_to_fixed_response_output():
    value = valid_definition()
    value["nodes"][1] = {"type": "http", "id": "http", "method": "GET", "url": "https://example.invalid"}
    assert WorkflowDefinition.model_validate(value).nodes[1].outputs == ["response"]


@pytest.mark.parametrize("outputs", [["../escape"], ["bad/name"], ["x" * 65], [""], ["nested/file"]])
def test_http_node_rejects_output_other_than_fixed_response(outputs):
    with pytest.raises(ValidationError) as caught:
        WorkflowDefinition.model_validate(http_definition(outputs))
    assert caught.value


@pytest.mark.parametrize("outputs", [[], ["other"], ["response", "other"]])
def test_http_node_rejects_non_fixed_outputs(outputs):
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(http_definition(outputs))


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

