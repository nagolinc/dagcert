"""Static application call edges used to locate embedded external consumers.

This is a call-site index, not an exception or execution proof. The backend still
proves the complete source closure, including decorators, globals and dispatch.
Only statically bound top-level functions are followed; dynamic calls do not
acquire an invented target.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .proof_sources import ProofSourceError, _absolute_import_module, _module_name


@dataclass(frozen=True, order=True)
class PythonSourceCall:
    consumer_path: str
    consumer_symbol: str
    provider_path: str
    provider_symbol: str


class _BodyNodes(ast.NodeVisitor):
    """Visit executed body expressions without entering a newly defined scope."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.bound: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bound.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.bound.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Import(self, node: ast.Import) -> None:
        self.bound.update(alias.asname or alias.name.split('.')[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.bound.update(alias.asname or alias.name for alias in node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)


def resolve_python_source_calls(
    source_root: str | Path,
    roots: Iterable[tuple[str, str]],
    manifest_paths: Iterable[str],
) -> tuple[PythonSourceCall, ...]:
    """Follow direct local/from-import/module-attribute calls from real roots.

    Source ownership comes exclusively from the exact manifest. Re-export aliases
    resolve to the defining function. Cycles terminate; distinct real callers are
    retained. Shadowed source bindings are refused rather than falsely attributed.
    """

    root = Path(source_root).resolve()
    manifest = frozenset(Path(path).as_posix() for path in manifest_paths)
    modules: dict[str, list[str]] = {}
    for path in sorted(manifest):
        if Path(path).suffix == '.py' and (module := _module_name(path)):
            modules.setdefault(module, []).append(path)
    trees: dict[str, ast.Module] = {}

    def tree_for(path: str) -> ast.Module:
        if path not in manifest:
            raise ProofSourceError(f'call source {path!r} is outside the exact manifest')
        if path not in trees:
            source = (root / path).resolve()
            if not source.is_relative_to(root):
                raise ProofSourceError(f'call source {path!r} escapes its source root')
            try:
                trees[path] = ast.parse(source.read_bytes(), filename=path)
            except (OSError, SyntaxError) as exc:
                raise ProofSourceError(f'cannot inspect call source {path!r}: {exc}') from exc
        return trees[path]

    def module_path(module: str) -> str | None:
        candidates = modules.get(module, [])
        if len(candidates) > 1:
            raise ProofSourceError(f'ambiguous application call module {module!r}: {candidates}')
        for candidate in (Path(*module.split('.')).with_suffix('.py'),
                          Path(*module.split('.')) / '__init__.py'):
            if (root / candidate).is_file() and candidate.as_posix() not in manifest:
                raise ProofSourceError(f'call provider {candidate.as_posix()!r} is outside the exact manifest')
        return candidates[0] if candidates else None

    def resolve(path: str, name: str, seen: frozenset[tuple[str, str]]) -> tuple[str, str] | None:
        key = (path, name)
        if key in seen:
            return None
        seen = seen | {key}
        parts = name.split('.')
        head = parts[0]
        bindings: list[ast.stmt] = []
        for statement in tree_for(path).body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if statement.name == head:
                    bindings.append(statement)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                if any((alias.asname or (alias.name.split('.')[0] if isinstance(statement, ast.Import)
                                        else alias.name)) == head for alias in statement.names):
                    bindings.append(statement)
            else:
                nodes = _BodyNodes()
                nodes.visit(statement)
                if head in nodes.bound:
                    bindings.append(statement)
        if not bindings:
            return None
        if len(bindings) != 1:
            raise ProofSourceError(f'ambiguous or rebound source call {path}:{name}')
        binding = bindings[0]
        if isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return (path, head) if len(parts) == 1 else None
        if isinstance(binding, ast.ImportFrom):
            module = _absolute_import_module(path, _module_name(path), binding.level, binding.module)
            if module is None:
                return None
            alias = next(alias for alias in binding.names if (alias.asname or alias.name) == head)
            provider = module_path(module)
            if provider is not None:
                resolved = resolve(provider, '.'.join([alias.name, *parts[1:]]), seen)
                if resolved is not None:
                    return resolved
            child = module_path(f'{module}.{alias.name}')
            if child is not None and len(parts) > 1:
                return resolve(child, '.'.join(parts[1:]), seen)
        elif isinstance(binding, ast.Import):
            alias = next(alias for alias in binding.names
                         if (alias.asname or alias.name.split('.')[0]) == head)
            qualified = '.'.join([alias.name, *parts[1:]]) if alias.asname else name
            module, _, symbol = qualified.rpartition('.')
            if module and (provider := module_path(module)) is not None:
                return resolve(provider, symbol, seen)
        return None

    pending = [(Path(path).as_posix(), symbol) for path, symbol in roots]
    visited: set[tuple[str, str]] = set()
    edges: set[PythonSourceCall] = set()
    while pending:
        path, symbol = pending.pop()
        if (path, symbol) in visited:
            continue
        visited.add((path, symbol))
        function = next((node for node in tree_for(path).body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name == symbol), None)
        if function is None:
            raise ProofSourceError(f'call root {path}:{symbol} is not a top-level function')
        nodes = _BodyNodes()
        for statement in function.body:
            nodes.visit(statement)
        nodes.bound.update(arg.arg for arg in (
            *function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs))
        if function.args.vararg:
            nodes.bound.add(function.args.vararg.arg)
        if function.args.kwarg:
            nodes.bound.add(function.args.kwarg.arg)
        for call in nodes.calls:
            names: list[str] = []
            expression = call.func
            while isinstance(expression, ast.Attribute):
                names.insert(0, expression.attr)
                expression = expression.value
            if not isinstance(expression, ast.Name):
                continue
            names.insert(0, expression.id)
            target = resolve(path, '.'.join(names), frozenset())
            if target is None:
                continue
            if names[0] in nodes.bound:
                raise ProofSourceError(f'shadowed source call {path}:{symbol}: {names[0]}')
            provider_path, provider_symbol = target
            edges.add(PythonSourceCall(path, symbol, provider_path, provider_symbol))
            pending.append(target)
    return tuple(sorted(edges))
