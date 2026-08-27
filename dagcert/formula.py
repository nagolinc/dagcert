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
    composition_refs = {
        reference for reference in references if reference.startswith("composition:")
    }
    if not composition_refs:
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
                } and isinstance(operand, str):
                    references.add(operand)
                else:
                    visit(operand)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(formula)
    return tuple(sorted(references))


def _validate_dag_surface(references: set[str], contract: Contract) -> None:
    timing_tasks = {
        reference.split(":", 1)[1].split("/", 1)[0]
        for reference in references if reference.startswith("timing:")
    }
    supporting_state = {
        reference for reference in references
        if reference.startswith("worker:") or reference.startswith("resource:")
    }
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
    raise FormulaError(f"{label} uses unsupported numeric operator {operator!r}")


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
