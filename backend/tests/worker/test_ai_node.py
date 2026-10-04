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

    async def close(self):
        return None


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
        {"id": "ai1", "inputs": ["report.md"], "prompt_template": "task prompt",
         "outputs": ["summary.md"], "validation": {"levels": [
             {"name": "format", "message_key": "v.format", "params_schema": {}},
             {"name": "schema", "message_key": "v.schema", "params_schema": {}},
             {"name": "business", "message_key": "v.business", "params_schema": {}},
         ]}, "max_validation_cycles": 3},
        adapter, output, "task1", persist, note, checkpoint,
        effective_config={"agent": {"instructions": "do it"}, "mcps": [], "skills": []},
    ))
    assert result["state"] == "success", result
    assert [entry[0] for entry in effects] == ["artifact", "checkpoint", "tasks.notes.validation_passed"]
    assert adapter.cycles == 1
    assert adapter.session_starts == 1
    assert "do it" in adapter.prompts[0] and "summary.md (text/markdown)" in adapter.prompts[0]
    assert "/workspace/inputs/report.md" in adapter.prompts[0]


def test_ai_node_delivers_full_effective_skill_sections_and_starts_with_resolved_agent(tmp_path):
    adapter = FakeAdapter([{}])
    async def noop(*args): return None
    async def persist(*args): return {"sha256": "abc"}
    effective = {"agent": {"model": "vendor/live", "reasoning_effort": "high", "instructions": "agent rules"},
                 "mcps": [], "skills": [
                     {"name": "Alpha", "description": "first skill", "instructions": "full alpha"},
                     {"name": "Beta", "description": "second skill", "instructions": "full beta"}]}
    result = asyncio.run(orchestrate_ai_node(
        {"id": "ai", "outputs": [], "prompt_template": "task prompt", "agent": {"instructions": "spoof"}},
        adapter, tmp_path, "task", persist, noop, noop, effective_config=effective))
    assert result["state"] == "success"
    assert adapter.session_starts == 1
    prompt = adapter.prompts[0]
    assert prompt.index("agent rules") < prompt.index("<skill name=\"Alpha\">") < prompt.index("full alpha")
    assert prompt.index("full alpha") < prompt.index("<skill name=\"Beta\">") < prompt.index("full beta") < prompt.index("task prompt")


def test_permission_request_secrets_are_redacted_before_note_persistence(tmp_path):
    class PermissionAdapter(FakeAdapter):
        async def events(self):
            yield InputRequested("agent.permission.requested", {"authorization": "CONFIGURED_SECRET"}, 7,
                                  "session/request_permission")
            yield CompletionProposed()
    adapter = PermissionAdapter([{}])
    effective = {"agent": {}, "mcps": [{"transport": {"type": "http"},
                  "headers": (("Authorization", "CONFIGURED_SECRET"),)}], "skills": []}
    persisted = []
    async def request_input(_key, params, *_args):
        persisted.append(params)
        return False
    async def noop(*_args): return None
    result = asyncio.run(orchestrate_ai_node({"id": "ai", "outputs": []}, adapter, tmp_path, "task",
        noop, noop, noop, request_input, effective_config=effective))
    assert result["state"] == "success"
    assert persisted == [{"authorization": "[REDACTED]"}]
    assert "CONFIGURED_SECRET" not in json.dumps(persisted)


def test_ai_executor_rejects_unsupported_runtime_with_keyed_error(monkeypatch):
    from worker.activities.ai_node import run_ai_node
    import app.core.db
    from app.domain.agents.resolution import AgentCatalogResolver
    class TaskRow:
        created_by = "creator"
        prompt = ""
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *_args): return TaskRow()
    monkeypatch.setattr(app.core.db, "AsyncSessionLocal", lambda: Session())
    from app.core.config import settings
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-secret-at-least-32-bytes")
    async def resolved(self, **kwargs):
        assert kwargs["created_by"] == "creator"
        return {"agent": {"runtime": "claude"}, "mcps": [], "skills": []}
    monkeypatch.setattr(AgentCatalogResolver, "resolve", resolved)
    import worker.activities.checkpoint as checkpoint
    async def not_recovered(*args): return None
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", not_recovered)
    result = asyncio.run(run_ai_node({"task_id": "task", "user_id": "spoofed", "node": {"id": "ai", "agent_id": "catalog-id", "outputs": []}}))
    assert result["state"] == "failed"
    assert result["error"] == {"code": "EXECUTOR_NOT_SUPPORTED", "message_key": "errors.executor.not_registered", "params": {"type": "claude"}}


