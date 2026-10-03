from __future__ import annotations

import ast
import keyword
from dataclasses import dataclass, field
from typing import Any


MAX_IDENTIFIER_LENGTH = 64
_HARNESS_NAME = "__kosmo_body__"


@dataclass(frozen=True)
class ScriptContractIssue:
    reason_code: str
    message_key: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptContractAnalysis:
    outputs: tuple[str, ...]
    issues: tuple[ScriptContractIssue, ...]


def analyze_script_body(code: str, input_names: list[str] | tuple[str, ...]) -> ScriptContractAnalysis:
    """Derive a script body's returned names without executing authored code."""
    issues: list[ScriptContractIssue] = []
    inputs = list(input_names)
    seen_inputs: set[str] = set()
    for name in inputs:
        if not _valid_identifier(name):
            issues.append(_issue("invalid_identifier", name=name, location="input"))
        if name == _HARNESS_NAME:
            issues.append(_issue("reserved_name", name=name))
        if name in seen_inputs:
            issues.append(_issue("duplicate_input", name=name))
        seen_inputs.add(name)

    safe_inputs = [name for name in inputs if _valid_identifier(name) and name != _HARNESS_NAME]
    wrapped = f"def {_HARNESS_NAME}({', '.join(safe_inputs)}):\n"
    wrapped += "\n".join("    " + line for line in code.splitlines())
    if not code.splitlines():
        wrapped += "    pass"
    try:
        tree = ast.parse(wrapped)
        compile(tree, "<script-body>", "exec")
    except (SyntaxError, ValueError) as error:
        issues.append(_issue(
            "syntax_error", line=max(1, (error.lineno or 1) - 1),
            column=max(0, (error.offset or 1) - 5),
        ))
        return ScriptContractAnalysis((), tuple(issues))

    function = tree.body[0]
    returns: list[tuple[str, ...]] = []

    class OuterReturns(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is function:
                self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_Return(self, node: ast.Return) -> None:
            if node.value is None:
                issues.append(_issue("bare_return", line=max(1, node.lineno - 1)))
                return
            expressions = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            names: list[str] = []
            for expression in expressions:
                if not isinstance(expression, ast.Name):
                    issues.append(_issue("unnamed_output", line=max(1, expression.lineno - 1)))
                    continue
                if expression.id == _HARNESS_NAME:
                    issues.append(_issue("reserved_name", name=expression.id))
                    continue
                names.append(expression.id)
            if len(set(names)) != len(names):
                issues.append(_issue("duplicate_output", names=names))
            returns.append(tuple(names))

    OuterReturns().visit(function)

    if returns and any(signature != returns[0] for signature in returns[1:]):
        issues.append(_issue("inconsistent_returns", signatures=[list(names) for names in returns]))
    outputs = returns[0] if returns else ()
    return ScriptContractAnalysis(outputs, tuple(issues))


def _valid_identifier(name: str) -> bool:
    return len(name) <= MAX_IDENTIFIER_LENGTH and name.isidentifier() and not keyword.iskeyword(name)


def _issue(reason_code: str, **params: Any) -> ScriptContractIssue:
    return ScriptContractIssue(reason_code, f"errors.script_contract.{reason_code}", params)
