"""Container-side execution harness for authored function-body scripts."""

from __future__ import annotations

import ast
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

_MANIFEST_NAME = "manifest.json"
_MAX_MANIFEST_BYTES = 64 * 1024
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RESERVED = {"__kosmo_runner", "__builtins__"}


def run_descriptor(descriptor_path: str | Path) -> None:
    """Run a JSON descriptor containing source, staged inputs, and output contract."""
    descriptor = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
    source = descriptor["source"]
    input_names = descriptor["input_names"]
    inputs = descriptor["inputs"]
    output_names = descriptor["output_names"]
    output_dir = Path(descriptor["output_dir"]).resolve(strict=True)
    if not isinstance(source, str) or not isinstance(input_names, list) or not isinstance(output_names, list):
        raise ValueError("Invalid script descriptor")
    all_names = input_names + output_names
    if (any(not isinstance(name, str) or not _VALID_NAME.fullmatch(name) or name in _RESERVED for name in all_names)
            or len(set(input_names)) != len(input_names) or len(set(output_names)) != len(output_names)):
        raise ValueError("Invalid or reserved variable name")
    if set(inputs) != set(input_names):
        raise ValueError("Input descriptors do not match declared inputs")

    bound = {name: _read_input(inputs[name]) for name in input_names}
    function_name = "__kosmo_runner"
    wrapped = f"def {function_name}({', '.join(input_names)}):\n"
    wrapped += "\n".join("    " + line for line in source.splitlines()) or "    pass"
    _validate_returns(source, input_names, output_names)
    namespace: dict[str, Any] = {}
    exec(compile(wrapped, "<authored-script>", "exec"), {"__builtins__": __builtins__}, namespace)
    result = namespace[function_name](**bound)
    values = result if isinstance(result, tuple) else (result,)
    if len(values) != len(output_names):
        raise ValueError("Returned value count does not match declared outputs")

    manifest: dict[str, str] = {}
    destinations = {name: _output_path(output_dir, name) for name in output_names}
    for name, value in zip(output_names, values, strict=True):
        media_type, content = _serialize(value)
        destinations[name].write_bytes(content)
        manifest[name] = media_type
    encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise ValueError("Output manifest exceeds size limit")
    _output_path(output_dir, _MANIFEST_NAME, allow_manifest=True).write_bytes(encoded)


def _read_input(descriptor: dict[str, str]) -> Any:
    media_type = descriptor["media_type"].split(";", 1)[0].strip().lower()
    path = Path(descriptor["path"])
    data = path.read_bytes()
    if media_type in {"text/plain", "text/markdown"}:
        return data.decode("utf-8")
    if media_type == "application/json":
        return json.loads(data.decode("utf-8"))
    raise ValueError(f"Unsupported input media type: {media_type}")


def _serialize(value: Any) -> tuple[str, bytes]:
    if isinstance(value, str):
        return "text/plain", value.encode("utf-8")
    try:
        content = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("Returned value is not JSON-compatible") from error
    _check_finite(value)
    return "application/json", content.encode("utf-8")


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite numbers are not allowed")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _check_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(item)


def _validate_returns(source: str, inputs: list[str], outputs: list[str]) -> None:
    function = ast.parse(f"def __kosmo_runner({', '.join(inputs)}):\n" +
                         ("\n".join("    " + line for line in source.splitlines()) or "    pass")).body[0]
    returns: list[tuple[str, ...]] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is function:
                for item in node.body:
                    self.visit(item)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Return(self, node: ast.Return) -> None:
            if node.value is None:
                raise ValueError("Bare return is invalid")
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            if any(not isinstance(item, ast.Name) for item in values):
                raise ValueError("Returned values must be named variables")
            returns.append(tuple(item.id for item in values))

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

    Visitor().visit(function)
    if any(signature != tuple(outputs) for signature in returns):
        raise ValueError("Return names do not match declared outputs")
    if outputs and not returns:
        raise ValueError("Declared outputs require a return")
    if not outputs and returns:
        raise ValueError("Unexpected returned values")


def _output_path(output_dir: Path, name: str, *, allow_manifest: bool = False) -> Path:
    if (name == _MANIFEST_NAME and not allow_manifest) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Invalid output filename")
    path = output_dir / name
    if path.is_symlink() or path.resolve(strict=False).parent != output_dir:
        raise ValueError("Output path escapes output directory or is a symlink")
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: script_runner.py DESCRIPTOR.json")
    run_descriptor(sys.argv[1])
