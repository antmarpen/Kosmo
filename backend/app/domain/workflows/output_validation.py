"""Shared validation entry points for API probes and worker execution."""

import json
from typing import Any, Awaitable, Callable

from app.domain.workflows.validation_logic import evaluate_content, validate_outputs, _safe_yaml_load
from pathlib import Path


async def validate_content(
    content: bytes,
    contract: dict,
    level: int,
    rule_runner: Callable[[str, Any, str], Awaitable[dict]] | None = None,
) -> list[dict]:
    """Evaluate parse/schema prerequisites and optionally run the sandboxed rule."""
    errors = evaluate_content(content, contract, level)
    if errors or level != 3 or not contract.get("rules"):
        return errors

    try:
        text = content.decode("utf-8")
        value = json.loads(text) if contract.get("format") == "json" else _safe_yaml_load(text)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return [{"artifact": "candidate", "level": "rules", "message_key": "validation.rules",
                 "params": {"reason": "unparseable"}}]

    if rule_runner is None:
        raise RuntimeError("Sandbox rule runner is unavailable")
    result = await rule_runner(contract["rules"], value, text)
    if result.get("passed") is True and result.get("reason") == "passed":
        return []
    return [{"artifact": "candidate", "level": "rules", "message_key": "validation.rules",
             "params": {"reason": result.get("reason", "execution_error")}}]


async def validate_outputs_async(
    outputs: dict,
    workspace: Path,
    contracts: dict | None,
    rule_runner: Callable[[str, Any, str], Awaitable[dict]],
    *,
    inputs: list[str] | None = None,
) -> list[dict]:
    """Validate outputs through one async gateway, preserving legacy readers."""
    contracts = contracts or {}
    if "levels" in contracts or any("levels" in item for item in contracts.values() if isinstance(item, dict)):
        return validate_outputs(outputs, workspace, contracts, inputs=inputs)
    failures: list[dict] = []
    for name in outputs:
        contract = contracts.get(name)
        if not contract:
            continue
        try:
            content = (workspace / name).read_bytes()
        except OSError:
            failures.append({"artifact": name, "level": "syntax", "message_key": "validation.syntax",
                             "params": {"reason": "missing"}})
            continue
        for level in (1, 2, 3):
            errors = await validate_content(content, contract, level, rule_runner)
            for error in errors:
                error["artifact"] = name
                failures.append(error)
            if errors:
                break
    return failures


__all__ = ["evaluate_content", "validate_outputs", "validate_content", "validate_outputs_async"]