def test_ai_recovery_returns_completed_artifact_without_live_catalog_resolution(monkeypatch):
    from worker.activities.ai_node import run_ai_node
    import worker.activities.checkpoint as checkpoint
    from app.domain.agents.resolution import AgentCatalogResolver
    recovered = {"state": "success", "outputs": {"out.md": {"id": "artifact"}}, "error": None}
    async def find(*args): return recovered
    async def must_not_resolve(*args, **kwargs): raise AssertionError("recovered node must not resolve catalog")
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", find)
    monkeypatch.setattr(AgentCatalogResolver, "resolve", must_not_resolve)
    result = asyncio.run(run_ai_node({"task_id": "task", "node": {"id": "ai", "agent_id": "deleted",
                                                                          "outputs": ["out.md"]}}))
    assert result == recovered


def test_ai_activity_fails_closed_when_platform_validator_cannot_be_installed(monkeypatch, tmp_path):
    from worker.activities.ai_node import run_ai_node
    import app.core.db
    import worker.activities.checkpoint as checkpoint
    from app.domain.agents.resolution import AgentCatalogResolver
    class TaskRow:
        created_by = "creator"
        prompt = ""
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *_args): return TaskRow()
    monkeypatch.setattr(app.core.db, "AsyncSessionLocal", lambda: Session())
    async def no_recovery(*args): return None
    async def resolve(self, **kwargs):
        return {"agent": {"runtime": "opencode", "model": "default", "instructions": ""}, "mcps": [], "skills": []}
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", no_recovery)
    monkeypatch.setattr(AgentCatalogResolver, "resolve", resolve)
    result = asyncio.run(run_ai_node({"task_id": "task", "workspace": str(tmp_path),
        "node": {"id": "ai", "agent_id": "agent", "outputs": []}}))
    assert result["state"] == "failed"
    assert result["error"]["code"] == "PLATFORM_VALIDATOR_UNAVAILABLE"


def test_ai_activity_resolves_fresh_consumer_catalog_and_merges_platform_validator(tmp_path, monkeypatch):
    from worker.activities.ai_node import run_ai_node
    import app.core.db
    from app.domain.agents.resolution import AgentCatalogResolver
    import worker.activities.checkpoint as checkpoint
    import worker.activities.ai_node as ai_node
    class TaskRow:
        created_by = "actual-creator"
        prompt = "task prompt"
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *_args): return TaskRow()
    monkeypatch.setattr(app.core.db, "AsyncSessionLocal", lambda: Session())
    from app.core.config import settings
    monkeypatch.setattr(settings, "jwt_secret", "test-validator-secret-at-least-32-bytes")
    async def not_recovered(*args): return None
    monkeypatch.setattr(checkpoint, "find_durable_artifact_result", not_recovered)
    seen = []
    live_model = ["vendor/updated"]
    async def resolve(self, *, created_by, node):
        seen.append((created_by, node["agent_id"]))
        return {"agent": {"runtime": "opencode", "model": live_model[0], "reasoning_effort": "high",
                           "instructions": "current instructions"},
                "mcps": [{"id": "m1", "name": "tools", "transport": {"type": "http", "url": "http://mcp",
                             "headers": [{"name": "X-Token", "secret": True}]},
                           "headers": (("X-Token", "CATALOG_SECRET"),)}],
                "skills": [{"name": "current-skill", "description": "desc", "instructions": "full skill"}]}
    monkeypatch.setattr(AgentCatalogResolver, "resolve", resolve)
    monkeypatch.setattr(ai_node, "_load_provider_runtime_config", lambda *_args: asyncio.sleep(0, result={}))
    async def no_note(*_args): return None
    monkeypatch.setattr(ai_node, "_add_task_note", no_note)
    started = {}
    started_models = []
    adapters = []
    async def start(cfg, workspace, **kwargs):
        started.update(cfg=cfg, kwargs=kwargs)
        started_models.append(cfg["model"])
        adapter = FakeAdapter([{}])
        adapters.append(adapter)
        return adapter
    import worker.activities.agent as agent
    monkeypatch.setattr(agent, "start_agent_session", start)
    monkeypatch.setattr(agent, "validator_mcp_server", lambda *_args: {"type": "http", "name": "kosmo-validator",
                                                                         "url": "http://validator", "headers": []})
    result = asyncio.run(run_ai_node({"task_id": "task", "user_id": "spoofed", "node_execution_id": "exec",
        "workspace": str(tmp_path), "node": {"id": "ai", "agent_id": "ref", "outputs": [],
        "prompt_template": "task-specific", "agent": {"instructions": "must not be used"}}}))
    assert result["state"] == "success", result
    assert seen == [("actual-creator", "ref")]
    assert started["cfg"]["model"] == "vendor/updated"
    assert "CATALOG_SECRET" in started["kwargs"]["diagnostic_secrets"]
    servers = started["kwargs"]["mcp_servers"]
    assert servers[0]["headers"] == (("X-Token", "CATALOG_SECRET"),)
    assert servers[-1]["name"] == "kosmo-validator"
    assert "current-skill" in adapters[0].prompts[0] and "full skill" in adapters[0].prompts[0]
    assert "must not be used" not in adapters[0].prompts[0]
    assert "CATALOG_SECRET" not in json.dumps(result)
    live_model[0] = "vendor/retry-updated"
    retry = asyncio.run(run_ai_node({"task_id": "task", "user_id": "spoofed", "node_execution_id": "exec",
        "workspace": str(tmp_path), "node": {"id": "ai", "agent_id": "ref", "outputs": [],
        "prompt_template": "task-specific", "agent": {"instructions": "must not be used"}}}))
    assert retry["state"] == "success"
    assert started_models == ["vendor/updated", "vendor/retry-updated"]


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


