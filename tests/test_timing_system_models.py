"""Production-shaped examples and adversarial timing assumptions."""

from copy import deepcopy
import json

import pytest

from dagcert.contract import ContractError, load_contract
from dagcert.analysis import analyze_contract
from dagcert.state_model import prove_state_claim
from dagcert.temporal import prove_temporal_bound, temporal_failure_upper
from examples.timing_systems.invariants import SOURCE_ROOT
from examples.timing_systems.models import contract_document


def test_all_example_invariants_and_infinite_variable_reserve(tmp_path) -> None:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract_document()), encoding="utf-8")
    contract = load_contract(path, source_root=SOURCE_ROOT)
    analysis = analyze_contract(contract, (), source_fingerprint="a" * 64)
    for claim in contract.state_claims:
        proof = prove_state_claim(claim, contract, analysis)
        assert proof.passed, proof.summary
    stream = contract.state_claim_by_id["stream.infinite-reserve"]
    assert "extremum=400 media_ms" in prove_temporal_bound(stream.specification, contract)[1]
    stronger = deepcopy(stream.specification)
    stronger["bound"] = 401
    assert not prove_temporal_bound(stronger, contract)[0]


def test_faster_average_but_larger_outage_exhausts_real_reserve(tmp_path) -> None:
    document = contract_document()
    stream = document["state_claims"][-1]
    cost = next(item for item in stream["network"]["envelopes"] if item["kind"] == "workload")
    cost["excess_work"] = 12000
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    contract = load_contract(path, source_root=SOURCE_ROOT)
    spec = contract.state_claim_by_id["stream.infinite-reserve"].specification
    assert not prove_temporal_bound(spec, contract)[0]


def test_finite_run_assumption_cannot_be_reused_forever(tmp_path) -> None:
    document = contract_document()
    document["state_claims"][-1]["network"]["envelopes"][0]["horizon_ms"] = 1800000
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractError, match="window"):
        load_contract(path, source_root=SOURCE_ROOT)


def test_whole_envelope_probability_is_explicit_not_independent_trials(tmp_path) -> None:
    document = contract_document()
    for premise in document["state_claims"][-1]["network"]["envelopes"]:
        premise["failure_probability_upper"] = "1/100"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    contract = load_contract(path, source_root=SOURCE_ROOT)
    spec = contract.state_claim_by_id["stream.infinite-reserve"].specification
    assert temporal_failure_upper(spec) == pytest.approx(0.04)
