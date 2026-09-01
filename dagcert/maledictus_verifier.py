"""Pinned external invocation of the independently owned Maledictus proof backend."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from subprocess import TimeoutExpired, run
from tempfile import TemporaryDirectory
from typing import Iterable, Literal


class MaledictusVerificationError(RuntimeError):
    pass


_REQUEST_SCHEMA = "maledictus-verification-request/v4"
_RESPONSE_SCHEMA = "maledictus-verification-result/v7"
_DAGCERT_FRAGMENT = "dagcert-closed-typed-operations/v3"
_RESPONSE_FIELDS = {
    "schema", "verifier", "version", "status", "proof_obligation",
    "source_fingerprint", "files", "source_imports", "external_contracts",
    "cross_language_bindings", "python_callable_bindings", "obligations",
    "verifier_identity", "python_typechecker", "diagnostics",
}
_OPTIONAL_RESPONSE_FIELDS = {"solver", "typescript_toolchain"}


@dataclass(frozen=True, slots=True)
class MaledictusSourceCallableProvider:
    path: str
    symbol: str


@dataclass(frozen=True, slots=True)
class MaledictusExternalCallableProvider:
    module: str
    symbol: str
    stub_path: str
    exception_policy: Literal["assume-no-exception", "declared-by-exsures"]


@dataclass(frozen=True, slots=True)
class MaledictusCallableBinding:
    id: str
    consumer_path: str
    operation_symbol: str
    input_record: str
    field: str
    provider: MaledictusSourceCallableProvider | MaledictusExternalCallableProvider


def verify_with_maledictus(
    source_root: str | Path,
    files: Iterable[str],
    symbols_by_file: dict[str, tuple[str, ...]],
    *,
    source_fingerprint: str,
    executable: str | Path,
    expected_executable_sha256: str,
    timeout_seconds: float = 120.0,
    callable_bindings: Iterable[MaledictusCallableBinding] = (),
) -> dict[str, object]:
    """Run one exact, digest-pinned Maledictus request and validate its complete response."""

    root = Path(source_root).resolve()
    verifier = Path(executable).resolve()
    if not verifier.is_file():
        raise MaledictusVerificationError(
            f"Maledictus executable does not exist: {verifier}"
        )
    expected_digest = expected_executable_sha256.strip().lower()
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise MaledictusVerificationError(
            "Maledictus executable SHA-256 pin must be 64 lowercase hexadecimal characters"
        )
    actual_digest = sha256(verifier.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise MaledictusVerificationError(
            "Maledictus executable digest mismatch: "
            f"expected {expected_digest}, observed {actual_digest}"
        )

    bindings = tuple(callable_bindings)
    binding_ids = [binding.id for binding in bindings]
    if any(not identifier for identifier in binding_ids) or len(binding_ids) != len(
        set(binding_ids)
    ):
        raise MaledictusVerificationError(
            "Maledictus callable binding IDs must be nonempty and unique"
        )
    binding_targets = [
        (
            binding.consumer_path,
            binding.operation_symbol,
            binding.input_record,
            binding.field,
        )
        for binding in bindings
    ]
    if len(binding_targets) != len(set(binding_targets)):
        raise MaledictusVerificationError(
            "Maledictus callable binding targets must be unique"
        )
    normalized_base_files = {Path(item).as_posix() for item in files}
    normalized_files_set = set(normalized_base_files)
    requested_symbols = {
        Path(path).as_posix(): tuple(symbols)
        for path, symbols in symbols_by_file.items()
    }
    for binding in bindings:
        consumer_path = Path(binding.consumer_path).as_posix()
        if consumer_path not in normalized_base_files:
            raise MaledictusVerificationError(
                f"callable binding {binding.id!r} consumer is not a bound operation file: "
                f"{consumer_path}"
            )
        if binding.operation_symbol not in requested_symbols.get(consumer_path, ()):
            raise MaledictusVerificationError(
                f"callable binding {binding.id!r} names unbound operation symbol "
                f"{binding.operation_symbol!r} in {consumer_path}"
            )
        if isinstance(binding.provider, MaledictusSourceCallableProvider):
            provider_path = Path(binding.provider.path).as_posix()
            normalized_files_set.add(provider_path)
            provider_symbols = list(requested_symbols.get(provider_path, ()))
            if binding.provider.symbol not in provider_symbols:
                provider_symbols.append(binding.provider.symbol)
            requested_symbols[provider_path] = tuple(provider_symbols)
    normalized_files = tuple(sorted(normalized_files_set))
    if not normalized_files:
        raise MaledictusVerificationError("Maledictus received no bound operation files")
    request_files: list[dict[str, object]] = []
    expected_hashes: dict[str, str] = {}
    for relative in normalized_files:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise MaledictusVerificationError(
                f"Maledictus source path escapes source root: {relative}"
            ) from exc
        if not path.is_file():
            raise MaledictusVerificationError(
                f"Maledictus source file does not exist: {relative}"
            )
        symbols = requested_symbols.get(relative, ())
        if not symbols:
            raise MaledictusVerificationError(
                f"Maledictus source file has no bound symbols: {relative}"
            )
        request_files.append({
            "path": relative,
            "language": "python",
            "symbols": list(symbols),
        })
        expected_hashes[relative] = sha256(path.read_bytes()).hexdigest()

    external_overlays: dict[tuple[str, str], dict[str, str]] = {}
    binding_rows: list[dict[str, object]] = []
    for binding in bindings:
        consumer_path = Path(binding.consumer_path).as_posix()
        provider = binding.provider
        if isinstance(provider, MaledictusSourceCallableProvider):
            provider_row = {
                "kind": "source",
                "path": Path(provider.path).as_posix(),
                "symbol": provider.symbol,
            }
        else:
            provider_row = {
                "kind": "external-contract",
                "module": provider.module,
                "symbol": provider.symbol,
            }
            overlay = {
                "adapter_path": consumer_path,
                "module": provider.module,
                "stub_path": Path(provider.stub_path).as_posix(),
                "exception_policy": provider.exception_policy,
            }
            overlay_key = (consumer_path, provider.module)
            prior = external_overlays.get(overlay_key)
            if prior is not None and prior != overlay:
                raise MaledictusVerificationError(
                    f"callable bindings declare conflicting external overlays for "
                    f"{consumer_path}:{provider.module}"
                )
            external_overlays[overlay_key] = overlay
        binding_rows.append({
            "id": binding.id,
            "consumer_path": consumer_path,
            "operation_symbol": binding.operation_symbol,
            "input_record": binding.input_record,
            "field": binding.field,
            "provider": provider_row,
        })

    request = {
        "schema": _REQUEST_SCHEMA,
        "source_root": str(root),
        "source_fingerprint": source_fingerprint,
        "proof_obligation": "no-undeclared-exceptional-exit",
        "files": request_files,
        "external_contract_overlays": list(external_overlays.values()),
        "cross_language_bindings": [],
        "python_callable_bindings": binding_rows,
    }
    with TemporaryDirectory(prefix="dagcert-maledictus-") as temporary:
        request_path = Path(temporary) / "request.json"
        request_path.write_text(
            json.dumps(request, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            completed = run(
                [str(verifier), "verify", "--request", str(request_path)],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, TimeoutExpired) as exc:
            raise MaledictusVerificationError(
                f"cannot execute digest-pinned Maledictus verifier: {exc}"
            ) from exc
    if completed.returncode != 0:
        detail = _refusal_detail(completed.stdout)
        if completed.stderr.strip():
            detail = "\n".join(item for item in (detail, completed.stderr.strip()) if item)
        raise MaledictusVerificationError(
            "Maledictus verifier process failed"
            + (f":\n{detail}" if detail else f" with exit code {completed.returncode}")
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MaledictusVerificationError(
            f"Maledictus returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(response, dict):
        raise MaledictusVerificationError("Maledictus response must be one JSON object")
    fields = set(response)
    if not _RESPONSE_FIELDS <= fields or fields - _RESPONSE_FIELDS - _OPTIONAL_RESPONSE_FIELDS:
        raise MaledictusVerificationError(
            "Maledictus response fields mismatch: "
            f"unexpected={sorted(fields - _RESPONSE_FIELDS - _OPTIONAL_RESPONSE_FIELDS)}, "
            f"missing={sorted(_RESPONSE_FIELDS - fields)}"
        )
    if (
        response.get("schema") != _RESPONSE_SCHEMA
        or response.get("verifier") != "maledictus"
        or response.get("proof_obligation") != "no-undeclared-exceptional-exit"
        or response.get("source_fingerprint") != source_fingerprint
    ):
        raise MaledictusVerificationError(
            "Maledictus response protocol, verifier, obligation, or source fingerprint mismatch"
        )
    if response.get("status") != "proved":
        diagnostics = response.get("diagnostics")
        raise MaledictusVerificationError(
            "Maledictus did not prove every bound operation: "
            + json.dumps(diagnostics, sort_keys=True)
        )
    if response.get("diagnostics") != []:
        raise MaledictusVerificationError(
            "Maledictus returned diagnostics with a proved response"
        )
    identity = response.get("verifier_identity")
    if not isinstance(identity, dict) or set(identity) != {
        "executable_sha256", "frontend_bundle_sha256", "kernel_bundle_sha256",
    }:
        raise MaledictusVerificationError("Maledictus verifier identity is missing or malformed")
    if identity.get("executable_sha256") != actual_digest:
        raise MaledictusVerificationError(
            "Maledictus self-reported executable digest does not match Dagcert's digest"
        )
    for key in ("frontend_bundle_sha256", "kernel_bundle_sha256"):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise MaledictusVerificationError(
                f"Maledictus verifier identity field {key} is not a SHA-256 digest"
            )
    _validate_python_typechecker_identity(response.get("python_typechecker"))
    file_results = response.get("files")
    if not isinstance(file_results, list) or len(file_results) != len(normalized_files):
        raise MaledictusVerificationError("Maledictus returned the wrong number of file results")
    returned_paths: set[str] = set()
    for result in file_results:
        if not isinstance(result, dict) or set(result) != {
            "path", "sha256", "symbols", "scope", "result", "fragment",
        }:
            raise MaledictusVerificationError("Maledictus returned a malformed file result")
        returned_path = result.get("path")
        if not isinstance(returned_path, str) or returned_path not in expected_hashes:
            raise MaledictusVerificationError(
                f"Maledictus returned unexpected file result {returned_path!r}"
            )
        if returned_path in returned_paths:
            raise MaledictusVerificationError(
                f"Maledictus returned duplicate file result {returned_path!r}"
            )
        returned_paths.add(returned_path)
        consumer_paths = {Path(item.consumer_path).as_posix() for item in bindings}
        provider_paths = {
            Path(item.provider.path).as_posix()
            for item in bindings
            if isinstance(item.provider, MaledictusSourceCallableProvider)
        }
        if returned_path in consumer_paths:
            expected_scope = (
                "hash-bound-operation-input-and-concrete-callable-provider-with-"
                "composed-exit-effects"
            )
        elif returned_path in provider_paths:
            expected_scope = (
                "hash-bound-source-callback-signature-body-and-complete-exit-effects"
            )
        else:
            expected_scope = "all-source-symbol-bodies"
        if (
            result.get("sha256") != expected_hashes[returned_path]
            or result.get("symbols") != list(requested_symbols[returned_path])
            or result.get("scope") != expected_scope
            or result.get("result") != "proved"
            or result.get("fragment") != _DAGCERT_FRAGMENT
        ):
            raise MaledictusVerificationError(
                f"Maledictus file proof does not exactly bind {returned_path!r} to {_DAGCERT_FRAGMENT}"
            )
    if returned_paths != set(normalized_files):
        raise MaledictusVerificationError("Maledictus omitted a bound operation file")
    if response.get("source_imports") != [] or response.get("cross_language_bindings") != []:
        raise MaledictusVerificationError(
            "Dagcert callable operation proof returned undeclared source or cross-language edges"
        )
    _validate_external_contract_results(
        root,
        tuple(external_overlays.values()),
        bindings,
        response.get("external_contracts"),
    )
    _validate_callable_binding_results(
        root, bindings, expected_hashes, response.get("python_callable_bindings")
    )
    return response


def _validate_external_contract_results(
    root: Path,
    overlays: tuple[dict[str, str], ...],
    bindings: tuple[MaledictusCallableBinding, ...],
    value: object,
) -> None:
    if not isinstance(value, list) or len(value) != len(overlays):
        raise MaledictusVerificationError(
            "Maledictus returned the wrong number of external contract results"
        )
    expected = {
        (item["adapter_path"], item["module"]): item for item in overlays
    }
    returned: set[tuple[str, str]] = set()
    required_fields = {
        "adapter_path", "module", "stub_path", "sha256", "functions",
        "nominal_types", "heap_types", "exception_types", "exception_policy",
        "declared_exceptions", "scope",
    }
    for result in value:
        if not isinstance(result, dict) or set(result) != required_fields:
            raise MaledictusVerificationError(
                "Maledictus returned a malformed external contract result"
            )
        key = (result.get("adapter_path"), result.get("module"))
        if key not in expected or key in returned:
            raise MaledictusVerificationError(
                f"Maledictus returned an unknown or duplicate external contract {key!r}"
            )
        returned.add(key)
        overlay = expected[key]
        stub_relative = overlay["stub_path"]
        stub_path = (root / stub_relative).resolve()
        try:
            stub_path.relative_to(root)
        except ValueError as exc:
            raise MaledictusVerificationError(
                f"external contract stub escapes source root: {stub_relative}"
            ) from exc
        if not stub_path.is_file():
            raise MaledictusVerificationError(
                f"external contract stub does not exist: {stub_relative}"
            )
        expected_scope = (
            "provider-import-conformance-and-normal-return-assumed; adapter-symbol-binding-"
            "call-sites-and-preconditions-verified"
            if overlay["exception_policy"] == "assume-no-exception"
            else "provider-import-and-contract-conformance-assumed; exsures-outcome-union-"
            "propagated; adapter-symbol-binding-call-sites-and-preconditions-verified"
        )
        expected_symbols = {
            binding.provider.symbol
            for binding in bindings
            if isinstance(binding.provider, MaledictusExternalCallableProvider)
            and Path(binding.consumer_path).as_posix() == key[0]
            and binding.provider.module == key[1]
        }
        returned_functions = result.get("functions")
        exception_types = result.get("exception_types")
        declared_exceptions = result.get("declared_exceptions")
        if (
            result.get("stub_path") != stub_relative
            or result.get("sha256") != sha256(stub_path.read_bytes()).hexdigest()
            or result.get("exception_policy") != overlay["exception_policy"]
            or result.get("scope") != expected_scope
            or result.get("nominal_types") != []
            or result.get("heap_types") != []
            or not isinstance(returned_functions, list)
            or not all(isinstance(item, str) for item in returned_functions)
            or len(returned_functions) != len(set(returned_functions))
            or not expected_symbols <= set(returned_functions)
            or not isinstance(exception_types, list)
            or not all(isinstance(item, str) for item in exception_types)
            or len(exception_types) != len(set(exception_types))
            or not isinstance(declared_exceptions, list)
            or not all(isinstance(item, str) for item in declared_exceptions)
            or len(declared_exceptions) != len(set(declared_exceptions))
            or (
                overlay["exception_policy"] == "assume-no-exception"
                and declared_exceptions != []
            )
            or (
                overlay["exception_policy"] == "declared-by-exsures"
                and not declared_exceptions
            )
        ):
            raise MaledictusVerificationError(
                f"Maledictus external contract evidence does not exactly bind {key!r}"
            )
    if returned != set(expected):
        raise MaledictusVerificationError("Maledictus omitted an external contract result")


def _validate_callable_binding_results(
    root: Path,
    bindings: tuple[MaledictusCallableBinding, ...],
    expected_hashes: dict[str, str],
    value: object,
) -> None:
    if not isinstance(value, list) or len(value) != len(bindings):
        raise MaledictusVerificationError(
            "Maledictus returned the wrong number of Python callable binding results"
        )
    expected = {binding.id: binding for binding in bindings}
    returned: set[str] = set()
    required_fields = {
        "id", "consumer_path", "consumer_sha256", "operation_symbol",
        "input_record", "field", "provider", "scope",
    }
    for result in value:
        if not isinstance(result, dict) or set(result) != required_fields:
            raise MaledictusVerificationError(
                "Maledictus returned a malformed Python callable binding result"
            )
        identifier = result.get("id")
        if not isinstance(identifier, str) or identifier not in expected or identifier in returned:
            raise MaledictusVerificationError(
                f"Maledictus returned an unknown or duplicate callable binding {identifier!r}"
            )
        returned.add(identifier)
        binding = expected[identifier]
        consumer_path = Path(binding.consumer_path).as_posix()
        provider = result.get("provider")
        if (
            result.get("consumer_path") != consumer_path
            or result.get("consumer_sha256") != expected_hashes.get(consumer_path)
            or result.get("operation_symbol") != binding.operation_symbol
            or result.get("input_record") != binding.input_record
            or result.get("field") != binding.field
            or not isinstance(provider, dict)
        ):
            raise MaledictusVerificationError(
                f"Maledictus callable binding evidence does not match {identifier!r}"
            )
        expected_scope: str
        if isinstance(binding.provider, MaledictusSourceCallableProvider):
            provider_path = Path(binding.provider.path).as_posix()
            expected_provider = {
                "kind": "source",
                "path": provider_path,
                "sha256": expected_hashes.get(provider_path),
                "symbol": binding.provider.symbol,
            }
            expected_scope = (
                "source-callback-signature-body-and-complete-normal-exception-outcomes-"
                "checked-and-composed"
            )
        else:
            stub_relative = Path(binding.provider.stub_path).as_posix()
            stub_path = (root / stub_relative).resolve()
            try:
                stub_path.relative_to(root)
            except ValueError as exc:
                raise MaledictusVerificationError(
                    f"external callable stub escapes source root: {stub_relative}"
                ) from exc
            if not stub_path.is_file():
                raise MaledictusVerificationError(
                    f"external callable stub does not exist: {stub_relative}"
                )
            expected_provider = {
                "kind": "external-contract",
                "module": binding.provider.module,
                "stub_path": stub_relative,
                "stub_sha256": sha256(stub_path.read_bytes()).hexdigest(),
                "symbol": binding.provider.symbol,
            }
            expected_scope = (
                "external-provider-conformance-assumed-by-explicit-hash-bound-contract; "
                "fixed-signature-and-declared-exception-outcomes-composed"
            )
        if provider != expected_provider or result.get("scope") != expected_scope:
            raise MaledictusVerificationError(
                f"Maledictus callable provider evidence does not match {identifier!r}"
            )
    if returned != set(expected):
        raise MaledictusVerificationError("Maledictus omitted a Python callable binding result")


def _validate_python_typechecker_identity(identity: object) -> None:
    """Require and bind the real strict Python typechecker used before proof issuance."""

    required_fields = {
        "checker", "checker_version", "profile", "package_sha256", "runtime",
        "runtime_version", "runtime_executable_sha256", "runtime_bundle_sha256",
        "configuration_sha256", "contract_support_sha256",
    }
    if not isinstance(identity, dict) or set(identity) != required_fields:
        raise MaledictusVerificationError(
            "Maledictus Python typechecker identity is missing or malformed"
        )
    if (
        identity.get("checker") != "mypy"
        or identity.get("checker_version") != "1.5.0"
        or identity.get("profile") != "strict-issuance"
        or identity.get("runtime") != "python"
        or not isinstance(identity.get("runtime_version"), str)
        or not identity["runtime_version"]
    ):
        raise MaledictusVerificationError(
            "Maledictus did not use the required strict pinned Python typechecker"
        )
    for key in (
        "package_sha256", "runtime_executable_sha256", "runtime_bundle_sha256",
        "configuration_sha256", "contract_support_sha256",
    ):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise MaledictusVerificationError(
                f"Maledictus Python typechecker identity field {key} is not a SHA-256 digest"
            )


def _refusal_detail(stdout: str) -> str:
    """Render stable source locations from a non-success response without trusting it as proof."""

    stripped = stdout.strip()
    if not stripped:
        return ""
    try:
        response = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if (
        not isinstance(response, dict)
        or response.get("schema") != _RESPONSE_SCHEMA
        or response.get("verifier") != "maledictus"
        or not isinstance(response.get("diagnostics"), list)
    ):
        return stripped
    rendered: list[str] = []
    for diagnostic in response["diagnostics"]:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code")
        message = diagnostic.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            continue
        path = diagnostic.get("path")
        line = diagnostic.get("line")
        column = diagnostic.get("column")
        location = path if isinstance(path, str) else "Maledictus"
        if isinstance(line, int) and not isinstance(line, bool):
            location += f":{line}"
            if isinstance(column, int) and not isinstance(column, bool):
                location += f":{column}"
        rendered.append(f"{location} [{code}] {message}")
    return "\n".join(rendered) or stripped
