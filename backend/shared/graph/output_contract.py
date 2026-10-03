"""Compatibility normalization for node output validation contracts."""

from copy import deepcopy
from typing import Any


def normalize_output_validation(definition: dict[str, Any]) -> dict[str, Any]:
    """Return a copied definition with legacy AI validation moved per output.

    An AI node with no outputs keeps its legacy field intact as draft content;
    this deterministic exception avoids discarding a contract before outputs
    are authored. The schema accepts that field for parsing, but excludes it
    from canonical serialization.
    """
    normalized = deepcopy(definition)
    nodes = normalized.get("nodes")
    if not isinstance(nodes, list):
        return normalized
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "ai" or "validation" not in node:
            continue
        if "output_validation" in node:
            raise ValueError("errors.graph.output_validation_conflict")
        outputs = node.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            continue
        legacy = node["validation"]
        node["output_validation"] = {name: deepcopy(legacy) for name in outputs if isinstance(name, str)}
        del node["validation"]
    return normalized
