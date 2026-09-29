from copy import deepcopy
import json
from pathlib import Path

import pytest

from dagcert.contract import ContractError, load_contract
from dagcert.javascript_interfaces import (
    JavaScriptInterface, JavaScriptInterfaceError, compiler_parameter_rows,
    parse_javascript_interface,
)
from dagcert.maledictus_verifier import (
    MaledictusVerificationError, MaledictusVerifiedInterface,
    _validate_verified_interfaces,
)
from dagcert.source_types import (
    SourceProofBackend, SourceTypeError, check_python_sources,
    type_enforcement_descriptor,
)


def _interface(execution="asynchronous", return_type="void", parameters=None):
    return {
        "execution": execution,
        "parameters": [] if parameters is None else parameters,
        "return_type": return_type,
    }


def _record():
    return {"kind": "record", "fields": [
        {"name": "revision", "type_name": "number"},
        {"name": "readyToServe", "type_name": "number"},
    ]}


def _contract(tmp_path, interface, *, symbol="loadBatch", source=None):
    (tmp_path / "browser.js").write_text(
        source or "/** @returns {Promise<void>} */\nexport async function loadBatch() {}\n",
        encoding="utf-8",
    )
    raw = {
        "schema": "dagcert-contract/v12",
        "workers": [{"id": "browser", "concurrency": 1}],
        "resources": [],
        "tasks": [{
            "id": "browser.callback", "role": "operation", "worker": "browser",
            "implementation": {"language": "javascript", "path": "browser.js", "symbol": symbol},
            "verified_interface": interface,
            "outcomes": [{"type": interface["return_type"], "resources": {}, "metadata": {}}],
            "error_budget": None, "external_contract": None,
            "start_resources": {}, "depends_on": [],
            "timings": {"completion": {
                "metric": "duration", "upper_ms": 10, "minimum_samples": 0,
                "safety_factor": 1, "evidence": "assumed",
            }},
        }],
        "channels": [], "external_handoffs": [], "external_boundaries": [],
        "compositions": [], "state_claims": [], "metadata": {},
    }
    path = tmp_path / "dag_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_contract(path, source_root=tmp_path)


@pytest.mark.parametrize("execution", ["synchronous", "asynchronous"])
@pytest.mark.parametrize("return_type", ["void", "boolean", "number", "string"])
def test_execution_and_fulfilled_return_survive_contract_parsing(tmp_path, execution, return_type):
    contract = _contract(tmp_path, _interface(execution, return_type))
    signature = contract.tasks[0].source_signature
    assert signature.execution == execution
    assert signature.outcome_types == (return_type,)


def test_closed_snapshot_shape_survives_proof_request_and_sealed_result(tmp_path, monkeypatch):
    declared = _interface("synchronous", "boolean", [{"name": "snapshot", "type": _record()}])
    contract = _contract(tmp_path, declared, symbol="apply")
    signature = contract.tasks[0].source_signature
    assert signature.record_parameters == (
        ("snapshot", (("readyToServe", "number"), ("revision", "number"))),
    )
    captured = []

    def verify(_root, _files, _symbols, **kwargs):
        captured.extend(kwargs["verified_interfaces"])
        return {"status": "proved"}  # Interface propagation test, not backend proof.

    monkeypatch.setattr("dagcert.source_types.verify_with_maledictus", verify)
    result = check_python_sources(
        tmp_path, (signature,), source_fingerprint="f" * 64,
        proof_backend=SourceProofBackend.maledictus(tmp_path / "backend.exe", "a" * 64),
    )
    assert captured[0].execution == "synchronous"
    assert captured[0].record_parameters == signature.record_parameters
    assert result["signatures"][0]["record_parameters"] == [{
        "name": "snapshot", "fields": [["readyToServe", "number"], ["revision", "number"]],
    }]


@pytest.mark.parametrize("bad_type", ["object", "any", "unknown", "void", "Promise<number>"])
def test_unsealed_parameter_types_refuse(tmp_path, bad_type):
    with pytest.raises(ContractError, match="closed record descriptors"):
        _contract(tmp_path, _interface(parameters=[{"name": "snapshot", "type": bad_type}]))


