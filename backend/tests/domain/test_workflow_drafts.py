import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import workflows as workflow_routes
from app.main import create_app
from app.domain.workflows.service import WorkflowService
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError


class DraftRepository:
    def __init__(self):
        self.workflows = {"wf": {"id": "wf", "name": "sample"}}
        self.active = {"wf": {"id": "version", "definition": {"schema_version": "v1"}}}
        self.drafts = {}
        self.versions = {}

    async def get_workflow(self, workflow_id):
        return self.workflows.get(workflow_id)

    async def get_active_version(self, workflow_id):
        return self.active.get(workflow_id)

    async def get_latest_version(self, workflow_id):
        versions = self.versions.get(workflow_id, [])
        return versions[-1] if versions else None

    async def create_draft(self, workflow_id, author_id, base_version_id, definition, layout):
        row = {"id": f"draft-{len(self.drafts)}", "workflow_id": workflow_id, "author_id": author_id,
               "base_version_id": base_version_id, "definition": definition, "layout": layout,
               "revision": 1, "updated_at": "now"}
        self.drafts[row["id"]] = row
        return row

    async def list_drafts(self, workflow_id, author_id):
        return [d for d in self.drafts.values() if d["workflow_id"] == workflow_id and d["author_id"] == author_id]

    async def get_draft(self, workflow_id, draft_id):
        draft = self.drafts.get(draft_id)
        return draft if draft and draft["workflow_id"] == workflow_id else None

    async def save_draft(self, draft_id, author_id, expected_revision, definition, layout):
        draft = self.drafts.get(draft_id)
        if not draft or draft["author_id"] != author_id:
            return None
        if draft["revision"] != expected_revision:
            raise ConflictError("errors.workflow.draft_revision_conflict", {"current_revision": draft["revision"]})
        draft.update(definition=definition, layout=layout, revision=draft["revision"] + 1)
        return draft


def setup(repository, user):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    original = workflow_routes.service
    workflow_routes.service = lambda _db: WorkflowService(repository)
    return TestClient(app), original


def user(user_id="author", role="builder"):
    return SimpleNamespace(id=user_id, role=SimpleNamespace(value=role))


def test_draft_lifecycle_preserves_invalid_json_and_validation_reports_issues():
    repository = DraftRepository()
    client, original = setup(repository, user())
    try:
        created = client.post("/workflows/wf/drafts")
        assert created.status_code == 201
        draft_id = created.json()["draft_id"]
        assert created.json()["revision"] == 1
        invalid = {"definition": {"nonsense": True}, "layout": {"nodes": []}, "expected_revision": 1}
        saved = client.put(f"/workflows/wf/drafts/{draft_id}", json=invalid)
        assert saved.status_code == 200 and saved.json()["revision"] == 2
        fetched = client.get(f"/workflows/wf/drafts/{draft_id}")
        assert fetched.json()["definition"] == invalid["definition"]
        validation = client.post(f"/workflows/wf/drafts/{draft_id}/validate")
        assert validation.status_code == 200 and validation.json()["issues"]
    finally:
        workflow_routes.service = original


def test_drafts_are_private_and_runner_cannot_create_them():
    repository = DraftRepository()
    client, original = setup(repository, user())
    try:
        draft_id = client.post("/workflows/wf/drafts").json()["draft_id"]
        other, _ = setup(repository, user("other"))
        assert other.get(f"/workflows/wf/drafts/{draft_id}").status_code == 404
        assert other.get("/workflows/wf/drafts").json() == []
        runner, _ = setup(repository, user("runner", "runner"))
        assert runner.post("/workflows/wf/drafts").status_code == 403
    finally:
        workflow_routes.service = original


def test_draft_seeds_from_latest_published_version_when_none_is_active():
    repository = DraftRepository()
    repository.active = {}
    repository.versions["wf"] = [{"id": "v1", "definition": {"schema_version": "v1", "name": "sample", "nodes": [
        {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "label_message_key": "workflow.topic.label"}]},
        {"type": "end", "id": "end"},
    ], "edges": [{"from": "start", "to": "end"}]}}]
    client, original = setup(repository, user())
    try:
        created = client.post("/workflows/wf/drafts")
        fetched = client.get(f"/workflows/wf/drafts/{created.json()['draft_id']}")
        assert fetched.json()["definition"]["name"] == "sample"
        assert [node["id"] for node in fetched.json()["definition"]["nodes"]] == ["start", "end"]
    finally:
        workflow_routes.service = original


def test_draft_revision_conflict_returns_current_revision():
    repository = DraftRepository()
    client, original = setup(repository, user())
    try:
        draft_id = client.post("/workflows/wf/drafts").json()["draft_id"]
        result = client.put(f"/workflows/wf/drafts/{draft_id}", json={"definition": {}, "layout": {}, "expected_revision": 9})
        assert result.status_code == 409
        assert result.json()["params"]["current_revision"] == 1
    finally:
        workflow_routes.service = original


def test_valid_draft_save_increments_revision_without_publishing():
    repository = DraftRepository()
    client, original = setup(repository, user())
    try:
        draft_id = client.post("/workflows/wf/drafts").json()["draft_id"]
        definition = {
            "schema_version": "v1", "name": "sample",
            "nodes": [
                {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "label_message_key": "workflow.topic.label"}]},
                {"type": "end", "id": "end"},
            ],
            "edges": [{"from": "start", "to": "end"}],
        }
        response = client.put(f"/workflows/wf/drafts/{draft_id}", json={"definition": definition, "layout": {}, "expected_revision": 1})
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert len(repository.drafts) == 1
        assert repository.active["wf"]["id"] == "version"
    finally:
        workflow_routes.service = original
