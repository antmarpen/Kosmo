"""Pure deterministic flat-graph interpreter; persistence is delegated to callers."""

from shared.execution import KosmoErrorData, NodeResult


def topological_nodes(definition):
    nodes = {node["id"]: node for node in definition["nodes"]}
    edges = definition.get("edges", [])
    incoming = {node_id: 0 for node_id in nodes}
    outgoing = {node_id: [] for node_id in nodes}
    for edge in edges:
        source = edge.get("from", edge.get("from_node"))
        target = edge["to"]
        outgoing[source].append(target)
        incoming[target] += 1
    # Preserve definition order among independent nodes for stable replay.
    ordered = []
    ready = [node["id"] for node in definition["nodes"] if incoming[node["id"]] == 0]
    while ready:
        node_id = ready.pop(0)
        ordered.append(nodes[node_id])
        for target in outgoing[node_id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if len(ordered) != len(nodes):
        return []
    return ordered


def resolve_declared_inputs(names, context):
    """Select declared node inputs from deterministic predecessor context."""
    missing = [name for name in names if name not in context]
    if missing:
        raise KeyError(", ".join(missing))
    return {name: context[name] for name in names}


def interpret(definition, context, run_node, completed=None):
    completed = completed or set()
    for node in topological_nodes(definition):
        if node["id"] in completed:
            continue
        kind = node.get("type")
        if kind not in {"start", "end", "script", "http", "ai"}:
            return {"state": "failed", "node_id": node["id"], "error": {"code": "EXECUTOR_NOT_REGISTERED", "message_key": "errors.executor.not_registered", "params": {"type": kind}}}
        result = run_node(node, context)
        state = result.get("state") if isinstance(result, dict) else result.state
        if state != "success":
            error = result.get("error") if isinstance(result, dict) else result.error
            if hasattr(error, "__dict__"):
                error = error.__dict__
            return {"state": "failed", "node_id": node["id"], "error": error or {"code": "NODE_FAILED", "message_key": "errors.task.node_failed", "params": {}}}
    return {"state": "success"}
