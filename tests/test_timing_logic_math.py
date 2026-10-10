"""Behavioral closure checks for examples written in ordinary quantified LRA."""

from __future__ import annotations

import pytest

from dagcert.linear_logic import prove_implication
from examples.timing_logic.math_examples import (
    all_time_reserve, buffer_preservation, examples,
    min_plus_convolution, quorum_readiness, unattained_supremum,
)


@pytest.mark.parametrize("example", examples(), ids=lambda example: example.name)
def test_every_example_is_decided_without_registering_application_operators(example: object) -> None:
    from examples.timing_logic.math_examples import MathematicalExample

    assert isinstance(example, MathematicalExample)
    proof = prove_implication(example.variables, example.assumptions, example.conclusion)
    assert proof.status == "valid", proof.as_dict()


def test_second_of_three_does_not_count_an_absent_acknowledgement() -> None:
    example = quorum_readiness()
    assumptions = example.assumptions + (
        "(not present_a)", "present_b", "present_c",
        "(= a 0)", "(= b 5)", "(= c 9)",
    )
    proof = prove_implication(example.variables, assumptions, "(and ready (= second 9))")
    assert proof.status == "valid", proof.as_dict()
    false_early_completion = prove_implication(example.variables, assumptions, "(<= second 5)")
    assert false_early_completion.status == "invalid"


def test_missing_quorum_has_no_completion_despite_arbitrary_timestamp_payload() -> None:
    example = quorum_readiness()
    proof = prove_implication(example.variables, example.assumptions + (
        "present_a", "(not present_b)", "(not present_c)", "(= second 0)",
    ), "(not ready)")
    assert proof.status == "valid", proof.as_dict()


def test_quorum_safety_does_not_imply_a_dispatch_deadline() -> None:
    example = quorum_readiness()
    variables = dict(example.variables, dispatched="real")
    assumptions = example.assumptions + (
        "present_a", "present_b", "present_c",
        "(= a 1)", "(= b 2)", "(= c 100)", "(>= dispatched second)",
    )
    proof = prove_implication(variables, assumptions, "(<= dispatched 3)")
    assert proof.status == "invalid"
    bounded = prove_implication(
        variables, assumptions + ("(<= (- dispatched second) 1)",),
        "(<= dispatched 3)",
    )
    assert bounded.status == "valid", bounded.as_dict()


def test_min_plus_curve_latency_cannot_be_shortened() -> None:
    example = min_plus_convolution()
    # Correct latency is five. Claiming four admits a counterexample at t=5.
    wrong = example.conclusion.replace("(- t 5)", "(- t 4)")
    assert prove_implication(example.variables, example.assumptions, wrong).status == "invalid"


def test_infinite_reserve_bound_does_not_follow_from_average_alone() -> None:
    example = all_time_reserve()
    wrong = example.conclusion.replace("(- t 3)", "(- t 30)")
    assert prove_implication(example.variables, example.assumptions, wrong).status == "invalid"


def test_supremum_is_not_an_attained_maximum() -> None:
    example = unattained_supremum()
    proof = prove_implication(
        example.variables, example.assumptions,
        "(exists ((x Real)) (and (> x 0) (< x 1) (= x upper)))",
    )
    assert proof.status == "invalid"


def test_unguarded_variable_size_buffer_update_has_a_counterexample() -> None:
    example = buffer_preservation()
    assumptions = (example.assumptions[0], example.assumptions[2])
    proof = prove_implication(example.variables, assumptions, example.conclusion)
    assert proof.status == "invalid"
    assert proof.counterexample is not None
