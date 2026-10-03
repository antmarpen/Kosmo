import json

import asyncio

from worker.activities.ai_node import orchestrate_ai_node
from worker.activities.validation import validate_outputs
from shared.agent_events import CompletionProposed, InputRequested


class FakeAdapter:
    def __init__(self, proposals):
        self.proposals = proposals
        self.feedback = []
        self.prompts = []
        self.cycles = 0
        self.answers = []
        self.session_starts = 0

    async def start_session(self, cfg):
        self.session_starts += 1
        return None

    async def send_prompt(self, text):
        self.prompts.append(text)

    async def events(self):
        yield CompletionProposed()

    async def request_completion(self, expected_artifacts):
        proposal = self.proposals[self.cycles]
        self.cycles += 1
        return proposal

    async def deliver_feedback(self, errors):
        self.feedback.append(errors)

    async def deliver_answer(self, answer, request_id=None):
        self.answers.append(answer)

    async def collect_artifacts(self):
        return {}


def test_ai_node_persists_validated_output_and_checkpoint(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "summary.md").write_text("valid", encoding="utf-8")
    adapter = FakeAdapter([{"summary.md": {"path": str(output / "summary.md"), "media_type": "text/markdown"}}])
    effects = []

    async def persist(name, source, attempt):
        effects.append(("artifact", name, attempt))
        return {"id": "art-1", "sha256": "abc", "storage_path": source["path"], "media_type": "text/markdown"}

    async def note(key, params):
        effects.append((key, params))

    async def checkpoint(record):
        effects.append(("checkpoint", record))

    result = asyncio.run(orchestrate_ai_node(
        {"id": "ai1", "agent": {"instructions": "do it"}, "inputs": ["report.md"], "prompt_template": "task prompt",
         "outputs": ["summary.md"], "validation": {"levels": [
             {"name": "format", "message_key": "v.format", "params_schema": {}},
             {"name": "schema", "message_key": "v.schema", "params_schema": {}},
             {"name": "business", "message_key": "v.business", "params_schema": {}},
         ]}, "max_validation_cycles": 3},
        adapter, output, "task1", persist, note, checkpoint,
    ))
    assert result["state"] == "success"
    assert [entry[0] for entry in effects] == ["artifact", "checkpoint", "tasks.notes.validation_passed"]
    assert adapter.cycles == 1
    assert adapter.session_starts == 1
    assert "do it" in adapter.prompts[0] and "summary.md (text/markdown)" in adapter.prompts[0]
    assert "/workspace/inputs/report.md" in adapter.prompts[0]


def test_ai_executor_rejects_unsupported_runtime_with_keyed_error():
    from worker.activities.ai_node import run_ai_node
    result = asyncio.run(run_ai_node({"task_id": "task", "node": {"id": "ai", "agent": {"runtime": "claude"}, "outputs": []}}))
    assert result["state"] == "failed"
    assert result["error"] == {"code": "EXECUTOR_NOT_SUPPORTED", "message_key": "errors.executor.not_registered", "params": {"type": "claude"}}


def test_ai_input_staging_accepts_direct_start_value_and_artifact_reference(tmp_path):
    from worker.activities.agent import stage_agent_inputs
    artifact = tmp_path / "source.md"
    artifact.write_text("artifact body", encoding="utf-8")
    env = stage_agent_inputs({"prompt": "direct value", "report.md": {"storage_path": str(artifact)}}, tmp_path / "workspace")
    workspace = tmp_path / "workspace" / "inputs"
    assert (workspace / "prompt").read_text(encoding="utf-8") == '"direct value"'
    assert (workspace / "report.md").read_text(encoding="utf-8") == "artifact body"
    assert env["KOSMO_INPUT_ARTIFACT_PROMPT"] == "/workspace/inputs/prompt"


