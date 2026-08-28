"""Small, closed claim algebra evaluated by the Dagcert kernel."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .analysis import AnalysisReport
from .contract import Contract


class FormulaError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FormulaEvaluation:
    passed: bool
    value: bool
    composition_refs: tuple[str, ...]
    primitive_refs: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "value": self.value,
            "composition_refs": list(self.composition_refs),
            "primitive_refs": list(self.primitive_refs),
        }


@dataclass(slots=True)
class _EvaluationState:
    contract: Contract
    analysis: AnalysisReport


def evaluate_formula(
    formula: Mapping[str, Any], contract: Contract, analysis: AnalysisReport,
) -> FormulaEvaluation:
    """Evaluate one closed derived formula from kernel-certified DAG leaf bounds.

    The initial algebra intentionally proves only finite, compositional bounds. Temporal
    state operators will be added only with a model checker capable of validating them.
    """
    state = _EvaluationState(contract, analysis)
    value = _boolean(formula, state, "formula")
    references = set(formula_references(formula))
    probability_compositions = {
        reference for reference in references
        if reference.startswith("composition:")
        and _formula_uses_probability_composition(formula, reference)
    }
    for composition_ref in probability_compositions:
        composition = contract.composition_by_id.get(composition_ref.split(":", 1)[1])
        if composition is not None:
            references.update(f"error-budget:{step.task}" for step in composition.steps)
    external_probability_refs = {
        reference for reference in references
        if reference.startswith("external-contract:")
        and _formula_uses_external_probability(formula, reference)
    }
    references.update(
        f"error-budget:{reference.split(':', 1)[1]}"
        for reference in external_probability_refs
    )
    composition_refs = {
        reference for reference in references if reference.startswith("composition:")
    }
    if not composition_refs and not external_probability_refs:
        _validate_dag_surface(references, contract)
    return FormulaEvaluation(
        value, value, tuple(sorted(composition_refs)), tuple(sorted(references))
    )


def formula_references(formula: Mapping[str, Any]) -> tuple[str, ...]:
    """Return primitive/composition references without evaluating the expression."""
    references: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for operator, operand in value.items():
                if operator in {
                    "composition_upper_ms", "timing_upper_ms", "timing_lower_ms",
                    "worker_concurrency", "resource_capacity", "resource_initial",
                    "composition_failure_probability_upper",
                    "composition_success_probability_lower",
                    "external_failure_probability_upper",
                    "external_success_probability_lower",
                } and isinstance(operand, str):
                    references.add(operand)
                elif operator in {"task_guaranteed_produce", "task_guaranteed_consume"}:
                    task_ref, resource_ref = _effect_pair(operand, f"formula.{operator}")
                    references.update({task_ref, resource_ref})
                    kind = "produce" if operator.endswith("produce") else "consume"
                    references.add(
                        f"guarantee:{task_ref.split(':', 1)[1]}/{kind}/{resource_ref.split(':', 1)[1]}"
                    )
                else:
                    visit(operand)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(formula)
    return tuple(sorted(references))


def formula_uses_error_budgets(formula: Mapping[str, Any]) -> bool:
    """Whether a formula invokes the kernel's finite-scenario union-bound operators."""
    if any(
        operator in {
            "composition_failure_probability_upper",
            "composition_success_probability_lower",
            "external_failure_probability_upper",
            "external_success_probability_lower",
        }
        for operator in formula
    ):
        return True
    return any(
        formula_uses_error_budgets(item)
        for value in formula.values()
        for item in (
            list(value) if isinstance(value, list)
            else [value] if isinstance(value, Mapping)
            else []
        )
        if isinstance(item, Mapping)
    )


