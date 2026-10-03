import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.api.deps import get_current_user
from app.api.routes import workflows as workflow_routes
from app.main import create_app
from app.domain.workflows.service import WorkflowService
from shared.errors import ConflictError, NotFoundError, ValidationFailedError
from shared.graph.schema import WorkflowDefinition


def definition(name="sample"):
    return WorkflowDefinition.model_validate({
        "schema_version": "v1", "name": name,
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "script", "id": "script", "code": "report = topic\nreturn report", "inputs": ["topic"], "outputs": ["report"]},
            {"type": "end", "id": "end", "inputs": ["report"]},
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

    async def find_name_conflict(self, name, exclude_workflow_id=None):
        lowered = name.lower()
        for workflow in self.workflows.values():
            if workflow["name"].lower() == lowered and workflow["id"] != exclude_workflow_id:
                return workflow
        return None

    async def create_workflow(self, name):
        workflow = {"id": name, "name": name, "publication_revision": 0}
        self.workflows[name] = workflow
        return workflow

    async def rename_workflow(self, workflow_id, name):
        workflow = await self.get_workflow(workflow_id)
        if workflow is None:
            return None
        self.workflows.pop(workflow["name"], None)
        workflow["name"] = name
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

    async def list_versions(self, workflow_id, limit, offset=0):
        versions = self.versions.get(workflow_id, [])
        return sorted(versions, key=lambda row: row["version"], reverse=True)[offset:offset + limit]

    async def count_drafts_by_author(self, author_id):
        counts = {}
        for draft in self.drafts.values():
            if draft["author_id"] == author_id:
                counts[draft["workflow_id"]] = counts.get(draft["workflow_id"], 0) + 1
        return counts

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

    async def save_draft(self, draft_id, author_id, expected_revision, definition, layout):
        row = self.drafts.get(draft_id)
        if row is None or row["author_id"] != author_id:
            return None
        if row["revision"] != expected_revision:
            raise ConflictError("errors.workflow.draft_revision_conflict", {"current_revision": row["revision"]})
        row.update(definition=definition, layout=layout, revision=row["revision"] + 1)
        return row


def test_publication_creates_first_version_without_activating_it():
    repository = FakeRepository()
    service = WorkflowService(repository)
    first = asyncio.run(service.publish(definition()))
    assert first["version"] == 1
    assert "sample" not in repository.activations
    asyncio.run(service.activate_version("sample", first["id"], 0))
    assert repository.activations["sample"] == first["id"]


def test_service_publish_rejects_existing_workflow_name():
    """Publication of an existing workflow must go through publish_draft, never append."""
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition()))
    with pytest.raises(ConflictError) as caught:
        asyncio.run(service.publish(definition()))
    assert caught.value.message_key == "errors.workflow.name_conflict"
    assert len(repository.versions["sample"]) == 1


def test_invalid_definition_is_rejected_before_persistence():
    repository = FakeRepository()
    invalid = definition().model_copy(update={"edges": []})
    with pytest.raises(ValidationFailedError) as caught:
        asyncio.run(WorkflowService(repository).publish(invalid))
    assert caught.value.details
    assert not repository.workflows


def test_create_workflow_produces_distinct_drafts_without_publishing():
    repository = FakeRepository()
    service = WorkflowService(repository)
    first = asyncio.run(service.create_workflow("Alpha", "author-1"))
    second = asyncio.run(service.create_workflow("Beta", "author-1"))
    assert first["id"] != second["id"]
    assert repository.versions.get(first["id"]) is None
    assert repository.versions.get(second["id"]) is None
    for workflow_id, created in ((first["id"], first), (second["id"], second)):
        drafts = [d for d in repository.drafts.values() if d["workflow_id"] == workflow_id]
        assert len(drafts) == 1
        assert drafts[0]["revision"] == 1
        assert drafts[0]["base_version_id"] is None
        assert drafts[0]["author_id"] == "author-1"
        assert created["draft_id"] == drafts[0]["id"]
        assert created["publication_revision"] == 0
        assert created["active_version"] is None


