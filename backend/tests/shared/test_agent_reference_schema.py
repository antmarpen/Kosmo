from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.graph.schema import WorkflowDefinition


def ai_node(**changes):
    node = {
        "type": "ai", "id": "agent", "prompt_template": "Summarize",
        "inputs": [], "outputs": [],
    }
    node.update(changes)
    return node


def definition(node):
    return {"schema_version": "v1", "name": "Draft", "nodes": [node], "edges": []}


def test_reference_node_accepts_catalog_id_and_canonicalizes_empty_deltas_and_overrides():
    node = ai_node(agent_id=str(uuid4()), model=None, reasoning_effort=None)
    dumped = WorkflowDefinition.model_validate(definition(node)).model_dump(mode="json")["nodes"][0]
    assert dumped["agent_id"] == node["agent_id"]
    assert "model" not in dumped
    assert "reasoning_effort" not in dumped
    assert all(key not in dumped for key in ("added_mcp_ids", "removed_mcp_ids", "added_skill_ids", "removed_skill_ids"))


@pytest.mark.parametrize("legacy", [
    {"agent": {"runtime": "opencode"}}, {"instructions": "inline"},
    {"runtime": "opencode"}, {"transport": {}}, {"secret": "value"},
])
def test_ai_node_rejects_legacy_inline_configuration(legacy):
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition(ai_node(agent_id=str(uuid4()), **legacy)))


@pytest.mark.parametrize("field,values", [
    ("added_mcp_ids", ["not-a-uuid"]),
    ("added_skill_ids", [str(uuid4()), str(uuid4())]),
])
def test_ai_node_rejects_invalid_or_duplicate_delta_ids(field, values):
    if field == "added_skill_ids":
        values[1] = values[0]
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition(ai_node(agent_id=str(uuid4()), **{field: values})))


def test_ai_node_rejects_overlapping_add_and_remove_deltas():
    reference = str(uuid4())
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition(ai_node(
            agent_id=str(uuid4()), added_mcp_ids=[reference], removed_mcp_ids=[reference]
        )))


def test_ai_node_rejects_duplicate_agent_configuration_alias():
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition(ai_node(agent={"runtime": "opencode"})))