def validate_claim_formula(formula: Mapping[str, Any], *, basis: str) -> None:
    """Reject vacuous claim shapes while keeping the kernel algebra deliberately small.

    Formula evaluation remains a reusable expression engine. Certificate claims use a stricter
    proof surface: deterministic claims are conjunctions of non-vacuous bound comparisons, and a
    chance claim is one direct comparison against one finite composition's union-bound result.
    This prevents a cited proof from being hidden in an always-true ``or`` branch.
    """

    if basis == "chance":
        _validate_chance_claim_formula(formula)
        return
    if basis == "derived":
        _validate_derived_claim_formula(formula, "formula")
        return
    raise FormulaError(f"unsupported formula-bearing claim basis {basis!r}")


def _validate_chance_claim_formula(formula: Mapping[str, Any]) -> None:
    row = _single_operator(formula, "formula")
    operator, operand = next(iter(row.items()))
    expected_probability_operators = {
        "gte": {
            "composition_success_probability_lower",
            "external_success_probability_lower",
        },
        "lte": {
            "composition_failure_probability_upper",
            "external_failure_probability_upper",
        },
    }.get(operator)
    if expected_probability_operators is None:
        raise FormulaError(
            "chance formula must directly compare a composition or external-contract "
            "probability bound with gte or lte"
        )
    left, right = _pair(operand, f"formula.{operator}")
    probability = _single_operator(left, f"formula.{operator}[0]")
    if len(probability) != 1 or next(iter(probability)) not in expected_probability_operators:
        raise FormulaError(
            f"chance formula {operator} left operand must be exactly one of "
            f"{sorted(expected_probability_operators)}"
        )
    expected_probability_operator = next(iter(probability))
    _reference(
        probability[expected_probability_operator],
        "external-contract" if expected_probability_operator.startswith("external_")
        else "composition",
        f"formula.{operator}[0].{expected_probability_operator}",
    )
    if isinstance(right, bool) or not isinstance(right, (int, float)):
        raise FormulaError("chance formula threshold must be a literal probability")
    threshold = float(right)
    if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise FormulaError("chance formula threshold must be finite and between 0 and 1")


def _validate_derived_claim_formula(formula: Mapping[str, Any], label: str) -> None:
    row = _single_operator(formula, label)
    operator, operand = next(iter(row.items()))
    if operator == "and":
        for index, item in enumerate(_items(operand, f"{label}.and", minimum=2)):
            if not isinstance(item, Mapping):
                raise FormulaError(f"{label}.and[{index}] must be a formula object")
            _validate_derived_claim_formula(item, f"{label}.and[{index}]")
        return
    if operator not in {"lt", "lte", "gt", "gte", "eq"}:
        raise FormulaError(
            "derived claim formulas may contain only bound comparisons or their conjunction; "
            f"{operator!r} can make a proof vacuous"
        )
    left, right = _pair(operand, f"{label}.{operator}")
    if left == right:
        raise FormulaError(f"{label}.{operator} compares an expression with itself")
    references = formula_references(row)
    if not references:
        raise FormulaError(f"{label}.{operator} must depend on a kernel DAG primitive")


def _formula_uses_probability_composition(
    formula: Mapping[str, Any], composition_ref: str,
) -> bool:
    for operator, operand in formula.items():
        if (
            operator in {
                "composition_failure_probability_upper",
                "composition_success_probability_lower",
            }
            and operand == composition_ref
        ):
            return True
        children = (
            value for value in (operand if isinstance(operand, list) else [operand])
            if isinstance(value, Mapping)
        )
        if any(
            _formula_uses_probability_composition(child, composition_ref)
            for child in children
        ):
            return True
    return False


def _formula_uses_external_probability(
    formula: Mapping[str, Any], external_ref: str,
) -> bool:
    for operator, operand in formula.items():
        if operator in {
            "external_failure_probability_upper",
            "external_success_probability_lower",
        } and operand == external_ref:
            return True
        children = (
            value for value in (operand if isinstance(operand, list) else [operand])
            if isinstance(value, Mapping)
        )
        if any(_formula_uses_external_probability(child, external_ref) for child in children):
            return True
    return False


