"""Bind joint operation/assertion proofs without admitting generic heap proofs.

These are protocol tests. Real assertion discharge is exercised by Maledictus
and the separate CLI integration controls, not by these mocked responses.
"""
from hashlib import sha256
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from dagcert.maledictus_verifier import MaledictusVerificationError, verify_with_maledictus


JOINT_FRAGMENT = "dagcert-closed-typed-operations+semantic-assertions/v1"


@pytest.fixture
def joint_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "worker.py"
    source.write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\n"
        "class Value:\n    text: str\n\n"
        "@operation\n"
        "def work(value: Value) -> Value:\n"
        "    assert value is value\n    return value\n",
        encoding="utf-8",
    )
    executable = tmp_path / "maledictus.exe"
    executable.write_bytes(b"joint proof protocol fixture")
    digest = sha256(executable.read_bytes()).hexdigest()
    file_result = {
        "path": "worker.py", "sha256": sha256(source.read_bytes()).hexdigest(),
        "symbols": ["work"], "scope": "all-source-symbol-bodies",
        "result": "proved", "fragment": JOINT_FRAGMENT,
    }
    response = {
        "schema": "maledictus-verification-result/v8",
        "verifier": "maledictus", "version": "0.1.0", "status": "proved",
        "proof_obligation": "no-undeclared-exceptional-exit",
        "source_fingerprint": "joint-proof-source",
        "files": [file_result], "source_imports": [], "external_contracts": [],
        "cross_language_bindings": [], "python_callable_bindings": [],
        "embedded_external_calls": [], "obligations": [], "diagnostics": [],
        "verifier_identity": {
            "executable_sha256": digest,
            "frontend_bundle_sha256": "1" * 64, "kernel_bundle_sha256": "2" * 64,
        },
        "python_typechecker": {
            "checker": "mypy", "checker_version": "1.5.0",
            "profile": "strict-issuance", "package_sha256": "3" * 64,
            "runtime": "python", "runtime_version": "Python 3.12.10",
            "runtime_executable_sha256": "4" * 64,
            "runtime_bundle_sha256": "5" * 64,
            "configuration_sha256": "6" * 64, "contract_support_sha256": "7" * 64,
        },
    }

    def backend(arguments, **kwargs):
        return CompletedProcess(arguments, 0, json.dumps(response), "")

    monkeypatch.setattr("dagcert.maledictus_verifier.run", backend)

    def verify(*, proof_only=False):
        return verify_with_maledictus(
            root, [] if proof_only else ["worker.py"],
            {} if proof_only else {"worker.py": ("work",)},
            source_fingerprint="joint-proof-source", executable=executable,
            expected_executable_sha256=digest,
            proof_only_files=["worker.py"] if proof_only else [],
        )

    return response, file_result, verify


def test_exact_joint_operation_assertion_proof_is_accepted(joint_proof):
    _, _, verify = joint_proof
    result = verify()
    assert result["files"][0]["fragment"] == JOINT_FRAGMENT


def test_joint_proof_is_also_valid_for_a_proof_only_import(joint_proof):
    _, file_result, verify = joint_proof
    file_result["symbols"] = []
    result = verify(proof_only=True)
    assert result["files"][0]["fragment"] == JOINT_FRAGMENT


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64),
    ("symbols", ["other"]),
    ("scope", "signature-only"),
    ("scope", "hash-bound-source-callback-signature-body-and-complete-exit-effects"),
    ("result", "refuted"),
    ("result", "refused"),
    ("fragment", "transitive-source-heap-contracts/v66"),
    ("fragment", "heap-method-contracts/v76"),
    ("fragment", "dagcert-closed-typed-operations+semantic-assertions/v999"),
])
def test_joint_proof_cannot_substitute_other_scope_source_or_fragment(joint_proof, field, value):
    _, file_result, verify = joint_proof
    file_result[field] = value
    with pytest.raises(MaledictusVerificationError, match="does not exactly bind"):
        verify()


def test_joint_file_cannot_override_overall_refutation(joint_proof):
    response, _, verify = joint_proof
    response["status"] = "refuted"
    with pytest.raises(MaledictusVerificationError, match="did not prove every bound operation"):
        verify()
