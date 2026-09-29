"""Resolve the exact application-owned Python source closure of proved operations."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Literal


class ProofSourceError(ValueError):
    """The application proof-source graph is ambiguous or cannot be inspected."""


@dataclass(frozen=True, slots=True)
class ProofSourceEdge:
    importer_path: str
    module: str
    provider_path: str
    imported_symbols: tuple[str, ...]
    kind: Literal["source-import", "package-initializer"]

    def to_mapping(self, root: Path) -> dict[str, object]:
        provider = root / self.provider_path
        return {
            "importer_path": self.importer_path,
            "module": self.module,
            "provider_path": self.provider_path,
            "provider_sha256": sha256(provider.read_bytes()).hexdigest(),
            "imported_symbols": list(self.imported_symbols),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class PythonProofSourceClosure:
    roots: tuple[str, ...]
    proof_only_files: tuple[str, ...]
    edges: tuple[ProofSourceEdge, ...]

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.roots) | set(self.proof_only_files)))

    def to_mapping(self, root: Path) -> dict[str, object]:
        return {
            "roots": list(self.roots),
            "proof_only_files": [
                {
                    "path": path,
                    "sha256": sha256((root / path).read_bytes()).hexdigest(),
                }
                for path in self.proof_only_files
            ],
            "edges": [edge.to_mapping(root) for edge in self.edges],
        }


def resolve_python_proof_sources(
    source_root: str | Path,
    root_files: Iterable[str],
    manifest_paths: Iterable[str],
) -> PythonProofSourceClosure:
    """Find application modules Python can reach from the proved operation files.

    The manifest is the authority for application ownership. An import that resolves to a
    manifest Python file is source-owned; imports with no manifest provider remain external and
    must be covered by the verifier's builtin model or an explicit external contract.
    """

    root = Path(source_root).resolve()
    manifest = frozenset(Path(path).as_posix() for path in manifest_paths)
    roots = tuple(sorted({Path(path).as_posix() for path in root_files}))
    missing_roots = sorted(set(roots) - manifest)
    if missing_roots:
        raise ProofSourceError(
            "proof root files must be present in the exact source manifest: "
            f"{missing_roots}"
        )

    module_paths: dict[str, list[str]] = {}
    path_modules: dict[str, str] = {}
    for path in sorted(manifest):
        if Path(path).suffix != ".py":
            continue
        module = _module_name(path)
        if module is None:
            continue
        module_paths.setdefault(module, []).append(path)
        path_modules[path] = module

    included = set(roots)
    pending = list(roots)
    edges: set[ProofSourceEdge] = set()

    for root_path in roots:
        _include_parent_initializers(
            root_path, root_path, manifest, path_modules, included, pending, edges
        )

    while pending:
        importer_path = pending.pop()
        source_path = root / importer_path
        try:
            tree = ast.parse(source_path.read_bytes(), filename=importer_path)
        except (OSError, SyntaxError) as exc:
            raise ProofSourceError(
                f"cannot inspect proof source imports for {importer_path!r}: {exc}"
            ) from exc
        importer_module = path_modules.get(importer_path)
        for node in ast.walk(tree):
            requests = _import_requests(node, importer_path, importer_module)
            for module, imported_symbols in requests:
                requested_modules = [module]
                requested_modules.extend(
                    f"{module}.{symbol}"
                    for symbol in imported_symbols
                    if symbol != "*"
                )
                for provider_module in requested_modules:
                    candidates = module_paths.get(provider_module, [])
                    if len(candidates) > 1:
                        raise ProofSourceError(
                            f"application import {provider_module!r} from "
                            f"{importer_path!r} is ambiguous: {candidates}"
                        )
                    if not candidates:
                        continue
                    provider_path = candidates[0]
                    edge_symbols = imported_symbols if provider_module == module else ()
                    edges.add(ProofSourceEdge(
                        importer_path,
                        provider_module,
                        provider_path,
                        tuple(sorted(set(edge_symbols))),
                        "source-import",
                    ))
                    if provider_path not in included:
                        included.add(provider_path)
                        pending.append(provider_path)
                    _include_parent_initializers(
                        importer_path,
                        provider_path,
                        manifest,
                        path_modules,
                        included,
                        pending,
                        edges,
                    )
                unsealed = sorted({
                    path
                    for requested in requested_modules
                    for path in _unsealed_local_candidates(root, requested, manifest)
                })
                if unsealed:
                    raise ProofSourceError(
                        f"application import {module!r} from {importer_path!r} resolves to "
                        f"source outside the exact manifest: {unsealed}"
                    )

    proof_only = tuple(sorted(included - set(roots)))
    return PythonProofSourceClosure(
        roots,
        proof_only,
        tuple(sorted(
            edges,
            key=lambda edge: (
                edge.importer_path,
                edge.module,
                edge.provider_path,
                edge.kind,
                edge.imported_symbols,
            ),
        )),
    )


def resolve_python_import_from_edges(
    source_root: str | Path,
    files: Iterable[str],
) -> tuple[ProofSourceEdge, ...]:
    """Resolve the exact source providers named by Python ``from`` imports.

    Python permits ``from package import child`` to bind the source module
    ``package.child`` rather than a value declared by ``package.__init__``.  The
    proof-source closure already resolves both candidates so it can hash-seal
    every file Python may execute.  This projection selects the provider that
    supplies each imported binding for verifier result comparison, while leaving
    package-initializer execution edges in the closure itself.

    Plain ``import module`` statements are intentionally not projected here.
    Backends that support their attribute semantics validate them separately.
    """

    root = Path(source_root).resolve()
    normalized_files = tuple(sorted({Path(path).as_posix() for path in files}))
    closure = resolve_python_proof_sources(root, normalized_files, normalized_files)
    source_edges = {
        (edge.importer_path, edge.module): edge
        for edge in closure.edges
        if edge.kind == "source-import"
    }
    path_modules = {
        path: module
        for path in normalized_files
        if (module := _module_name(path)) is not None
    }
    selected: dict[tuple[str, str, str], set[str]] = {}

    for importer_path in normalized_files:
        source_path = root / importer_path
        try:
            tree = ast.parse(source_path.read_bytes(), filename=importer_path)
        except (OSError, SyntaxError) as exc:
            raise ProofSourceError(
                f"cannot inspect proof source imports for {importer_path!r}: {exc}"
            ) from exc
        importer_module = path_modules.get(importer_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = _absolute_import_module(
                importer_path, importer_module, node.level, node.module
            )
            if module is None:
                continue
            base_edge = source_edges.get((importer_path, module))
            for alias in node.names:
                if alias.name == "*":
                    if base_edge is not None:
                        raise ProofSourceError(
                            f"proved source import {importer_path!r} uses unsupported "
                            "wildcard import"
                        )
                    continue
                child_edge = source_edges.get(
                    (importer_path, f"{module}.{alias.name}")
                )
                provider = child_edge or base_edge
                if provider is None:
                    continue
                key = (
                    provider.importer_path,
                    provider.module,
                    provider.provider_path,
                )
                symbols = selected.setdefault(key, set())
                if child_edge is None:
                    symbols.add(alias.name)

    return tuple(
        ProofSourceEdge(
            importer_path,
            module,
            provider_path,
            tuple(sorted(symbols)),
            "source-import",
        )
        for (importer_path, module, provider_path), symbols in sorted(selected.items())
    )


def _module_name(path: str) -> str | None:
    parts = list(Path(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _import_requests(
    node: ast.AST,
    importer_path: str,
    importer_module: str | None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if isinstance(node, ast.Import):
        return tuple((alias.name, ()) for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    module = _absolute_import_module(
        importer_path, importer_module, node.level, node.module
    )
    if module is None:
        return ()
    symbols = tuple(alias.name for alias in node.names)
    return ((module, symbols),)


def _absolute_import_module(
    importer_path: str,
    importer_module: str | None,
    level: int,
    imported_module: str | None,
) -> str | None:
    if level == 0:
        return imported_module
    if importer_module is None:
        raise ProofSourceError(
            f"relative import in {importer_path!r} has no importable module context"
        )
    importer = Path(importer_path)
    package_parts = importer_module.split(".")
    if importer.name != "__init__.py":
        package_parts.pop()
    ascents = level - 1
    if ascents >= len(package_parts):
        raise ProofSourceError(
            f"relative import in {importer_path!r} escapes its application package"
        )
    if ascents:
        package_parts = package_parts[:-ascents]
    if imported_module:
        package_parts.extend(imported_module.split("."))
    return ".".join(package_parts) or None


def _include_parent_initializers(
    importer_path: str,
    provider_path: str,
    manifest: frozenset[str],
    path_modules: dict[str, str],
    included: set[str],
    pending: list[str],
    edges: set[ProofSourceEdge],
) -> None:
    parent = Path(provider_path).parent
    while parent != Path("."):
        initializer = (parent / "__init__.py").as_posix()
        if initializer in manifest:
            module = path_modules.get(initializer)
            if module is not None:
                edges.add(ProofSourceEdge(
                    importer_path,
                    module,
                    initializer,
                    (),
                    "package-initializer",
                ))
                if initializer not in included:
                    included.add(initializer)
                    pending.append(initializer)
        parent = parent.parent


def _unsealed_local_candidates(
    root: Path, module: str, manifest: frozenset[str]
) -> list[str]:
    relative = Path(*module.split("."))
    candidates = (relative.with_suffix(".py"), relative / "__init__.py")
    return sorted(
        candidate.as_posix()
        for candidate in candidates
        if candidate.as_posix() not in manifest and (root / candidate).is_file()
    )