def test_create_workflow_rejects_duplicate_names_case_insensitively():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.create_workflow("Billing", "author-1"))
    with pytest.raises(ConflictError) as caught:
        asyncio.run(service.create_workflow("  billing  ", "author-2"))
    assert caught.value.message_key == "errors.workflow.name_conflict"
    assert len(repository.workflows) == 1
    assert len(repository.drafts) == 1


def test_create_workflow_rejects_blank_names():
    repository = FakeRepository()
    with pytest.raises(ValidationFailedError) as caught:
        asyncio.run(WorkflowService(repository).create_workflow("   ", "author-1"))
    assert caught.value.message_key == "errors.workflow.name_required"
    assert not repository.workflows


def test_publish_draft_rejects_blank_definition_names_without_publishing():
    """A whitespace-only definition name is a validation failure: nothing is
    published and the workflow keeps its own name (no silent blank rename)."""
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.create_workflow("Alpha", "author-1"))
    workflow = repository.workflows["Alpha"]
    draft = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                definition("   ").model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    with pytest.raises(ValidationFailedError) as caught:
        asyncio.run(service.publish_draft(workflow["id"], draft["id"], user, 0))
    assert caught.value.message_key == "errors.workflow.invalid"
    assert {"message_key": "errors.workflow.name_required", "params": {}} in [detail.__dict__ for detail in caught.value.details]
    assert repository.versions.get(workflow["id"]) is None
    assert workflow["name"] == "Alpha"


def test_publish_draft_reports_blank_names_through_draft_validation():
    """The draft-validation endpoint surfaces the same keyed issue before any
    publish is attempted, so the editor can show it next to the graph issues."""
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.create_workflow("Alpha", "author-1"))
    workflow = repository.workflows["Alpha"]
    draft = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                definition("  ").model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    issues = asyncio.run(service.validate_draft(workflow["id"], draft["id"], user))
    assert {"message_key": "errors.workflow.name_required", "params": {}} in issues


def test_publish_draft_trims_surrounding_whitespace_from_the_published_name():
    """Publication normalizes the definition name exactly like creation: a
    padded name never reaches the workflow row or the published version."""
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.create_workflow("Alpha", "author-1"))
    workflow = repository.workflows["Alpha"]
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))

    # Same name modulo whitespace: no rename, and the version stores the
    # trimmed name.
    padded = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                 definition("  Alpha  ").model_dump(mode="json", by_alias=True), {}))
    published = asyncio.run(service.publish_draft(workflow["id"], padded["id"], user, 0))
    assert published["definition"]["name"] == "Alpha"
    assert workflow["name"] == "Alpha"

    # A real rename is trimmed too: the workflow row takes the clean name.
    renamed = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                  definition("  Alpha Prime  ").model_dump(mode="json", by_alias=True), {}))
    published = asyncio.run(service.publish_draft(workflow["id"], renamed["id"], user, 1))
    assert published["definition"]["name"] == "Alpha Prime"
    assert workflow["name"] == "Alpha Prime"
    assert asyncio.run(repository.get_by_name("Alpha Prime"))["id"] == workflow["id"]


def test_publish_draft_enforces_expected_publication_revision():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition(), "author-1"))
    draft = asyncio.run(repository.create_draft("sample", "author-1", None,
                                                definition().model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    with pytest.raises(ConflictError) as caught:
        asyncio.run(service.publish_draft("sample", draft["id"], user, 99))
    assert caught.value.message_key == "errors.workflow.publication_revision_conflict"
    assert caught.value.params == {"current_revision": 1}
    assert len(repository.versions["sample"]) == 1


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


def test_publish_draft_syncs_renamed_definition_to_the_workflow_name():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition("Old name"), "author-1"))
    workflow = repository.workflows["Old name"]
    draft = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                definition("New name").model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    published = asyncio.run(service.publish_draft(workflow["id"], draft["id"], user, 1))
    assert published["version"] == 2
    assert asyncio.run(repository.get_by_name("New name"))["id"] == workflow["id"]
    assert asyncio.run(repository.get_by_name("Old name")) is None


