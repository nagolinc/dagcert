"""Source-owned operation signatures used by hardened Dagcert contracts.

The contract points at code.  It does not get to restate the code's types.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import ast
import os
import re
import sys


class SourceTypeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceSignature:
    language: str
    path: str
    symbol: str
    input_type: str
    outcome_types: tuple[str, ...]
    line: int


def check_python_sources(source_root: str | Path, signatures: Iterable[SourceSignature]) -> dict[str, object]:
    """Run the Python type checker over the exact implementation files.

    Dagcert invokes mypy itself.  A checker result supplied by the application or an LLM is not
    accepted as a substitute.
    """
    bound_signatures = tuple(signatures)
    files = tuple(sorted({item.path for item in bound_signatures if item.language == "python"}))
    if not files:
        raise SourceTypeError("source-typed contract contains no Python implementation files")
    try:
        from mypy import api as mypy_api
        from mypy.version import __version__ as mypy_version
    except ImportError as exc:
        raise SourceTypeError("mypy is required to certify Python operation types") from exc
    root = Path(source_root).resolve()
    arguments = [
        *(str(root / item) for item in files),
        "--strict",
        "--disallow-any-explicit",
        "--disallow-any-unimported",
        "--no-incremental",
        "--show-error-codes",
        "--no-error-summary",
        "--python-executable",
        sys.executable,
    ]
    package_root = str(Path(__file__).resolve().parent.parent)
    previous_path = os.environ.get("MYPYPATH")
    os.environ["MYPYPATH"] = os.pathsep.join(
        item for item in (str(root), package_root, previous_path) if item
    )
    try:
        stdout, stderr, status = mypy_api.run(arguments)
    finally:
        if previous_path is None:
            os.environ.pop("MYPYPATH", None)
        else:
            os.environ["MYPYPATH"] = previous_path
    if status != 0:
        detail = "\n".join(item for item in (stdout.strip(), stderr.strip()) if item)
        raise SourceTypeError("bound application source failed strict mypy checking:\n" + detail)
    return {
        "checker": "mypy",
        "version": mypy_version,
        "mode": "strict",
        "files": list(files),
        "signatures": [
            {
                "path": item.path,
                "symbol": item.symbol,
                "line": item.line,
                "input_type": item.input_type,
                "outcome_types": list(item.outcome_types),
            }
            for item in sorted(bound_signatures, key=lambda value: (value.path, value.symbol))
        ],
    }


def read_python_signature(
    source_root: str | Path, relative_path: str, symbol: str,
) -> SourceSignature:
    """Read one closed, strongly annotated callable signature from Python source.

    This intentionally uses the source AST rather than importing the application.  Importing
    would execute application code and could observe a generated or monkey-patched signature.
    """

    root = Path(source_root).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SourceTypeError(f"implementation path escapes source root: {relative_path}") from exc
    if not path.is_file():
        raise SourceTypeError(f"implementation source does not exist: {relative_path}")
    try:
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(path), type_comments=True)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise SourceTypeError(f"cannot parse implementation source {relative_path}: {exc}") from exc

    _reject_type_escape_hatches(tree, source_text, relative_path)

    function = _find_function(tree, symbol)
    if isinstance(function, ast.AsyncFunctionDef):
        raise SourceTypeError(
            f"operation {symbol} is async; the Python v4 provider currently certifies only "
            "synchronous guarded boundaries"
        )
    class_nodes = {
        item.name: item for item in tree.body if isinstance(item, ast.ClassDef)
    }
    local_classes = set(class_nodes)
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    if function.args.vararg is not None or function.args.kwarg is not None:
        raise SourceTypeError(f"operation {symbol} must not use variadic parameters")
    if len(arguments) != 1:
        raise SourceTypeError(
            f"operation {symbol} must accept exactly one typed task input; observed {len(arguments)} parameters"
        )
    parameter = arguments[0]
    if parameter.annotation is None:
        raise SourceTypeError(f"operation {symbol} input lacks a source annotation")
    if function.returns is None:
        raise SourceTypeError(f"operation {symbol} return lacks a source annotation")

    input_type = _annotation(parameter.annotation, f"operation {symbol} input")
    _require_local_variant(parameter.annotation, local_classes, f"operation {symbol} input")
    outcome_nodes = tuple(_flatten_union(function.returns))
    outcomes: tuple[str, ...] = tuple(
        _annotation(item, f"operation {symbol} outcome") for item in outcome_nodes
    )
    for node in outcome_nodes:
        _require_local_variant(node, local_classes, f"operation {symbol} outcome")
    variant_names = {input_type, *outcomes}
    for variant_name in variant_names:
        _validate_variant_class(
            class_nodes[variant_name], f"operation {symbol} type {variant_name}",
            class_nodes, set(),
        )
    if len(outcomes) != len(set(outcomes)):
        raise SourceTypeError(f"operation {symbol} return union contains duplicate variants")
    if any(item in {"None", "NoneType", "object"} for item in outcomes):
        raise SourceTypeError(
            f"operation {symbol} return union must use explicit named outcomes, not None/object"
        )
    if _has_operation_decorator(function.decorator_list):
        outcomes = (*outcomes, "dagcert.runtime.UnhandledException")
    else:
        raise SourceTypeError(
            f"operation {symbol} must use @dagcert.operation so escaped exceptions are typed"
        )
    return SourceSignature(
        "python", Path(relative_path).as_posix(), symbol, input_type,
        tuple(dict.fromkeys(outcomes)), function.lineno,
    )


def _find_function(tree: ast.Module, symbol: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    parts = symbol.split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise SourceTypeError(f"invalid implementation symbol {symbol!r}")
    body: Iterable[ast.stmt] = tree.body
    node: ast.AST | None = None
    for index, part in enumerate(parts):
        matches = [
            item for item in body
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == part
        ]
        if len(matches) != 1:
            raise SourceTypeError(f"implementation symbol {symbol!r} was not found exactly once")
        node = matches[0]
        if index < len(parts) - 1:
            if not isinstance(node, ast.ClassDef):
                raise SourceTypeError(f"implementation symbol {symbol!r} crosses a non-class value")
            body = node.body
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise SourceTypeError(f"implementation symbol {symbol!r} is not a function")
    return node


def _flatten_union(node: ast.expr) -> Iterable[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        yield from _flatten_union(node.left)
        yield from _flatten_union(node.right)
        return
    if isinstance(node, ast.Subscript) and _qualified_name(node.value) in {"Union", "typing.Union"}:
        if isinstance(node.slice, ast.Tuple):
            for item in node.slice.elts:
                yield from _flatten_union(item)
        else:
            yield from _flatten_union(node.slice)
        return
    yield node


def _annotation(node: ast.expr, label: str) -> str:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == "Any":
            raise SourceTypeError(f"{label} must not contain Any")
        if isinstance(child, ast.Attribute) and child.attr == "Any":
            raise SourceTypeError(f"{label} must not contain Any")
    value = ast.unparse(node).strip()
    if not value:
        raise SourceTypeError(f"{label} is unresolved")
    return value


def _require_local_variant(node: ast.expr, class_names: set[str], label: str) -> None:
    if not isinstance(node, ast.Name) or node.id not in class_names:
        raise SourceTypeError(
            f"{label} must be an explicit class defined in the bound source file; "
            "aliases, primitives, and imported catch-all types are not closed task variants"
        )


def _validate_variant_class(
    node: ast.ClassDef, label: str, class_nodes: dict[str, ast.ClassDef], seen: set[str],
) -> None:
    if node.name in seen:
        return
    seen.add(node.name)
    if node.bases or node.keywords:
        raise SourceTypeError(f"{label} must not inherit from an open or external base type")
    if not any(
        _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        in {"dataclass", "dataclasses.dataclass"}
        for decorator in node.decorator_list
    ):
        raise SourceTypeError(f"{label} must be an explicit dataclass variant")
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign):
            _annotation(statement.annotation, f"{label} field")
            for child in ast.walk(statement.annotation):
                if isinstance(child, ast.Name) and child.id in class_nodes:
                    _validate_variant_class(
                        class_nodes[child.id], f"{label} nested type {child.id}",
                        class_nodes, seen,
                    )
        elif isinstance(statement, ast.Assign):
            raise SourceTypeError(f"{label} contains an untyped class field")


def _has_operation_decorator(decorators: list[ast.expr]) -> bool:
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _qualified_name(target) in {"operation", "dagcert.operation"}:
            return True
    return False


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _reject_type_escape_hatches(tree: ast.Module, source: str, path: str) -> None:
    if tree.type_ignores or re.search(r"#\s*mypy\s*:", source):
        raise SourceTypeError(
            f"bound implementation {path} contains a type-check suppression directive"
        )
    cast_aliases = {"cast"}
    typing_module_aliases = {"typing", "typing_extensions"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"typing", "typing_extensions"}:
                    typing_module_aliases.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and node.module in {"typing", "typing_extensions"}:
            for alias in node.names:
                if alias.name == "cast":
                    cast_aliases.add(alias.asname or alias.name)
    for walked in ast.walk(tree):
        if not isinstance(walked, ast.Call):
            continue
        name = _qualified_name(walked.func)
        if name in cast_aliases or name in {
            f"{module}.cast" for module in typing_module_aliases
        }:
            raise SourceTypeError(
                f"bound implementation {path} uses typing.cast; certified task types must be inferred"
            )
