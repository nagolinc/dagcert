"""Real solver decisions and closure checks for first-order linear arithmetic."""

from __future__ import annotations

import json
from fractions import Fraction

import pytest
import z3  # type: ignore[import-untyped]

from dagcert import linear_logic
from dagcert.linear_logic import (
    LinearLogicError,
    prove_implication,
    substitute_formula,
    validate_formula,
)


def test_exact_rational_arithmetic_has_no_float_rounding() -> None:
    result = prove_implication({"x": "real"}, ["(= x (+ 0.1 0.2))"], "(= x 0.3)")
    assert result.status == "valid"
    assert result.counterexample is None
    assert result.solver_metadata["backend"] == "z3"
    assert json.loads(json.dumps(result.as_dict()))["status"] == "valid"


def test_invalid_bound_produces_a_real_counterexample() -> None:
    result = prove_implication({"x": "real", "enabled": "bool"}, ["(>= x 0)", "enabled"], "(< x 0.5)")
    assert result.status == "invalid"
    assert result.counterexample is not None
    assert Fraction(str(result.counterexample["x"])) >= Fraction(1, 2)
    assert result.counterexample["enabled"] is True


def test_contradictory_premises_do_not_certify_an_arbitrary_conclusion() -> None:
    result = prove_implication({"x": "real"}, ["(> x 1)", "(< x 0)"], "false")
    assert result.status == "inconsistent"
    assert result.counterexample is None


@pytest.mark.parametrize("formula", [
    "(forall ((x Real)) (exists ((y Real)) (> y x)))",
    "(forall ((x Real)) (exists ((y Real)) (forall ((z Real)) (=> (> z y) (> z x)))))",
    "(forall ((x Real)) (exists ((y Real)) (forall ((z Real)) (exists ((w Real)) "
    "(and (> y x) (> w (+ z y)))))))",
    "(forall ((b Bool)) (exists ((x Real)) (= x (ite b 1 2))))",
    "(exists ((b Bool)) (forall ((c Bool)) (= (xor b c) (not c))))",
    "(forall ((x Real) (y Real)) (= (ite (<= x y) x y) (ite (>= y x) x y)))",
])
def test_quantifier_alternation_and_boolean_quantification(formula: str) -> None:
    assert prove_implication({}, [], formula).status == "valid"


@pytest.mark.parametrize("formula", [
    "(exists ((x Real)) (forall ((y Real)) (> x y)))",
    "(forall ((x Real)) (exists ((y Real)) (and (> y x) (< y x))))",
    "(forall ((b Bool)) b)",
])
def test_invalid_closed_quantified_sentences_have_no_invented_bound_witness(formula: str) -> None:
    result = prove_implication({}, [], formula)
    assert result.status == "invalid"
    assert result.counterexample == {}


def test_quantified_assumptions_are_checked_for_consistency() -> None:
    result = prove_implication(
        {"ceiling": "real"}, ["(forall ((t Real)) (<= t ceiling))"], "true",
    )
    assert result.status == "inconsistent"


def test_quantifier_elimination_preserves_free_parameter_counterexamples() -> None:
    result = prove_implication(
        {"limit": "real"}, ["(>= limit 0)"],
        "(forall ((t Real)) (=> (and (>= t 0) (<= t limit)) (<= t 10)))",
    )
    assert result.status == "invalid"
    assert result.counterexample is not None
    assert Fraction(str(result.counterexample["limit"])) > 10


def test_piecewise_expression_results_can_feed_further_piecewise_expressions() -> None:
    result = prove_implication(
        {"x": "real"}, [],
        "(= (ite (<= (ite (>= x 0) x (- x)) 3) (ite (>= x 0) x (- x)) 3) "
        "(ite (and (>= x (- 3)) (<= x 3)) (ite (>= x 0) x (- x)) 3))",
    )
    assert result.status == "valid"


def test_standard_let_bindings_are_typed_and_expanded_by_z3() -> None:
    checked = validate_formula(
        "(let ((doubled (* 2 x))) (= (+ doubled doubled) (* 4 x)))", {"x": "real"},
    )
    assert checked.free_variables == ("x",)
    assert not checked.quantified
    assert prove_implication(dict(checked.variables), [], checked.text).status == "valid"


