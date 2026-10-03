from app.domain.workflows.validation import validate_output_validation_catalogue


def issue_keys(contract, field_type="string"):
    return [issue.message_key for issue in validate_output_validation_catalogue({"nodes": [
        {"id": "writer", "type": "ai", "outputs": ["result"], "output_validation": {"result": contract}},
        {"id": "start", "type": "start", "input_form": [{"name": "age", "type": field_type,
         "required": True, "validation": contract}]}
    ]})]


def test_valid_draft_2020_12_schema_is_accepted():
    assert issue_keys({"format": "json", "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "integer"}}, "number") == []


def test_remote_json_schema_reference_is_rejected():
    assert "errors.workflow.validation_remote_ref_forbidden" in issue_keys({"format": "json", "json_schema": {"$ref": "https://example.com/schema"}})


def test_invalid_rules_code_is_rejected_without_execution():
    assert "errors.workflow.validation_rules_invalid" in issue_keys({"format": "json", "rules_code": "return ("})


def test_text_contract_rejects_schema_properties():
    assert "errors.workflow.validation_forbidden_property" in issue_keys({"format": "text", "json_schema": {"type": "string"}})


def test_number_field_rejects_json_string_schema():
    assert "errors.workflow.validation_start_type_incompatible" in issue_keys({"format": "json", "json_schema": {"type": "string"}}, "number")


def test_unknown_contract_options_are_rejected():
    assert "errors.workflow.validation_option_invalid" in issue_keys({"format": "json", "unknown": True})


def test_valid_local_fragment_reference_is_allowed():
    contract = {"format": "json", "json_schema": {"$defs": {"name": {"type": "string"}}, "$ref": "#/$defs/name"}}
    assert issue_keys(contract) == []