def test_ai_node_stops_after_three_failed_validation_cycles(tmp_path):
    adapter = FakeAdapter([{}, {}, {}])
    notes = []

    async def noop(*args):
        return None

    async def persist(*args):
        return {"sha256": "abc"}

    async def note(key, params):
        notes.append((key, params))

    node = {"id": "ai1", "agent": {}, "prompt_template": "p", "outputs": ["summary.md"],
            "validation": {"levels": [{"name": str(i), "message_key": f"v.{i}", "params_schema": {}} for i in range(3)]},
            "max_validation_cycles": 3}
    result = asyncio.run(orchestrate_ai_node(node, adapter, tmp_path, "task1", noop, note, noop))
    assert result["state"] == "failed"
    assert adapter.cycles == 3
    assert len(notes) == 3
    assert all(note[0] == "tasks.notes.validation_failed" for note in notes)
    assert result["error"]["message_key"] == "errors.node.validation_exhausted"
    assert len(result["error"]["details"]) == 3
    assert result["error"]["params"] == {"node": "ai1", "attempts": 3}
    assert all(entry["message_key"] == "v.0" and entry["attempt"] in (1, 2, 3) for entry in result["error"]["details"])
    assert "Traceback" not in str(result["error"])


def test_ai_node_surfaces_input_request_and_delivers_answer_before_completion(tmp_path):
    class InputAdapter(FakeAdapter):
        async def events(self):
            yield InputRequested("agent.question", {"field": "confirm"}, 101, "session/request_permission")
            yield CompletionProposed()

    output = tmp_path / "summary.md"
    output.write_text("okay", encoding="utf-8")
    adapter = InputAdapter([{"summary.md": {"path": str(output), "media_type": "text/markdown"}}])
    delivered = []

    async def answer(key, params, adapter, request_id, request_key):
        delivered.append((key, params, request_id, request_key))
        await adapter.deliver_answer("approved", request_id)

    async def noop(*args):
        return None

    async def persist(*args):
        return {"sha256": "abc"}

    node = {"id": "ai1", "agent": {}, "outputs": ["summary.md"], "validation": {"levels": [
        {"name": str(i), "message_key": f"v.{i}", "params_schema": {}} for i in range(3)
    ]}}
    asyncio.run(orchestrate_ai_node(node, adapter, tmp_path, "task1", persist, noop, noop, answer))
    assert delivered == [("agent.question", {"field": "confirm"}, 101, "101")]
    assert adapter.answers == ["approved"]


def test_human_wait_cancellation_exits_ai_orchestration(tmp_path):
    class InputAdapter(FakeAdapter):
        async def events(self):
            yield InputRequested("agent.question", {}, 1, "session/request")
            yield CompletionProposed()

    adapter = InputAdapter([{}])
    async def cancelled(*args):
        return True
    async def noop(*args):
        return None
    node = {"id": "ai1", "agent": {}, "outputs": ["out.md"], "validation": {"levels": [
        {"name": str(i), "message_key": f"v.{i}", "params_schema": {}} for i in range(3)
    ]}}
    result = asyncio.run(orchestrate_ai_node(node, adapter, tmp_path, "task", noop, noop, noop, cancelled))
    assert result["state"] == "stopped"
    assert adapter.cycles == 0


def test_missing_declared_output_is_reported_as_level_one_error(tmp_path):
    errors = validate_outputs(
        {"summary.md": {"media_type": "text/markdown"}},
        tmp_path,
        {"levels": [
            {"name": "format", "message_key": "validation.format", "params_schema": {}},
            {"name": "schema", "message_key": "validation.schema", "params_schema": {}},
            {"name": "business", "message_key": "validation.business", "params_schema": {}},
        ]},
    )
    assert errors == [{
        "artifact": "summary.md", "level": "format",
        "message_key": "validation.format", "params": {"reason": "missing"},
    }]


