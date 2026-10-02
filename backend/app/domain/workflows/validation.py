from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

from shared.errors import ErrorDetail, ValidationFailedError
from shared.graph.schema import AiNode, DecisionNode, EndNode, HttpNode, ScriptNode, StartNode, WorkflowDefinition, WorkflowNode


def validate_workflow(
    definition: WorkflowDefinition,
    workflow_exists: Callable[[str], bool] | None = None,
) -> None:
    """Validate graph-wide invariants and raise one error containing every violation."""
    issues: list[ErrorDetail] = []
    nodes = definition.nodes
    ids = [node.id for node in nodes]
    node_ids = set(ids)
    counts: dict[str, int] = defaultdict(int)
    for node_id in ids:
        counts[node_id] += 1
    for node_id, count in counts.items():
        if count > 1:
            issues.append(_detail("duplicate_node_id", node_id=node_id))

    starts = [node for node in nodes if isinstance(node, StartNode)]
    ends = [node for node in nodes if isinstance(node, EndNode)]
    if len(starts) != 1:
        issues.append(_detail("start_count", count=len(starts)))
    if len(ends) != 1:
        issues.append(_detail("end_count", count=len(ends)))

    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    valid_edges = []
    for edge in definition.edges:
        if edge.from_node not in node_ids or edge.to not in node_ids:
            issues.append(_detail("edge_node_missing", source=edge.from_node, target=edge.to))
            continue
        outgoing[edge.from_node].append(edge.to)
        incoming[edge.to].append(edge.from_node)
        valid_edges.append(edge)

    for node in nodes:
        if isinstance(node, DecisionNode):
            if node.selected_next_node_id not in node_ids:
                issues.append(_detail("decision_target_missing", node_id=node.id, target=node.selected_next_node_id))
            elif node.selected_next_node_id not in outgoing[node.id]:
                issues.append(_detail("decision_target_not_outgoing", node_id=node.id, target=node.selected_next_node_id))
        if isinstance(node, WorkflowNode):
            if not node.workflow_id.strip():
                issues.append(_detail("workflow_id_required", node_id=node.id))
            elif workflow_exists is None or not workflow_exists(node.workflow_id):
                issues.append(_detail("workflow_not_found", node_id=node.id, workflow_id=node.workflow_id))

    if len(starts) == 1:
        if incoming[starts[0].id]:
            issues.append(_detail("start_incoming_edge", node_id=starts[0].id))
        if not starts[0].input_form:
            issues.append(_detail("start_input_required", node_id=starts[0].id))
    if len(ends) == 1 and outgoing[ends[0].id]:
        issues.append(_detail("end_outgoing_edge", node_id=ends[0].id))

    if nodes:
        reachable = _reachable(ids[0], outgoing)
        if len(reachable) < len(node_ids):
            issues.append(_detail("disconnected"))

    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited < len(node_ids):
        issues.append(_detail("cycle"))

    artifacts = {field.name for node in starts for field in node.input_form}
    artifacts.update(name for node in nodes if isinstance(node, (ScriptNode, AiNode)) for name in node.outputs)
    artifacts.update(name for node in nodes if isinstance(node, (ScriptNode, HttpNode, AiNode)) for name in node.outputs)
    for node in nodes:
        if isinstance(node, (ScriptNode, AiNode)):
            for name in node.inputs:
                if name not in artifacts:
                    issues.append(_detail("artifact_not_declared", node_id=node.id, artifact=name))
        if isinstance(node, AiNode) and len(node.validation.levels) != 3:
            issues.append(_detail("ai_validation_level_count", node_id=node.id, count=len(node.validation.levels)))

    if issues:
        raise ValidationFailedError("errors.workflow.invalid", details=issues)


def _reachable(start: str, outgoing: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(outgoing[current])
    return found


def _detail(rule: str, **params: object) -> ErrorDetail:
    return ErrorDetail(message_key=f"errors.workflow.{rule}", params=params)
