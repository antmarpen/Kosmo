import pytest

from app.domain.workflows.output_validation import validate_content


@pytest.mark.asyncio
async def test_level_three_parse_failure_does_not_execute_rule():
    calls = []

    async def run_rule(*args):
        calls.append(args)
        return {"passed": True, "reason": "passed"}

    result = await validate_content(b"not-json", {"format": "json", "rules_code": "return True"}, 3, run_rule)

    assert result
    assert calls == []


@pytest.mark.asyncio
async def test_async_gateway_fails_closed_when_rule_rejects():
    calls = []

    async def run_rule(*args):
        calls.append(args)
        return {"passed": False, "reason": "rule_failed"}

    result = await validate_content(b'{"ok": true}', {"format": "json", "rules_code": "return False"}, 3, run_rule)

    assert result[0]["params"]["reason"] == "rule_failed"
    assert len(calls) == 1
    assert calls[0][0] == "return False"
