"""Shared output validation used by the API and worker execution paths."""

def validate_outputs(outputs: dict, workspace: Path, contract: dict, level: int | None = None,
                    inputs: list[str] | None = None) -> list[dict]:
    levels = contract.get("levels", [])
    if len(levels) != 3:
        raise ValueError("Validation contract must declare exactly three levels")
    failures = []
    for logical_name, metadata in outputs.items():
        try:
            path = safe_path(workspace, logical_name)
        except (ValueError, OSError):
            failures.append(_failure(logical_name, levels[0], "invalid_path"))
            continue
        if level in (None, 1):
            if os.getenv("KOSMO_E2E_FAIL_VALIDATION") == "1":
                failures.append(_failure(logical_name, levels[0], "forced"))
                continue
            try:
                if not path.is_file():
                    raise FileNotFoundError
                media_type = metadata.get("media_type", "application/octet-stream")
                if media_type == "application/json" or path.suffix.lower() == ".json":
                    json.loads(path.read_text(encoding="utf-8"))
                elif media_type in {"text/markdown", "text/plain"} or path.suffix.lower() in {".md", ".txt"}:
                    path.read_text(encoding="utf-8")
            except FileNotFoundError:
                failures.append(_failure(logical_name, levels[0], "missing"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                failures.append(_failure(logical_name, levels[0], "unparseable"))
        if level in (None, 2) and path.is_file() and metadata.get("media_type") == "application/json":
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
                missing = [key for key in levels[1].get("params_schema", {}).get("required", [])
                           if not isinstance(parsed, dict) or key not in parsed]
                if missing:
                    failures.append(_failure(logical_name, levels[1], "required_fields_missing", fields=missing))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        if level in (None, 2) and path.is_file() and (metadata.get("media_type") == "text/markdown" or path.suffix.lower() == ".md"):
            schema = levels[1].get("params_schema", {})
            required = schema.get("required_sections", schema.get("sections", []))
            if required:
                max_level = max(schema.get("heading_levels", list(range(1, 7))))
                headings = {match.group(2).strip().casefold() for match in
                            re.finditer(r"^(#{1," + str(max_level) + r"})\s+(.+?)\s*#*\s*$",
                                        path.read_text(encoding="utf-8"), re.MULTILINE)}
                missing = [section for section in required if section.casefold() not in headings]
                if missing:
                    failures.append(_failure(logical_name, levels[1], "required_sections_missing", sections=missing))
        if level in (None, 3):
            schema = levels[2].get("params_schema", {})
            terms = schema.get("required_terms", [])
            if path.is_file() and schema.get("rule_type") == "supported_claims":
                input_name = schema.get("input_artifact")
                try:
                    source = safe_path(workspace, Path("inputs") / input_name) if input_name else None
                except (ValueError, OSError):
                    source = None
                if source is None and inputs:
                    input_name = inputs[0]
                    try:
                        source = safe_path(workspace, Path("inputs") / input_name)
                    except (ValueError, OSError):
                        source = None
                if source is None or not source.is_file():
                    failures.append(_failure(logical_name, levels[2], "source_artifact_missing", input_artifact=input_name))
                else:
                    tokens = set(re.findall(r"[a-z0-9]{4,}", source.read_text(encoding="utf-8").casefold()))
                    text = re.sub(r"(?m)^#{1,6}\s+.*$", "", path.read_text(encoding="utf-8"))
                    unsupported = [sentence.strip()[:160] for sentence in re.split(r"(?<=[.!?])\s+", text)
                                   if sentence.strip() and not (set(re.findall(r"[a-z0-9]{4,}", sentence.casefold())) & tokens)]
                    if unsupported:
                        failures.append(_failure(logical_name, levels[2], "unsupported_claim", input_artifact=input_name, claims=unsupported))
            elif path.is_file() and terms:
                text = path.read_text(encoding="utf-8")
                missing = [term for term in terms if term not in text]
                if missing:
                    failures.append(_failure(logical_name, levels[2], "required_terms_missing", terms=missing))
    return failures


def _failure(artifact: str, level: dict, reason: str, **params: object) -> dict:
    return {"artifact": artifact, "level": level["name"], "message_key": level["message_key"],
            "params": {"reason": reason, **params}}

import json
import os
import re
from pathlib import Path
from shared.paths import safe_path