def _validate_dag_surface(references: set[str], contract: Contract) -> None:
    timing_tasks = {
        reference.split(":", 1)[1].split("/", 1)[0]
        for reference in references if reference.startswith("timing:")
    }
    supporting_state = {
        reference for reference in references
        if reference.startswith("worker:") or reference.startswith("resource:")
    }
    if contract.schema in {"dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6"}:
        resource_ids = {
            reference.split(":", 1)[1]
            for reference in references if reference.startswith("resource:")
        }
        guarantees = {
            reference.split(":", 1)[1]
            for reference in references if reference.startswith("guarantee:")
        }
        required_guarantees: set[str] = set()
        for task_id in timing_tasks:
            task = contract.task_by_id.get(task_id)
            if task is None:
                continue
            for resource_id in resource_ids & set(task.resources):
                effect = task.resources[resource_id]
                if effect.produce > 0:
                    required_guarantees.add(f"{task_id}/produce/{resource_id}")
                if effect.consume > 0:
                    required_guarantees.add(f"{task_id}/consume/{resource_id}")
        missing_guarantees = required_guarantees - guarantees
        if resource_ids and (not guarantees or missing_guarantees):
            raise FormulaError(
                "v4 resource derivations must use task_guaranteed_produce/consume for every "
                f"referenced task effect; missing {sorted(missing_guarantees)}"
            )
    if len(timing_tasks) < 2 or not supporting_state:
        raise FormulaError(
            "derived formula must use a declared composition or bounds from at least two "
            "connected tasks plus worker/resource state"
        )
    tasks = contract.task_by_id
    unknown = timing_tasks - set(tasks)
    if unknown:
        raise FormulaError(f"derived formula cites unknown timing tasks {sorted(unknown)}")
    connected = {next(iter(timing_tasks))}
    changed = True
    while changed:
        changed = False
        for task_id in timing_tasks - connected:
            task = tasks[task_id]
            related = set(task.depends_on)
            related.update(
                candidate.id for candidate in contract.tasks if task_id in candidate.depends_on
            )
            task_resources = set(task.resources)
            related.update(
                candidate.id for candidate in contract.tasks
                if task_resources & set(candidate.resources)
            )
            if related & connected:
                connected.add(task_id)
                changed = True
    if connected != timing_tasks:
        raise FormulaError(
            "derived formula timing tasks do not form one dependency/resource DAG surface"
        )


def _boolean(value: Any, state: _EvaluationState, label: str) -> bool:
    row = _single_operator(value, label)
    operator, operand = next(iter(row.items()))
    if operator in {"lt", "lte", "gt", "gte", "eq"}:
        left, right = _pair(operand, f"{label}.{operator}")
        left_value = _number(left, state, f"{label}.{operator}[0]")
        right_value = _number(right, state, f"{label}.{operator}[1]")
        return {
            "lt": left_value < right_value,
            "lte": left_value <= right_value,
            "gt": left_value > right_value,
            "gte": left_value >= right_value,
            "eq": left_value == right_value,
        }[operator]
    if operator in {"and", "or"}:
        items = _items(operand, f"{label}.{operator}", minimum=2)
        values = [_boolean(item, state, f"{label}.{operator}") for item in items]
        return all(values) if operator == "and" else any(values)
    if operator == "not":
        return not _boolean(operand, state, f"{label}.not")
    if operator == "implies":
        antecedent, consequent = _pair(operand, f"{label}.implies")
        antecedent_value = _boolean(antecedent, state, f"{label}.implies[0]")
        consequent_value = _boolean(consequent, state, f"{label}.implies[1]")
        return not antecedent_value or consequent_value
    raise FormulaError(f"{label} uses unsupported boolean operator {operator!r}")


