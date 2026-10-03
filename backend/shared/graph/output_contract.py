"""Non-destructive normalization for historical output validation contracts.

Legacy ``levels`` support is deliberately isolated here; persisted versions and
task snapshots are never rewritten by this function.
"""
from copy import deepcopy
from typing import Any

REPAIR_KEY = "errors.graph.legacy_validation_repair_required"
CONFLICT_KEY = "errors.graph.output_validation_conflict"


def _convert_legacy(contract: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(contract, dict) or not isinstance(contract.get("levels"), list):
        return None, REPAIR_KEY
    levels = contract["levels"]
    try:
        parse = levels[0]["params_schema"]
        structure = levels[1]["params_schema"]
        rules = levels[2]["params_schema"]
        fmt = parse.get("format")
        if set(parse) != {"format"}:
            return None, REPAIR_KEY
        if fmt not in {"text", "markdown", "json", "yaml"}:
            return None, REPAIR_KEY
        if fmt in {"text", "markdown"}:
            if any(structure.values()) or any(rules.values()):
                return None, REPAIR_KEY
            return {"format": fmt}, None
        output: dict[str, Any] = {"format": fmt}
        required = structure.get("required_keys")
        if required:
            if fmt != "json" or not isinstance(required, list) or not all(isinstance(k, str) for k in required):
                return None, REPAIR_KEY
            output["json_schema"] = {"type": "object", "required": required}
        elif structure:
            return None, REPAIR_KEY
        if rules:
            return None, REPAIR_KEY
        return output, None
    except (IndexError, KeyError, TypeError, AttributeError):
        return None, REPAIR_KEY


def normalize_validation_contracts(definition: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Deep-copy a definition, converting provably equivalent legacy contracts.

    Returns ``(definition, keyed_issues)``. Unconvertible legacy data remains
    byte-for-byte structurally intact and is accompanied by a repair issue.
    """
    normalized = deepcopy(definition)
    issues: list[dict[str, str]] = []
    nodes = normalized.get("nodes")
    if not isinstance(nodes, list):
        return normalized, issues
    for ni, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        path = f"nodes.{ni}"
        if "output_validation" in node and isinstance(node["output_validation"], dict):
            for name, contract in list(node["output_validation"].items()):
                if isinstance(contract, dict) and "levels" in contract:
                    converted, issue = _convert_legacy(contract)
                    if converted is None:
                        issues.append({"key": issue or REPAIR_KEY, "path": f"{path}.output_validation.{name}"})
                    else:
                        node["output_validation"][name] = converted
        if node.get("type") == "ai" and "validation" in node:
            if "output_validation" in node:
                issues.append({"key": CONFLICT_KEY, "path": f"{path}.validation"})
                continue
            outputs = node.get("outputs")
            legacy = node["validation"]
            if not isinstance(outputs, list) or not outputs:
                issues.append({"key": REPAIR_KEY, "path": f"{path}.validation"})
                continue
            converted, issue = _convert_legacy(legacy)
            if converted is None:
                issues.append({"key": issue or REPAIR_KEY, "path": f"{path}.validation"})
                continue
            node["output_validation"] = {name: deepcopy(converted) for name in outputs if isinstance(name, str)}
            del node["validation"]
    return normalized, issues


def normalize_output_validation(definition: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper; use the issues-returning API for repair handling."""
    return normalize_validation_contracts(definition)[0]
