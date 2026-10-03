from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
import ast
import jsonschema
from jsonschema.validators import validator_for

from shared.errors import ErrorDetail, ValidationFailedError
from shared.graph.schema import AiNode, DecisionNode, EndNode, HttpNode, ScriptNode, StartNode, WorkflowDefinition, WorkflowNode
from shared.graph.script_contract import analyze_script_body
from shared.graph.output_contract import normalize_validation_contracts


def validate_output_validation_catalogue(definition: dict) -> list[ErrorDetail]:
    """Validate authored format contracts without executing user rules."""
    issues: list[ErrorDetail] = []
    for node in definition.get("nodes", []):
        if not isinstance(node, dict):
            continue
        contracts = node.get("output_validation") or {}
        for output, contract in contracts.items():
            _validate_contract(contract, issues, node_id=node.get("id"), output=output)
        if node.get("type") == "start":
            for field in node.get("input_form", []):
                contract = field.get("validation")
                if contract:
                    _validate_contract(contract, issues, node_id=node.get("id"), output=field.get("name"))
                    _validate_start_type(contract, field, issues, node.get("id"))
    return issues


def _validate_contract(contract: dict, issues: list[ErrorDetail], **params) -> None:
    if not isinstance(contract, dict):
        issues.append(_detail("validation_contract_invalid", **params)); return
    fmt = contract.get("format")
    allowed = {"format", "json_schema", "rules_code"}
    if set(contract) - allowed:
        issues.append(_detail("validation_option_invalid", **params))
    if fmt in {"text", "markdown"}:
        if "json_schema" in contract or "rules_code" in contract:
            issues.append(_detail("validation_forbidden_property", **params))
        return
    if fmt not in {"json", "yaml"}:
        issues.append(_detail("validation_format_invalid", **params)); return
    if fmt == "yaml" and "json_schema" in contract:
        issues.append(_detail("validation_forbidden_property", **params))
    schema = contract.get("json_schema")
    if schema is not None:
        if fmt != "json" or not isinstance(schema, (dict, bool)):
            issues.append(_detail("validation_schema_invalid", **params))
        else:
            try:
                validator = validator_for(schema)
                if validator.META_SCHEMA.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                    issues.append(_detail("validation_schema_draft_invalid", **params))
                validator.check_schema(schema)
                if _has_remote_ref(schema):
                    issues.append(_detail("validation_remote_ref_forbidden", **params))
            except (jsonschema.SchemaError, TypeError, ValueError):
                issues.append(_detail("validation_schema_invalid", **params))
    code = contract.get("rules_code")
    if code is not None:
        if not isinstance(code, str):
            issues.append(_detail("validation_rules_invalid", **params))
        else:
            try:
                ast.parse("def __rule__(value, content):\n" + "\n".join("    " + line for line in code.splitlines()), mode="exec")
            except (SyntaxError, ValueError, TypeError):
                issues.append(_detail("validation_rules_invalid", **params))


def _has_remote_ref(value) -> bool:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            return True
        return any(_has_remote_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_remote_ref(item) for item in value)
    return False


def _validate_start_type(contract, field, issues, node_id) -> None:
    if field.get("type") == "string":
        return
    schema = contract.get("json_schema") if contract.get("format") == "json" else None
    expected = "integer" if field.get("type") == "number" else "boolean"
    schema_type = schema.get("type") if isinstance(schema, dict) else None
    compatible = schema is None or schema_type in ({"number", "integer"} if expected == "integer" else {"boolean"})
    if not compatible:
        issues.append(_detail("validation_start_type_incompatible", node_id=node_id, field=field.get("name")))


def inventory_output_validation_records(records: list[dict]) -> list[dict]:
    """Read-only, path-specific inventory of definitions needing contract repair."""
    report = []
    for record in records:
        definition = record.get("definition", {})
        legacy_paths = _legacy_catalogue_paths(definition)
        try:
            normalized, _ = normalize_validation_contracts(definition)
            issues = validate_output_validation_catalogue(normalized)
        except ValueError:
            issues = [_detail("output_validation_conflict", record_id=record.get("id"))]
        if issues or legacy_paths:
            report.append({"id": record.get("id"), "issues": [issue.message_key for issue in issues],
                           "legacy_catalogue_paths": legacy_paths,
                           "repair_required": bool(issues or legacy_paths)})
    return report


def _legacy_catalogue_paths(definition: dict) -> list[dict]:
    """Identify legacy levels contracts without mutating or interpreting them."""
    found = []
    for node_index, node in enumerate(definition.get("nodes", [])):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        for output, contract in (node.get("output_validation") or {}).items():
            if isinstance(contract, dict) and "levels" in contract:
                found.append({"path": f"nodes[{node_index}].output_validation.{output}",
                              "node_id": node_id, "output": output,
                              "reason": "legacy_levels_requires_explicit_repair"})
        for field_index, field in enumerate(node.get("input_form", [])):
            contract = field.get("validation") if isinstance(field, dict) else None
            if isinstance(contract, dict) and "levels" in contract:
                found.append({"path": f"nodes[{node_index}].input_form[{field_index}].validation",
                              "node_id": node_id, "output": field.get("name"),
                              "reason": "legacy_levels_requires_explicit_repair"})
    return found


def validate_workflow(definition: WorkflowDefinition, workflow_exists: Callable[[str], bool] | None = None,
                      workflow_contract: Callable[[str], tuple[list[str], list[str]] | None] | None = None) -> None:
    try:
        raw_definition = definition.model_dump(mode="json", exclude_none=True)
    except TypeError:
        # Defensive support for deliberately model_construct-created instances
        # in tests and old in-memory integrations.
        raw_definition = definition.__dict__
    raw, repair = normalize_validation_contracts(raw_definition)
    issues: list[ErrorDetail] = [_detail("legacy_validation_repair_required", path=item["path"]) for item in repair]
    issues.extend(validate_output_validation_catalogue(raw))
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
        declared = output_map.get(node.id, [])
        for output in (getattr(node, "output_validation", None) or {}):
            if output not in declared:
                issues.append(_detail("output_validation_orphan", node_id=node.id, output=output))
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
