import json

import pytest

from app.domain.workflows.output_validation import evaluate_content


def test_json_schema_reports_nested_path_and_accepts_arrays_and_scalars():
    contract = {"format": "json", "json_schema": {"type": "array", "items": {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}}}
    errors = evaluate_content(b'[{"age":"old"}]', contract, 2)
    assert errors[0]["params"]["reason"] == "schema_invalid"
    assert errors[0]["params"]["path"] == "0.age"
    assert evaluate_content(b'4', {"format": "json", "json_schema": {"type": "integer"}}, 2) == []


def test_json_schema_supports_local_fragment_refs():
    contract = {"format": "json", "json_schema": {"$defs": {"name": {"type": "string"}}, "$ref": "#/$defs/name"}}
    assert evaluate_content(b'"ok"', contract, 2) == []


@pytest.mark.parametrize("payload", [b"{}", b'"value"'])
def test_false_json_schema_rejects_every_json_value(payload):
    errors = evaluate_content(payload, {"format": "json", "json_schema": False}, 2)
    assert errors and errors[0]["params"]["reason"] == "schema_invalid"


def test_true_json_schema_accepts_any_valid_json_value():
    assert evaluate_content(b'"value"', {"format": "json", "json_schema": True}, 2) == []


@pytest.mark.parametrize("payload", [b'\xff', b'{"x": NaN}', b'{"x":1e999}', b'{bad'])
def test_json_rejects_invalid_encoding_nonfinite_and_malformed(payload):
    assert evaluate_content(payload, {"format": "json"}, 1)[0]["params"]["reason"] == "unparseable"


@pytest.mark.parametrize("payload", [b'a: [', b'a: !!python/object/apply:os.system [echo x]', b'a: 1\na: 2', b'a: 1\n---\nb: 2', b'a: &x [*x]'])
def test_yaml_rejects_malformed_unsafe_duplicate_multi_document_and_alias_cycle(payload):
    assert evaluate_content(payload, {"format": "yaml"}, 1)


def test_text_requires_utf8_and_diagnostics_are_bounded():
    assert evaluate_content(b'\xff', {"format": "text"}, 1)
    schema = {"type": "array", "items": {"type": "integer"}}
    errors = evaluate_content(json.dumps(["x"] * 100).encode(), {"format": "json", "json_schema": schema}, 2)
    assert len(errors) <= 20


def test_legacy_contract_remains_on_historical_validation_path(tmp_path):
    from app.domain.workflows.validation_logic import validate_outputs

    (tmp_path / "x.txt").write_text("ordinary", encoding="utf-8")
    levels = [{"name": f"level-{i}", "message_key": f"validation.level_{i}", "params_schema": {}} for i in range(1, 4)]
    levels[2]["params_schema"] = {"required_terms": ["secret"]}
    errors = validate_outputs({"x.txt": {}}, tmp_path, {"levels": levels}, 3)
    assert errors[0]["params"]["reason"] == "required_terms_missing"
