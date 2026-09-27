from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagcert.analysis import analyze_contract
from dagcert.contract import ContractError, load_contract
from dagcert.formula import evaluate_formula


def _write_contract(tmp_path: Path, *, transport: str = "json") -> Path:
    (tmp_path / "browser.js").write_text(
        "/** @param {string} prompt @returns {boolean} */\n"
        "export function requestAccepted(prompt) { return prompt !== ''; }\n",
        encoding="utf-8",
    )
    (tmp_path / "server.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\n"
        "class AdmissionInput:\n"
        "    request_accepted: bool\n\n"
        "@dataclass(frozen=True)\n"
        "class Admitted:\n"
        "    accepted: bool\n\n"
        "@operation\n"
        "def admit(request: AdmissionInput) -> Admitted:\n"
        "    return Admitted(request.request_accepted)\n",
        encoding="utf-8",
    )
    task_common: dict[str, object] = {
        "role": "operation",
        "error_budget": None,
        "external_contract": None,
        "start_resources": {},
        "metadata": {},
    }
    contract = {
        "schema": "dagcert-contract/v9",
        "workers": [
            {"id": "browser", "concurrency": 1, "metadata": {}},
            {"id": "server", "concurrency": 1, "metadata": {}},
        ],
        "resources": [],
        "tasks": [
            {
                **task_common,
                "id": "browser.request.accept",
                "worker": "browser",
                "implementation": {
                    "language": "javascript",
                    "path": "browser.js",
                    "symbol": "requestAccepted",
                },
                "verified_interface": {
                    "execution": "synchronous",
                    "parameters": [{"name": "prompt", "type": "string"}],
                    "return_type": "boolean",
                },
                "outcomes": [{"type": "boolean", "resources": {}, "metadata": {}}],
                "depends_on": [],
                "timings": {
                    "decision": {
                        "metric": "duration",
                        "upper_ms": 1,
                        "minimum_samples": 0,
                        "safety_factor": 1,
                        "evidence": "assumed",
                    }
                },
            },
            {
                **task_common,
                "id": "server.request.admit",
                "worker": "server",
                "implementation": {
                    "language": "python",
                    "path": "server.py",
                    "symbol": "admit",
                },
                "outcomes": [{"type": "Admitted", "resources": {}, "metadata": {}}],
                "depends_on": [
                    {
                        "task": "browser.request.accept",
                        "outcome_type": "boolean",
                        "input_field": "request_accepted",
                    }
                ],
                "timings": {
                    "completion": {
                        "metric": "duration",
                        "upper_ms": 2,
                        "minimum_samples": 0,
                        "safety_factor": 1,
                        "evidence": "assumed",
                    }
                },
            },
        ],
        "channels": [],
        "external_handoffs": [
            {
                "id": "fetch-request-accepted",
                "transport": transport,
                "wire_field": "requestAccepted",
                "source": {
                    "task": "browser.request.accept",
                    "outcome_type": "boolean",
                },
                "destination": {
                    "task": "server.request.admit",
                    "input_field": "request_accepted",
                },
                "assumption": (
                    "JSON fetch and Flask decoding preserve the named boolean field or report "
                    "a failed crossing."
                ),
                "upper_ms": 20,
                "bad_event_probability_upper": 0.01,
                "metadata": {},
            }
        ],
        "compositions": [
            {
                "id": "fetch-admission",
                "expression": {
                    "kind": "external_handoff",
                    "handoff": "fetch-request-accepted",
                    "producer": {
                        "kind": "leaf",
                        "task": "browser.request.accept",
                        "timing": "decision",
                        "outcome_type": "boolean",
                    },
                    "consumer": {
                        "kind": "leaf",
                        "task": "server.request.admit",
                        "timing": "completion",
                        "outcome_type": "Admitted",
                    },
                },
                "metadata": {},
            }
        ],
        "state_claims": [],
        "metadata": {},
    }
    path = tmp_path / "dag_contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return path


def test_json_handoff_maps_compiler_types_and_composes_bounds(tmp_path: Path) -> None:
    contract = load_contract(_write_contract(tmp_path), source_root=tmp_path)
    analysis = analyze_contract(contract, (), source_fingerprint="0" * 64)

    duration = evaluate_formula(
        {"eq": [{"composition_upper_ms": "composition:fetch-admission"}, 23]},
        contract,
        analysis,
    )
    probability = evaluate_formula(
        {
            "eq": [
                {
                    "composition_failure_probability_upper": (
                        "composition:fetch-admission"
                    )
                },
                0.01,
            ]
        },
        contract,
        analysis,
    )

    assert duration.passed
    assert probability.passed
    assert "external-handoff:fetch-request-accepted" in probability.primitive_refs


def test_finite_repeat_counts_each_transport_crossing(tmp_path: Path) -> None:
    path = _write_contract(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    handoff_expression = raw["compositions"][0]["expression"]
    raw["compositions"][0]["expression"] = {
        "kind": "finite_repeat",
        "count": 3,
        "body": handoff_expression,
    }
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    contract = load_contract(path, source_root=tmp_path)
    analysis = analyze_contract(contract, (), source_fingerprint="0" * 64)

    duration = evaluate_formula(
        {"eq": [{"composition_upper_ms": "composition:fetch-admission"}, 69]},
        contract,
        analysis,
    )
    probability = evaluate_formula(
        {
            "eq": [
                {
                    "composition_failure_probability_upper": (
                        "composition:fetch-admission"
                    )
                },
                0.03,
            ]
        },
        contract,
        analysis,
    )

    assert duration.passed
    assert probability.passed


def test_url_query_refuses_boolean_to_bool_as_not_representation_preserving(
    tmp_path: Path,
) -> None:
    with pytest.raises(ContractError, match="representation-preserving primitive mapping"):
        load_contract(
            _write_contract(tmp_path, transport="url_query"),
            source_root=tmp_path,
        )


def test_type_mismatch_without_declared_handoff_remains_rejected(tmp_path: Path) -> None:
    path = _write_contract(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["external_handoffs"] = []
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    with pytest.raises(ContractError, match="expects 'bool', not 'boolean'"):
        load_contract(path, source_root=tmp_path)