def test_json_output_is_parsed_and_valid_output_has_no_errors(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    contract = {"levels": [
        {"name": "format", "message_key": "validation.format", "params_schema": {}},
        {"name": "schema", "message_key": "validation.schema", "params_schema": {}},
        {"name": "business", "message_key": "validation.business", "params_schema": {}},
    ]}
    assert validate_outputs({"summary.json": {"media_type": "application/json"}}, tmp_path, contract) == []


def test_validation_forcing_flag_fails_level_one_deterministically(tmp_path, monkeypatch):
    (tmp_path / "summary.md").write_text("valid", encoding="utf-8")
    monkeypatch.setenv("KOSMO_E2E_FAIL_VALIDATION", "1")
    contract = {"levels": [
        {"name": "format", "message_key": "v.format", "params_schema": {}},
        {"name": "schema", "message_key": "v.schema", "params_schema": {}},
        {"name": "business", "message_key": "v.business", "params_schema": {}},
    ]}
    errors = validate_outputs({"summary.md": {"media_type": "text/markdown"}}, tmp_path, contract)
    assert errors[0]["message_key"] == "v.format"
    assert errors[0]["params"]["reason"] == "forced"


def test_seeded_markdown_sections_and_supported_claims_are_enforced(tmp_path):
    from scripts.seed import reference_workflow_definition
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    (tmp_path / "summary.md").write_text("An unrelated claim about Atlantis.", encoding="utf-8")
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "report.md").write_text("# Security analysis\n\n## Findings\n- Review supplied topic.\n", encoding="utf-8")
    errors = validate_outputs({"summary.md": {"media_type": "text/markdown"}}, tmp_path,
                              node.validation.model_dump(), inputs=["report.md"])
    assert [(e["level"], e["params"]["reason"]) for e in errors] == [
        ("required_sections", "required_sections_missing"),
        ("content_rule", "unsupported_claim"),
    ]
    assert errors[0]["params"]["sections"] == ["Overview", "Findings", "Recommendations"]
    assert errors[1]["params"]["input_artifact"] == "report.md"


def test_seeded_validator_uses_staged_inputs_and_checks_each_sentence(tmp_path):
    from scripts.seed import reference_workflow_definition
    from app.domain.workflows.validation_logic import validate_outputs as canonical
    from worker.activities.validation import validate_outputs as compatibility
    assert canonical is compatibility
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "report.md").write_text("Security analysis reviews supplied topic and findings.", encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("## Overview\nSecurity analysis reviews findings.\n## Findings\nReview supplied topic.\n## Recommendations\nAtlantis discovered.", encoding="utf-8")
    errors = canonical({"summary.md": {"media_type": "text/markdown"}}, tmp_path, node.validation.model_dump(), inputs=["report.md"])
    assert [(error["level"], error["params"]["reason"]) for error in errors] == [("content_rule", "unsupported_claim")]
    assert errors[0]["params"]["claims"] == ["Atlantis discovered."]


def test_seeded_validator_reports_absent_staged_source(tmp_path):
    from scripts.seed import reference_workflow_definition
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    (tmp_path / "summary.md").write_text("## Overview\nSecurity analysis.\n## Findings\nReview findings.\n## Recommendations\nReview topic.", encoding="utf-8")
    errors = validate_outputs({"summary.md": {"media_type": "text/markdown"}}, tmp_path, node.validation.model_dump(), inputs=["report.md"])
    assert len(errors) == 1
    assert errors[0]["params"] == {"reason": "source_artifact_missing", "input_artifact": "report.md"}


def test_validation_failures_are_flat_attempt_details_and_feedback_is_structured(tmp_path):
    adapter = FakeAdapter([{}, {}, {}])
    notes = []
    async def noop(*args): return None
    async def note(key, params): notes.append((key, params))
    node = {"id": "ai1", "agent": {}, "outputs": ["summary.md"], "inputs": [],
            "validation": {"levels": [{"name": str(i), "message_key": f"v.{i}", "params_schema": {}} for i in range(3)]}}
    result = asyncio.run(orchestrate_ai_node(node, adapter, tmp_path, "task1", noop, note, noop))
    assert len(result["error"]["details"]) == 3
    assert all(set(d) == {"attempt", "level", "artifact", "message_key", "params"} for d in result["error"]["details"])
    assert all("errors" not in entry for entry in adapter.feedback[0])
    assert all("details" in params for _, params in notes)