@pytest.mark.parametrize("bad_shape", [
    {"kind": "record", "fields": [{"name": "x", "type_name": "object"}]},
    {"kind": "record", "fields": [{"name": "x", "type_name": "number", "optional": True}]},
    {"kind": "record", "fields": [{"name": "x", "type_name": "number"}] * 2},
    {"kind": "record", "fields": [], "additionalProperties": True},
])
def test_record_shape_cannot_smuggle_dynamic_fields_or_effects(tmp_path, bad_shape):
    with pytest.raises(ContractError):
        _contract(tmp_path, _interface(parameters=[{"name": "snapshot", "type": bad_shape}]))


def _expected_proof():
    interface = parse_javascript_interface(
        _interface(parameters=[{"name": "snapshot", "type": _record()}]), "callback",
    )
    assertion = MaledictusVerifiedInterface(
        "browser.js", "javascript", "loadBatch", interface.parameters,
        interface.return_type, execution=interface.execution,
        record_parameters=interface.record_parameters,
    )
    row = {
        "symbol": "loadBatch", "execution": "asynchronous",
        "parameters": compiler_parameter_rows(interface), "return_type": "void",
    }
    return assertion, row


def test_exact_async_record_compiler_evidence_is_accepted():
    assertion, row = _expected_proof()
    _validate_verified_interfaces("browser.js", "javascript", [row], (assertion,))


@pytest.mark.parametrize("mutation", ["sync", "return", "primitive", "field", "extra", "missing"])
def test_forged_or_missing_callback_interface_evidence_refuses(mutation):
    assertion, original = _expected_proof()
    row = deepcopy(original)
    if mutation == "sync":
        row["execution"] = "synchronous"
    elif mutation == "return":
        row["return_type"] = "boolean"
    elif mutation == "primitive":
        row["parameters"] = [{"name": "snapshot", "type_name": "object"}]
    elif mutation == "field":
        row["parameters"][0]["descriptor"]["fields"][0]["type_name"] = "string"
    elif mutation == "extra":
        row["platform_calls"] = ["fetch"]
    with pytest.raises(MaledictusVerificationError):
        _validate_verified_interfaces(
            "browser.js", "javascript", [] if mutation == "missing" else [row], (assertion,),
        )


@pytest.mark.parametrize("source, diagnostic", [
    ("export async function loadBatch() { return await unknown(); }", "unsealed async callee"),
    ("export async function loadBatch() { await fetch('/feed'); }", "unsealed platform call"),
])
def test_interface_parsing_never_overrides_backend_source_refusal(tmp_path, monkeypatch, source, diagnostic):
    signature = _contract(tmp_path, _interface(), source=source).tasks[0].source_signature

    def refuse(*_args, **_kwargs):
        raise MaledictusVerificationError(diagnostic)

    monkeypatch.setattr("dagcert.source_types.verify_with_maledictus", refuse)
    with pytest.raises(SourceTypeError, match=diagnostic):
        check_python_sources(
            tmp_path, (signature,), source_fingerprint="f" * 64,
            proof_backend=SourceProofBackend.maledictus(tmp_path / "backend.exe", "a" * 64),
        )


def test_record_assertions_cannot_hide_unused_shapes():
    with pytest.raises(JavaScriptInterfaceError):
        compiler_parameter_rows(JavaScriptInterface(
            "synchronous", (), "void", (("unused", (("x", "number"),)),),
        ))


def test_interface_parser_is_part_of_the_sealed_type_kernel():
    assert "javascript_interfaces.py" in type_enforcement_descriptor()["kernel_manifest"]


def test_void_completion_cannot_impersonate_a_python_record_named_void(tmp_path):
    _contract(tmp_path, _interface())
    (tmp_path / "consumer.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n"
        "@dataclass(frozen=True)\nclass void:\n    value: int\n"
        "@dataclass(frozen=True)\nclass Done:\n    value: int\n"
        "@operation\ndef consume(request: void) -> Done:\n    return Done(request.value)\n",
        encoding="utf-8",
    )
    path = tmp_path / "dag_contract.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    consumer = deepcopy(raw["tasks"][0])
    consumer.update({
        "id": "consume",
        "implementation": {"language": "python", "path": "consumer.py", "symbol": "consume"},
        "outcomes": [{"type": "Done", "resources": {}, "metadata": {}}],
        "depends_on": [{"task": "browser.callback", "outcome_type": "void"}],
    })
    consumer.pop("verified_interface")
    raw["tasks"].append(consumer)
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="cannot consume void callback completion"):
        load_contract(path, source_root=tmp_path)
