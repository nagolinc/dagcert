"""Mechanical bridge from source-proved primitive relations to timing logic.

The real source verifier proves the original Python predicate. This module only
translates a deliberately small, exact primitive fragment to LRA and preserves
outcome guards and aliases. It is not a replacement Python type checker.

An outcome selection describes a completed invocation. Completion has its own
Boolean binding; postconditions never imply that an invocation finishes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import groupby
from typing import Any, Mapping

import z3  # type: ignore[import-untyped]

from .contract import Contract, Task
from .linear_logic import LinearLogicError, validate_formula
from .relations import RelationError, SourceRelation, parse_relation_predicate


class TheoremSourceError(ValueError):
    """A source fact cannot be bound without changing its verified semantics."""


@dataclass(frozen=True)
class _Binding:
    name: str
    sort: str
    task: str
    invocation: str
    outcome: str
    field: str

    @property
    def identity(self) -> tuple[str, str, str, str]:
        # Inputs belong to the invocation, not to a particular eventual result.
        outcome = "" if self.field.startswith("input.") or self.field == "$completed" else self.outcome
        return self.task, self.invocation, outcome, self.field


def _symbol(name: str, sort: str) -> str:
    return str((z3.Bool(name) if sort == "bool" else z3.Real(name)).sexpr())


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TheoremSourceError(f"{label} must be nonempty text")
    return value


def _task(contract: Contract, name: str, outcome: str) -> Task:
    task = contract.task_by_id.get(name)
    if (
        task is None or task.role != "operation" or task.implementation is None
        or task.implementation.language != "python" or task.source_signature is None
        or task.source_signature.language != "python"
    ):
        raise TheoremSourceError(f"{name}: theorem source fact requires a compiler-bound Python operation")
    actual = task.source_signature.outcome_types
    if set(actual) != set(task.outcome_by_type):
        raise TheoremSourceError(f"{name}: declared outcomes differ from the compiler-extracted union")
    if outcome not in actual:
        raise TheoremSourceError(f"{name}: unknown source outcome {outcome!r}")
    return task


def _bindings(variables: Mapping[str, Any], contract: Contract) -> tuple[_Binding, ...]:
    result: list[_Binding] = []
    for name, descriptor in variables.items():
        _text(name, "theorem variable name")
        if not isinstance(descriptor, Mapping):
            raise TheoremSourceError(f"{name}: theorem variable descriptor must be an object")
        if set(descriptor) != {"sort", "unit", "binding"}:
            raise TheoremSourceError(f"{name}: variable requires exactly sort, unit, binding")
        sort = descriptor["sort"]
        if sort not in ("real", "bool"):
            raise TheoremSourceError(f"{name}: theorem sort must be real or bool")
        _text(descriptor["unit"], f"{name} unit")
        row = descriptor["binding"]
        if row is None:
            continue
        if not isinstance(row, Mapping) or set(row) != {"task", "invocation", "outcome", "field"}:
            raise TheoremSourceError(f"{name}: source binding requires task, invocation, outcome, field")
        task_id = _text(row["task"], f"{name} task")
        invocation = _text(row["invocation"], f"{name} invocation")
        outcome = _text(row["outcome"], f"{name} outcome")
        field = _text(row["field"], f"{name} field")
        task = _task(contract, task_id, outcome)
        signature = task.source_signature
        assert signature is not None
        if field in ("$selected", "$completed"):
            expected = "bool"
        else:
            parts = field.split(".")
            if (len(parts) != 2 or parts[0] not in ("input", "result")
                or not parts[1].isidentifier() or parts[1].startswith("__")):
                raise TheoremSourceError(
                    f"{name}: source binding requires an exact top-level input.x/result.x projection; "
                    "nested projections are outside this source bridge, not outside LRA"
                )
            fields = dict(signature.input_fields) if parts[0] == "input" else dict(
                dict(signature.outcome_fields).get(outcome, ())
            )
            source_type = fields.get(parts[1])
            if source_type not in ("int", "bool"):
                raise TheoremSourceError(
                    f"{name}: {field} must be a compiler-extracted int or bool field, got {source_type!r}; "
                    "IEEE float is not exact real arithmetic"
                )
            expected = "real" if source_type == "int" else "bool"
        if sort != expected:
            raise TheoremSourceError(f"{name}: source field requires theorem sort {expected}, not {sort}")
        result.append(_Binding(name, sort, task_id, invocation, outcome, field))
    return tuple(result)


def _selected(bindings: tuple[_Binding, ...], task: str, invocation: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for binding in bindings:
        if binding.task == task and binding.invocation == invocation and binding.field == "$selected":
            result.setdefault(binding.outcome, _symbol(binding.name, "bool"))
    return result


def _completed(bindings: tuple[_Binding, ...], task: str, invocation: str) -> str:
    for binding in bindings:
        if binding.task == task and binding.invocation == invocation and binding.field == "$completed":
            return _symbol(binding.name, "bool")
    raise TheoremSourceError(f"{task}/{invocation}: source facts require an explicit Boolean $completed binding")


def source_binding_constraints(variables: Mapping[str, Any], contract: Contract) -> list[str]:
    """Enforce source aliases and closed outcome selection for completed invocations."""
    bindings = _bindings(variables, contract)
    constraints: list[str] = []
    for _, group in groupby(sorted(bindings, key=lambda item: item.identity), key=lambda item: item.identity):
        aliases = list(group)
        first = aliases[0]
        for alias in aliases[1:]:
            # Unit relabeling of one physical field cannot justify a conversion.
            if variables[first.name]["unit"] != variables[alias.name]["unit"]:
                raise TheoremSourceError(f"source aliases {first.name!r} and {alias.name!r} disagree on units")
            constraints.append(f"(= {_symbol(first.name, first.sort)} {_symbol(alias.name, alias.sort)})")
    invocations = sorted({(item.task, item.invocation) for item in bindings})
    for task_id, invocation in invocations:
        task = contract.task_by_id[task_id]
        signature = task.source_signature
        assert signature is not None
        selected = _selected(bindings, task_id, invocation)
        completed = _completed(bindings, task_id, invocation)
        if len(signature.outcome_types) == 1:
            if selected:
                constraints.append(f"(= {next(iter(selected.values()))} {completed})")
            continue
        if set(selected) != set(signature.outcome_types):
            missing = sorted(set(signature.outcome_types) - set(selected))
            raise TheoremSourceError(
                f"{task_id}/{invocation}: $selected bindings must cover every compiler outcome; missing {missing}"
            )
        # Linear cardinality encoding avoids quadratic pairwise exclusions.
        indicators = " ".join(f"(ite {selected[outcome]} 1.0 0.0)" for outcome in signature.outcome_types)
        constraints.append(f"(= (+ 0.0 {indicators}) (ite {completed} 1.0 0.0))")
    sorts = {name: descriptor["sort"] for name, descriptor in variables.items()}
    try:
        for constraint in constraints:
            validate_formula(constraint, sorts)
    except LinearLogicError as exc:
        raise TheoremSourceError(str(exc)) from exc
    return constraints


@dataclass(frozen=True)
class _Term:
    text: str
    sort: str
    constant: int | None = None


class _Predicate:
    def __init__(self, bindings: tuple[_Binding, ...], task: str, invocation: str, outcome: str) -> None:
        self.fields: dict[str, _Term] = {}
        for binding in bindings:
            if binding.task != task or binding.invocation != invocation:
                continue
            if binding.field.startswith("input.") or (
                binding.field.startswith("result.") and binding.outcome == outcome
            ):
                self.fields.setdefault(binding.field, _Term(_symbol(binding.name, binding.sort), binding.sort))

    @staticmethod
    def _require(terms: tuple[_Term, ...], sort: str, expression: ast.expr) -> None:
        if any(term.sort != sort for term in terms):
            raise TheoremSourceError(
                f"source predicate {ast.unparse(expression)!r} is outside the exact {sort} bridge; "
                "Python truthiness and implicit bool/numeric conversions are not silently changed"
            )

    def visit(self, node: ast.expr) -> _Term:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return _Term("true" if node.value else "false", "bool")
            if isinstance(node.value, int):
                text = f"{node.value}.0" if node.value >= 0 else f"(- {-node.value}.0)"
                return _Term(text, "real", node.value)
            raise TheoremSourceError("source predicate constants must be bool or exact int; floats/strings/None are outside this bridge")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id not in ("input", "result"):
                raise TheoremSourceError("source predicate requires top-level bound input.x/result.x projections")
            field = f"{node.value.id}.{node.attr}"
            term = self.fields.get(field)
            if term is None:
                raise TheoremSourceError(f"source predicate field {field!r} has no variable binding for this invocation/outcome")
            return term
        if isinstance(node, ast.BoolOp):
            terms = tuple(self.visit(value) for value in node.values)
            self._require(terms, "bool", node)
            operator = "and" if isinstance(node.op, ast.And) else "or"
            return _Term(f"({operator} {' '.join(term.text for term in terms)})", "bool")
        if isinstance(node, ast.UnaryOp):
            term = self.visit(node.operand)
            if isinstance(node.op, ast.Not):
                self._require((term,), "bool", node)
                return _Term(f"(not {term.text})", "bool")
            self._require((term,), "real", node)
            if isinstance(node.op, ast.UAdd):
                return term
            if isinstance(node.op, ast.USub):
                return _Term(f"(- {term.text})", "real", None if term.constant is None else -term.constant)
        if isinstance(node, ast.BinOp):
            left, right = self.visit(node.left), self.visit(node.right)
            self._require((left, right), "real", node)
            constant: int | None = None
            if isinstance(node.op, ast.Add):
                operator = "+"
                if left.constant is not None and right.constant is not None:
                    constant = left.constant + right.constant
            elif isinstance(node.op, ast.Sub):
                operator = "-"
                if left.constant is not None and right.constant is not None:
                    constant = left.constant - right.constant
            elif isinstance(node.op, ast.Mult):
                if left.constant is None and right.constant is None:
                    raise TheoremSourceError("source relation variable multiplication is outside linear arithmetic")
                operator = "*"
                if left.constant is not None and right.constant is not None:
                    constant = left.constant * right.constant
            else:
                raise TheoremSourceError(
                    "source arithmetic permits +, -, and integer-constant multiplication; "
                    "Python division, floor division and modulo are not exact LRA operators"
                )
            return _Term(f"({operator} {left.text} {right.text})", "real", constant)
        if isinstance(node, ast.Compare):
            operands = tuple(self.visit(value) for value in (node.left, *node.comparators))
            comparisons: list[str] = []
            for comparison_operator, left, right in zip(node.ops, operands, operands[1:]):
                if left.sort != right.sort:
                    raise TheoremSourceError("source comparison mixes bool and int; no implicit conversion is modeled")
                if isinstance(comparison_operator, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
                    if isinstance(comparison_operator, (ast.Is, ast.IsNot)) and left.sort != "bool":
                        raise TheoremSourceError("Python object identity is not numeric equality; is requires bool operands")
                    comparison = f"(= {left.text} {right.text})"
                    if isinstance(comparison_operator, (ast.NotEq, ast.IsNot)):
                        comparison = f"(not {comparison})"
                else:
                    self._require((left, right), "real", node)
                    operators = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
                    symbol = operators.get(type(comparison_operator))
                    if symbol is None:
                        raise TheoremSourceError(f"unsupported source predicate comparison {type(comparison_operator).__name__}")
                    comparison = f"({symbol} {left.text} {right.text})"
                comparisons.append(comparison)
            return _Term(comparisons[0] if len(comparisons) == 1 else f"(and {' '.join(comparisons)})", "bool")
        raise TheoremSourceError(f"source predicate syntax {type(node).__name__} is outside the exact primitive bridge")


def source_fact(
    premise: Mapping[str, Any], variables: Mapping[str, Any], contract: Contract,
) -> tuple[str, SourceRelation]:
    """Derive an outcome-guarded SMT fact from the same predicate sent to source proof."""
    if set(premise) != {"id", "kind", "task", "invocation", "outcome", "predicate"} or premise["kind"] != "source":
        raise TheoremSourceError("source premise requires id, kind=source, task, invocation, outcome, predicate")
    identifier = _text(premise["id"], "source premise id")
    task_id = _text(premise["task"], "source premise task")
    invocation = _text(premise["invocation"], "source premise invocation")
    outcome = _text(premise["outcome"], "source premise outcome")
    predicate = _text(premise["predicate"], "source premise predicate")
    task = _task(contract, task_id, outcome)
    bindings = _bindings(variables, contract)
    source_binding_constraints(variables, contract)
    try:
        expression = parse_relation_predicate(predicate)
        term = _Predicate(bindings, task_id, invocation, outcome).visit(expression)
        if term.sort != "bool":
            raise TheoremSourceError("source predicate must be Boolean, not Python numeric truthiness")
        signature = task.source_signature
        assert signature is not None
        completed = _completed(bindings, task_id, invocation)
        if len(signature.outcome_types) > 1:
            guard = _selected(bindings, task_id, invocation).get(outcome)
            if guard is None:
                raise TheoremSourceError(f"{task_id}/{invocation}: missing complete $selected source outcome bindings")
            formula = f"(=> (and {completed} {guard}) {term.text})"
        else:
            formula = f"(=> {completed} {term.text})"
        validate_formula(formula, {name: row["sort"] for name, row in variables.items()})
    except (RelationError, LinearLogicError) as exc:
        raise TheoremSourceError(str(exc)) from exc
    return formula, SourceRelation(identifier, task_id, outcome, predicate)
