from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

from shared.errors import ErrorDetail, ValidationFailedError
from shared.graph.schema import AiNode, DecisionNode, EndNode, HttpNode, ScriptNode, StartNode, WorkflowDefinition, WorkflowNode
from shared.graph.script_contract import analyze_script_body


def validate_workflow(definition: WorkflowDefinition, workflow_exists: Callable[[str], bool] | None = None,
                      workflow_contract: Callable[[str], tuple[list[str], list[str]] | None] | None = None) -> None:
    issues: list[ErrorDetail] = []
    if not definition.name.strip():
        issues.append(_detail("name_required"))
    nodes = definition.nodes
    by_id = {node.id: node for node in nodes}
    ids = [node.id for node in nodes]
    node_ids = set(ids)
    for node_id in set(ids):
        if ids.count(node_id) > 1:
            issues.append(_detail("duplicate_node_id", node_id=node_id))
    starts = [n for n in nodes if isinstance(n, StartNode)]
    ends = [n for n in nodes if isinstance(n, EndNode)]
    if len(starts) != 1: issues.append(_detail("start_count", count=len(starts)))
    if len(ends) != 1: issues.append(_detail("end_count", count=len(ends)))
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    predecessors: dict[str, list[str]] = defaultdict(list)
    for edge in definition.edges:
        if edge.from_node not in node_ids or edge.to not in node_ids:
            issues.append(_detail("edge_node_missing", source=edge.from_node, target=edge.to)); continue
        outgoing[edge.from_node].append(edge.to); incoming[edge.to].append(edge.from_node)
        predecessors[edge.to].append(edge.from_node)
    if len(starts) == 1:
        start = starts[0]
        if incoming[start.id]: issues.append(_detail("start_incoming_edge", node_id=start.id))
        if not start.input_form: issues.append(_detail("start_input_required", node_id=start.id))
    if len(ends) == 1 and outgoing[ends[0].id]: issues.append(_detail("end_outgoing_edge", node_id=ends[0].id))
    for node in nodes:
        if isinstance(node, DecisionNode):
            if node.selected_next_node_id not in node_ids: issues.append(_detail("decision_target_missing", node_id=node.id, target=node.selected_next_node_id))
            elif node.selected_next_node_id not in outgoing[node.id]: issues.append(_detail("decision_target_not_outgoing", node_id=node.id, target=node.selected_next_node_id))
    if starts:
        reachable = _reachable(starts[0].id, outgoing)
        if len(reachable) < len(node_ids): issues.append(_detail("disconnected"))
    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    queue = deque(i for i, degree in indegree.items() if degree == 0); visited = 0
    while queue:
        current = queue.popleft(); visited += 1
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0: queue.append(target)
    if visited < len(node_ids): issues.append(_detail("cycle"))

    output_map: dict[str, list[str]] = {}
    script_analyses = {}
    for node in nodes:
        if isinstance(node, StartNode): output_map[node.id] = [field.name for field in node.input_form]
        elif isinstance(node, ScriptNode):
            output_map[node.id] = list(analyze_script_body(node.code, []).outputs)
        elif isinstance(node, AiNode): output_map[node.id] = list(node.outputs)
        elif isinstance(node, HttpNode): output_map[node.id] = ["response"]
        elif isinstance(node, WorkflowNode):
            if not node.workflow_id.strip():
                issues.append(_detail("workflow_id_required", node_id=node.id))
            contract = workflow_contract(node.workflow_id) if workflow_contract is not None and node.workflow_id.strip() else None
            exists = workflow_exists(node.workflow_id) if workflow_exists is not None and node.workflow_id.strip() else None
            if contract is None and exists is not False:
                issues.append(_detail("reference_contract_unavailable", node_id=node.id, workflow_id=node.workflow_id))
            if contract is None:
                output_map[node.id] = []
            else:
                output_map[node.id] = list(contract[1])
        else: output_map[node.id] = []
    for node in nodes:
        if isinstance(node, WorkflowNode):
            if workflow_exists is not None and node.workflow_id.strip() and not workflow_exists(node.workflow_id):
                issues.append(_detail("workflow_not_found", node_id=node.id, workflow_id=node.workflow_id))
        source_outputs = [name for source in predecessors[node.id] for name in output_map.get(source, [])]
        if len(source_outputs) != len(set(source_outputs)):
            issues.append(_detail("duplicate_input_names", node_id=node.id))
        inputs = list(dict.fromkeys(source_outputs))
        if isinstance(node, (ScriptNode, AiNode, EndNode, HttpNode, WorkflowNode)) and hasattr(node, "inputs"):
            _check_snapshot(node, inputs, "inputs", issues)
        if isinstance(node, ScriptNode):
            analysis = analyze_script_body(node.code, inputs)
            for issue in analysis.issues:
                issues.append(ErrorDetail(issue.message_key, {**issue.params, "node_id": node.id}))
            output_map[node.id] = list(analysis.outputs)
            _check_snapshot(node, list(analysis.outputs), "outputs", issues)
        if isinstance(node, HttpNode):
            _check_snapshot(node, ["response"], "outputs", issues)
        if isinstance(node, AiNode) and len(node.validation.levels) != 3:
            issues.append(_detail("ai_validation_level_count", node_id=node.id, count=len(node.validation.levels)))
    if issues: raise ValidationFailedError("errors.workflow.invalid", details=issues)


def _check_snapshot(node, expected: list[str], field: str, issues: list[ErrorDetail]) -> None:
    if list(getattr(node, field, [])) != expected:
        issues.append(_detail("derived_contract_stale", node_id=node.id, field=field, expected=expected))


def _reachable(start: str, outgoing: dict[str, list[str]]) -> set[str]:
    found: set[str] = set(); pending = [start]
    while pending:
        current = pending.pop()
        if current in found: continue
        found.add(current); pending.extend(outgoing[current])
    return found


def _detail(rule: str, **params: object) -> ErrorDetail:
    return ErrorDetail(message_key=f"errors.workflow.{rule}", params=params)
