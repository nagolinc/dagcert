"""Small, reusable first-order LRA obligations, not application certificates.

No new Dagcert operator is registered for any of these constructions. They are
ordinary formulas of the same recognized mathematical language. A production
certificate must separately bind their premises to source and platform facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class MathematicalExample:
    name: str
    variables: Mapping[str, str]
    assumptions: tuple[str, ...]
    conclusion: str
    explanation: str


def _positive_part(term: str) -> str:
    return f"(ite (>= {term} 0) {term} 0)"


def _maximum(left: str, right: str) -> str:
    return f"(ite (>= {left} {right}) {left} {right})"


def _pipeline_graph(start: str, end: str) -> str:
    """Three ordinary affine/piecewise operation relations, with no UF symbols."""
    return f"""(exists ((middle Real))
        (and (= middle {_positive_part(f'(- {start} 2)')})
             (= {end} (* (/ 1 2) middle))))"""


def pipeline_associativity() -> MathematicalExample:
    first = "(= u (ite (>= x 2) (- x 2) 0))"
    second = "(= v (* (/ 1 2) u))"
    third = "(= y (ite (>= v 3) (- v 3) 0))"
    return MathematicalExample(
        "relational-pipeline-associativity",
        {"x": "real", "y": "real"}, (),
        f"""(=
            (exists ((v Real))
                (and (exists ((u Real)) (and {first} {second})) {third}))
            (exists ((u Real))
                (and {first} (exists ((v Real)) (and {second} {third})))))""",
        "Rebracketing relational composition preserves a three-stage piecewise pipeline.",
    )


def repeated_pipeline() -> MathematicalExample:
    return MathematicalExample(
        "pipeline-result-is-another-pipeline-input",
        {"x": "real", "y": "real"},
        (f"(exists ((z Real)) (and {_pipeline_graph('x', 'z')} {_pipeline_graph('z', 'y')}))",),
        f"(= y (* (/ 1 4) {_positive_part('(- x 6)')}))",
        "A derived relation can be composed again; no ingress-only scalar restriction exists.",
    )


def min_plus_convolution() -> MathematicalExample:
    cost = f"(+ {_positive_part('(- s 2)')} (* 2 {_positive_part('(- (- t s) 3)')}))"
    valid_split = "(and (>= s 0) (<= s t))"
    output = _positive_part("(- t 5)")
    return MathematicalExample(
        "min-plus-convolution-of-rate-latency-curves",
        {}, (),
        f"""(forall ((t Real))
            (=> (>= t 0)
                (and
                    (forall ((s Real)) (=> {valid_split} (<= {output} {cost})))
                    (exists ((s Real)) (and {valid_split} (= {output} {cost}))))))""",
        "The exact convolution has rate 1 and latency 5; quantified bounds are not time samples.",
    )


def quorum_readiness() -> MathematicalExample:
    pairs = (("a", "b"), ("a", "c"), ("b", "c"))
    available = [f"(and present_{left} present_{right})" for left, right in pairs]
    bounds = [
        f"(=> {valid} (<= second {_maximum(left, right)}))"
        for (left, right), valid in zip(pairs, available)
    ]
    witnesses = [
        f"(and {valid} (= second {_maximum(left, right)}))"
        for (left, right), valid in zip(pairs, available)
    ]
    by_deadline = [
        f"(and {valid} (<= {left} deadline) (<= {right} deadline))"
        for (left, right), valid in zip(pairs, available)
    ]
    return MathematicalExample(
        "second-of-three-with-absent-events",
        {
            "a": "real", "b": "real", "c": "real", "second": "real",
            "present_a": "bool", "present_b": "bool", "present_c": "bool",
            "ready": "bool", "deadline": "real",
        },
        (
            f"(= ready (or {' '.join(available)}))",
            f"(=> ready (and {' '.join(bounds)} (or {' '.join(witnesses)})))",
        ),
        f"(= (and ready (<= second deadline)) (or {' '.join(by_deadline)}))",
        "Missing acknowledgements have presence flags, not invented finite or infinite times.",
    )


def all_time_reserve() -> MathematicalExample:
    return MathematicalExample(
        "all-time-reserve-from-variable-output-bounds", {}, (),
        f"""(forall ((t Real) (produced Real) (consumed Real))
            (=> (and (>= t 0)
                     (>= produced {_positive_part('(- t 3)')})
                     (>= consumed 0) (<= consumed t))
                (>= (- (+ 4 produced) consumed) 1)))""",
        "Every nonnegative time is quantified; physical production and demand still need binding.",
    )


def discontinuous_quota() -> MathematicalExample:
    return MathematicalExample(
        "discontinuous-release-quota", {}, (),
        """(forall ((t Real))
            (let ((quota (ite (< t 3) 0 5)))
                (and (=> (and (>= t 0) (< t 3)) (= quota 0))
                     (=> (>= t 3) (= quota 5)))))""",
        "A finite jump is an ordinary piecewise LRA relation, not a new curve operator.",
    )


def unattained_supremum() -> MathematicalExample:
    upper_bound = "(forall ((x Real)) (=> (and (> x 0) (< x 1)) (<= x upper)))"
    least_upper_bound = """(forall ((candidate Real))
        (=> (forall ((x Real)) (=> (and (> x 0) (< x 1)) (<= x candidate)))
            (<= upper candidate)))"""
    return MathematicalExample(
        "supremum-does-not-require-attainment", {"upper": "real"},
        (upper_bound, least_upper_bound), "(= upper 1)",
        "The open interval (0,1) has supremum 1 although no member equals 1.",
    )


def no_finite_upper_bound() -> MathematicalExample:
    return MathematicalExample(
        "unbounded-set-has-no-finite-real-supremum", {}, (),
        "(not (exists ((upper Real)) (forall ((x Real)) (=> (>= x 0) (<= x upper)))))",
        "Unboundedness is represented logically; +infinity is not silently coerced to a Real.",
    )


def buffer_initialization() -> MathematicalExample:
    return MathematicalExample(
        "supplied-buffer-invariant-initialization",
        {"capacity": "real", "fill": "real"},
        ("(>= capacity 0)", "(= fill 0)"),
        "(and (>= fill 0) (<= fill capacity))",
        "The initial case is a supplied proof obligation, not a guessed invariant.",
    )


def buffer_preservation() -> MathematicalExample:
    return MathematicalExample(
        "supplied-buffer-invariant-preservation",
        {"capacity": "real", "fill": "real", "amount": "real", "after": "real", "putting": "bool"},
        (
            "(and (>= capacity 0) (>= fill 0) (<= fill capacity) (>= amount 0))",
            "(ite putting (<= amount (- capacity fill)) (<= amount fill))",
            "(= after (ite putting (+ fill amount) (- fill amount)))",
        ),
        "(and (>= after 0) (<= after capacity))",
        "The guarded step preserves capacity for variable-size production and consumption.",
    )


def examples() -> tuple[MathematicalExample, ...]:
    return (
        pipeline_associativity(), repeated_pipeline(), min_plus_convolution(),
        quorum_readiness(), all_time_reserve(), discontinuous_quota(),
        unattained_supremum(), no_finite_upper_bound(),
        buffer_initialization(), buffer_preservation(),
    )
