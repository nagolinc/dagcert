"""A mathematical proof artifact is checked by replay, not by its pass field."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

import pytest

from dagcert.linear_certificates import MathCertificateError, issue_math_certificate, verify_math_certificate


def _reseal(document: dict[str, Any]) -> None:
    payload = {key: value for key, value in document.items() if key != "certificate_sha256"}
    document["certificate_sha256"] = sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def test_mathematical_certificate_round_trip_replays_actual_quantified_proof() -> None:
    certificate = issue_math_certificate(
        {"delay": "real"}, ["(>= delay 0)"],
        "(forall ((start Real)) (exists ((finish Real)) (= finish (+ start delay))))",
    )
    assert certificate["schema"] == "dagcert-mathematical-certificate/v1"
    assert certificate["logic"] == "SMT-LIB/LRA"
    assert verify_math_certificate(json.loads(json.dumps(certificate))).status == "valid"


def test_unchanged_inputs_and_backend_give_a_stable_artifact() -> None:
    assert issue_math_certificate({}, [], "true") == issue_math_certificate({}, [], "true")


@pytest.mark.parametrize(("assumptions", "conclusion", "status"), [
    ([], "false", "invalid"),
    (["false"], "true", "inconsistent"),
])
def test_nonvalid_requests_do_not_issue_a_certificate(assumptions: list[str], conclusion: str, status: str) -> None:
    with pytest.raises(MathCertificateError) as caught:
        issue_math_certificate({}, assumptions, conclusion)
    assert caught.value.result is not None
    assert caught.value.result.status == status


def test_logical_implication_with_false_antecedent_remains_a_valid_mathematical_formula() -> None:
    certificate = issue_math_certificate({"p": "bool"}, [], "(=> false p)")
    assert verify_math_certificate(certificate).status == "valid"


def test_modified_conclusion_is_not_accepted_with_old_hash() -> None:
    certificate = issue_math_certificate({"x": "real"}, ["(>= x 0)"], "(>= x 0)")
    certificate["conclusion"] = "(> x 0)"
    with pytest.raises(MathCertificateError, match="SHA-256"):
        verify_math_certificate(certificate)


def test_resealed_false_conclusion_is_refuted_by_actual_solver() -> None:
    certificate = issue_math_certificate({"x": "real"}, ["(>= x 0)"], "(>= x 0)")
    certificate["conclusion"] = "(> x 0)"
    _reseal(certificate)
    result = verify_math_certificate(certificate)
    assert result.status == "invalid"
    assert result.counterexample == {"x": "0"}


def test_resealed_inconsistent_premises_do_not_create_a_vacuous_pass() -> None:
    certificate = issue_math_certificate({}, [], "true")
    certificate["assumptions"] = ["false"]
    _reseal(certificate)
    assert verify_math_certificate(certificate).status == "inconsistent"


def test_resealed_backend_replacement_is_refused() -> None:
    certificate = issue_math_certificate({}, [], "true")
    certificate["backend"]["solver"]["version"] = "not the solver that issued this"
    certificate["backend_sha256"] = sha256(json.dumps(
        certificate["backend"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    _reseal(certificate)
    with pytest.raises(MathCertificateError, match="backend differs"):
        verify_math_certificate(certificate)


def test_recorded_decision_does_not_override_recomputed_metadata() -> None:
    certificate = issue_math_certificate({}, [], "true")
    certificate["decision"]["reason"] = "a checker said trust me"
    _reseal(certificate)
    with pytest.raises(MathCertificateError, match="recomputed"):
        verify_math_certificate(certificate)


@pytest.mark.parametrize("field", ["schema", "logic", "variables", "assumptions", "conclusion", "decision"])
def test_malformed_resealed_artifact_is_rejected(field: str) -> None:
    certificate = deepcopy(issue_math_certificate({}, [], "true"))
    certificate[field] = None
    _reseal(certificate)
    with pytest.raises(MathCertificateError):
        verify_math_certificate(certificate)


def test_certificate_does_not_admit_arbitrary_new_trust_fields() -> None:
    certificate = issue_math_certificate({}, [], "true")
    certificate["skip_replay"] = True
    _reseal(certificate)
    with pytest.raises(MathCertificateError):
        verify_math_certificate(certificate)


def test_resealed_malformed_formula_has_a_certificate_diagnostic() -> None:
    certificate = issue_math_certificate({}, [], "true")
    certificate["conclusion"] = "("
    _reseal(certificate)
    with pytest.raises(MathCertificateError, match="invalid formula"):
        verify_math_certificate(certificate)


def test_malformed_request_has_a_certificate_diagnostic() -> None:
    with pytest.raises(MathCertificateError, match="invalid mathematical proof request"):
        issue_math_certificate({}, [], "(= unknown 0)")
