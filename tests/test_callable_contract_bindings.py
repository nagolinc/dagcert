from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagcert.certificate import (
    issue_certificate,
    maledictus_callable_bindings,
    source_fingerprint,
    verify_certificate,
)
from dagcert.contract import (
    ContractError,
    ExternalCallableProvider,
    SourceCallableProvider,
    load_contract,
)
from dagcert.maledictus_verifier import (
    MaledictusSourceCallableProvider,
)
from dagcert.source_types import SourceProofBackend


def _add_source_callable_binding(project: dict[str, object]) -> None:
    root = Path(project["root"])
    (root / "provider.py").write_text(
        "def enhance(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    contract_path = Path(project["contract"])
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["callable_bindings"] = [{
        "id": "work-enhance",
        "field": "enhance",
        "provider": {
            "kind": "source",
            "path": "provider.py",
            "symbol": "enhance",
        },
    }]
    contract_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def _refresh_evidence_fingerprint(project: dict[str, object]) -> str:
    root = Path(project["root"])
    evidence_path = Path(project["evidence"])
    fingerprint = source_fingerprint(
        root,
        exclude=[
            "dag_contract.json",
            "english_requirements.json",
            "artifacts/timings.jsonl",
            "artifacts/certificate.json",
        ],
    )
    rows = [
        {**json.loads(line), "source_fingerprint": fingerprint}
        for line in evidence_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    evidence_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return fingerprint


def test_v6_contract_resolves_source_callable_provenance_without_prose_trust(project):
    _add_source_callable_binding(project)

    contract = load_contract(project["contract"], source_root=project["root"])

    declaration = contract.tasks[0].callable_bindings[0]
    assert declaration.id == "work-enhance"
    assert declaration.field == "enhance"
    assert declaration.provider == SourceCallableProvider("provider.py", "enhance")
    resolved = maledictus_callable_bindings(contract)
    assert len(resolved) == 1
    assert resolved[0].consumer_path == "app.py"
    assert resolved[0].operation_symbol == "work"
    assert resolved[0].input_record == "WorkInput"
    assert resolved[0].field == "enhance"
    assert resolved[0].provider == MaledictusSourceCallableProvider(
        "provider.py", "enhance"
    )


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        (
            [
                {
                    "id": "duplicate",
                    "field": "first",
                    "provider": {
                        "kind": "source", "path": "provider.py", "symbol": "enhance",
                    },
                },
                {
                    "id": "duplicate",
                    "field": "second",
                    "provider": {
                        "kind": "source", "path": "provider.py", "symbol": "enhance",
                    },
                },
            ],
            "callable binding IDs must be unique",
        ),
        (
            [{
                "id": "invalid-external",
                "field": "enhance",
                "provider": {
                    "kind": "external-contract",
                    "module": "provider",
                    "symbol": "enhance",
                    "stub_path": "provider_contract.py",
                    "exception_policy": "trust-me",
                },
            }],
            "exception_policy must be assume-no-exception or declared-by-exsures",
        ),
    ],
)
def test_contract_rejects_duplicate_or_invalid_callable_provenance(
    project, bindings, message: str,
):
    root = Path(project["root"])
    (root / "provider.py").write_text(
        "def enhance(value: int) -> int:\n    return value\n", encoding="utf-8"
    )
    contract_path = Path(project["contract"])
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["callable_bindings"] = bindings
    contract_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match=message):
        load_contract(contract_path, source_root=root)


def test_issuance_and_independent_verification_forward_the_same_callable_edges(
    project, monkeypatch: pytest.MonkeyPatch,
):
    _add_source_callable_binding(project)
    fingerprint = _refresh_evidence_fingerprint(project)
    captured = []

    def fake_source_verification(*_args, **kwargs):
        captured.append(tuple(kwargs["callable_bindings"]))
        return {
            "provider": "dagcert.python-source-verification/v2",
            "type_checker": {"checker": "mypy", "version": "test", "mode": "strict"},
            "exception_verifier": {
                "checker": "maledictus",
                "version": "0.1.0",
                "schema": "maledictus-verification-result/v7",
                "result": "proved",
                "source_fingerprint": fingerprint,
                "python_callable_bindings": [],
            },
            "external_contracts": [],
            "signatures": [],
        }

    monkeypatch.setattr(
        "dagcert.certificate.check_python_sources", fake_source_verification
    )
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    backend = SourceProofBackend.maledictus(root / "maledictus.exe", "a" * 64)

    issue_certificate(
        project["contract"],
        project["evidence"],
        certificate,
        requirements_path=project["requirements"],
        source_root=root,
        proof_backend=backend,
    )
    verification = verify_certificate(
        certificate,
        contract_path=project["contract"],
        evidence_path=project["evidence"],
        requirements_path=project["requirements"],
        source_root=root,
        proof_backend=backend,
    )

    assert verification.valid, verification.problems
    assert len(captured) == 2
    assert captured[0] == captured[1]
    assert captured[0][0].id == "work-enhance"


def test_external_callable_provider_resolves_to_a_checked_overlay(project):
    root = Path(project["root"])
    (root / "provider_contract.py").write_text(
        "from nagini_contracts.contracts import ContractOnly\n"
        "@ContractOnly\n"
        "def enhance(value: int) -> int:\n"
        "    ...\n",
        encoding="utf-8",
    )
    contract_path = Path(project["contract"])
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["callable_bindings"] = [{
        "id": "work-external",
        "field": "enhance",
        "provider": {
            "kind": "external-contract",
            "module": "provider",
            "symbol": "enhance",
            "stub_path": "provider_contract.py",
            "exception_policy": "declared-by-exsures",
        },
    }]
    contract_path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_contract(contract_path, source_root=root)
    provider = loaded.tasks[0].callable_bindings[0].provider
    assert provider == ExternalCallableProvider(
        "provider", "enhance", "provider_contract.py", "declared-by-exsures"
    )
    resolved = maledictus_callable_bindings(loaded)[0].provider
    assert resolved.module == "provider"
    assert resolved.symbol == "enhance"
    assert resolved.stub_path == "provider_contract.py"
