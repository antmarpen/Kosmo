import json

import pytest
from fastapi.testclient import TestClient

from app.domain.events.service import format_sse
from app.domain.events.service import aggregate_event_visible
from app.main import create_app
from app.api.deps import get_current_user
from types import SimpleNamespace


def test_sse_frame_uses_event_id_and_stable_wire_payload():
    event = {
        "id": 17,
        "kind": "task.state",
        "task_id": "task-1",
        "node_id": None,
        "state": "running",
        "note": None,
        "at": "2026-09-30T12:00:00+00:00",
    }

    frame = format_sse(event)

    assert frame.startswith("id: 17\nevent: task.state\ndata: ")
    assert json.loads(frame.split("data: ", 1)[1]) == {
        "task_id": "task-1", "node_id": None, "state": "running",
        "note": None, "at": "2026-09-30T12:00:00+00:00",
    }
    assert frame.endswith("\n\n")


def test_task_event_stream_requires_bearer_authentication():
    response = TestClient(create_app()).get("/tasks/events")

    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_ERROR", "message_key": "errors.auth.invalid_token", "params": {}, "details": []}


@pytest.mark.parametrize("cursor", ["abc", "-1"])
def test_malformed_event_cursor_returns_keyed_error(cursor):
    from app.core.security import create_access_token
    from app.core.config import settings
    settings.jwt_secret = "test-validator-signing-secret-32-bytes"
    token = create_access_token("user-1", "runner", settings.jwt_secret)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", role="runner")
    response = TestClient(app).get("/tasks/events", headers={
        "Authorization": f"Bearer {token}", "Last-Event-ID": cursor,
    })
    assert response.status_code == 400
    assert response.json() == {"code": "VALIDATION_FAILED", "message_key": "errors.events.invalid_cursor", "params": {}, "details": []}


def test_aggregate_stream_hides_notes_for_tasks_not_owned_by_user_but_keeps_state():
    user_b = {"id": "user-b", "role": "runner"}
    note = {"kind": "task.note", "task_id": "task-a"}
    state = {"kind": "task.state", "task_id": "task-a"}
    assert not aggregate_event_visible(note, user_b, "user-a")
    assert aggregate_event_visible(state, user_b, "user-a")
    assert aggregate_event_visible(note, {"id": "user-a", "role": "runner"}, "user-a")
    assert aggregate_event_visible(note, {"id": "admin", "role": "admin"}, "user-a")
