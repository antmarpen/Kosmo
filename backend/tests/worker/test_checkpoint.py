import asyncio
import json

import pytest

from shared.checkpoint import Checkpoint, is_execution_completed
from worker.activities.checkpoint import (checkpoint_path, publish_completion, reconcile_artifact_completions,
                                          valid_artifact_group, validate_checkpoint_references,
                                          publish_completion_if_current)


def record(node_id="script", iteration=0, digest="abc"):
    return {
        "attempt": 1,
        "outputs": {"report.md": {"storage_path": "/artifacts/report.md", "sha256": digest}},
        "artifact_hashes": {"report.md": digest},
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }


def test_checkpoint_schema_roundtrip():
    checkpoint = Checkpoint(task_id="task", version=1, completed={"script:0": record()})
    assert Checkpoint.model_validate_json(checkpoint.model_dump_json()) == checkpoint


def test_loaded_checkpoint_marks_node_for_skip():
    checkpoint = Checkpoint(task_id="task", version=2, completed={"script:0": record()}).model_dump(mode="json")
    assert is_execution_completed(checkpoint, "script")
    assert not is_execution_completed(checkpoint, "other")


def test_replace_failure_leaves_previous_checkpoint_valid(tmp_path, monkeypatch):
    old = Checkpoint(task_id="task", version=1).model_dump(mode="json")
    path = checkpoint_path("task", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old))
    import worker.activities.checkpoint as activity_module

    def crash_before_replace(source, destination):
        raise OSError("simulated crash")

    monkeypatch.setattr(activity_module.os, "replace", crash_before_replace)
    with pytest.raises(OSError, match="simulated crash"):
        activity_module.write_checkpoint(path, Checkpoint(task_id="task", version=1, completed={"script:0": record()}))
    assert Checkpoint.model_validate_json(path.read_text()) == Checkpoint(task_id="task", version=1)


@pytest.mark.asyncio
async def test_sequential_completion_records_are_deduplicated(tmp_path):
    for i in range(12):
        await publish_completion({"task_id": "task", "completion": {"node_id": f"node{i}", "iteration": 0, **record()}}, storage_root=tmp_path)
    await publish_completion({"task_id": "task", "completion": {"node_id": "node0", "iteration": 0, **record()}}, storage_root=tmp_path)
    saved = Checkpoint.model_validate_json(checkpoint_path("task", tmp_path).read_text())
    assert len(saved.completed) == 12
    assert set(saved.completed) == {f"node{i}:0" for i in range(12)}


def test_artifact_recovery_reconciles_missing_entry_without_reexecution():
    checkpoint = Checkpoint(task_id="task", version=1)
    artifacts = [{"node_id": "script", "iteration": 0, "attempt": 1,
                  "outputs": {"report.md": {"storage_path": "/volume/report.md", "sha256": "abc"}},
                  "artifact_hashes": {"report.md": "abc"}}]
    executions = 1  # The sandbox already ran before its artifacts were persisted.
    reconcile_artifact_completions(checkpoint, artifacts)
    reconcile_artifact_completions(checkpoint, artifacts)
    if "script:0" not in checkpoint.completed:
        executions += 1
    assert executions == 1
    assert checkpoint.completed["script:0"].artifact_hashes == {"report.md": "abc"}


def test_partial_artifact_group_is_not_complete():
    group = {"report.md": {"storage_path": "unused", "sha256": "x"}}
    assert not valid_artifact_group(group, ["report.md", "data.json"])


def test_artifact_group_requires_matching_content_hash(tmp_path):
    path = tmp_path / "report.md"
    path.write_text("actual")
    group = {"report.md": {"storage_path": str(path), "sha256": "wrong"}}
    assert not valid_artifact_group(group, ["report.md"])


def test_invalid_checkpoint_reference_is_removed_for_reexecution(tmp_path):
    checkpoint = Checkpoint(task_id="task", version=4, completed={"script:0": record()})
    validate_checkpoint_references(checkpoint)
    assert "script:0" not in checkpoint.completed


def test_stale_writer_cannot_replace_new_checkpoint(tmp_path):
    from worker.activities.checkpoint import read_checkpoint
    path = checkpoint_path("task", tmp_path)
    current = Checkpoint(task_id="task", version=3, completed={"newer:0": record()})
    write = __import__("worker.activities.checkpoint", fromlist=["write_checkpoint"]).write_checkpoint
    write(path, current)
    stale = Checkpoint(task_id="task", version=2)
    with pytest.raises(ValueError, match="Stale checkpoint writer"):
        publish_completion_if_current(path, stale, {"node_id": "old", **record()})
    assert read_checkpoint(path).version == 3


def test_activity_retry_uses_durable_result_without_running_again(tmp_path):
    from worker.activities.checkpoint import durable_execution_result
    runs = 0

    artifact = tmp_path / "report.md"
    artifact.write_text("actual")
    import hashlib

    def execute():
        nonlocal runs
        runs += 1
        return {"state": "success", "outputs": {"report.md": {"storage_path": str(artifact), "sha256": hashlib.sha256(b"actual").hexdigest()}}}

    durable = execute()
    result = durable_execution_result(durable["outputs"], ["report.md"])
    assert result["outputs"] == durable["outputs"]
    assert runs == 1