def test_closed_rational_coefficient_expressions_remain_linear() -> None:
    assert prove_implication(
        {"x": "real"}, [], "(= (* (/ (+ 1 2) 6) x) (/ x 2))",
    ).status == "valid"


def test_strict_bounds_and_unattained_infimum_are_distinct() -> None:
    variables = {"infimum": "real"}
    assert prove_implication(variables, ["(= infimum 0)"],
        "(forall ((epsilon Real)) (=> (> epsilon 0) "
        "(exists ((x Real)) (and (> x infimum) (< x (+ infimum epsilon))))))",
    ).status == "valid"
    assert prove_implication(variables, ["(= infimum 0)"],
        "(exists ((x Real)) (and (> x 0) (= x infimum)))",
    ).status == "invalid"


def test_lemma_conclusion_can_be_substituted_and_used_as_next_premise() -> None:
    lemma = "(>= (+ x 2) 2)"
    assert prove_implication({"x": "real"}, ["(>= x 0)"], lemma).status == "valid"
    instance = substitute_formula(lemma, {"x": "real"}, {"x": "(+ delay queue)"},
                                  result_variables={"delay": "real", "queue": "real"})
    assert prove_implication(
        {"delay": "real", "queue": "real"}, [instance], "(>= (+ queue delay 10) 10)",
    ).status == "valid"


def test_substitution_is_simultaneous_not_a_sequential_text_rewrite() -> None:
    variables = {"x": "real", "y": "real"}
    formula = substitute_formula("(< x y)", variables, {"x": "y", "y": "x"})
    assert prove_implication(variables, [formula], "(< y x)").status == "valid"


def test_substitution_does_not_capture_a_free_variable_with_a_quantified_name() -> None:
    instance = substitute_formula(
        "(forall ((y Real)) (> x y))", {"x": "real"}, {"x": "y"},
        result_variables={"y": "real"},
    )
    assert validate_formula(instance, {"y": "real"}).free_variables == ("y",)
    assert prove_implication({"y": "real"}, [], instance).status == "invalid"


def test_bound_occurrences_are_not_replaced_when_they_shadow_a_declared_constant() -> None:
    formula = substitute_formula(
        "(and (= x 0) (forall ((x Real)) (= x x)))", {"x": "real"}, {"x": "0"},
        result_variables={},
    )
    assert prove_implication({}, [], formula).status == "valid"


def test_nested_alpha_renaming_is_stable_and_retains_free_names() -> None:
    variables = {"x": "real", "y": "real", "z": "real", "__dagcert_bound_0": "real"}
    formula = "(forall ((x Real)) (exists ((y Real)) (and (< x y) (< z y))))"
    checked = validate_formula(formula, variables)
    reparsed = validate_formula(checked.text, variables)
    assert reparsed == checked
    assert checked.free_variables == ("z",)
    assert prove_implication(variables, [], f"(= {formula} {checked.text})").status == "valid"


def test_smt_let_expansion_cannot_capture_a_free_symbol_during_serialization() -> None:
    variables = {"x": "real"}
    formula = "(let ((free x)) (forall ((x Real)) (> free x)))"
    checked = validate_formula(formula, variables)
    assert checked.free_variables == ("x",)
    assert validate_formula(checked.text, variables).free_variables == ("x",)
    assert prove_implication(variables, [], checked.text).status == "invalid"


def test_expression_family_is_closed_under_repeated_substitution() -> None:
    variables = {"x": "real", "enabled": "bool"}
    lemma = "(>= (ite (>= x 0) x (- x)) 0)"
    terms = ["x", "(+ x 1)", "(/ x 3)", "(ite enabled x (- x))"]
    for _ in range(3):
        next_terms = []
        for term in terms:
            composed = f"(ite (< {term} 0) (+ {term} 2) (/ {term} 2))"
            next_terms.append(composed)
            instance = substitute_formula(lemma, {"x": "real"}, {"x": composed}, result_variables=variables)
            assert prove_implication(variables, [], instance).status == "valid"
        terms = next_terms


def test_boolean_substitution_accepts_an_arbitrary_formula() -> None:
    formula = substitute_formula(
        "(or ready (not ready))", {"ready": "bool"}, {"ready": "(forall ((t Real)) (> x t))"},
        result_variables={"x": "real"},
    )
    assert prove_implication({"x": "real"}, [], formula).status == "valid"


