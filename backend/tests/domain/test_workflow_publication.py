import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.api.deps import get_current_user
from app.api.routes import workflows as workflow_routes
from app.main import create_app
from app.domain.workflows.service import WorkflowService
from shared.errors import ValidationFailedError
from shared.graph.schema import WorkflowDefinition


def definition(name="sample"):
    return WorkflowDefinition.model_validate({
        "schema_version": "v1", "name": name,
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "label_message_key": "workflow.topic.label"}]},
            {"type": "script", "id": "script", "code": "pass", "inputs": ["topic"], "outputs": ["report"]},
            {"type": "end", "id": "end"},
        ], "edges": [{"from": "start", "to": "script"}, {"from": "script", "to": "end"}],
    })


class FakeRepository:
    def __init__(self):
        self.workflows = {}
        self.versions = {}
        self.activations = {}
        self.publication_revision = {}
        self.drafts = {}

    async def get_by_name(self, name):
        return self.workflows.get(name)

    async def create_workflow(self, name):
        workflow = {"id": name, "name": name, "publication_revision": 0}
        self.workflows[name] = workflow
        return workflow

    async def next_version(self, workflow_id):
        return len(self.versions.get(workflow_id, [])) + 1

    async def create_version(self, workflow_id, version, graph, published_by=None):
        row = {"id": f"{workflow_id}:{version}", "workflow_id": workflow_id, "version": version, "definition": graph, "created_at": datetime.now(timezone.utc), "published_by": published_by}
        self.versions.setdefault(workflow_id, []).append(row)
        return row

    async def activate(self, workflow_id, version_id):
        self.activations[workflow_id] = version_id

    async def list_workflows(self):
        return list(self.workflows.values())

    async def get_workflow(self, workflow_id):
        return next((w for w in self.workflows.values() if w["id"] == workflow_id), None)

    async def get_active_version(self, workflow_id):
        version_id = self.activations.get(workflow_id)
        return next((v for v in self.versions.get(workflow_id, []) if v["id"] == version_id), None)

    async def increment_publication_revision(self, workflow):
        workflow["publication_revision"] += 1
        self.publication_revision[workflow["id"]] = workflow["publication_revision"]

    async def get_latest_version(self, workflow_id):
        versions = self.versions.get(workflow_id, [])
        return versions[-1] if versions else None

    async def lock_workflow(self, workflow_id):
        return await self.get_workflow(workflow_id)

    async def get_version(self, version_id):
        return next((v for versions in self.versions.values() for v in versions if v["id"] == version_id), None)

    async def create_draft(self, workflow_id, author_id, base_version_id, graph, layout):
        row = {"id": f"draft-{len(self.drafts) + 1}", "workflow_id": workflow_id, "author_id": author_id,
               "base_version_id": base_version_id, "definition": graph, "layout": layout, "revision": 1}
        self.drafts[row["id"]] = row
        return row

    async def get_draft(self, workflow_id, draft_id):
        row = self.drafts.get(draft_id)
        return row if row and row["workflow_id"] == workflow_id else None


def test_publications_increment_without_activating_immutable_versions():
    repository = FakeRepository()
    service = WorkflowService(repository)
    first = asyncio.run(service.publish(definition()))
    second = asyncio.run(service.publish(definition()))
    assert first["version"] == 1
    assert second["version"] == 2
    assert "sample" not in repository.activations
    asyncio.run(service.activate_version("sample", second["id"], 0))
    assert repository.activations["sample"] == second["id"]
    assert repository.versions["sample"][0]["version"] == 1


def test_invalid_definition_is_rejected_before_persistence():
    repository = FakeRepository()
    invalid = definition().model_copy(update={"edges": []})
    with pytest.raises(ValidationFailedError) as caught:
        asyncio.run(WorkflowService(repository).publish(invalid))
    assert caught.value.details
    assert not repository.workflows


def test_publish_draft_does_not_activate_and_recent_other_publisher_requires_confirmation():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition(), "first-user"))
    workflow = repository.workflows["sample"]
    draft = asyncio.run(repository.create_draft("sample", "second-user", None,
                                                definition().model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="second-user", role=SimpleNamespace(value="builder"))
    with pytest.raises(Exception) as caught:
        asyncio.run(service.publish_draft("sample", draft["id"], user, workflow["publication_revision"]))
    assert getattr(caught.value, "message_key", None) == "errors.workflow.publication_confirmation_required"
    published = asyncio.run(service.publish_draft("sample", draft["id"], user, workflow["publication_revision"], True))
    assert published["version"] == 2
    assert "sample" not in repository.activations


def test_workflow_routes_publish_and_reject_invalid_definitions():
    repository = FakeRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    original_service = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    try:
        response = TestClient(app).post("/workflows", json=definition().model_dump(mode="json", by_alias=True))
        assert response.status_code == 201
        assert response.json()["version"] == 1
        invalid = definition().model_dump(mode="json", by_alias=True)
        invalid["edges"] = []
        rejected = TestClient(app).post("/workflows", json=invalid)
        assert rejected.status_code == 422
        assert rejected.json()["details"]
    finally:
        workflow_routes.service = original_service


def test_non_builder_cannot_publish():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=SimpleNamespace(value="runner"))
    response = TestClient(app).post("/workflows", json=definition().model_dump(mode="json", by_alias=True))
    assert response.status_code == 403


def test_workflow_list_and_detail_expose_publication_revision():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition()))
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    original_service = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    try:
        client = TestClient(app)
        listed = client.get("/workflows").json()[0]
        assert listed["publication_revision"] == 1
        assert listed["active_version"] is None
        detail = client.get("/workflows/sample").json()
        assert detail["publication_revision"] == 1
        asyncio.run(service.activate_version("sample", repository.versions["sample"][-1]["id"], 0))
        detail = client.get("/workflows/sample").json()
        assert detail["active_version"]["version"] == 1
        assert detail["publication_revision"] == 1
    finally:
        workflow_routes.service = original_service


def test_seed_reference_workflow_definition_has_required_shape():
    from scripts.seed import reference_workflow_definition

    seed = reference_workflow_definition()
    assert seed.name == "reference-security-analysis"
    assert [node.type for node in seed.nodes] == ["start", "script", "ai", "end"]
    assert seed.nodes[2].outputs == ["summary.md"]
    assert seed.nodes[2].max_validation_cycles == 3
    assert len(seed.nodes[2].validation.levels) == 3


def test_seed_is_idempotent_when_reference_workflow_already_exists():
    from scripts.seed import ensure_reference_workflow

    repository = FakeRepository()
    asyncio.run(ensure_reference_workflow(repository))
    asyncio.run(ensure_reference_workflow(repository))
    assert len(repository.versions["reference-security-analysis"]) == 1
