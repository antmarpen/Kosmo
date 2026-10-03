import pytest

from app.domain.workflows.validation import validate_workflow
from shared.errors import ValidationFailedError
from shared.graph.schema import AiNode, Edge, EndNode, FormField, StartNode, ValidationContract, WorkflowDefinition


def workflow(nodes=None, edges=None):
    return WorkflowDefinition.model_validate({
        "schema_version": "v1", "name": "example",
        "nodes": nodes or [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "script", "id": "script", "code": "report = topic\nreturn report", "inputs": ["topic"], "outputs": ["report"]},
            {"type": "end", "id": "end", "inputs": ["report"]},
        ], "edges": edges or [{"from": "start", "to": "script"}, {"from": "script", "to": "end"}],
    })


def keys(definition):
    with pytest.raises(ValidationFailedError) as caught:
        validate_workflow(definition)
    return [detail.message_key for detail in caught.value.details]


def test_valid_reference_definition_passes():
    assert validate_workflow(workflow()) is None


def decision_definition(target):
    return workflow(
        nodes=[
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "decision", "id": "decision", "selected_next_node_id": target},
            {"type": "script", "id": "script", "code": "result = topic; return result", "inputs": [], "outputs": ["result"]},
            {"type": "end", "id": "end", "inputs": ["result"]},
        ],
        edges=[{"from": "start", "to": "decision"}, {"from": "decision", "to": "script"}, {"from": "decision", "to": "end"}, {"from": "script", "to": "end"}],
    )


def test_decision_selected_outgoing_target_passes():
    assert validate_workflow(decision_definition("script")) is None


@pytest.mark.parametrize("target,rule", [("missing", "decision_target_missing"), ("start", "decision_target_not_outgoing")])
def test_decision_invalid_target_is_reported(target, rule):
    assert f"errors.workflow.{rule}" in keys(decision_definition(target))


def workflow_node_definition(workflow_id):
    return workflow(nodes=[
        {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
        {"type": "workflow", "id": "invoke", "workflow_id": workflow_id},
        {"type": "end", "id": "end"},
    ], edges=[{"from": "start", "to": "invoke"}, {"from": "invoke", "to": "end"}])


def test_workflow_node_requires_nonempty_existing_reference():
    assert "errors.workflow.workflow_id_required" in keys(workflow_node_definition(""))
    assert "errors.workflow.reference_contract_unavailable" in keys(workflow_node_definition("child"))


def test_workflow_node_without_resolver_fails_closed():
    """Callers must inject existence checking: absent resolver means the reference cannot be verified."""
    assert "errors.workflow.reference_contract_unavailable" in keys(workflow_node_definition("child"))


def test_workflow_node_reports_missing_reference():
    with pytest.raises(ValidationFailedError) as caught:
        validate_workflow(workflow_node_definition("missing"), workflow_exists=lambda _: False)
    assert "errors.workflow.workflow_not_found" in [detail.message_key for detail in caught.value.details]


def test_duplicate_node_ids_are_reported():
    assert "errors.workflow.duplicate_node_id" in keys(workflow(nodes=[
        {"type": "start", "id": "same", "input_form": [{"name": "topic", "type": "string", "required": True}]},
        {"type": "end", "id": "same"},
    ], edges=[]))


def test_unknown_edge_endpoints_are_reported():
    assert "errors.workflow.edge_node_missing" in keys(workflow(edges=[{"from": "start", "to": "missing"}]))


def test_exactly_one_start_and_end_are_required():
    assert "errors.workflow.start_count" in keys(workflow(nodes=[{"type": "end", "id": "end"}], edges=[]))
    assert "errors.workflow.end_count" in keys(workflow(nodes=[{"type": "start", "id": "start", "input_form": [{"name": "x", "type": "string", "required": True}] }], edges=[]))


def test_start_cannot_have_incoming_edge():
    assert "errors.workflow.start_incoming_edge" in keys(workflow(edges=[{"from": "script", "to": "start"}, {"from": "start", "to": "end"}]))


def test_end_cannot_have_outgoing_edge():
    assert "errors.workflow.end_outgoing_edge" in keys(workflow(edges=[{"from": "start", "to": "end"}, {"from": "end", "to": "script"}]))


def test_disconnected_graph_is_reported():
    nodes = workflow().model_dump(mode="python")["nodes"] + [{"type": "script", "id": "orphan", "code": "return", "inputs": ["topic"], "outputs": []}]
    assert "errors.workflow.disconnected" in keys(workflow(nodes=nodes))


def test_cyclic_graph_is_reported():
    assert "errors.workflow.cycle" in keys(workflow(edges=[{"from": "start", "to": "script"}, {"from": "script", "to": "start"}, {"from": "script", "to": "end"}]))


def test_unresolved_input_and_output_artifacts_are_reported():
    nodes = workflow().model_dump(mode="python")["nodes"]
    nodes[1]["inputs"] = ["absent"]
    found = keys(workflow(nodes=nodes))
    assert found.count("errors.workflow.derived_contract_stale") == 1


def test_start_requires_at_least_one_form_field():
    nodes = workflow().model_dump(mode="python")["nodes"]
    nodes[0]["input_form"] = []
    assert "errors.workflow.start_input_required" in keys(workflow(nodes=nodes))


def test_ai_requires_three_validation_levels():
    invalid_ai = AiNode.model_construct(id="ai", validation=ValidationContract.model_construct(levels=[]), inputs=["topic"], outputs=[])
    definition = WorkflowDefinition.model_construct(
        schema_version="v1", name="example",
        nodes=[StartNode.model_construct(id="start", input_form=[FormField.model_construct(name="topic")]), invalid_ai, EndNode.model_construct(id="end")],
        edges=[Edge.model_construct(from_node="start", to="ai"), Edge.model_construct(from_node="ai", to="end")], phases=None,
    )
    assert "errors.workflow.ai_validation_level_count" in keys(definition)