def test_seeded_markdown_contract_is_parse_only(tmp_path):
    from scripts.seed import reference_workflow_definition
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    (tmp_path / "summary.md").write_text("An unrelated claim about Atlantis.", encoding="utf-8")
    errors = validate_outputs({"summary.md": {"media_type": "text/markdown"}}, tmp_path,
                              node.output_validation["summary.md"].model_dump())
    assert errors == []


def test_seeded_validator_does_not_apply_obsolete_claim_rules(tmp_path):
    from scripts.seed import reference_workflow_definition
    from app.domain.workflows.validation_logic import validate_outputs as canonical
    from worker.activities.validation import validate_outputs as compatibility
    assert canonical is compatibility
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    summary = tmp_path / "summary.md"
    summary.write_text("## Overview\nSecurity analysis reviews findings.\n## Findings\nReview supplied topic.\n## Recommendations\nAtlantis discovered.", encoding="utf-8")
    errors = canonical({"summary.md": {"media_type": "text/markdown"}}, tmp_path, node.output_validation["summary.md"].model_dump())
    assert errors == []


def test_seeded_validator_accepts_summary_without_legacy_staged_source(tmp_path):
    from scripts.seed import reference_workflow_definition
    node = next(n for n in reference_workflow_definition().nodes if n.type == "ai")
    (tmp_path / "summary.md").write_text("## Overview\nSecurity analysis.\n## Findings\nReview findings.\n## Recommendations\nReview topic.", encoding="utf-8")
    errors = validate_outputs({"summary.md": {"media_type": "text/markdown"}}, tmp_path, node.output_validation["summary.md"].model_dump())
    assert errors == []


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


def test_ai_node_prompts_and_validates_contract_per_output(tmp_path):
    (tmp_path / "one.md").write_text("present", encoding="utf-8")
    (tmp_path / "two.md").write_text("present", encoding="utf-8")
    adapter = FakeAdapter([{
        "one.md": {"path": str(tmp_path / "one.md"), "media_type": "text/markdown"},
        "two.md": {"path": str(tmp_path / "two.md"), "media_type": "text/markdown"},
    }])
    contracts = {
        "one.md": {"levels": [{"name": f"one-{i}", "message_key": f"one.{i}", "params_schema": {}} for i in range(3)]},
        "two.md": {"levels": [{"name": f"two-{i}", "message_key": f"two.{i}", "params_schema": {}} for i in range(3)]},
    }
    async def noop(*args): return None
    async def persist(*args): return {"sha256": "abc"}
    result = asyncio.run(orchestrate_ai_node(
        {"id": "ai", "agent": {}, "outputs": ["one.md", "two.md"], "output_validation": contracts},
        adapter, tmp_path, "task", persist, noop, noop,
    ))
    assert result["state"] == "success"
    assert json.dumps(contracts, sort_keys=True) in adapter.prompts[0]


