from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from dagcert.maledictus_verifier import (
    MaledictusCallableBinding, MaledictusExternalCallableProvider,
    MaledictusSourceCallableProvider, MaledictusVerificationError,
    MaledictusVerifiedInterface,
    verify_with_maledictus,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "app"
    root.mkdir()
    (root / "app.py").write_text("def work() -> int:\n    return 1\n", encoding="utf-8")
    executable = tmp_path / "maledictus.exe"
    executable.write_bytes(b"pinned verifier")
    return root, executable, sha256(executable.read_bytes()).hexdigest()


def _proved_response(root: Path, executable_digest: str) -> dict[str, object]:
    return {
        "schema": "maledictus-verification-result/v7",
        "verifier": "maledictus",
        "version": "0.1.0",
        "status": "proved",
        "proof_obligation": "no-undeclared-exceptional-exit",
        "source_fingerprint": "source-fingerprint",
        "files": [{
            "path": "app.py",
            "sha256": sha256((root / "app.py").read_bytes()).hexdigest(),
            "symbols": ["work"],
            "scope": "all-source-symbol-bodies",
            "result": "proved",
            "fragment": "dagcert-closed-typed-operations/v3",
        }],
        "source_imports": [],
        "external_contracts": [],
        "cross_language_bindings": [],
        "python_callable_bindings": [],
        "obligations": [],
        "verifier_identity": {
            "executable_sha256": executable_digest,
            "frontend_bundle_sha256": "1" * 64,
            "kernel_bundle_sha256": "2" * 64,
        },
        "python_typechecker": {
            "checker": "mypy",
            "checker_version": "1.5.0",
            "profile": "strict-issuance",
            "package_sha256": "3" * 64,
            "runtime": "python",
            "runtime_version": "Python 3.12.10",
            "runtime_executable_sha256": "4" * 64,
            "runtime_bundle_sha256": "5" * 64,
            "configuration_sha256": "6" * 64,
            "contract_support_sha256": "7" * 64,
        },
        "diagnostics": [],
    }


def test_digest_pinned_maledictus_response_is_exactly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest = _fixture(tmp_path)

    def fake_run(arguments, **kwargs):
        request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert arguments[:3] == [str(executable.resolve()), "verify", "--request"]
        assert request["source_root"] == str(root.resolve())
        assert request["source_fingerprint"] == "source-fingerprint"
        assert request["files"] == [{
            "path": "app.py", "language": "python", "symbols": ["work"],
        }]
        assert request["external_contract_overlays"] == []
        assert request["cross_language_bindings"] == []
        assert request["python_callable_bindings"] == []
        return CompletedProcess(arguments, 0, json.dumps(_proved_response(root, digest)), "")

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    result = verify_with_maledictus(
        root,
        ["app.py"],
        {"app.py": ("work",)},
        source_fingerprint="source-fingerprint",
        executable=executable,
        expected_executable_sha256=digest,
    )
    assert result["status"] == "proved"
    assert result["python_typechecker"] == _proved_response(root, digest)["python_typechecker"]


def test_compiler_derived_typescript_interface_is_exactly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "typescript-app"
    root.mkdir()
    source = root / "present.ts"
    source.write_text(
        "export function present(value: string): string { return value; }\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("# response template\n", encoding="utf-8")
    executable = tmp_path / "maledictus.exe"
    executable.write_bytes(b"pinned verifier")
    digest = sha256(executable.read_bytes()).hexdigest()
    response = _proved_response(root, digest)
    response["files"] = [{
        "path": "present.ts",
        "sha256": sha256(source.read_bytes()).hexdigest(),
        "symbols": ["present"],
        "scope": "all-source-symbol-bodies",
        "result": "proved",
        "fragment": "strict-typescript-closed-total-functions/v11",
        "verified_interfaces": [{
            "symbol": "present",
            "execution": "synchronous",
            "parameters": [{"name": "value", "type_name": "string"}],
            "return_type": "string",
        }],
    }]
    response.pop("python_typechecker")
    response["typescript_toolchain"] = {
        "compiler": "typescript",
        "compiler_version": "5.9.3",
        "compiler_bundle_sha256": "8" * 64,
        "runtime": "node",
        "runtime_version": "v24.0.0",
        "runtime_executable_sha256": "9" * 64,
    }

    def fake_run(arguments, **_kwargs):
        request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert request["files"] == [{
            "path": "present.ts", "language": "typescript", "symbols": ["present"],
        }]
        return CompletedProcess(arguments, 0, json.dumps(response), "")

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    result = verify_with_maledictus(
        root,
        ["present.ts"],
        {"present.ts": ("present",)},
        source_fingerprint="source-fingerprint",
        executable=executable,
        expected_executable_sha256=digest,
        languages_by_file={"present.ts": "typescript"},
        verified_interfaces=(MaledictusVerifiedInterface(
            "present.ts", "typescript", "present", (("value", "string"),), "string",
        ),),
    )

    assert result["files"] == response["files"]


def test_typescript_interface_mismatch_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "typescript-app"
    root.mkdir()
    source = root / "present.ts"
    source.write_text(
        "export function present(value: string): string { return value; }\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("# response template\n", encoding="utf-8")
    executable = tmp_path / "maledictus.exe"
    executable.write_bytes(b"pinned verifier")
    digest = sha256(executable.read_bytes()).hexdigest()
    response = _proved_response(root, digest)
    response["files"] = [{
        "path": "present.ts",
        "sha256": sha256(source.read_bytes()).hexdigest(),
        "symbols": ["present"],
        "scope": "all-source-symbol-bodies",
        "result": "proved",
        "fragment": "strict-typescript-closed-total-functions/v11",
        "verified_interfaces": [{
            "symbol": "present", "execution": "synchronous",
            "parameters": [{"name": "value", "type_name": "string"}],
            "return_type": "string",
        }],
    }]
    response.pop("python_typechecker")
    response["typescript_toolchain"] = {
        "compiler": "typescript", "compiler_version": "5.9.3",
        "compiler_bundle_sha256": "8" * 64, "runtime": "node",
        "runtime_version": "v24.0.0", "runtime_executable_sha256": "9" * 64,
    }
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **_kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )

    with pytest.raises(MaledictusVerificationError, match="does not match"):
        verify_with_maledictus(
            root,
            ["present.ts"],
            {"present.ts": ("present",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
            languages_by_file={"present.ts": "typescript"},
            verified_interfaces=(MaledictusVerifiedInterface(
                "present.ts", "typescript", "present", (("value", "boolean"),), "string",
            ),),
        )


def test_maledictus_executable_digest_mismatch_refuses_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, _digest = _fixture(tmp_path)
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("untrusted executable must not run")

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    with pytest.raises(MaledictusVerificationError, match="digest mismatch"):
        verify_with_maledictus(
            root,
            ["app.py"],
            {"app.py": ("work",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256="0" * 64,
        )
    assert not called


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda response: response.update(
                schema="maledictus-verification-result/v4",
            ),
            "protocol, verifier, obligation, or source fingerprint mismatch",
        ),
        (lambda response: response.update(status="refused"), "did not prove"),
        (
            lambda response: response["files"][0].update(fragment="some-other-fragment"),
            "does not exactly bind",
        ),
        (
            lambda response: response["verifier_identity"].update(
                executable_sha256="0" * 64,
            ),
            "self-reported executable digest",
        ),
        (
            lambda response: response.update(source_imports=[{"untrusted": True}]),
            "malformed source import",
        ),
        (
            lambda response: response["python_typechecker"].update(
                checker_version="1.5.1",
            ),
            "required strict pinned Python typechecker",
        ),
        (
            lambda response: response["python_typechecker"].pop(
                "runtime_bundle_sha256",
            ),
            "typechecker identity is missing or malformed",
        ),
        (
            lambda response: response["python_typechecker"].update(
                configuration_sha256="not-a-digest",
            ),
            "configuration_sha256 is not a SHA-256 digest",
        ),
        (
            lambda response: response["python_typechecker"].update(
                runtime_version="",
            ),
            "required strict pinned Python typechecker",
        ),
    ],
)
def test_maledictus_tampered_or_weaker_response_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    message: str,
):
    root, executable, digest = _fixture(tmp_path)
    response = _proved_response(root, digest)
    mutation(response)
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )
    with pytest.raises(MaledictusVerificationError, match=message):
        verify_with_maledictus(
            root,
            ["app.py"],
            {"app.py": ("work",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
        )


def _source_import_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, str, dict[str, object]]:
    root = tmp_path / "source-import-app"
    root.mkdir()
    provider = root / "produced.py"
    provider.write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\n"
        "class Candidate:\n"
        "    value: str\n\n"
        "@dataclass(frozen=True)\n"
        "class Request:\n"
        "    value: str\n\n"
        "@operation\n"
        "def build(request: Request) -> Candidate:\n"
        "    return Candidate(request.value)\n",
        encoding="utf-8",
    )
    consumer = root / "consume.py"
    consumer.write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n"
        "from produced import Candidate\n\n"
        "@dataclass(frozen=True)\n"
        "class Request:\n"
        "    candidate: Candidate\n\n"
        "@dataclass(frozen=True)\n"
        "class Completed:\n"
        "    value: str\n\n"
        "@operation\n"
        "def consume(request: Request) -> Completed:\n"
        "    return Completed(request.candidate.value)\n",
        encoding="utf-8",
    )
    executable = tmp_path / "source-import-maledictus.exe"
    executable.write_bytes(b"source import verifier")
    digest = sha256(executable.read_bytes()).hexdigest()
    (root / "app.py").write_text("# response template\n", encoding="utf-8")
    response = _proved_response(root, digest)
    response["files"] = [
        {
            "path": "consume.py",
            "sha256": sha256(consumer.read_bytes()).hexdigest(),
            "symbols": ["consume"],
            "scope": "all-source-symbol-bodies",
            "result": "proved",
            "fragment": "dagcert-closed-typed-operations/v3",
        },
        {
            "path": "produced.py",
            "sha256": sha256(provider.read_bytes()).hexdigest(),
            "symbols": ["build"],
            "scope": "all-source-symbol-bodies",
            "result": "proved",
            "fragment": "dagcert-closed-typed-operations/v3",
        },
    ]
    response["source_imports"] = [{
        "importer_path": "consume.py",
        "module": "produced",
        "provider_path": "produced.py",
        "provider_sha256": sha256(provider.read_bytes()).hexdigest(),
        "imported_symbols": ["Candidate"],
    }]
    return root, executable, digest, response