def test_publish_draft_rejects_rename_to_an_existing_name():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.create_workflow("Alpha", "author-1"))
    asyncio.run(service.publish(definition("Beta"), "author-1"))
    workflow = repository.workflows["Beta"]
    draft = asyncio.run(repository.create_draft(workflow["id"], "author-1", None,
                                                definition("alpha").model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    with pytest.raises(ConflictError) as caught:
        asyncio.run(service.publish_draft(workflow["id"], draft["id"], user, 1))
    assert caught.value.message_key == "errors.workflow.name_conflict"
    assert len(repository.versions["Beta"]) == 1
    assert repository.workflows["Beta"]["name"] == "Beta"


def test_workflow_routes_create_only_contract():
    repository = FakeRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    original_service = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    try:
        client = TestClient(app)
        created = client.post("/workflows", json={"name": "Review flow"})
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "Review flow"
        assert body["publication_revision"] == 0
        assert body["active_version"] is None
        assert body["draft_revision"] == 1
        assert repository.versions.get(body["id"]) is None
        draft = repository.drafts[body["draft_id"]]
        assert draft["author_id"] == "builder"

        duplicate = client.post("/workflows", json={"name": "review FLOW"})
        assert duplicate.status_code == 409
        assert duplicate.json()["message_key"] == "errors.workflow.name_conflict"
        assert len(repository.workflows) == 1

        blank = client.post("/workflows", json={"name": "   "})
        assert blank.status_code == 422
        assert blank.json()["message_key"] == "errors.workflow.name_required"

        listed = client.get("/workflows").json()
        assert len(listed) == 1
        assert listed[0]["active_version"] is None
    finally:
        workflow_routes.service = original_service


def test_workflow_routes_reject_invalid_definitions_through_draft_publish():
    repository = FakeRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    original_service = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    try:
        client = TestClient(app)
        created = client.post("/workflows", json={"name": "Review flow"})
        workflow_id = created.json()["id"]
        draft_id = created.json()["draft_id"]
        invalid = definition().model_dump(mode="json", by_alias=True)
        invalid["edges"] = []
        saved = client.put(f"/workflows/{workflow_id}/drafts/{draft_id}",
                           json={"definition": invalid, "layout": {}, "expected_revision": 1})
        assert saved.status_code == 200
        rejected = client.post(f"/workflows/{workflow_id}/drafts/{draft_id}/publish",
                               json={"expected_pub_revision": 0, "confirm_overwrite": False})
        assert rejected.status_code == 422
        assert rejected.json()["details"]
        assert repository.versions.get(workflow_id) is None
    finally:
        workflow_routes.service = original_service


def test_workflow_routes_reject_blank_publish_names_with_a_keyed_error():
    """Publishing a draft whose definition name is blank fails with a keyed,
    localizable issue and leaves the workflow unnamed-but-intact."""
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        created = client.post("/workflows", json={"name": "Review flow"}).json()
        blank = definition("   ").model_dump(mode="json", by_alias=True)
        saved = client.put(f"/workflows/{created['id']}/drafts/{created['draft_id']}",
                           json={"definition": blank, "layout": {}, "expected_revision": 1})
        assert saved.status_code == 200
        issues = client.post(f"/workflows/{created['id']}/drafts/{created['draft_id']}/validate").json()["issues"]
        assert {"message_key": "errors.workflow.name_required", "params": {}} in issues

        rejected = client.post(f"/workflows/{created['id']}/drafts/{created['draft_id']}/publish",
                               json={"expected_pub_revision": 0})
        assert rejected.status_code == 422
        body = rejected.json()
        assert body["message_key"] == "errors.workflow.invalid"
        assert {"message_key": "errors.workflow.name_required", "params": {}} in body["details"]
        # Nothing was published and the workflow kept its entered name.
        assert repository.versions.get(created["id"]) is None
        assert repository.workflows["Review flow"]["name"] == "Review flow"
    finally:
        workflow_routes.service = original_service


def test_non_builder_cannot_create_workflows():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=SimpleNamespace(value="runner"))
    response = TestClient(app).post("/workflows", json={"name": "Review flow"})
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
    assert seed.nodes[0].input_form[0].validation.format == "text"
    assert seed.nodes[1].output_validation["data"].format == "json"
    assert seed.nodes[1].output_validation["data"].json_schema["type"] == "object"
    assert seed.nodes[2].output_validation["summary.md"].model_dump(exclude_none=True) == {"format": "markdown"}
    assert seed.nodes[2].agent.runtime == "opencode"
    assert seed.nodes[2].agent.model == "default"
    assert seed.nodes[2].inputs == ["report", "data"]


def test_seed_is_idempotent_when_reference_workflow_already_exists():
    from scripts.seed import ensure_reference_workflow

    repository = FakeRepository()
    asyncio.run(ensure_reference_workflow(repository))
    asyncio.run(ensure_reference_workflow(repository))
    assert len(repository.versions["reference-security-analysis"]) == 1
    stored_contract = repository.versions["reference-security-analysis"][0]["definition"]["nodes"][2]["output_validation"]["summary.md"]
    assert stored_contract["format"] == "markdown"
    assert stored_contract["json_schema"] is None and stored_contract["rules_code"] is None


def test_explicit_reference_upgrade_publishes_without_activation():
    from scripts.seed import ensure_reference_workflow, upgrade_reference_workflow
    repository = FakeRepository()
    asyncio.run(ensure_reference_workflow(repository))
    original = repository.versions["reference-security-analysis"][0]["definition"]
    asyncio.run(upgrade_reference_workflow(repository))
    asyncio.run(ensure_reference_workflow(repository))
    versions = repository.versions["reference-security-analysis"]
    assert len(versions) == 2
    assert versions[0]["definition"] == original
    assert repository.activations["reference-security-analysis"] == versions[0]["id"]


def test_legacy_catalogue_inventory_identifies_repair_path_without_mutation():
    from app.domain.workflows.validation import inventory_output_validation_records
    original = {"nodes": [{"type": "ai", "id": "legacy", "output_validation": {
        "summary.md": {"levels": [{"name": "parse", "params_schema": {"format": "auto"}}]}
    }}]}
    result = inventory_output_validation_records([{"id": "version-1", "definition": original}])
    assert result[0]["legacy_catalogue_paths"] == [{
        "path": "nodes[0].output_validation.summary.md", "node_id": "legacy",
        "output": "summary.md", "reason": "legacy_levels_requires_explicit_repair"}]
    assert result[0]["repair_required"] is True
    assert original["nodes"][0]["output_validation"]["summary.md"]["levels"][0]["params_schema"]["format"] == "auto"


def test_list_published_versions_reports_active_metadata_newest_first():
    repository = FakeRepository()
    service = WorkflowService(repository)
    first = asyncio.run(service.publish(definition(), "author-1"))
    asyncio.run(service.activate_version("sample", first["id"], 0))
    draft = asyncio.run(repository.create_draft("sample", "author-1", first["id"],
                                                definition().model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    asyncio.run(service.publish_draft("sample", draft["id"], user, 1))

    listed = asyncio.run(service.list_published_versions("sample", 50))

    assert [row["version"] for row in listed] == [2, 1]
    assert [row["id"] for row in listed] == [f"sample:{version}" for version in (2, 1)]
    assert all(row["published_at"] is not None for row in listed)
    # The active version is reported per row; publishing v2 never auto-activated it.
    assert [row["is_active"] for row in listed] == [False, True]
    # Version metadata only: the definition payload stays out of the listing.
    assert all("definition" not in row for row in listed)


def test_list_published_versions_is_bounded_by_limit():
    repository = FakeRepository()
    service = WorkflowService(repository)
    asyncio.run(service.publish(definition(), "author-1"))
    draft = asyncio.run(repository.create_draft("sample", "author-1", None,
                                                definition().model_dump(mode="json", by_alias=True), {}))
    user = SimpleNamespace(id="author-1", role=SimpleNamespace(value="builder"))
    asyncio.run(service.publish_draft("sample", draft["id"], user, 1))

    assert [row["version"] for row in asyncio.run(service.list_published_versions("sample", 1))] == [2]


def test_list_published_versions_rejects_unknown_workflow():
    repository = FakeRepository()
    service = WorkflowService(repository)
    with pytest.raises(NotFoundError) as caught:
        asyncio.run(service.list_published_versions("absent", 50))
    assert caught.value.message_key == "errors.workflow.not_found"


def test_list_published_versions_offset_returns_following_pages():
    """Offset pagination walks the newest-first listing page by page."""
    repository = FakeRepository()
    asyncio.run(repository.create_workflow("sample"))
    for version in (1, 2, 3):
        asyncio.run(repository.create_version("sample", version, {}))
    service = WorkflowService(repository)

    first_page = asyncio.run(service.list_published_versions("sample", 2, 0))
    second_page = asyncio.run(service.list_published_versions("sample", 2, 2))

    assert [row["version"] for row in first_page] == [3, 2]
    assert [row["version"] for row in second_page] == [1]


def test_workflow_versions_route_paginates_with_offset_and_validates_it():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        created = client.post("/workflows", json={"name": "Review flow"}).json()
        for version in (1, 2, 3):
            asyncio.run(repository.create_version(created["id"], version, {}))

        first = client.get(f"/workflows/{created['id']}/versions", params={"limit": 2, "offset": 0})
        assert [row["version"] for row in first.json()] == [3, 2]
        second = client.get(f"/workflows/{created['id']}/versions", params={"limit": 2, "offset": 2})
        assert [row["version"] for row in second.json()] == [1]

        negative = client.get(f"/workflows/{created['id']}/versions", params={"offset": -1})
        assert negative.status_code == 422
    finally:
        workflow_routes.service = original_service


def test_list_workflows_reports_only_the_callers_drafts():
    """Drafts are author-private: each caller's list view counts their own drafts."""
    repository = FakeRepository()
    service = WorkflowService(repository)
    created = asyncio.run(service.create_workflow("Alpha", "author-1"))
    workflow_id = created["id"]
    asyncio.run(repository.create_draft(workflow_id, "author-2", None, {}, {}))
    asyncio.run(repository.create_draft(workflow_id, "author-1", None, {}, {}))

    mine = asyncio.run(service.list_workflows("author-1"))[0]
    theirs = asyncio.run(service.list_workflows("author-2"))[0]

    assert mine["draft_count"] == 2
    assert theirs["draft_count"] == 1


def test_workflow_routes_report_the_callers_draft_count():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        created = client.post("/workflows", json={"name": "Review flow"}).json()
        # Creation reports the initial draft it just created for the caller.
        assert created["draft_count"] == 1

        listed = client.get("/workflows").json()
        assert listed[0]["draft_count"] == 1

        # Another author's draft never leaks into this caller's count.
        asyncio.run(repository.create_draft(created["id"], "someone-else", None, {}, {}))
        listed = client.get("/workflows").json()
        assert listed[0]["draft_count"] == 1

        # The detail response stays schema-valid and carries the field.
        detail = client.get(f"/workflows/{created['id']}").json()
        assert detail["draft_count"] == 0
    finally:
        workflow_routes.service = original_service


def route_client(repository):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="builder", role=SimpleNamespace(value="builder"))
    original_service = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    return TestClient(app), original_service


def http_draft_definition(outputs, name="Parent flow"):
    return {
        "schema_version": "v1", "name": name,
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "http", "id": "http", "method": "GET", "url": "https://example.invalid", "outputs": outputs, "inputs": ["topic"]},
            {"type": "end", "id": "end", "inputs": ["response"]},
        ],
        "edges": [{"from": "start", "to": "http"}, {"from": "http", "to": "end"}],
    }