@pytest.mark.parametrize(("formula", "variables"), [
    ("(= (* x x) 0)", {"x": "real"}),
    ("(let ((hidden (* x x))) (= hidden hidden))", {"x": "real"}),
    ("(or true (= (* x x) 0))", {"x": "real"}),
    ("(= (/ 1 x) 0)", {"x": "real"}),
    ("(= (/ x 0) 0)", {"x": "real"}),
    ("(= (/ x (- 2 2)) 0)", {"x": "real"}),
    ("(= (^ x 2) 0)", {"x": "real"}),
    ("(forall ((x Int)) (= x x))", {}),
    ("(= (div 4 2) 2)", {}),
    ("(= (mod 4 2) 0)", {}),
    ("(= (to_int x) 0)", {"x": "real"}),
    ("(is_int x)", {"x": "real"}),
    ("(forall ((a (Array Real Real))) (= (select a 0) 0))", {}),
    ("(= (f x) x)", {"x": "real"}),
    ("(= missing 0)", {}),
    ("(= x true)", {"x": "real"}),
    ("(= x 0)", {"x": "int"}),
    ("true) (assert false) (assert true", {}),
    ('(= "value" "value")', {}),
    ("true false", {}),
    ("(>= x 0", {"x": "real"}),
    ("", {}),
])
def test_outside_fragment_and_ill_typed_inputs_are_rejected(formula: str, variables: dict[str, str]) -> None:
    with pytest.raises(LinearLogicError):
        validate_formula(formula, variables)


def test_standard_quoted_symbols_and_comments_do_not_break_expression_framing() -> None:
    variables = {"a (time)": "real"}
    formula = "(= |a (time)| |a (time)|) ; a harmless unmatched ) in a comment"
    assert prove_implication(variables, [], formula).status == "valid"


@pytest.mark.parametrize("substitutions", [{"x": "true"}, {"x": "(* x x)"}, {"unknown": "0"}])
def test_substitution_cannot_escape_types_or_fragment(substitutions: dict[str, str]) -> None:
    with pytest.raises(LinearLogicError):
        substitute_formula("(> x 0)", {"x": "real"}, substitutions)


def test_substitution_cannot_leave_an_undeclared_free_symbol() -> None:
    with pytest.raises(LinearLogicError):
        substitute_formula("(> x y)", {"x": "real", "y": "real"}, {"x": "0"}, result_variables={})


def test_solver_failure_is_explicit_unknown_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_elimination(expression: object) -> None:
        raise z3.Z3Exception("test backend failure")

    monkeypatch.setattr(linear_logic, "_eliminate", fail_elimination)
    result = prove_implication({}, [], "true")
    assert result.status == "unknown"
    assert result.counterexample is None
    assert "test backend failure" in result.reason


def test_uneliminated_quantifiers_cannot_fall_through_to_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    class IncompleteElimination:
        def __init__(self, expression: object) -> None:
            self.expression = expression

        def as_expr(self) -> object:
            return self.expression

    def unchanged_tactic(name: str, *, ctx: object) -> object:
        return IncompleteElimination

    monkeypatch.setattr(linear_logic.z3, "Tactic", unchanged_tactic)
    result = prove_implication({}, [], "(forall ((x Real)) (exists ((y Real)) (> y x)))")
    assert result.status == "unknown"
    assert "unresolved quantifier" in result.reason


def test_string_is_not_silently_treated_as_a_sequence_of_assumptions() -> None:
    with pytest.raises(LinearLogicError):
        prove_implication({}, "true", "true")


def test_native_parser_configuration_does_not_mutate_other_z3_clients() -> None:
    client_context = z3.main_ctx()
    x = z3.Real("independent_client_x", ctx=client_context)
    before = z3.parse_smt2_string("(assert (= independent_client_x true))", decls={"independent_client_x": x})
    validate_formula("(>= x 0)", {"x": "real"})
    prove_implication({}, [], "true")
    substitute_formula("(>= x 0)", {"x": "real"}, {"x": "1"})
    after = z3.parse_smt2_string("(assert (= independent_client_x true))", decls={"independent_client_x": x})
    assert before[0].eq(after[0])