def test_ai_missing_outputs_fail_even_without_validation_contract(tmp_path):
    adapter = FakeAdapter([{}, {}, {}])
    writes = []
    async def persist(*args): writes.append("persist")
    async def checkpoint(*args): writes.append("checkpoint")
    async def noop(*args): return None
    result = asyncio.run(orchestrate_ai_node(
        {"id": "ai", "agent": {}, "outputs": ["required.md"]}, adapter,
        tmp_path, "task", persist, noop, checkpoint,
    ))
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VALIDATION_EXHAUSTED"
    assert result["error"]["details"][0]["artifact"] == "required.md"
    assert result["error"]["details"][0]["params"]["reason"] == "missing"
    assert writes == []


def test_ai_runs_shared_validation_before_persisting_new_contract_outputs(tmp_path, monkeypatch):
    import worker.activities.ai_node as module
    candidate = tmp_path / "out.json"
    candidate.write_text('{"ok": false}', encoding="utf-8")
    proposal = {"out.json": {"path": str(candidate), "media_type": "application/json"}}
    adapter = FakeAdapter([proposal, proposal, proposal])
    effects = []

    async def validate(outputs, workspace, contracts, *, inputs=None):
        effects.append("validate")
        assert outputs["out.json"]["media_type"] == "application/json"
        return [{"artifact": "out.json", "level": "schema", "message_key": "validation.schema", "params": {"reason": "invalid"}}]

    monkeypatch.setattr(module, "validate_outputs_async", validate)
    async def persist(*args): effects.append("persist")
    async def checkpoint(*args): effects.append("checkpoint")
    async def note(*args): pass
    result = asyncio.run(module.orchestrate_ai_node(
        {"id": "ai", "agent": {}, "outputs": ["out.json"], "output_validation": {"out.json": {"format": "json"}}},
        adapter, tmp_path, "task", persist, note, checkpoint,
    ))
    assert result["error"]["code"] == "VALIDATION_EXHAUSTED"
    assert effects == ["validate"] * 3
    assert all(error["artifact"] == "out.json" for batch in adapter.feedback for error in batch)


def test_ai_feedback_only_contains_failing_output_errors(tmp_path):
    (tmp_path / "one.md").write_text("present", encoding="utf-8")
    proposal = {
        "one.md": {"path": str(tmp_path / "one.md"), "media_type": "text/markdown"},
        "two.md": {"path": str(tmp_path / "two.md"), "media_type": "text/markdown"},
    }
    adapter = FakeAdapter([proposal, proposal, proposal])
    contracts = {name: {"levels": [{"name": name, "message_key": name, "params_schema": {}} for _ in range(3)]}
                 for name in ("one.md", "two.md")}
    async def noop(*args): return None
    async def persist(*args): return {"sha256": "abc"}
    result = asyncio.run(orchestrate_ai_node(
        {"id": "ai", "agent": {}, "outputs": ["one.md", "two.md"], "output_validation": contracts},
        adapter, tmp_path, "task", persist, noop, noop,
    ))
    assert result["state"] == "failed"
    assert {error["artifact"] for error in adapter.feedback[0]} == {"two.md"}


def test_ai_legacy_snapshot_normalizes_node_validation_without_mutating_node(tmp_path):
    (tmp_path / "legacy.md").write_text("valid", encoding="utf-8")
    contract = {"levels": [{"name": str(i), "message_key": f"v.{i}", "params_schema": {}} for i in range(3)]}
    node = {"id": "ai", "agent": {}, "outputs": ["legacy.md"], "validation": contract}
    original = json.loads(json.dumps(node))
    adapter = FakeAdapter([{"legacy.md": {"path": str(tmp_path / "legacy.md"), "media_type": "text/markdown"}}])
    async def noop(*args): return None
    async def persist(*args): return {"sha256": "abc"}
    result = asyncio.run(orchestrate_ai_node(node, adapter, tmp_path, "task", persist, noop, noop))
    assert result["state"] == "success"
    assert json.dumps(contract, sort_keys=True) in adapter.prompts[0]
    assert node == original