def workflow_draft_definition(child_workflow_id, name="Parent flow"):
    return {
        "schema_version": "v1", "name": name,
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "workflow", "id": "invoke", "workflow_id": child_workflow_id, "inputs": ["topic"]},
            {"type": "end", "id": "end", "inputs": []},
        ],
        "edges": [{"from": "start", "to": "invoke"}, {"from": "invoke", "to": "end"}],
    }


def save_draft(client, workflow_id, draft_id, definition):
    return client.put(f"/workflows/{workflow_id}/drafts/{draft_id}",
                      json={"definition": definition, "layout": {}, "expected_revision": 1})


def draft_issues(client, workflow_id, draft_id):
    return client.post(f"/workflows/{workflow_id}/drafts/{draft_id}/validate").json()["issues"]


def test_workflow_versions_route_lists_metadata_and_publish_never_activates():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        created = client.post("/workflows", json={"name": "Review flow"}).json()
        saved = client.put(f"/workflows/{created['id']}/drafts/{created['draft_id']}",
                           json={"definition": definition("Review flow").model_dump(mode="json", by_alias=True),
                                 "layout": {}, "expected_revision": 1})
        assert saved.status_code == 200
        first = client.post(f"/workflows/{created['id']}/drafts/{created['draft_id']}/publish",
                            json={"expected_pub_revision": 0})
        assert first.status_code == 201
        first_id = first.json()["id"]
        activated = client.post(f"/workflows/{created['id']}/activate",
                                json={"version_id": first_id, "expected_active_revision": 0})
        assert activated.status_code == 200

        # Second publication of the same draft: publishing alone must leave the
        # active version untouched, and the listing must prove it.
        saved = client.put(f"/workflows/{created['id']}/drafts/{created['draft_id']}",
                           json={"definition": definition("Review flow").model_dump(mode="json", by_alias=True),
                                 "layout": {}, "expected_revision": 2})
        assert saved.status_code == 200
        # The draft was seeded before any version existed (base is stale after
        # activation), so republishing it needs the explicit confirmation.
        second = client.post(f"/workflows/{created['id']}/drafts/{created['draft_id']}/publish",
                             json={"expected_pub_revision": 1, "confirm_overwrite": True})
        assert second.status_code == 201

        listed = client.get(f"/workflows/{created['id']}/versions")
        assert listed.status_code == 200
        rows = listed.json()
        assert [row["version"] for row in rows] == [2, 1]
        assert [row["id"] for row in rows] == [second.json()["id"], first_id]
        assert [row["is_active"] for row in rows] == [False, True]
        assert all(row["published_at"] for row in rows)
        assert all("definition" not in row for row in rows)

        # The listing is bounded: limit=1 keeps only the newest version.
        bounded = client.get(f"/workflows/{created['id']}/versions", params={"limit": 1})
        assert [row["version"] for row in bounded.json()] == [2]

        unknown = client.get("/workflows/absent/versions")
        assert unknown.status_code == 404
        assert unknown.json()["message_key"] == "errors.workflow.not_found"

        over_limit = client.get(f"/workflows/{created['id']}/versions", params={"limit": 1000})
        assert over_limit.status_code == 422
    finally:
        workflow_routes.service = original_service