def test_maledictus_source_import_edge_is_recomputed_from_bound_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest, response = _source_import_fixture(tmp_path)
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **_kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )

    result = verify_with_maledictus(
        root,
        ["consume.py", "produced.py"],
        {"consume.py": ("consume",), "produced.py": ("build",)},
        source_fingerprint="source-fingerprint",
        executable=executable,
        expected_executable_sha256=digest,
    )

    assert result["source_imports"] == response["source_imports"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda edge: edge.update(provider_sha256="0" * 64),
        lambda edge: edge.update(imported_symbols=["Other"]),
        lambda edge: edge.update(importer_path="produced.py"),
        lambda edge: edge.update(module="other"),
    ],
)
def test_maledictus_tampered_source_import_edge_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation,
):
    root, executable, digest, response = _source_import_fixture(tmp_path)
    edges = response["source_imports"]
    assert isinstance(edges, list)
    assert isinstance(edges[0], dict)
    mutation(edges[0])
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **_kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )

    with pytest.raises(MaledictusVerificationError, match="bound source graph"):
        verify_with_maledictus(
            root,
            ["consume.py", "produced.py"],
            {"consume.py": ("consume",), "produced.py": ("build",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
        )


def test_maledictus_timeout_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, executable, digest = _fixture(tmp_path)

    def fake_run(arguments, **kwargs):
        raise TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    with pytest.raises(MaledictusVerificationError, match="cannot execute"):
        verify_with_maledictus(
            root,
            ["app.py"],
            {"app.py": ("work",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
        )


def test_nonzero_maledictus_response_reports_source_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest = _fixture(tmp_path)
    response = _proved_response(root, digest)
    response["status"] = "refused"
    response["diagnostics"] = [{
        "severity": "error",
        "code": "frontend.python.dagcert.partial-or-unsupported-operator",
        "message": "floor division may raise",
        "path": "app.py",
        "line": 14,
        "column": 26,
    }]
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **kwargs: CompletedProcess(
            arguments, 2, json.dumps(response), "",
        ),
    )
    with pytest.raises(
        MaledictusVerificationError,
        match=r"app\.py:14:26 \[frontend\.python\.dagcert.*\] floor division may raise",
    ):
        verify_with_maledictus(
            root,
            ["app.py"],
            {"app.py": ("work",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
        )


def _callable_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, str, MaledictusCallableBinding]:
    root = tmp_path / "callable-app"
    root.mkdir()
    (root / "app.py").write_text("# response template\n", encoding="utf-8")
    (root / "consumer.py").write_text("# consumer\n", encoding="utf-8")
    (root / "provider.py").write_text("# provider\n", encoding="utf-8")
    executable = tmp_path / "callable-maledictus.exe"
    executable.write_bytes(b"callable verifier")
    return (
        root,
        executable,
        sha256(executable.read_bytes()).hexdigest(),
        MaledictusCallableBinding(
            "prepare-enhance",
            "consumer.py",
            "prepare",
            "Request",
            "enhance",
            MaledictusSourceCallableProvider("provider.py", "enhance"),
        ),
    )


def _callable_response(
    root: Path,
    executable_digest: str,
    bindings: tuple[MaledictusCallableBinding, ...],
) -> dict[str, object]:
    response = _proved_response(root, executable_digest)
    response["files"] = [
        {
            "path": "consumer.py",
            "sha256": sha256((root / "consumer.py").read_bytes()).hexdigest(),
            "symbols": ["prepare"],
            "scope": (
                "hash-bound-operation-input-and-concrete-callable-provider-with-"
                "composed-exit-effects"
            ),
            "result": "proved",
            "fragment": "dagcert-closed-typed-operations/v3",
        },
        {
            "path": "provider.py",
            "sha256": sha256((root / "provider.py").read_bytes()).hexdigest(),
            "symbols": ["enhance"],
            "scope": (
                "hash-bound-source-callback-signature-body-and-complete-exit-effects"
            ),
            "result": "proved",
            "fragment": "dagcert-closed-typed-operations/v3",
        },
    ]
    response["python_callable_bindings"] = [
        {
            "id": binding.id,
            "consumer_path": binding.consumer_path,
            "consumer_sha256": sha256(
                (root / binding.consumer_path).read_bytes()
            ).hexdigest(),
            "operation_symbol": binding.operation_symbol,
            "input_record": binding.input_record,
            "field": binding.field,
            "provider": {
                "kind": "source",
                "path": "provider.py",
                "sha256": sha256((root / "provider.py").read_bytes()).hexdigest(),
                "symbol": "enhance",
            },
            "scope": (
                "source-callback-signature-body-and-complete-normal-exception-outcomes-"
                "checked-and-composed"
            ),
        }
        for binding in bindings
    ]
    return response


def test_callable_request_and_returned_source_provenance_are_exactly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest, binding = _callable_fixture(tmp_path)

    def fake_run(arguments, **kwargs):
        request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert request["schema"] == "maledictus-verification-request/v4"
        assert request["files"] == [
            {"path": "consumer.py", "language": "python", "symbols": ["prepare"]},
            {"path": "provider.py", "language": "python", "symbols": ["enhance"]},
        ]
        assert request["python_callable_bindings"] == [{
            "id": "prepare-enhance",
            "consumer_path": "consumer.py",
            "operation_symbol": "prepare",
            "input_record": "Request",
            "field": "enhance",
            "provider": {
                "kind": "source", "path": "provider.py", "symbol": "enhance",
            },
        }]
        return CompletedProcess(
            arguments, 0, json.dumps(_callable_response(root, digest, (binding,))), "",
        )

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    response = verify_with_maledictus(
        root,
        ["consumer.py"],
        {"consumer.py": ("prepare",)},
        source_fingerprint="source-fingerprint",
        executable=executable,
        expected_executable_sha256=digest,
        callable_bindings=(binding,),
    )
    assert response["python_callable_bindings"] == _callable_response(
        root, digest, (binding,)
    )["python_callable_bindings"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.clear(), "wrong number"),
        (lambda rows: rows[0].update(id="unknown"), "unknown or duplicate"),
        (
            lambda rows: rows[0]["provider"].update(sha256="0" * 64),
            "provider evidence does not match",
        ),
        (
            lambda rows: rows[0].update(consumer_sha256="0" * 64),
            "binding evidence does not match",
        ),
    ],
)
def test_missing_unknown_or_tampered_callable_evidence_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    message: str,
):
    root, executable, digest, binding = _callable_fixture(tmp_path)
    response = _callable_response(root, digest, (binding,))
    rows = response["python_callable_bindings"]
    assert isinstance(rows, list)
    mutation(rows)
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )
    with pytest.raises(MaledictusVerificationError, match=message):
        verify_with_maledictus(
            root,
            ["consumer.py"],
            {"consumer.py": ("prepare",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
            callable_bindings=(binding,),
        )


def test_duplicate_callable_evidence_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest, first = _callable_fixture(tmp_path)
    second = MaledictusCallableBinding(
        "prepare-other",
        "consumer.py",
        "prepare",
        "Request",
        "other",
        MaledictusSourceCallableProvider("provider.py", "enhance"),
    )
    response = _callable_response(root, digest, (first, second))
    rows = response["python_callable_bindings"]
    assert isinstance(rows, list)
    assert isinstance(rows[1], dict)
    rows[1]["id"] = first.id
    monkeypatch.setattr(
        "dagcert.maledictus_verifier.run",
        lambda arguments, **kwargs: CompletedProcess(
            arguments, 0, json.dumps(response), "",
        ),
    )
    with pytest.raises(MaledictusVerificationError, match="unknown or duplicate"):
        verify_with_maledictus(
            root,
            ["consumer.py"],
            {"consumer.py": ("prepare",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
            callable_bindings=(first, second),
        )


def test_external_callable_overlay_and_hash_evidence_are_exactly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, executable, digest, _source_binding = _callable_fixture(tmp_path)
    (root / "provider_contract.py").write_text(
        "from nagini_contracts.contracts import ContractOnly\n"
        "@ContractOnly\n"
        "def enhance(value: str) -> str:\n"
        "    ...\n",
        encoding="utf-8",
    )
    binding = MaledictusCallableBinding(
        "prepare-external",
        "consumer.py",
        "prepare",
        "Request",
        "enhance",
        MaledictusExternalCallableProvider(
            "provider", "enhance", "provider_contract.py", "assume-no-exception"
        ),
    )
    consumer_digest = sha256((root / "consumer.py").read_bytes()).hexdigest()
    stub_digest = sha256((root / "provider_contract.py").read_bytes()).hexdigest()
    response = _proved_response(root, digest)
    response["files"] = [{
        "path": "consumer.py",
        "sha256": consumer_digest,
        "symbols": ["prepare"],
        "scope": (
            "hash-bound-operation-input-and-concrete-callable-provider-with-"
            "composed-exit-effects"
        ),
        "result": "proved",
        "fragment": "dagcert-closed-typed-operations/v3",
    }]
    response["external_contracts"] = [{
        "adapter_path": "consumer.py",
        "module": "provider",
        "stub_path": "provider_contract.py",
        "sha256": stub_digest,
        "functions": ["enhance"],
        "nominal_types": [],
        "heap_types": [],
        "exception_types": [],
        "exception_policy": "assume-no-exception",
        "declared_exceptions": [],
        "scope": (
            "provider-import-conformance-and-normal-return-assumed; adapter-symbol-binding-"
            "call-sites-and-preconditions-verified"
        ),
    }]
    response["python_callable_bindings"] = [{
        "id": binding.id,
        "consumer_path": "consumer.py",
        "consumer_sha256": consumer_digest,
        "operation_symbol": "prepare",
        "input_record": "Request",
        "field": "enhance",
        "provider": {
            "kind": "external-contract",
            "module": "provider",
            "stub_path": "provider_contract.py",
            "stub_sha256": stub_digest,
            "symbol": "enhance",
        },
        "scope": (
            "external-provider-conformance-assumed-by-explicit-hash-bound-contract; "
            "fixed-signature-and-declared-exception-outcomes-composed"
        ),
    }]

    def fake_run(arguments, **kwargs):
        request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert request["external_contract_overlays"] == [{
            "adapter_path": "consumer.py",
            "module": "provider",
            "stub_path": "provider_contract.py",
            "exception_policy": "assume-no-exception",
        }]
        assert request["python_callable_bindings"][0]["provider"] == {
            "kind": "external-contract", "module": "provider", "symbol": "enhance",
        }
        return CompletedProcess(arguments, 0, json.dumps(response), "")

    monkeypatch.setattr("dagcert.maledictus_verifier.run", fake_run)
    result = verify_with_maledictus(
        root,
        ["consumer.py"],
        {"consumer.py": ("prepare",)},
        source_fingerprint="source-fingerprint",
        executable=executable,
        expected_executable_sha256=digest,
        callable_bindings=(binding,),
    )
    assert result["python_callable_bindings"] == response["python_callable_bindings"]

    external_results = response["external_contracts"]
    assert isinstance(external_results, list)
    assert isinstance(external_results[0], dict)
    external_results[0]["sha256"] = "0" * 64
    with pytest.raises(MaledictusVerificationError, match="does not exactly bind"):
        verify_with_maledictus(
            root,
            ["consumer.py"],
            {"consumer.py": ("prepare",)},
            source_fingerprint="source-fingerprint",
            executable=executable,
            expected_executable_sha256=digest,
            callable_bindings=(binding,),
        )
