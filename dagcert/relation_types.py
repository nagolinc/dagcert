"""Read relation return coverage from the real strict mypy compiler.

No inference lives here: nominal identities, subtyping and possible overlaps all
come from mypy's checked syntax tree and exported expression types.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Iterable

from mypy.build import build
from mypy.errors import CompileError
from mypy.main import process_options
from mypy.meet import is_overlapping_types
from mypy.nodes import Decorator, FuncDef, MypyFile, SymbolNode, TypeInfo
from mypy.subtypes import is_subtype
from mypy.traverser import all_return_statements
from mypy.types import Instance, Type, UnionType, get_proper_type
from mypy.version import __version__ as mypy_version


class RelationTypeError(ValueError):
    """The real compiler could not supply complete nominal return coverage."""


def _lookup(module: MypyFile, name: str) -> SymbolNode:
    scope: MypyFile | TypeInfo = module
    node: SymbolNode | None = None
    components = name.split(".")
    for index, component in enumerate(components):
        entry = scope.names.get(component)
        node = entry.node if entry is not None else None
        if node is None:
            raise RelationTypeError(f"mypy cannot resolve source symbol {name!r}")
        if index + 1 < len(components):
            if not isinstance(node, (MypyFile, TypeInfo)):
                raise RelationTypeError(f"mypy symbol {name!r} is not a nominal scope")
            scope = node
    assert node is not None
    return node


def _closed_nominal(value: Type) -> bool:
    proper = get_proper_type(value)
    if isinstance(proper, UnionType):
        return all(_closed_nominal(item) for item in proper.items)
    return isinstance(proper, Instance) and not proper.args


def compiler_return_bindings(
    root: Path,
    python_files: Iterable[str],
    owners: dict[tuple[str, str], tuple[str, ...]],
) -> tuple[dict[tuple[str, str], list[dict[str, str]]], dict[str, object]]:
    """Return per-exit outcome modes and their compiler-generated provenance.

    Modes are ``always`` (subtype), ``possible`` (overlap), or ``never``
    (disjoint). Unknown/Any/unexported/generic expression types are refusals,
    never a reason to omit an obligation.
    """
    arguments = [
        *(str(root / path) for path in sorted(python_files)),
        "--strict", "--disallow-any-explicit", "--disallow-any-unimported",
        "--no-incremental", "--explicit-package-bases", "--show-error-codes",
        "--no-error-summary", "--python-executable", sys.executable,
    ]
    with TemporaryDirectory(prefix="dagcert-relation-types-") as temporary:
        scratch = Path(temporary)
        stub_root = scratch / "stubs"
        shutil.copytree(Path(__file__).parent / "mypy_stubs", stub_root)
        sources, options = process_options(arguments)
        options.mypy_path = [str(stub_root), str(root)]
        options.cache_dir = str(scratch / "cache")
        options.sqlite_cache = False
        options.export_types = True
        options.preserve_asts = True
        try:
            compiled = build(sources, options)
        except CompileError as exc:
            raise RelationTypeError("strict mypy return coverage refused:\n" + "\n".join(exc.messages)) from exc
        if compiled.errors:
            raise RelationTypeError("strict mypy return coverage refused:\n" + "\n".join(compiled.errors))
    modules = {Path(module.path).resolve(): module for module in compiled.files.values()}
    bindings: dict[tuple[str, str], list[dict[str, str]]] = {}
    rows: list[dict[str, object]] = []
    for (relative, symbol), outcomes in sorted(owners.items()):
        module = modules.get((root / relative).resolve())
        if module is None:
            raise RelationTypeError(f"mypy omitted source module {relative}")
        owner = _lookup(module, symbol)
        function = owner.func if isinstance(owner, Decorator) else owner
        if not isinstance(function, FuncDef):
            raise RelationTypeError(f"mypy owner {symbol!r} is not one concrete function")
        outcome_types: dict[str, Instance] = {}
        for name in outcomes:
            nominal = _lookup(module, name)
            if not isinstance(nominal, TypeInfo) or nominal.type_vars:
                raise RelationTypeError(f"outcome {name!r} is not a closed compiler-resolved nominal type")
            outcome_types[name] = Instance(nominal, [])
        exit_modes: list[dict[str, str]] = []
        exit_rows: list[dict[str, object]] = []
        for statement in all_return_statements(function):
            inferred = compiled.types.get(statement.expr) if statement.expr is not None else None
            if inferred is None or not _closed_nominal(inferred):
                raise RelationTypeError(
                    f"mypy return {relative}:{statement.line} lacks a closed nominal type: {inferred}"
                )
            modes = {
                name: (
                    "always" if is_subtype(inferred, nominal)
                    else "possible" if is_overlapping_types(inferred, nominal)
                    else "never"
                )
                for name, nominal in outcome_types.items()
            }
            exit_modes.append(modes)
            exit_rows.append({
                "line": statement.line, "column": statement.column,
                "inferred_type": str(inferred), "outcomes": modes,
            })
        if not exit_modes:
            raise RelationTypeError(f"mypy found no explicit returns for {relative}:{symbol}")
        bindings[(relative, symbol)] = exit_modes
        rows.append({
            "path": relative, "symbol": symbol, "compiler_symbol": function.fullname,
            "outcome_types": {name: value.type.fullname for name, value in outcome_types.items()},
            "returns": exit_rows,
        })
    return bindings, {"checker": "mypy", "version": mypy_version, "owners": rows}