def _number(value: Any, state: _EvaluationState, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Mapping)):
        raise FormulaError(f"{label} must be a finite number expression")
    if isinstance(value, (int, float)):
        result = float(value)
        if not isfinite(result):
            raise FormulaError(f"{label} must be finite")
        return result
    row = _single_operator(value, label)
    operator, operand = next(iter(row.items()))
    if operator in {"add", "max"}:
        items = _items(operand, f"{label}.{operator}", minimum=1)
        values = [_number(item, state, f"{label}.{operator}") for item in items]
        return sum(values) if operator == "add" else max(values)
    if operator in {"multiply", "divide"}:
        left, right = _pair(operand, f"{label}.{operator}")
        left_value = _number(left, state, f"{label}.{operator}[0]")
        right_value = _number(right, state, f"{label}.{operator}[1]")
        if operator == "divide" and right_value == 0:
            raise FormulaError(f"{label}.divide divisor must be nonzero")
        return left_value * right_value if operator == "multiply" else left_value / right_value
    if operator == "composition_upper_ms":
        reference = _reference(operand, "composition", f"{label}.{operator}")
        composition = state.contract.composition_by_id.get(reference)
        if composition is None:
            raise FormulaError(f"{label} cites unknown composition {reference!r}")
        total = 0.0
        timing_by_ref = {
            f"timing:{item.task_id}/{item.case}": item for item in state.analysis.timings
        }
        for step in composition.steps:
            timing_ref = f"timing:{step.task}/{step.timing}"
            timing_result = timing_by_ref.get(timing_ref)
            if timing_result is None or not timing_result.passed or timing_result.certified_upper_ms is None:
                raise FormulaError(
                    f"composition {reference} lacks a passing certified upper bound for {timing_ref}"
                )
            total += timing_result.certified_upper_ms * step.count
        return total
    if operator in {
        "composition_failure_probability_upper",
        "composition_success_probability_lower",
    }:
        reference = _reference(operand, "composition", f"{label}.{operator}")
        failure_upper = _composition_failure_probability_upper(reference, state)
        return (
            failure_upper
            if operator == "composition_failure_probability_upper"
            else max(0.0, 1.0 - failure_upper)
        )
    if operator in {
        "external_failure_probability_upper",
        "external_success_probability_lower",
    }:
        reference = _reference(operand, "external-contract", f"{label}.{operator}")
        failure_upper = _external_failure_probability_upper(reference, state)
        return failure_upper if operator.startswith("external_failure") else 1.0 - failure_upper
    if operator in {"timing_upper_ms", "timing_lower_ms"}:
        reference = _reference(operand, "timing", f"{label}.{operator}")
        timing = next(
            (item for item in state.analysis.timings if f"{item.task_id}/{item.case}" == reference),
            None,
        )
        if timing is None or not timing.passed:
            raise FormulaError(f"{label} cites timing without a passing kernel result {reference!r}")
        bound = timing.certified_upper_ms if operator == "timing_upper_ms" else timing.certified_lower_ms
        if bound is None:
            raise FormulaError(f"{label} cites an unavailable {operator} for {reference!r}")
        return bound
    if operator == "worker_concurrency":
        reference = _reference(operand, "worker", f"{label}.{operator}")
        worker = state.contract.worker_by_id.get(reference)
        if worker is None:
            raise FormulaError(f"{label} cites unknown worker {reference!r}")
        return float(worker.concurrency)
    if operator in {"resource_capacity", "resource_initial"}:
        reference = _reference(operand, "resource", f"{label}.{operator}")
        resource = state.contract.resource_by_id.get(reference)
        if resource is None:
            raise FormulaError(f"{label} cites unknown resource {reference!r}")
        return resource.capacity if operator == "resource_capacity" else resource.initial
    if operator in {"task_guaranteed_produce", "task_guaranteed_consume"}:
        task_ref, resource_ref = _effect_pair(operand, f"{label}.{operator}")
        task_id = task_ref.split(":", 1)[1]
        resource_id = resource_ref.split(":", 1)[1]
        task = state.contract.task_by_id.get(task_id)
        if task is None:
            raise FormulaError(f"{label} cites unknown task {task_id!r}")
        if resource_id not in state.contract.resource_by_id:
            raise FormulaError(f"{label} cites unknown resource {resource_id!r}")
        kind = "produce" if operator.endswith("produce") else "consume"
        return task.guaranteed_effect(resource_id, kind)
    raise FormulaError(f"{label} uses unsupported numeric operator {operator!r}")


