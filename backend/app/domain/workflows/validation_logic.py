"""Shared, deterministic validation of output artifacts."""

import json
import math
import os
import re
from pathlib import Path

import jsonschema
import yaml
from yaml.nodes import MappingNode, SequenceNode

from shared.paths import safe_path

MAX_CANDIDATE_BYTES = 1_048_576
MAX_SCHEMA_BYTES = 262_144
MAX_ERRORS = 20
MAX_YAML_DEPTH = 64
MAX_YAML_NODES = 10_000


def evaluate_content(content: bytes, contract: dict, level: int) -> list[dict]:
    """Evaluate a candidate without I/O or rule execution; levels are 1..3."""
    if level not in (1, 2, 3):
        raise ValueError("Validation level must be between 1 and 3")
    fmt = contract.get("format")
    level_names = ("syntax", "format", "rules")
    message_keys = ("validation.syntax", "validation.format", "validation.rules")

    def failure(reason, **params):
        return [{"artifact": "candidate", "level": level_names[level - 1], "message_key": message_keys[level - 1],
                 "params": {"reason": reason, **params}}]

    if len(content) > MAX_CANDIDATE_BYTES:
        return failure("candidate_too_large", limit=MAX_CANDIDATE_BYTES)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return failure("unparseable")
    if fmt in {"text", "markdown"}:
        return []
    value = None
    try:
        if fmt == "json":
            def reject_constant(token):
                raise ValueError(token)
            def finite_float(token):
                number = float(token)
                if not math.isfinite(number):
                    raise ValueError("non-finite JSON number")
                return number
            value = json.loads(text, parse_constant=reject_constant, parse_float=finite_float)
        elif fmt == "yaml":
            value = _safe_yaml_load(text)
        else:
            return failure("format_invalid")
    except (ValueError, yaml.YAMLError, RecursionError):
        return failure("unparseable")
    if level == 1 or fmt == "yaml" or "json_schema" not in contract or level == 3:
        return []
    schema = contract["json_schema"]
    if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > MAX_SCHEMA_BYTES:
        return failure("schema_too_large", limit=MAX_SCHEMA_BYTES)
    try:
        validator = jsonschema.Draft202012Validator(schema)
        failures = sorted(validator.iter_errors(value), key=lambda error: (list(map(str, error.absolute_path)), error.message))
    except (jsonschema.SchemaError, TypeError, ValueError):
        return failure("schema_invalid")
    return [{"artifact": "candidate", "level": "format", "message_key": "validation.format",
             "params": {"reason": "schema_invalid", "path": ".".join(map(str, error.absolute_path)), "detail": "Value does not match schema"}}
            for error in failures[:MAX_ERRORS]]


def _safe_yaml_load(text: str):
    class UniqueSafeLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, (str, int, float, bool, type(None))) or key in mapping:
                    raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark,
                        "duplicate or unsupported mapping key", key_node.start_mark)
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping
    loader = UniqueSafeLoader(text)
    try:
        root = loader.get_single_node()
        if root is None:
            raise ValueError("empty YAML document")
        active = set()
        visits = 0
        def inspect(node, depth=0):
            nonlocal visits
            visits += 1
            if depth > MAX_YAML_DEPTH or visits > MAX_YAML_NODES:
                raise ValueError("YAML resource limit")
            identity = id(node)
            if identity in active:
                raise ValueError("recursive YAML alias")
            if isinstance(node, (MappingNode, SequenceNode)):
                active.add(identity)
                children = ([part for pair in node.value for part in pair] if isinstance(node, MappingNode) else node.value)
                for child in children:
                    inspect(child, depth + 1)
                active.remove(identity)
        inspect(root)
        value = loader.construct_document(root)
        def supported(item):
            if item is None or isinstance(item, (str, bool, int)): return True
            if isinstance(item, float): return item == item and abs(item) != float("inf")
            if isinstance(item, list): return all(supported(v) for v in item)
            if isinstance(item, dict): return all(isinstance(k, str) and supported(v) for k, v in item.items())
            return False
        if not supported(value):
            raise ValueError("unsupported YAML value")
        return value
    finally:
        loader.dispose()


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
        if "format" in contract:
            try:
                content = path.read_bytes()
            except OSError:
                failures.append(_failure(logical_name, _empty_level(), "unparseable")); continue
            selected_levels = (1, 2, 3) if level is None else (level,)
            for selected in selected_levels:
                selected_errors = evaluate_content(content, contract, selected)
                for issue in selected_errors:
                    issue["artifact"] = logical_name
                    failures.append(issue)
                    if len(failures) >= MAX_ERRORS:
                        return failures[:MAX_ERRORS]
                if selected == 1 and selected_errors:
                    break
            # rules_code is deliberately a hook for the sandbox package; never run here.
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
