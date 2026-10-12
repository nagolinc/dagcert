"""Native dependency contracts and annotation-only views for public source checks.

This is proof input, never an imported proof result. Every invocation reruns the
backend. Executable application code cannot be replaced by a ContractOnly stub.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from .maledictus_verifier import MaledictusExternalBoundary

_GHOST = {"Requires", "Ensures", "Exsures", "Assert", "Invariant"}
_IMPORTS = _GHOST | {"Old", "Result", "ResultT", "Acc", "Rd", "Predicate", "Implies", "Forall", "Exists", "Let", "Previous", "Unfolding", "Fold", "Unfold", "list_pred", "dict_pred", "set_pred"}


def _ghost(node: ast.AST) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id in _GHOST)


def _predicate(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef) and any(
        isinstance(d, ast.Name) and d.id == "Predicate" for d in node.decorator_list)


def _erase(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if ((isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in _IMPORTS)
                or (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in _IMPORTS)
                or (isinstance(node, ast.arg) and node.arg in _IMPORTS)):
            raise ValueError("proof annotation names may not be shadowed")
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not (
            isinstance(node, ast.ImportFrom) and node.module == "nagini_contracts.contracts"
        ) and any((a.asname or a.name.split('.')[0]) in _IMPORTS for a in node.names):
            raise ValueError("proof annotation names require canonical imports")
    class Erase(ast.NodeTransformer):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
            return None if _predicate(node) else self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
            self.generic_visit(node)
            node.body = node.body or [ast.Pass()]
            return node

        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
            if node.module == "nagini_contracts.contracts":
                if any(a.asname or a.name not in _IMPORTS for a in node.names):
                    raise ValueError("unsupported or aliased proof annotation import")
                return None
            return node

        def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
            return None if _ghost(node) else self.generic_visit(node)

    result = Erase().visit(deepcopy(tree))
    if not isinstance(result, ast.AST):
        raise ValueError("annotation view erased its module")
    return result


def annotation_view(source: str, annotated: str) -> str:
    """Preserve executable AST and any postconditions added by Dagcert itself."""
    original, proposed = ast.parse(source), ast.parse(annotated)
    predicate_names = {n.name for n in ast.walk(proposed) if isinstance(n, ast.FunctionDef) and _predicate(n)}
    for node in ast.walk(_erase(original)):
        if ((isinstance(node, ast.Name) and node.id in predicate_names)
                or (isinstance(node, ast.Attribute) and node.attr in predicate_names)):
            raise ValueError("proof-only predicate is referenced by executable source")
    if ast.dump(_erase(original)) != ast.dump(_erase(proposed)):
        raise ValueError("proof annotations change executable source")
    # Merge ghost statements by their position among executable statements. This
    # also preserves generated relation obligations inside nested blocks.
    def merge(left: ast.AST, right: ast.AST) -> None:
        for field, values in ast.iter_fields(left):
            other = getattr(right, field, None)
            if isinstance(values, list) and isinstance(other, list):
                def ordinary(n: Any) -> bool:
                    return not (_ghost(n) or _predicate(n) or isinstance(n, ast.Pass) or isinstance(n, ast.ImportFrom)
                                and n.module == "nagini_contracts.contracts")
                lreal = [n for n in values if ordinary(n)]
                rreal = [n for n in other if ordinary(n)]
                for a, b in zip(lreal, rreal, strict=True):
                    if isinstance(a, ast.AST) and isinstance(b, ast.AST):
                        merge(a, b)
                existing = {ast.dump(n) for n in other if isinstance(n, ast.AST)}
                position = 0
                for node in values:
                    if ordinary(node):
                        position += 1
                    elif ast.dump(node) not in existing:
                        offset = next((i for i, n in enumerate(other)
                                       if ordinary(n) and sum(ordinary(x) for x in other[:i]) == position), len(other))
                        other.insert(offset, deepcopy(node))
                        existing.add(ast.dump(node))
            elif isinstance(values, ast.AST) and isinstance(other, ast.AST):
                merge(values, other)
    merge(original, proposed)
    return ast.unparse(ast.fix_missing_locations(proposed)) + "\n"


def check_native_bundle(root: Any, signatures: Any, proof_signatures: Any, backend: Any,
                        **options: Any) -> dict[str, Any] | None:
    """Check disjoint task components separately, retaining their native scopes."""
    from .source_types import SourceTypeError, check_python_sources

    path = Path(backend.native_proof_support)
    body = path.read_bytes()
    document = json.loads(body)
    if document.get("schema") != "dagcert-native-proof-bundle/v1":
        return None
    if set(document) != {"schema", "components"} or not isinstance(document["components"], list):
        raise SourceTypeError("invalid native proof bundle")
    if any(options[name] for name in ("external_contracts", "callable_bindings", "embedded_external_calls")):
        raise SourceTypeError("native proof bundles currently contain closed operation tasks only")
    requested = {(s.path, s.symbol): s for s in proof_signatures}
    if requested.keys() != {(s.path, s.symbol) for s in signatures}:
        raise SourceTypeError("native proof bundle must cover exactly the bound operations")
    manifest = options["source_manifest_paths"]
    options["source_manifest_paths"] = tuple(manifest) if manifest is not None else None
    covered: set[tuple[str, str]] = set()
    components = []
    for row in document["components"]:
        if set(row) not in ({"operations", "support", "sha256"}, {"operations", "support", "sha256", "backend"}):
            raise SourceTypeError("invalid native proof component")
        identities = {(v["path"], v["symbol"]) for v in row["operations"]}
        selected = identities & requested.keys()
        if not selected:
            continue
        if covered & selected:
            raise SourceTypeError("native proof component coverage overlaps")
        covered.update(selected)
        support = (path.parent / row["support"]).resolve()
        if sha256(support.read_bytes()).hexdigest() != row["sha256"]:
            raise SourceTypeError("native proof component digest mismatch")
        if json.loads(support.read_bytes()).get("schema") != "dagcert-native-proof-support/v1":
            raise SourceTypeError("native proof components must be leaves, not nested bundles")
        selected_signatures = tuple(requested[key] for key in sorted(selected))
        component_options = {**options, "required_postcondition_files": tuple(
            p for p in options["required_postcondition_files"] if p in {s.path for s in selected_signatures})}
        component_backend = replace(backend, native_proof_support=str(support))
        if "backend" in row:
            pin = row["backend"]
            if set(pin) != {"executable", "sha256"}:
                raise SourceTypeError("component backend requires an explicit executable and digest")
            component_backend = replace(component_backend, executable=str(Path(pin["executable"]).resolve()),
                                        executable_sha256=pin["sha256"])
        logging.getLogger(__name__).info("Proving source component: %s", sorted(selected))
        result = check_python_sources(root, selected_signatures, proof_signatures=selected_signatures,
            proof_backend=component_backend, **component_options)
        logging.getLogger(__name__).info("Proved source component: %s", sorted(selected))
        components.append({"operations": [list(key) for key in sorted(selected)],
                           "support_sha256": row["sha256"], "verification": result})
    if covered != requested.keys():
        raise SourceTypeError("native proof bundle omits bound operations")
    return {"provider": "dagcert.python-source-verification/v3", "type_checker": {
                "checker": "mypy", "mode": "sealed-native-component-contracts"},
            "exception_verifier": {"checker": "maledictus", "result": "proved",
                "source_fingerprint": options["source_fingerprint"], "bundle_sha256": sha256(body).hexdigest(),
                "components": components},
            "signatures": [s for c in components for s in c["verification"]["signatures"]]}


@contextmanager
def native_proof_view(root: Path, files: tuple[str, ...], support_path: str,
                      manifest: frozenset[str] | None, operations: dict[str, tuple[str, ...]]) -> Iterator[tuple[Path, tuple[MaledictusExternalBoundary, ...], dict[str, Any]]]:
    from .source_types import _resolve_external_provider, read_python_signature

    path = Path(support_path).resolve()
    raw = path.read_bytes()
    support = json.loads(raw)
    if set(support) != {"schema", "annotations", "native_contracts"} or support["schema"] != "dagcert-native-proof-support/v1":
        raise ValueError("invalid native proof support document")
    annotations = support["annotations"]
    if not isinstance(annotations, dict) or not isinstance(support["native_contracts"], list):
        raise ValueError("invalid native proof support collections")
    originals = {name: (root / name).read_bytes() for name in files}
    sources = dict(originals)
    identities: dict[str, Any] = {"schema": support["schema"], "document_sha256": sha256(raw).hexdigest(),
                                  "annotations": {}, "native_contracts": []}

    def input_bytes(entry: dict[str, Any]) -> bytes:
        body = (path.parent / str(entry["path"])).read_bytes()
        if sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("native proof support input digest mismatch")
        return body

    for name, entry in annotations.items():
        if name not in sources:
            continue
        proof = input_bytes(entry)
        sources[name] = annotation_view(sources[name].decode("utf-8"), proof.decode("utf-8")).encode("utf-8")
        identities["annotations"][name] = {"annotation_sha256": entry["sha256"], "view_sha256": sha256(sources[name]).hexdigest()}
    boundaries = []
    stubs: dict[str, bytes] = {}
    seen: set[str] = set()
    for row in support["native_contracts"]:
        if row["adapter_path"] not in sources:
            continue
        if not isinstance(row["assumption"], str) or not row["assumption"].strip():
            raise ValueError("native provider contract requires an explicit assumption")
        provider = _resolve_external_provider(root, row["provider_module"], manifest)
        module_path = row["provider_module"].replace(".", "/")
        if manifest is not None and ({module_path + ".py", module_path + "/__init__.py"} & manifest):
            raise ValueError("native proof support cannot trust application-owned provider code: " + row["provider_module"])
        body = input_bytes(row["stub"])
        stub = "_dagcert_native/" + sha256(body).hexdigest() + ".py"
        if stub in sources:
            raise ValueError("native stub collides with executable application source")
        stubs[stub] = body
        boundary = MaledictusExternalBoundary(row["boundary_id"], row["adapter_path"], row["adapter_symbol"],
            stub, row["provider_module"], tuple(row["provider_symbols"]), row["exception_policy"])
        if boundary.boundary_id in seen:
            raise ValueError("duplicate native proof boundary identity")
        seen.add(boundary.boundary_id)
        boundaries.append(boundary)
        identities["native_contracts"].append({**row, "provider_identity": provider, "materialized_stub": stub})
    with TemporaryDirectory(prefix="dagcert-native-proof-") as temporary:
        view = Path(temporary)
        for name, body in {**sources, **stubs}.items():
            destination = (view / name).resolve()
            if not destination.is_relative_to(view):
                raise ValueError("native proof source path escapes view")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
        # An annotation may strengthen checked helper preconditions, but never
        # restrict a closed operation's caller or add a trusted operation body.
        postconditions = []
        for name in annotations.keys() & sources.keys() & operations.keys():
            for symbol in operations[name]:
                read_python_signature(view, name, symbol)
                tree = ast.parse(sources[name])
                target = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol)
                if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "Ensures" for n in ast.walk(target)):
                    postconditions.append(name)
        identities["required_postcondition_files"] = sorted(set(postconditions))
        yield view, tuple(boundaries), identities
    if any((root / name).read_bytes() != body for name, body in originals.items()):
        raise ValueError("application source changed during native proof verification")
