"""Source-owned operation signatures used by hardened Dagcert contracts.

The contract points at code.  It does not get to restate the code's types.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import ast
import dataclasses as dataclasses_module
from hashlib import sha256
import importlib.metadata
import importlib.util
import json
import os
import re
import sys

from .python_verifier import PythonVerificationError, verify_exception_freedom


class SourceTypeError(ValueError):
    pass


def type_enforcement_descriptor() -> dict[str, object]:
    """Return the exact source/runtime type kernel sealed into new certificates."""
    from ._version import VERSION

    package = Path(__file__).resolve().parent
    kernel_files = (
        "_version.py", "__init__.py", "analysis.py", "certificate.py", "contract.py",
        "evidence.py", "formula.py", "requirements.py", "runtime.py", "runtime.pyi",
        "python_verifier.py", "source_types.py",
        "nagini_stubs/dagcert/__init__.pyi", "nagini_stubs/dagcert/runtime.pyi",
        "mypy_stubs/dagcert/__init__.pyi", "mypy_stubs/dagcert/runtime.pyi",
    )
    manifest = {
        name: sha256((package / name).read_bytes()).hexdigest()
        for name in kernel_files
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return {
        "provider": "dagcert.python/v6",
        "dagcert_version": VERSION,
        "static_analysis": "source-ast+strict-mypy/v1",
        "mypy_import_surface": "sealed-type-preserving-dagcert-stub/v1",
        "decorator_provenance": "trusted-imports-and-shadow-rejection/v1",
        "operation_marker": "type-preserving/v1",
        "exception_verification": "nagini-viper-external-contract-overlays/v3",
        "external_contracts": "p1-contract-only+typeguard-runtime/v2",
        "reachability": "typed-may-must/v1",
        "chance_composition": "engineering-envelope-exact-path+external/v3",
        "kernel_manifest": manifest,
        "kernel_sha256": sha256(manifest_bytes).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class SourceSignature:
    language: str
    path: str
    symbol: str
    input_type: str
    outcome_types: tuple[str, ...]
    line: int


@dataclass(frozen=True, slots=True)
class ExternalSourceContract:
    boundary_id: str
    adapter_path: str
    symbol: str
    stub_path: str
    provider_module: str
    provider_symbols: tuple[str, ...]
    assumption: str
    signature: SourceSignature


def check_python_sources(
    source_root: str | Path,
    signatures: Iterable[SourceSignature],
    *,
    source_fingerprint: str | None = None,
    prove_exceptions: bool = True,
    proof_signatures: Iterable[SourceSignature] | None = None,
    external_contracts: Iterable[ExternalSourceContract] = (),
) -> dict[str, object]:
    """Run strict mypy and external exception verification over real implementation files.

    Dagcert invokes mypy itself.  A checker result supplied by the application or an LLM is not
    accepted as a substitute.
    """
    bound_signatures = tuple(signatures)
    proof_bound_signatures = (
        bound_signatures if proof_signatures is None else tuple(proof_signatures)
    )
    external_boundaries = tuple(external_contracts)
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
    mypy_stub_root = str(Path(__file__).resolve().parent / "mypy_stubs")
    previous_path = os.environ.get("MYPYPATH")
    os.environ["MYPYPATH"] = os.pathsep.join(
        item for item in (mypy_stub_root, str(root), package_root, previous_path) if item
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
    signatures_result = [
        {
            "path": item.path,
            "symbol": item.symbol,
            "line": item.line,
            "input_type": item.input_type,
            "outcome_types": list(item.outcome_types),
        }
        for item in sorted(bound_signatures, key=lambda value: (value.path, value.symbol))
    ]
    if not prove_exceptions:
        return {
            "checker": "mypy",
            "version": mypy_version,
            "mode": "strict",
            "files": list(files),
            "signatures": signatures_result,
        }
    if source_fingerprint is None:
        raise SourceTypeError("source fingerprint is required for sealed exception verification")
    external_results = [
        _validate_external_source_contract(root, item)
        for item in external_boundaries
    ]
    overlays = {item.adapter_path: item.stub_path for item in external_boundaries}
    if len(overlays) != len(external_boundaries):
        raise SourceTypeError(
            "each external adapter module may have only one ContractOnly overlay"
        )
    proof_files = tuple(sorted({item.path for item in proof_bound_signatures}))
    if proof_files:
        symbols_by_file = {
            path: tuple(item.symbol for item in proof_bound_signatures if item.path == path)
            for path in proof_files
        }
        try:
            exception_verification = verify_exception_freedom(
                root,
                proof_files,
                symbols_by_file,
                source_fingerprint=source_fingerprint,
                external_overlays=overlays,
            )
        except PythonVerificationError as exc:
            raise SourceTypeError(str(exc)) from exc
    else:
        exception_verification = {
            "checker": "nagini",
            "version": None,
            "proof_obligation": "no-undeclared-exceptional-exit",
            "result": "not-applicable",
            "reason": "contract contains no operation tasks; instrumentation is observational",
            "source_fingerprint": source_fingerprint,
            "files": [],
        }
    return {
        "provider": "dagcert.python-source-verification/v1",
        "type_checker": {
            "checker": "mypy",
            "version": mypy_version,
            "mode": "strict",
            "dagcert_import_surface": "sealed-type-preserving-stub",
            "files": list(files),
        },
        "exception_verifier": exception_verification,
        "external_contracts": external_results,
        "signatures": signatures_result,
    }


def read_python_signature(
    source_root: str | Path, relative_path: str, symbol: str, *,
    include_legacy_unhandled: bool = False,
    external_boundary_id: str | None = None,
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
    _reject_trusted_module_shadowing(root, path)
    try:
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(path), type_comments=True)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise SourceTypeError(f"cannot parse implementation source {relative_path}: {exc}") from exc

    _reject_type_escape_hatches(tree, source_text, relative_path)

    function = _find_function(tree, symbol)
    if isinstance(function, ast.AsyncFunctionDef):
        raise SourceTypeError(
            f"operation {symbol} is async; the current Python provider certifies only "
            "synchronous guarded boundaries"
        )
    operation_decorators, external_decorators, dataclass_decorators = _trusted_decorators(tree)
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
    outcome_nodes = tuple(_flatten_union(function.returns))
    if external_boundary_id is not None and len(outcome_nodes) != 1:
        raise SourceTypeError(
            f"external boundary {symbol} must declare exactly one success return type; Dagcert "
            "adds monitored raised/type-violation outcomes at the decorator boundary"
        )
    outcomes: tuple[str, ...] = tuple(
        _annotation(item, f"operation {symbol} outcome") for item in outcome_nodes
    )
    variant_nodes = (parameter.annotation, *outcome_nodes)
    for variant_node in variant_nodes:
        variant_name = _annotation(variant_node, f"operation {symbol} type")
        class_node, class_nodes, resolved_dataclasses = _resolve_variant_definition(
            root, path, tree, variant_node, f"operation {symbol} type {variant_name}",
        )
        _validate_variant_class(
            class_node, f"operation {symbol} type {variant_name}",
            class_nodes, set(), resolved_dataclasses,
        )
    if len(outcomes) != len(set(outcomes)):
        raise SourceTypeError(f"operation {symbol} return union contains duplicate variants")
    if any(item in {"None", "NoneType", "object"} for item in outcomes):
        raise SourceTypeError(
            f"operation {symbol} return union must use explicit named outcomes, not None/object"
        )
    if external_boundary_id is not None:
        _require_external_boundary_decorator(
            function.decorator_list, external_decorators, external_boundary_id, symbol,
        )
        _reject_contract_only_in_executable_module(tree, relative_path)
        outcomes = (
            outcomes[0],
            "dagcert.runtime.ExternalRaised",
            "dagcert.runtime.ExternalTypeViolation",
        )
    elif _has_operation_decorator(function.decorator_list, operation_decorators):
        _reject_nagini_proof_escape_hatches(
            function, tree, relative_path, symbol, input_type,
        )
        _reject_operation_exsures(function, tree, symbol)
    else:
        raise SourceTypeError(
            f"operation {symbol} must use @dagcert.runtime.operation so its real proof boundary "
            "is source-visible"
        )
    if include_legacy_unhandled:
        outcomes = (*outcomes, "dagcert.runtime.UnhandledException")
    return SourceSignature(
        "python", Path(relative_path).as_posix(), symbol, input_type,
        tuple(dict.fromkeys(outcomes)), function.lineno,
    )


def validate_external_contract_stub(
    source_root: str | Path,
    relative_path: str,
    symbol: str,
    signature: SourceSignature,
) -> dict[str, object]:
    """Validate a source-owned Nagini ContractOnly stub for one external adapter."""

    root = Path(source_root).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SourceTypeError(f"external contract stub escapes source root: {relative_path}") from exc
    if not path.is_file():
        raise SourceTypeError(f"external contract stub does not exist: {relative_path}")
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as exc:
        raise SourceTypeError(f"cannot parse external contract stub {relative_path}: {exc}") from exc
    _reject_type_escape_hatches(tree, source, relative_path)
    _validate_external_module_surface(
        tree,
        symbol,
        {signature.input_type, signature.outcome_types[0]},
        f"external ContractOnly stub {relative_path}",
    )
    function = _find_function(tree, symbol)
    if isinstance(function, ast.AsyncFunctionDef):
        raise SourceTypeError("external ContractOnly stubs must be synchronous")
    contract_only = _nagini_contract_names(tree, "ContractOnly")
    if not any(
        _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        in contract_only
        for decorator in function.decorator_list
    ):
        raise SourceTypeError(
            f"external contract stub {relative_path}:{symbol} must use Nagini @ContractOnly"
        )
    if len((*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)) != 1:
        raise SourceTypeError(f"external contract stub {symbol} must accept exactly one input")
    parameter = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)[0]
    if parameter.annotation is None or function.returns is None:
        raise SourceTypeError(f"external contract stub {symbol} must be fully annotated")
    input_type = _annotation(parameter.annotation, f"external contract stub {symbol} input")
    if input_type != signature.input_type:
        raise SourceTypeError(
            f"external contract stub {symbol} input {input_type!r} does not match real adapter "
            f"input {signature.input_type!r}"
        )
    stub_success = _annotation(
        function.returns, f"external contract stub {symbol} return",
    )
    if stub_success != signature.outcome_types[0]:
        raise SourceTypeError(
            f"external contract stub {symbol} must return the adapter success type "
            f"{signature.outcome_types[0]!r}; observed {stub_success!r}. The proof stub is the "
            "explicit p=1 premise, while runtime monitoring adds violation outcomes."
        )
    _validate_canonical_external_ensures(tree, function, relative_path, symbol)
    return {
        "path": Path(relative_path).as_posix(),
        "symbol": symbol,
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "input_type": signature.input_type,
        "outcome_types": list(signature.outcome_types),
        "assumption_kind": "nagini-contract-only",
    }


def _validate_external_source_contract(
    root: Path, contract: ExternalSourceContract,
) -> dict[str, object]:
    stub = validate_external_contract_stub(
        root, contract.stub_path, contract.symbol, contract.signature,
    )
    adapter = (root / contract.adapter_path).resolve()
    try:
        adapter.relative_to(root)
    except ValueError as exc:
        raise SourceTypeError(
            f"external adapter escapes source root: {contract.adapter_path}"
        ) from exc
    source = adapter.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(adapter), type_comments=True)
    _validate_external_module_surface(
        tree,
        contract.symbol,
        {contract.signature.input_type, contract.signature.outcome_types[0]},
        f"external adapter {contract.adapter_path}",
    )
    stub_path = (root / contract.stub_path).resolve()
    stub_tree = ast.parse(
        stub_path.read_text(encoding="utf-8"), filename=str(stub_path), type_comments=True,
    )
    adapter_function = _find_function(tree, contract.symbol)
    stub_function = _find_function(stub_tree, contract.symbol)
    adapter_parameters = (*adapter_function.args.posonlyargs, *adapter_function.args.args)
    stub_parameters = (*stub_function.args.posonlyargs, *stub_function.args.args)
    assert adapter_parameters[0].annotation is not None
    assert stub_parameters[0].annotation is not None
    assert adapter_function.returns is not None
    assert stub_function.returns is not None
    adapter_nodes = (adapter_parameters[0].annotation, *_flatten_union(adapter_function.returns))
    stub_nodes = (stub_parameters[0].annotation, stub_function.returns)
    for variant, adapter_node, stub_node in zip(
        (contract.signature.input_type, contract.signature.outcome_types[0]),
        adapter_nodes,
        stub_nodes,
        strict=True,
    ):
        adapter_shape = _variant_field_schema(
            root, adapter, tree, adapter_node, f"external adapter {contract.adapter_path}",
        )
        stub_shape = _variant_field_schema(
            root, stub_path, stub_tree, stub_node,
            f"external contract stub {contract.stub_path}",
        )
        if adapter_shape != stub_shape:
            raise SourceTypeError(
                f"external ContractOnly stub changes source type {variant}: "
                f"adapter={adapter_shape}, stub={stub_shape}"
            )
    function = _find_function(tree, contract.symbol)
    imported_calls = _external_provider_call_names(tree, function, contract.provider_module)
    missing = set(contract.provider_symbols) - imported_calls
    if missing:
        raise SourceTypeError(
            f"external adapter {contract.adapter_path}:{contract.symbol} does not directly call "
            f"declared provider symbols {sorted(missing)} from {contract.provider_module}"
        )

    try:
        spec = importlib.util.find_spec(contract.provider_module)
    except (ImportError, AttributeError, ValueError) as exc:
        raise SourceTypeError(
            f"cannot resolve external provider module {contract.provider_module!r}: {exc}"
        ) from exc
    if spec is None:
        raise SourceTypeError(
            f"cannot resolve external provider module {contract.provider_module!r}"
        )
    origin = spec.origin
    origin_digest: str | None = None
    origin_kind = "built-in" if origin in {None, "built-in", "frozen"} else "file"
    if origin_kind == "file":
        provider_path = Path(str(origin)).resolve()
        try:
            provider_path.relative_to(root)
        except ValueError:
            pass
        else:
            raise SourceTypeError(
                f"external provider {contract.provider_module!r} resolves inside the certified "
                "source tree; app-owned code cannot be relabeled external"
            )
        if not provider_path.is_file():
            raise SourceTypeError(
                f"external provider origin is not a file: {contract.provider_module!r}"
            )
        origin_digest = sha256(provider_path.read_bytes()).hexdigest()

    top_level = contract.provider_module.split(".", 1)[0]
    distributions: list[dict[str, str]] = []
    for distribution in sorted(importlib.metadata.packages_distributions().get(top_level, ())):
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
        distributions.append({"name": distribution, "version": version})
    return {
        "boundary_id": contract.boundary_id,
        "assumption": contract.assumption,
        "adapter": {
            "path": contract.adapter_path,
            "symbol": contract.symbol,
            "sha256": sha256(adapter.read_bytes()).hexdigest(),
        },
        "contract_stub": stub,
        "provider": {
            "module": contract.provider_module,
            "symbols": list(contract.provider_symbols),
            "origin_kind": origin_kind,
            "origin_sha256": origin_digest,
            "distributions": distributions,
            "python_implementation": sys.implementation.name,
            "python_version": list(sys.version_info[:3]),
            "python_cache_tag": sys.implementation.cache_tag,
        },
        "runtime_validation": "typeguard-return-annotation/v1",
    }


def _external_provider_call_names(
    tree: ast.Module,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    provider_module: str,
) -> set[str]:
    direct: dict[str, str] = {}
    module_aliases: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == provider_module:
            for imported in statement.names:
                direct[imported.asname or imported.name] = imported.name
        elif isinstance(statement, ast.Import):
            for imported in statement.names:
                if imported.name == provider_module:
                    binding = imported.asname or imported.name.split(".", 1)[0]
                    parts = imported.name.split(".", 1)
                    suffix = "" if imported.asname or len(parts) == 1 else parts[1]
                    module_aliases[binding] = suffix
    calls: set[str] = set()
    for descendant in ast.walk(function):
        if not isinstance(descendant, ast.Call):
            continue
        name = _qualified_name(descendant.func)
        if name in direct:
            calls.add(direct[str(name)])
        if name is not None:
            for module_alias, provider_suffix in module_aliases.items():
                prefix = module_alias + "."
                if name.startswith(prefix):
                    called = name[len(prefix):]
                    suffix_prefix = provider_suffix + "." if provider_suffix else ""
                    if suffix_prefix and called.startswith(suffix_prefix):
                        called = called[len(suffix_prefix):]
                    calls.add(called)
    return calls


def _variant_field_schema(
    root: Path,
    path: Path,
    tree: ast.Module,
    annotation: ast.expr,
    label: str,
) -> tuple[tuple[str, str], ...]:
    variant = _annotation(annotation, f"{label} variant")
    node, _class_nodes, _dataclasses = _resolve_variant_definition(
        root, path, tree, annotation, f"{label} variant {variant}",
    )
    fields: list[tuple[str, str]] = []
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            fields.append((statement.target.id, ast.unparse(statement.annotation)))
        elif isinstance(statement, ast.Pass):
            continue
        else:
            raise SourceTypeError(
                f"{label} type {variant} must be a field-only dataclass"
            )
    return tuple(fields)


def _validate_external_module_surface(
    tree: ast.Module,
    symbol: str,
    allowed_classes: set[str],
    label: str,
) -> None:
    """Keep an overlaid adapter module narrow enough that the stub cannot replace app logic."""
    functions = {
        item.name for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if functions != {symbol}:
        raise SourceTypeError(
            f"{label} must contain only the declared adapter function {symbol!r}; "
            f"observed functions {sorted(functions)}"
        )
    unexpected_classes = {
        item.name for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name not in allowed_classes
    }
    if unexpected_classes:
        raise SourceTypeError(
            f"{label} contains undeclared classes {sorted(unexpected_classes)}"
        )
    for item in tree.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            raise SourceTypeError(
                f"{label} may not define module state; put shared application state outside the "
                "overlaid adapter module"
            )


def _validate_canonical_external_ensures(
    tree: ast.Module,
    function: ast.FunctionDef,
    path: str,
    symbol: str,
) -> None:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    ensures = _nagini_contract_names(tree, "Ensures")
    results = _nagini_contract_names(tree, "Result")
    valid = False
    if len(body) == 1 and isinstance(body[0], ast.Expr):
        call = body[0].value
        if (
            isinstance(call, ast.Call)
            and _qualified_name(call.func) in ensures
            and not call.keywords
            and len(call.args) == 1
        ):
            predicate = call.args[0]
            valid = (
                isinstance(predicate, ast.Compare)
                and len(predicate.ops) == 1
                and isinstance(predicate.ops[0], ast.IsNot)
                and len(predicate.comparators) == 1
                and isinstance(predicate.comparators[0], ast.Constant)
                and predicate.comparators[0].value is None
                and isinstance(predicate.left, ast.Call)
                and _qualified_name(predicate.left.func) in results
                and not predicate.left.args
                and not predicate.left.keywords
            )
    if not valid:
        raise SourceTypeError(
            f"external contract stub {path}:{symbol} must contain exactly "
            "Ensures(Result() is not None). Arbitrary proof axioms are forbidden; the runtime "
            "boundary enforces the declared success type."
        )


def _resolve_variant_definition(
    root: Path,
    implementation: Path,
    tree: ast.Module,
    annotation: ast.expr,
    label: str,
) -> tuple[ast.ClassDef, dict[str, ast.ClassDef], set[str]]:
    if not isinstance(annotation, ast.Name):
        raise SourceTypeError(f"{label} must be a named source dataclass")
    name = annotation.id
    local = {
        item.name: item for item in tree.body if isinstance(item, ast.ClassDef)
    }
    if name in local:
        return local[name], local, _trusted_decorators(tree)[2]

    imported_module: str | None = None
    imported_name: str | None = None
    level = 0
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom) or statement.module is None:
            continue
        for imported in statement.names:
            binding = imported.asname or imported.name
            if binding != name:
                continue
            if imported.asname is not None and imported.asname != imported.name:
                raise SourceTypeError(
                    f"{label} may not rename imported source variant {imported.name!r}"
                )
            imported_module = statement.module
            imported_name = imported.name
            level = statement.level
    if imported_module is None or imported_name is None:
        raise SourceTypeError(
            f"{label} must be defined locally or imported from a source-owned module"
        )
    base = implementation.parent if level else root
    for _ in range(max(0, level - 1)):
        base = base.parent
    candidate = (base / Path(*imported_module.split("."))).with_suffix(".py").resolve()
    if not candidate.is_file():
        candidate = (base / Path(*imported_module.split(".")) / "__init__.py").resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SourceTypeError(f"{label} import escapes source root") from exc
    if not candidate.is_file():
        raise SourceTypeError(
            f"{label} source type module does not exist: {imported_module}"
        )
    source = candidate.read_text(encoding="utf-8")
    imported_tree = ast.parse(source, filename=str(candidate), type_comments=True)
    _reject_type_escape_hatches(imported_tree, source, candidate.relative_to(root).as_posix())
    imported_classes = {
        item.name: item for item in imported_tree.body if isinstance(item, ast.ClassDef)
    }
    class_node = imported_classes.get(imported_name)
    if class_node is None:
        raise SourceTypeError(
            f"{label} imported module does not define {imported_name}"
        )
    return class_node, imported_classes, _trusted_decorators(imported_tree)[2]


def _reject_nagini_proof_escape_hatches(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
    path: str,
    symbol: str,
    input_type: str,
) -> None:
    """Forbid verifier features that weaken totality over the declared input type.

    Dagcert asks Nagini to prove the real implementation; it must not accept a proof obtained by
    assuming an arbitrary fact, declaring the operation unreachable with a precondition, or using
    a specification-only implementation in the bound module.
    """

    assume_names = _nagini_contract_names(tree, "Assume")
    requires_names = _nagini_contract_names(tree, "Requires")
    contract_only_names = _nagini_contract_names(tree, "ContractOnly")
    for descendant in ast.walk(tree):
        qualified = _qualified_name(descendant.func) if isinstance(descendant, ast.Call) else None
        if qualified in assume_names:
            raise SourceTypeError(
                f"bound implementation {path} uses Nagini Assume; certificate proofs may not "
                "introduce trusted axioms"
            )
        if isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in descendant.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if _qualified_name(target) in contract_only_names:
                    raise SourceTypeError(
                        f"bound implementation {path} uses Nagini ContractOnly; every proved "
                        "application implementation must have a verified executable body"
                    )
    for descendant in ast.walk(function):
        if (
            isinstance(descendant, ast.Call)
            and _qualified_name(descendant.func) in requires_names
        ):
            raise SourceTypeError(
                f"operation {symbol} declares Nagini Requires; Task<{input_type}> "
                "must be total over its complete source-declared input type"
            )


def _nagini_contract_names(tree: ast.Module, name: str) -> set[str]:
    names = {name, f"nagini_contracts.contracts.{name}"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "nagini_contracts.contracts":
                    names.add(f"{alias.asname or alias.name}.{name}")
        elif isinstance(node, ast.ImportFrom) and node.module == "nagini_contracts.contracts":
            for alias in node.names:
                if alias.name == name or alias.name == "*":
                    names.add(alias.asname or name)
    return names


def _reject_operation_exsures(
    function: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module, symbol: str,
) -> None:
    """Do not let a task operation declare an exceptional exit outside its outcome union."""

    names = {"Exsures", "nagini_contracts.contracts.Exsures"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "nagini_contracts.contracts":
                    names.add(f"{alias.asname or alias.name}.Exsures")
        elif isinstance(node, ast.ImportFrom) and node.module == "nagini_contracts.contracts":
            for alias in node.names:
                if alias.name == "Exsures":
                    names.add(alias.asname or alias.name)
    for descendant in ast.walk(function):
        if isinstance(descendant, ast.Call) and _qualified_name(descendant.func) in names:
            raise SourceTypeError(
                f"operation {symbol} declares Exsures; task failures must be explicit return "
                "outcomes and the operation itself must prove exception-free"
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
    dataclass_decorators: set[str],
) -> None:
    if node.name in seen:
        return
    seen.add(node.name)
    if node.bases or node.keywords:
        raise SourceTypeError(f"{label} must not inherit from an open or external base type")
    if not any(
        _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        in dataclass_decorators
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
                        class_nodes, seen, dataclass_decorators,
                    )
        elif isinstance(statement, ast.Assign):
            raise SourceTypeError(f"{label} contains an untyped class field")


def _has_operation_decorator(decorators: list[ast.expr], trusted: set[str]) -> bool:
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _qualified_name(target) in trusted:
            return True
    return False


def _require_external_boundary_decorator(
    decorators: list[ast.expr], trusted: set[str], boundary_id: str, symbol: str,
) -> None:
    matches: list[ast.Call] = []
    for decorator in decorators:
        if isinstance(decorator, ast.Call) and _qualified_name(decorator.func) in trusted:
            matches.append(decorator)
    if len(matches) != 1:
        raise SourceTypeError(
            f"external adapter {symbol} must use exactly one trusted "
            "@dagcert.runtime.external_boundary(...) decorator"
        )
    call = matches[0]
    if call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Constant):
        raise SourceTypeError(
            f"external adapter {symbol} decorator must contain one literal boundary ID"
        )
    if call.args[0].value != boundary_id:
        raise SourceTypeError(
            f"external adapter {symbol} decorator ID {call.args[0].value!r} does not match "
            f"contract task {boundary_id!r}"
        )


def _reject_contract_only_in_executable_module(tree: ast.Module, path: str) -> None:
    contract_only = _nagini_contract_names(tree, "ContractOnly")
    for descendant in ast.walk(tree):
        if isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in descendant.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if _qualified_name(target) in contract_only:
                    raise SourceTypeError(
                        f"real external adapter {path} uses ContractOnly; ContractOnly is allowed "
                        "only in its separately declared proof stub"
                    )


def _trusted_decorators(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    """Resolve only decorators imported from the actual owning modules.

    Name spelling is not provenance. A local function called ``operation`` or ``dataclass`` must
    not be able to impersonate the runtime guard or a closed record type.
    """

    operation_imports: list[tuple[str, str]] = []
    external_imports: list[tuple[str, str]] = []
    dataclass_imports: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split(".", 1)[0]
                qualified = alias.asname or alias.name
                if alias.name == "dagcert":
                    operation_imports.append((f"{qualified}.operation", binding))
                    external_imports.append((f"{qualified}.external_boundary", binding))
                elif alias.name == "dagcert.runtime":
                    operation_imports.append((f"{qualified}.operation", binding))
                    external_imports.append((f"{qualified}.external_boundary", binding))
                elif alias.name == "dataclasses":
                    dataclass_imports.append((f"{qualified}.dataclass", binding))
        elif isinstance(node, ast.ImportFrom):
            if node.module in {"dagcert", "dagcert.runtime"}:
                for alias in node.names:
                    if alias.name == "operation":
                        binding = alias.asname or alias.name
                        operation_imports.append((binding, binding))
                    elif alias.name == "external_boundary":
                        binding = alias.asname or alias.name
                        external_imports.append((binding, binding))
            elif node.module == "dataclasses":
                for alias in node.names:
                    if alias.name == "dataclass":
                        binding = alias.asname or alias.name
                        dataclass_imports.append((binding, binding))

    rebound = _top_level_rebindings(tree)
    operations = {name for name, binding in operation_imports if binding not in rebound}
    externals = {name for name, binding in external_imports if binding not in rebound}
    dataclasses = {name for name, binding in dataclass_imports if binding not in rebound}
    return operations, externals, dataclasses


def _top_level_rebindings(tree: ast.Module) -> set[str]:
    rebound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                rebound.update(
                    child.id for child in ast.walk(target) if isinstance(child, ast.Name)
                )
    return rebound


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


def _reject_trusted_module_shadowing(root: Path, implementation: Path) -> None:
    actual_dagcert = Path(__file__).resolve().parent
    actual_dataclasses = Path(dataclasses_module.__file__).resolve()
    directories: list[Path] = []
    current = implementation.parent
    while True:
        directories.append(current)
        if current == root:
            break
        if root not in current.parents:
            break
        current = current.parent
    for directory in directories:
        dagcert_file = directory / "dagcert.py"
        dagcert_package = directory / "dagcert" / "__init__.py"
        if dagcert_file.is_file():
            raise SourceTypeError(
                f"trusted decorator module dagcert is shadowed by {dagcert_file.relative_to(root)}"
            )
        if dagcert_package.is_file() and dagcert_package.parent.resolve() != actual_dagcert:
            raise SourceTypeError(
                "trusted decorator module dagcert is shadowed by "
                f"{dagcert_package.parent.relative_to(root)}"
            )
        dataclasses_file = directory / "dataclasses.py"
        if dataclasses_file.is_file() and dataclasses_file.resolve() != actual_dataclasses:
            raise SourceTypeError(
                "trusted decorator module dataclasses is shadowed by "
                f"{dataclasses_file.relative_to(root)}"
            )
        dataclasses_package = directory / "dataclasses" / "__init__.py"
        if dataclasses_package.is_file():
            raise SourceTypeError(
                "trusted decorator module dataclasses is shadowed by "
                f"{dataclasses_package.parent.relative_to(root)}"
            )