def test_draft_with_http_node_outputs_saves_and_publishes():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        parent = client.post("/workflows", json={"name": "Parent flow"}).json()
        saved = save_draft(client, parent["id"], parent["draft_id"], http_draft_definition(["response"]))
        assert saved.status_code == 200
        assert draft_issues(client, parent["id"], parent["draft_id"]) == []
        published = client.post(f"/workflows/{parent['id']}/drafts/{parent['draft_id']}/publish",
                                json={"expected_pub_revision": 0})
        assert published.status_code == 201
        assert published.json()["definition"]["nodes"][1]["outputs"] == ["response"]
    finally:
        workflow_routes.service = original_service


def test_draft_with_invalid_http_output_reports_keyed_issue_and_blocks_publication():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        parent = client.post("/workflows", json={"name": "Parent flow"}).json()
        saved = save_draft(client, parent["id"], parent["draft_id"], http_draft_definition(["../escape"]))
        assert saved.status_code == 200
        assert draft_issues(client, parent["id"], parent["draft_id"]) == [
            {"message_key": "errors.workflow.invalid_definition",
             "params": {"field": "nodes.1.http.outputs.0", "type": "literal_error"}},
        ]
        rejected = client.post(f"/workflows/{parent['id']}/drafts/{parent['draft_id']}/publish",
                               json={"expected_pub_revision": 0})
        assert rejected.status_code == 422
        assert rejected.json()["message_key"] == "errors.workflow.invalid_definition"
        assert repository.versions.get(parent["id"]) is None
    finally:
        workflow_routes.service = original_service


