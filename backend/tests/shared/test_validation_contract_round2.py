from copy import deepcopy

import pytest
from pydantic import ValidationError

from shared.graph.output_contract import normalize_validation_contracts
from shared.graph.schema import FormField, ValidationContract


@pytest.mark.parametrize("contract", [
    {"format": "text"}, {"format": "markdown"},
    {"format": "json", "json_schema": True, "rules_code": "return True"},
    {"format": "json", "json_schema": {"type": "object"}},
    {"format": "yaml", "rules_code": "return True"},
])
def test_round2_contracts_parse(contract):
    assert ValidationContract.model_validate(contract).model_dump(exclude_none=True) == contract


@pytest.mark.parametrize("contract", [
    {"format": "text", "json_schema": True},
    {"format": "markdown", "rules_code": "return True"},
    {"format": "yaml", "json_schema": {}},
    {"format": "auto"},
])
def test_invalid_format_properties_are_rejected(contract):
    with pytest.raises(ValidationError):
        ValidationContract.model_validate(contract)


def test_start_field_contract_round_trips():
    field = FormField.model_validate({"name": "prompt", "type": "string", "required": True, "validation": {"format": "text"}})
    assert field.model_dump(exclude_none=True)["validation"] == {"format": "text"}


def test_legacy_ai_and_levels_are_preserved_or_converted_without_mutation():
    source = {"nodes": [{"type": "ai", "outputs": ["a"], "validation": {"levels": [
        {"name": "parse", "message_key": "x", "params_schema": {"format": "json"}},
        {"name": "format", "message_key": "x", "params_schema": {"required_keys": ["id"]}},
        {"name": "rules", "message_key": "x", "params_schema": {}},
    ]}}]}
    original = deepcopy(source)
    normalized, issues = normalize_validation_contracts(source)
    assert source == original
    assert normalized["nodes"][0]["output_validation"]["a"]["format"] == "json"
    assert normalized["nodes"][0]["output_validation"]["a"]["json_schema"] == {"type": "object", "required": ["id"]}
    assert not issues
    again, again_issues = normalize_validation_contracts(normalized)
    assert again == normalized and again_issues == issues


def test_ambiguous_legacy_contract_preserved_with_keyed_issue():
    legacy = {"levels": [{"name": "parse", "message_key": "x", "params_schema": {"format": "auto"}}]}
    result, issues = normalize_validation_contracts({"nodes": [{"type": "script", "outputs": ["out"], "output_validation": {"out": legacy}}]})
    assert result["nodes"][0]["output_validation"]["out"] == legacy
    assert issues and issues[0]["key"] == "errors.graph.legacy_validation_repair_required"


def test_conflicting_ai_contracts_are_reported_without_overwrite():
    source = {"nodes": [{"type": "ai", "outputs": ["x"], "validation": {"levels": []}, "output_validation": {"x": {"format": "json"}}}]}
    result, issues = normalize_validation_contracts(source)
    assert result["nodes"][0]["validation"] == source["nodes"][0]["validation"]
    assert result["nodes"][0]["output_validation"] == source["nodes"][0]["output_validation"]
    assert issues[0]["key"] == "errors.graph.output_validation_conflict"
