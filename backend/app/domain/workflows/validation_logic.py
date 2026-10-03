"""Shared, deterministic validation of output artifacts."""

import json
import os
import re
from pathlib import Path

from shared.paths import safe_path


def validate_outputs(outputs: dict, workspace: Path, contracts: dict | None, level: int | None = None,
                    inputs: list[str] | None = None) -> list[dict]:
    """Validate declared outputs. Contracts are keyed by logical output name."""
    failures = []
    contracts = contracts or {}
    # Accept a single legacy contract for existing worker call sites during migration.
    legacy = contracts if "levels" in contracts else None
    for logical_name, metadata in outputs.items():
        contract = legacy or contracts.get(logical_name)
        levels = contract.get("levels", []) if contract else []
        if contract and len(levels) != 3:
            raise ValueError("Validation contract must declare exactly three levels")
        try:
            path = safe_path(workspace, logical_name)
            if not path.is_file():
                raise FileNotFoundError
        except FileNotFoundError:
            failures.append(_failure(logical_name, levels[0] if levels else _empty_level(), "missing"))
            continue
        except (ValueError, OSError):
            failures.append(_failure(logical_name, levels[0] if levels else _empty_level(), "invalid_path"))
            continue
        if not contract:
            continue
        if os.getenv("KOSMO_E2E_FAIL_VALIDATION") == "1" and level in (None, 1):
            failures.append(_failure(logical_name, levels[0], "forced")); continue
        media = metadata.get("media_type", "application/octet-stream")
        format_name = levels[0].get("params_schema", {}).get("format", "auto")
        is_json = format_name == "json" or (format_name == "auto" and media == "application/json")
        is_markdown = format_name == "markdown" or (format_name == "auto" and media == "text/markdown")
        text = None
        parsed = None
        if level in (None, 1) or level in (None, 2) and (is_json or is_markdown) or level in (None, 3) and levels[2].get("params_schema", {}).get("required_terms"):
            try:
                text = path.read_text(encoding="utf-8")
                if is_json:
                    parsed = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                failures.append(_failure(logical_name, levels[0], "unparseable")); continue
        if level in (None, 2) and is_json:
            required = levels[1].get("params_schema", {}).get("required", [])
            missing = [key for key in required if not isinstance(parsed, dict) or key not in parsed]
            if missing: failures.append(_failure(logical_name, levels[1], "required_fields_missing", fields=missing))
        if level in (None, 2) and is_markdown:
            schema = levels[1].get("params_schema", {})
            allowed = schema.get("heading_levels", list(range(1, 7)))
            headings = [(len(m.group(1)), m.group(2).strip().casefold()) for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*#*\s*$", text or "", re.M)]
            missing = [section for section in schema.get("required_sections", schema.get("sections", [])) if section.casefold() not in {title for depth, title in headings if depth in allowed}]
            if missing: failures.append(_failure(logical_name, levels[1], "required_sections_missing", sections=missing))
        if level in (None, 3):
            schema = levels[2].get("params_schema", {})
            if schema.get("required_terms"):
                missing = [term for term in schema["required_terms"] if term.casefold() not in (text or "").casefold()]
                if missing: failures.append(_failure(logical_name, levels[2], "required_terms_missing", terms=missing))
            # supported_claims requires authorized staged-input paths; callers must stage inputs under inputs/.
            if schema.get("rule_type") == "supported_claims":
                name = schema.get("input_artifact")
                try: source = safe_path(workspace, Path("inputs") / name) if name else None
                except (ValueError, OSError): source = None
                if source is None or not source.is_file():
                    failures.append(_failure(logical_name, levels[2], "source_artifact_missing", input_artifact=name))
                else:
                    source_tokens = set(re.findall(r"[a-z0-9]{4,}", source.read_text(encoding="utf-8").casefold()))
                    plain = re.sub(r"(?m)^#{1,6}\s+.*$", "", text or "")
                    unsupported = [s.strip()[:160] for s in re.split(r"(?<=[.!?])\s+", plain) if s.strip() and not set(re.findall(r"[a-z0-9]{4,}", s.casefold())) & source_tokens]
                    if unsupported: failures.append(_failure(logical_name, levels[2], "unsupported_claim", input_artifact=name, claims=unsupported))
    return failures


def _empty_level():
    return {"name": "syntax", "message_key": "validation.syntax"}


def _failure(artifact: str, level: dict, reason: str, **params: object) -> dict:
    return {"artifact": artifact, "level": level["name"], "message_key": level["message_key"], "params": {"reason": reason, **params}}
