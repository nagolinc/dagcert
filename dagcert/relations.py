"""Source-bound relational obligations discharged by the existing proof backend.

This module constructs proof obligations; it does not prove Python expressions.  A
deterministic, temporary proof view adds outcome-conditioned assertions at every
return of the real operation.  Mypy and the selected semantic verifier check that
view, and the result binds both the original source and the transformation.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from .contract import Contract
from .proof_sources import ProofSourceError, resolve_python_proof_sources
from .relation_types import RelationTypeError, compiler_return_bindings
from .source_types import SourceProofBackend, SourceTypeError, check_python_sources


class RelationError(ValueError):
    """A requested source relation cannot be bound or proved."""


@dataclass(frozen=True, slots=True)
class SourceRelation:
    id: str
    task_id: str
    outcome_type: str
    predicate: str


_TRANSFORMATION = "compiler-bound-outcome-relations/v3"
_NAGINI_TYPE_STUB = """from typing import TypeVar

T = TypeVar("T")

def Ensures(expression: bool) -> None: ...
def Old(value: T) -> T: ...
def ResultT(kind: type[T]) -> T: ...
"""
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Attribute, ast.Name, ast.Constant, ast.Call, ast.Load,
    ast.And, ast.Or, ast.Not, ast.UAdd, ast.USub,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
)


def parse_relation_predicate(predicate: str) -> ast.expr:
    """Parse a deliberately non-executable specification expression.

    Field existence, types, arithmetic safety, and truth belong to the real
    compiler/verifier, not this syntactic/provenance allowlist.
    """
    if not isinstance(predicate, str) or not predicate.strip():
        raise RelationError("source relation predicate must be a nonempty expression")
    try:
        expression = ast.parse(predicate, mode="eval")
    except SyntaxError as exc:
        raise RelationError(f"invalid source relation expression: {exc.msg}") from exc
    for node in ast.walk(expression):
        if not isinstance(node, _ALLOWED_NODES):
            raise RelationError(
                f"source relation contains unsupported syntax {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in {"input", "result", "len"}:
            raise RelationError(f"source relation contains unbound name {node.id!r}")
        if isinstance(node, ast.Attribute):
            root: ast.expr = node
            while isinstance(root, ast.Attribute):
                if root.attr.startswith("__"):
                    raise RelationError("source relation may not inspect dunder attributes")
                root = root.value
            if not isinstance(root, ast.Name) or root.id not in {"input", "result"}:
                raise RelationError("source relation fields must belong to input or result")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id != "len"
            or len(node.args) != 1 or node.keywords
        ):
            raise RelationError("source relation permits only the builtin len(value) call")
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise RelationError("source relation has an unsupported constant")
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise RelationError("source relation constants must be finite")
    # A bare `len` is not a value projection, even though it is an allowed callee.
    callee_names = {id(node.func) for node in ast.walk(expression) if isinstance(node, ast.Call)}
    if any(
        isinstance(node, ast.Name) and node.id == "len" and id(node) not in callee_names
        for node in ast.walk(expression)
    ):
        raise RelationError("len is permitted only as a builtin call")
    return expression.body


class _Substitute(ast.NodeTransformer):
    def __init__(self, parameter: str, result: str) -> None:
        self.names = {"input": parameter, "result": result}

    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.copy_location(
            ast.Name(id=self.names.get(node.id, node.id), ctx=node.ctx), node,
        )


class _InputSnapshots(ast.NodeTransformer):
    """Capture entry projections, not a parameter that production may rebind.

    Scalar projections capture their entry values. Composite references retain
    reference identity, not a deep-copy promise; quantitative consumers must use
    scalar projections. A length projection captures the length itself.
    """

    def __init__(self, parameter: str, prefix: str) -> None:
        self.parameter = parameter
        self.prefix = prefix
        self.names: dict[str, str] = {}
        self.assignments: list[ast.stmt] = []

    @staticmethod
    def _is_input(node: ast.expr) -> bool:
        while isinstance(node, ast.Attribute):
            node = node.value
        return isinstance(node, ast.Name) and node.id == "input"

    def _snapshot(self, expression: ast.expr) -> ast.Name:
        key = ast.dump(expression, include_attributes=False)
        name = self.names.get(key)
        if name is None:
            name = f"{self.prefix}{len(self.names)}"
            self.names[key] = name
            source = _Substitute(self.parameter, "result").visit(deepcopy(expression))
            assert isinstance(source, ast.expr)
            self.assignments.append(ast.Assign(
                targets=[ast.Name(id=name, ctx=ast.Store())], value=source,
            ))
        return ast.copy_location(ast.Name(id=name, ctx=ast.Load()), expression)

    def visit_Attribute(self, node: ast.Attribute) -> ast.expr:
        return self._snapshot(node) if self._is_input(node) else node

    def visit_Call(self, node: ast.Call) -> ast.expr:
        if len(node.args) == 1 and self._is_input(node.args[0]):
            return self._snapshot(node)
        transformed = self.generic_visit(node)
        assert isinstance(transformed, ast.expr)
        return transformed


class _PostconditionExpression(ast.NodeTransformer):
    def __init__(
        self, parameter: str, result_name: str, old_name: str, outcome_type: str,
    ) -> None:
        self.parameter = parameter
        self.result_name = result_name
        self.old_name = old_name
        self.outcome_type = outcome_type

    def _old(self, expression: ast.expr) -> ast.Call:
        source = _Substitute(self.parameter, "result").visit(deepcopy(expression))
        assert isinstance(source, ast.expr)
        return ast.Call(
            func=ast.Name(id=self.old_name, ctx=ast.Load()), args=[source], keywords=[],
        )

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if node.id == "result":
            return ast.Call(
                func=ast.Name(id=self.result_name, ctx=ast.Load()),
                args=[ast.parse(self.outcome_type, mode="eval").body], keywords=[],
            )
        if node.id == "input":
            return self._old(node)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.expr:
        if _InputSnapshots._is_input(node):
            return self._old(node)
        transformed = self.generic_visit(node)
        assert isinstance(transformed, ast.expr)
        return transformed

    def visit_Call(self, node: ast.Call) -> ast.expr:
        if len(node.args) == 1 and _InputSnapshots._is_input(node.args[0]):
            return self._old(node)
        transformed = self.generic_visit(node)
        assert isinstance(transformed, ast.expr)
        return transformed


class _ReturnAssertions(ast.NodeTransformer):
    def __init__(
        self, parameter: str, relations: tuple[SourceRelation, ...], fresh: str,
        snapshots: _InputSnapshots, return_annotation: ast.expr | None,
        return_modes: list[dict[str, str]] | None,
    ) -> None:
        self.parameter = parameter
        self.relations = relations
        self.fresh = fresh
        self.snapshots = snapshots
        self.return_annotation = return_annotation
        self.return_count = 0
        self.return_modes = return_modes

    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        if node.value is None:
            raise RelationError("source relations require explicit typed return values")
        self.return_count += 1
        name = f"{self.fresh}{self.return_count}"
        result = ast.Name(id=name, ctx=ast.Load())
        assignment: ast.stmt
        if self.return_annotation is None:
            assignment = ast.Assign(
                targets=[ast.Name(id=name, ctx=ast.Store())], value=node.value,
            )
        else:
            assignment = ast.AnnAssign(
                target=ast.Name(id=name, ctx=ast.Store()), annotation=deepcopy(self.return_annotation),
                value=node.value, simple=1,
            )
        statements: list[ast.stmt] = [assignment]
        for relation in self.relations:
            mode = "possible"
            if self.return_modes is not None:
                if self.return_count > len(self.return_modes):
                    raise RelationError("compiler return coverage omits an actual source return")
                mode = self.return_modes[self.return_count - 1][relation.outcome_type]
            if mode == "never":
                # Mypy's overlap test is an optimization hint, not a semantic
                # disjointness proof (multiple inheritance can overlap nominal
                # classes). Require the real backend to prove inapplicability.
                statements.append(ast.Assert(test=ast.UnaryOp(
                    op=ast.Not(), operand=ast.Call(
                        func=ast.Name(id="isinstance", ctx=ast.Load()),
                        args=[deepcopy(result), ast.parse(relation.outcome_type, mode="eval").body],
                        keywords=[],
                    ),
                )))
                continue
            predicate = self.snapshots.visit(parse_relation_predicate(relation.predicate))
            assert isinstance(predicate, ast.expr)
            predicate = _Substitute(self.parameter, name).visit(predicate)
            assert isinstance(predicate, ast.expr)
            outcome = ast.parse(relation.outcome_type, mode="eval").body
            if mode == "always":
                statements.append(ast.Assert(test=predicate))
                continue
            statements.append(ast.If(
                test=ast.Call(
                    func=ast.Name(id="isinstance", ctx=ast.Load()),
                    args=[deepcopy(result), outcome], keywords=[],
                ), body=[ast.Assert(test=predicate)], orelse=[],
            ))
        statements.append(ast.Return(value=result))
        return [ast.copy_location(statement, node) for statement in statements]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Nested helper returns are not owner exits. They are independently proved
        # by the backend along with the rest of the unchanged module.
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        return node


def _function(tree: ast.Module, symbol: str) -> ast.FunctionDef:
    body = tree.body
    node: ast.AST | None = None
    for component in symbol.split("."):
        candidates = [
            item for item in body
            if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == component
        ]
        if len(candidates) != 1:
            raise RelationError(f"relation owner {symbol!r} was not found exactly once")
        node = candidates[0]
        body = node.body
    if not isinstance(node, ast.FunctionDef):
        raise RelationError("source relation owner must be a synchronous function")
    return node


def build_relation_proof_view(
    source: str,
    symbol: str,
    relations: Iterable[SourceRelation],
    *,
    backend_postconditions: bool = False,
    annotate_results: bool = True,
    return_modes: list[dict[str, str]] | None = None,
) -> tuple[str, int]:
    """Return deterministic instrumented source and the number of covered exits."""
    requested = tuple(relations)
    if not requested:
        raise RelationError("source relation proof view requires at least one relation")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RelationError(f"cannot parse relation owner source: {exc}") from exc
    function = _function(tree, symbol)
    parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    if len(parameters) != 1 or function.args.vararg or function.args.kwarg:
        raise RelationError("source relations require one source-typed operation input")
    # Cleanup runs after evaluation of a return expression and can change the
    # returned object. Pre-return assertions cannot establish a post-cleanup fact.
    cleanup = any(
        isinstance(node, (ast.With, ast.AsyncWith, ast.Yield, ast.YieldFrom))
        or isinstance(node, (ast.Try, ast.TryStar)) and bool(node.finalbody)
        for node in ast.walk(function)
    )
    if cleanup and not backend_postconditions:
        raise RelationError(
            "source relation owner uses cleanup/yield after return evaluation; "
            "this proof-view transformation requires backend postcondition support"
        )
    # Do not let an application override the operators used by generated proof
    # expressions. Ordinary fields named len/isinstance are not global bindings.
    reserved = {"isinstance", "len"}
    for node in ast.walk(tree):
        binding: str | None = None
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            binding = node.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binding = node.name
        elif isinstance(node, ast.arg):
            binding = node.arg
        elif isinstance(node, ast.alias):
            binding = node.asname or node.name.split(".")[0]
        if binding in reserved:
            raise RelationError(f"relation proof builtin {binding!r} is shadowed by source")
    for relation in requested:
        parse_relation_predicate(relation.predicate)
        outcome = ast.parse(relation.outcome_type, mode="eval").body
        if not isinstance(outcome, (ast.Name, ast.Attribute)):
            raise RelationError("source relation outcome must name a source outcome type")
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    prefix = "dagcert_relation_result_"
    while any(name.startswith(prefix) for name in identifiers):
        prefix += "_"
    original_body = deepcopy(function.body)
    snapshots = _InputSnapshots(parameters[0].arg, prefix + "input_")
    if function.returns is None:
        raise RelationError("source relation owner lacks a declared return type")
    transformer = _ReturnAssertions(
        parameters[0].arg, requested, prefix, snapshots,
        function.returns if annotate_results else None,
        return_modes,
    )
    body: list[ast.stmt] = []
    for statement in function.body:
        transformed = transformer.visit(statement)
        if isinstance(transformed, list):
            body.extend(transformed)
        elif isinstance(transformed, ast.stmt):
            body.append(transformed)
        else:  # pragma: no cover - transformer preserves every original statement
            raise RelationError("source relation transformation lost an owner statement")
    # Keep a docstring first; snapshots must precede all executable owner work.
    docstring: list[ast.stmt] = []
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            docstring = [body.pop(0)]
    function.body = [*docstring, *snapshots.assignments, *body]
    if not transformer.return_count:
        raise RelationError("source relation owner contains no explicit return")
    if return_modes is not None and len(return_modes) != transformer.return_count:
        raise RelationError("compiler/source return counts disagree")
    if backend_postconditions:
        # Nagini recognizes these canonical intrinsic names. Its translator does
        # not support renamed imports of every contract builtin.
        ensures_name, result_name, old_name = "Ensures", "ResultT", "Old"
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if node.id in {ensures_name, result_name, old_name}:
                    raise RelationError(f"source shadows canonical verifier intrinsic {node.id}")
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.arg)):
                identifier = node.arg if isinstance(node, ast.arg) else node.name
                if identifier in {ensures_name, result_name, old_name}:
                    raise RelationError(f"source shadows canonical verifier intrinsic {identifier}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound == "*":
                        if not isinstance(node, ast.ImportFrom) or node.module != "nagini_contracts.contracts":
                            raise RelationError("wildcard source imports could shadow verifier intrinsics")
                    if bound not in {ensures_name, result_name, old_name}:
                        continue
                    if (
                        not isinstance(node, ast.ImportFrom)
                        or node.module != "nagini_contracts.contracts"
                        or node.level != 0 or alias.name != bound
                    ):
                        raise RelationError(f"source import shadows canonical verifier intrinsic {bound}")
        declarations: list[ast.stmt] = []
        for relation in requested:
            predicate = _PostconditionExpression(
                parameters[0].arg, result_name, old_name, relation.outcome_type,
            ).visit(parse_relation_predicate(relation.predicate))
            assert isinstance(predicate, ast.expr)
            result_call = ast.Call(
                func=ast.Name(id=result_name, ctx=ast.Load()),
                args=[ast.parse(relation.outcome_type, mode="eval").body], keywords=[],
            )
            guarded = ast.BoolOp(op=ast.Or(), values=[
                ast.UnaryOp(op=ast.Not(), operand=ast.Call(
                    func=ast.Name(id="isinstance", ctx=ast.Load()),
                    args=[result_call, ast.parse(relation.outcome_type, mode="eval").body],
                    keywords=[],
                )), predicate,
            ])
            declarations.append(ast.Expr(value=ast.Call(
                func=ast.Name(id=ensures_name, ctx=ast.Load()), args=[guarded], keywords=[],
            )))
        if docstring:
            original_body.pop(0)
        function.body = [*docstring, *declarations, *original_body]
        import_node = ast.ImportFrom(module="nagini_contracts.contracts", names=[
            ast.alias(name="Ensures"), ast.alias(name="ResultT"), ast.alias(name="Old"),
        ], level=0)
        insertion = 0
        for index, statement in enumerate(tree.body):
            if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
                insertion = index + 1
            elif index == 0 and isinstance(statement, ast.Expr):
                if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                    insertion = 1
        tree.body.insert(insertion, import_node)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", transformer.return_count


def _digest(value: object) -> str:
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def verify_source_relations(
    contract: Contract,
    source_root: str | Path,
    relations: Iterable[SourceRelation],
    proof_backend: SourceProofBackend | None,
    original_source_fingerprint: str,
    *,
    source_manifest_paths: Iterable[str] | None = None,
) -> dict[str, object]:
    """Prove requested relations with the real backend and seal exact provenance.

    Only the already sealed Python import closure and explicit external stubs are
    copied. Assets, environments, and unrelated source are never copied into the
    temporary proof view. No caller-provided pass boolean is accepted.
    """
    from .certificate import (
        external_source_contracts, maledictus_callable_bindings,
        maledictus_embedded_external_calls, source_manifest,
    )

    root = Path(source_root).resolve()
    requested = tuple(sorted(relations, key=lambda item: item.id))
    ids = [relation.id for relation in requested]
    if not requested or any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
        raise RelationError("source relation IDs must be nonempty and unique")
    if not original_source_fingerprint:
        raise RelationError("source relations require the original source fingerprint")
    groups: dict[tuple[str, str], list[SourceRelation]] = {}
    for relation in requested:
        task = contract.task_by_id.get(relation.task_id)
        if task is None or task.role != "operation" or task.source_signature is None:
            raise RelationError(f"relation {relation.id} requires a source-bound operation task")
        signature = task.source_signature
        if signature.language != "python":
            raise RelationError(f"relation {relation.id}: proof-view generation currently requires Python")
        if relation.outcome_type not in signature.outcome_types:
            raise RelationError(f"relation {relation.id} names an unknown source outcome")
        parse_relation_predicate(relation.predicate)
        groups.setdefault((signature.path, signature.symbol), []).append(relation)
    signatures = tuple(
        task.source_signature for task in contract.tasks
        if task.source_signature is not None and task.source_signature.language == "python"
    )
    proof_signatures = tuple(
        task.source_signature for task in contract.tasks
        if task.role == "operation" and task.source_signature is not None
        and task.source_signature.language == "python"
    )
    external = external_source_contracts(contract)
    bindings = maledictus_callable_bindings(contract)
    manifest_paths = tuple(
        source_manifest(root) if source_manifest_paths is None else source_manifest_paths
    )
    root_files = {signature.path for signature in signatures}
    root_files.update(boundary.adapter_path for boundary in external)
    root_files.update(
        binding.provider.path for binding in bindings if hasattr(binding.provider, "path")
    )
    try:
        closure = resolve_python_proof_sources(root, root_files, manifest_paths)
    except ProofSourceError as exc:
        raise RelationError(str(exc)) from exc
    files = set(closure.files)
    files.update(boundary.stub_path for boundary in external)
    files.update(
        binding.provider.stub_path for binding in bindings if hasattr(binding.provider, "stub_path")
    )
    if not files <= set(manifest_paths):
        raise RelationError("relation proof source/stub files must belong to the exact source manifest")
    original: dict[str, bytes] = {}
    for relative in sorted(files):
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RelationError(f"relation proof source escapes root or is absent: {relative}")
        original[relative] = path.read_bytes()
    proof_content = dict(original)
    try:
        return_bindings, compiler_provenance = compiler_return_bindings(
            root, (path for path in files if path.endswith(".py")),
            {key: tuple(sorted({item.outcome_type for item in items})) for key, items in groups.items()},
        )
    except RelationTypeError as exc:
        raise RelationError(str(exc)) from exc
    exits: dict[str, int] = {}
    transformations: dict[str, str] = {}
    for (relative_file, symbol), items in sorted(groups.items()):
        # Backend postconditions run after cleanup. Nagini supports them natively;
        # the alternate backend continues to use semantically proved assertions.
        owner_signature = next(
            signature for signature in signatures
            if signature.path == relative_file and signature.symbol == symbol
        )
        use_postconditions = (
            (proof_backend is None or proof_backend.name == "nagini")
            and len(owner_signature.outcome_types) == 1
        )
        generated, count = build_relation_proof_view(
            proof_content[relative_file].decode("utf-8"), symbol, items,
            backend_postconditions=use_postconditions,
            annotate_results=False,
            return_modes=return_bindings[(relative_file, symbol)],
        )
        proof_content[relative_file] = generated.encode("utf-8")
        exits[f"{relative_file}:{symbol}"] = count
        transformations[f"{relative_file}:{symbol}"] = (
            "nagini-native-postconditions" if use_postconditions else "all-return-assertions"
        )
    if proof_backend is None or proof_backend.name == "nagini":
        # Type signatures only: the real contract semantics come from the pinned
        # verifier's own nagini_contracts implementation, never from these stubs.
        # Do not install Nagini's Java tooling or conflicting mypy on the host.
        for relative_file, content in {
            "nagini_contracts/__init__.pyi": b"",
            "nagini_contracts/contracts.pyi": _NAGINI_TYPE_STUB.encode("utf-8"),
        }.items():
            if relative_file in proof_content:
                raise RelationError("application source shadows canonical verifier contract stubs")
            proof_content[relative_file] = content
    original_hashes = {path: sha256(content).hexdigest() for path, content in original.items()}
    proof_hashes = {path: sha256(content).hexdigest() for path, content in proof_content.items()}
    relation_rows = [asdict(relation) for relation in requested]
    proof_request: dict[str, object] = {
        "transformation": _TRANSFORMATION,
        "original_source_fingerprint": original_source_fingerprint,
        "original_sources": original_hashes,
        "proof_sources": proof_hashes,
        "relations": relation_rows,
        "covered_return_counts": exits,
        "owner_transformations": transformations,
        "compiler_return_coverage": compiler_provenance,
    }
    proof_fingerprint = _digest(proof_request)
    try:
        with TemporaryDirectory(prefix="dagcert-relations-") as temporary:
            view = Path(temporary)
            for relative, content in proof_content.items():
                path = view / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            verification = check_python_sources(
                view, signatures,
                source_fingerprint=proof_fingerprint,
                source_manifest_paths=proof_content,
                proof_signatures=proof_signatures,
                external_contracts=external,
                callable_bindings=bindings,
                embedded_external_calls=maledictus_embedded_external_calls(
                    contract, view, source_manifest_paths=proof_content,
                ),
                proof_backend=proof_backend,
            )
    except SourceTypeError as exc:
        raise RelationError(f"source relational proof refused: {exc}") from exc
    if any((root / path).read_bytes() != content for path, content in original.items()):
        raise RelationError("application source changed during relational verification")
    return {
        "schema": "dagcert-source-relations/v1",
        **proof_request,
        "proof_fingerprint": proof_fingerprint,
        "verification": verification,
        "status": "proved",
    }
