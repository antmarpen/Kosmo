import pytest

from shared.graph.script_contract import analyze_script_body


def test_analyzes_tuple_return_ac_09():
    result = analyze_script_body("return size, distance", ["size", "distance"])
    assert result.outputs == ("size", "distance")
    assert result.issues == ()


@pytest.mark.parametrize("body", ["return result", "# comment\nreturn (\n    result,\n)"])
def test_analyzes_single_plain_name(body):
    assert analyze_script_body(body, []).outputs == ("result",)


def test_ignores_nested_function_returns():
    result = analyze_script_body("def helper():\n    return hidden\nreturn visible", [])
    assert result.outputs == ("visible",)


@pytest.mark.parametrize("body,reason", [
    ("if flag:\n    return first\nreturn second", "inconsistent_returns"),
    ("return call(value), 2", "unnamed_output"),
    ("return bad-name", "unnamed_output"),
    ("return value, value", "duplicate_output"),
    ("return", "bare_return"),
    ("return (", "syntax_error"),
])
def test_reports_contract_issues(body, reason):
    result = analyze_script_body(body, [])
    assert result.issues
    assert result.issues[0].reason_code == reason
    assert result.issues[0].message_key.startswith("errors.script_contract.")


def test_no_return_and_empty_body_have_no_outputs_or_issues():
    assert analyze_script_body("value = 1", []).outputs == ()
    assert analyze_script_body("", []).outputs == ()


def test_rejects_invalid_input_names_and_generated_harness_collision():
    result = analyze_script_body("return value", ["bad-name", "__kosmo_body__"])
    assert {issue.reason_code for issue in result.issues} == {"invalid_identifier", "reserved_name"}


def test_rejects_keyword_input_name():
    result = analyze_script_body("return value", ["class"])
    assert result.issues[0].reason_code == "invalid_identifier"
