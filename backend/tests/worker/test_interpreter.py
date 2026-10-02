from worker.interpreter import interpret


def test_flat_graph_uses_dependency_order_and_implicit_phase():
    graph = {"nodes": [{"type": "start", "id": "s"}, {"type": "end", "id": "e"}], "edges": [{"from": "s", "to": "e"}], "phases": None}
    visited = []

    def run_node(node, ctx):
        visited.append(node["id"])
        return {"state": "success", "outputs": {}, "error": None}

    result = interpret(graph, {}, run_node)
    assert visited == ["s", "e"]
    assert result["state"] == "success"


def test_unregistered_node_type_returns_structured_failure():
    graph = {"nodes": [{"type": "alien", "id": "x"}], "edges": [], "phases": None}
    result = interpret(graph, {}, lambda node, ctx: None)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "EXECUTOR_NOT_REGISTERED"


def test_decision_and_workflow_nodes_are_not_executable():
    for kind in ("decision", "workflow"):
        graph = {"nodes": [{"type": kind, "id": "new-node"}], "edges": [], "phases": None}
        result = interpret(graph, {}, lambda node, ctx: None)
        assert result["state"] == "failed"
        assert result["error"]["code"] == "EXECUTOR_NOT_REGISTERED"
        assert result["error"]["params"]["type"] == kind


def test_http_node_reaches_executor_dispatch_and_is_reported_unsupported():
    """HTTP nodes are not executable: the dispatch must keep failing them structurally."""
    import asyncio

    from worker.activities.tasks import run_node

    result = asyncio.run(run_node(("task-1", {"type": "http", "id": "http"}, {})))
    assert result["state"] == "failed"
    assert result["error"]["code"] == "EXECUTOR_NOT_REGISTERED"
    assert result["error"]["message_key"] == "errors.executor.not_registered"
    assert result["error"]["params"]["type"] == "http"


def test_node_failure_stops_walk_and_returns_failed_state():
    graph = {"nodes": [{"type": "script", "id": "work"}], "edges": [], "phases": None}
    result = interpret(graph, {}, lambda node, ctx: {"state": "failed", "error": {"code": "SCRIPT_ERROR"}})
    assert result["state"] == "failed"
    assert result["error"]["code"] == "SCRIPT_ERROR"


def test_resolve_declared_node_inputs_from_interpreter_context():
    from worker.interpreter import resolve_declared_inputs

    artifact = {"storage_path": "/var/lib/kosmo/tasks/task/artifacts/collect/report.md"}
    assert resolve_declared_inputs(["report.md"], {"topic": "test", "report.md": artifact}) == {"report.md": artifact}


def test_resolve_declared_node_inputs_reports_missing_predecessor_output():
    import pytest
    from worker.interpreter import resolve_declared_inputs

    with pytest.raises(KeyError, match="report.md"):
        resolve_declared_inputs(["report.md"], {"topic": "test"})