def test_draft_with_existing_subworkflow_reference_saves_and_publishes():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        child = client.post("/workflows", json={"name": "Child flow"}).json()
        child_definition = {
            "schema_version": "v1", "name": "Child flow",
            "nodes": [
                {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
                {"type": "end", "id": "end", "inputs": ["topic"]},
            ],
            "edges": [{"from": "start", "to": "end"}],
        }
        save_draft(client, child["id"], child["draft_id"], child_definition)
        published_child = client.post(f"/workflows/{child['id']}/drafts/{child['draft_id']}/publish",
                                      json={"expected_pub_revision": 0}).json()
        client.post(f"/workflows/{child['id']}/activate",
                    json={"version_id": published_child["id"], "expected_active_revision": 0})
        parent = client.post("/workflows", json={"name": "Parent flow"}).json()
        saved = save_draft(client, parent["id"], parent["draft_id"], workflow_draft_definition(child["id"]))
        assert saved.status_code == 200
        assert draft_issues(client, parent["id"], parent["draft_id"]) == []
        published = client.post(f"/workflows/{parent['id']}/drafts/{parent['draft_id']}/publish",
                                json={"expected_pub_revision": 0})
        assert published.status_code == 201
        assert published.json()["definition"]["nodes"][1]["workflow_id"] == child["id"]
    finally:
        workflow_routes.service = original_service


def test_draft_with_missing_subworkflow_reference_fails_with_keyed_issue():
    repository = FakeRepository()
    client, original_service = route_client(repository)
    try:
        parent = client.post("/workflows", json={"name": "Parent flow"}).json()
        saved = save_draft(client, parent["id"], parent["draft_id"], workflow_draft_definition("absent-workflow"))
        assert saved.status_code == 200
        assert draft_issues(client, parent["id"], parent["draft_id"]) == [
            {"message_key": "errors.workflow.workflow_not_found",
             "params": {"node_id": "invoke", "workflow_id": "absent-workflow"}},
        ]
        rejected = client.post(f"/workflows/{parent['id']}/drafts/{parent['draft_id']}/publish",
                               json={"expected_pub_revision": 0})
        assert rejected.status_code == 422
        assert {"message_key": "errors.workflow.workflow_not_found",
                "params": {"node_id": "invoke", "workflow_id": "absent-workflow"}} in rejected.json()["details"]
        assert repository.versions.get(parent["id"]) is None
    finally:
        workflow_routes.service = original_service


def test_bootstrap_publish_checks_subworkflow_references():
    repository = FakeRepository()
    service = WorkflowService(repository)
    child_definition = WorkflowDefinition.model_validate({
        "schema_version": "v1", "name": "Child",
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True}]},
            {"type": "end", "id": "end", "inputs": ["topic"]},
        ],
        "edges": [{"from": "start", "to": "end"}],
    })
    published_child = asyncio.run(service.publish(child_definition))
    asyncio.run(service.activate_version(published_child["workflow_id"], published_child["id"], 0))
    published = asyncio.run(service.publish(WorkflowDefinition.model_validate(workflow_draft_definition(published_child["workflow_id"], name="Parent"))))
    assert published["version"] == 1
    missing = WorkflowDefinition.model_validate(workflow_draft_definition("absent", name="Other"))
    with pytest.raises(ValidationFailedError) as caught:
        asyncio.run(service.publish(missing))
    assert "errors.workflow.workflow_not_found" in [detail.message_key for detail in caught.value.details]
    assert not repository.versions.get("Other")
