import json

import pytest

from worker.activities.artifacts import validate_output, artifact_digest


def test_script_outputs_are_validated_and_hashed(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    validate_output(path, "application/json")
    assert artifact_digest(path) == __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_invalid_json_output_is_rejected(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_output(path, "application/json")