def _composition_failure_probability_upper(
    composition_id: str, state: _EvaluationState,
) -> float:
    if state.contract.schema not in {"dagcert-contract/v5", "dagcert-contract/v6"}:
        raise FormulaError("error-budget formulas require dagcert-contract/v5 or v6")
    composition = state.contract.composition_by_id.get(composition_id)
    if composition is None:
        raise FormulaError(f"formula cites unknown composition {composition_id!r}")
    total = 0.0
    for step in composition.steps:
        task = state.contract.task_by_id[step.task]
        budget = task.error_budget
        if budget is None:
            raise FormulaError(
                f"composition {composition_id} task {task.id} has no error budget"
            )
        if step.timing != budget.evidence_case:
            raise FormulaError(
                f"composition {composition_id} step {task.id}/{step.timing} does not use "
                f"its error-budget evidence case {budget.evidence_case}"
            )
        if step.outcome_type not in budget.good_outcomes:
            raise FormulaError(
                f"composition {composition_id} selects {task.id}/{step.outcome_type}, "
                "which its error budget does not classify as good"
            )
        if set(budget.good_outcomes) != {step.outcome_type}:
            raise FormulaError(
                f"composition {composition_id} requires exactly {task.id}/{step.outcome_type}, "
                f"but its error budget treats {list(budget.good_outcomes)} as good; the budget "
                "therefore does not bound failure of this typed path"
            )
        result = next(
            (item for item in state.analysis.error_budgets if item.task_id == task.id),
            None,
        )
        if result is None or not result.passed:
            raise FormulaError(
                f"composition {composition_id} lacks a passing error-budget analysis for {task.id}"
            )
        total += step.count * budget.bad_event_probability_upper
    return min(1.0, total)


def _external_failure_probability_upper(
    task_id: str, state: _EvaluationState,
) -> float:
    if state.contract.schema != "dagcert-contract/v6":
        raise FormulaError("external-contract formulas require dagcert-contract/v6")
    task = state.contract.task_by_id.get(task_id)
    if task is None or task.external_contract is None:
        raise FormulaError(f"formula cites unknown external contract {task_id!r}")
    budget = task.error_budget
    if budget is None:
        raise FormulaError(f"external task {task_id} has no error budget")
    result = next(
        (item for item in state.analysis.error_budgets if item.task_id == task_id), None,
    )
    if result is None or not result.passed:
        raise FormulaError(
            f"external contract {task_id} lacks a passing error-budget analysis"
        )
    return budget.bad_event_probability_upper


def _single_operator(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or len(value) != 1:
        raise FormulaError(f"{label} must be an object containing exactly one operator")
    operator = next(iter(value))
    if not isinstance(operator, str) or not operator:
        raise FormulaError(f"{label} operator must be a nonempty string")
    return value


def _items(value: Any, label: str, *, minimum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise FormulaError(f"{label} must be an array with at least {minimum} items")
    return value


def _pair(value: Any, label: str) -> tuple[Any, Any]:
    items = _items(value, label, minimum=2)
    if len(items) != 2:
        raise FormulaError(f"{label} must contain exactly two items")
    return items[0], items[1]


def _reference(value: Any, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix + ":") or not value[len(prefix) + 1:]:
        raise FormulaError(f"{label} must be a {prefix}: reference")
    return value[len(prefix) + 1:]


def _effect_pair(value: Any, label: str) -> tuple[str, str]:
    task_value, resource_value = _pair(value, label)
    if not isinstance(task_value, str) or not task_value.startswith("task:"):
        raise FormulaError(f"{label}[0] must be a task: reference")
    if not isinstance(resource_value, str) or not resource_value.startswith("resource:"):
        raise FormulaError(f"{label}[1] must be a resource: reference")
    return task_value, resource_value
