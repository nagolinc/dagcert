"""Source-bound, solver-checked inductive invariants over numeric state.

Z3 discharges linear integer/real arithmetic, not application code. Separate
source-relation obligations prove every declared outcome's transition against
the real operation. Issuance must verify those obligations and establish the
declared initial-state/transition-scope premises: selected functions alone do
not prove that no other production code mutates the modeled state.

This is an invariant proof, not a liveness or fair-scheduling proof. An
unreachable outcome need not have a satisfiable transition; the initial state
must be satisfiable. Mathematical reals are never silently identified with
IEEE floats, whose rounding, infinities, and NaNs need different semantics.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from math import lcm
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import z3  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from .contract import Contract, StateClaim
    from .relations import SourceRelation


class InductionError(ValueError):
    """An induction request is malformed or cannot establish its obligation."""


@dataclass(frozen=True)
class _Linear:
    terms: Mapping[tuple[str, str], Fraction]
    constant: Fraction = Fraction(0)

    def scale(self, factor: Fraction) -> _Linear:
        return _Linear(
            {key: value * factor for key, value in self.terms.items() if value * factor},
            self.constant * factor,
        )

    def add(self, other: _Linear) -> _Linear:
        terms = dict(self.terms)
        for key, value in other.terms.items():
            terms[key] = terms.get(key, Fraction(0)) + value
        return _Linear({key: value for key, value in terms.items() if value}, self.constant + other.constant)


def _parse(expression: Any, label: str) -> ast.expr:
    if not isinstance(expression, str) or not expression.strip():
        raise InductionError(f"{label} must be a nonempty predicate")
    try:
        return ast.parse(expression, mode="eval").body
    except SyntaxError as exc:
        raise InductionError(f"invalid {label}: {exc.msg}") from exc


def _linear(node: ast.expr, variables: Mapping[str, str], namespaces: set[str]) -> _Linear:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        if isinstance(node.value, (int, float)):
            try:
                return _Linear({}, Fraction(str(node.value)))
            except (ValueError, OverflowError) as exc:
                raise InductionError("arithmetic constants must be finite") from exc
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id not in namespaces or node.attr not in variables:
            raise InductionError(f"unbound state variable {ast.unparse(node)!r}")
        return _Linear({(node.value.id, node.attr): Fraction(1)})
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _linear(node.operand, variables, namespaces).scale(
            Fraction(-1 if isinstance(node.op, ast.USub) else 1),
        )
    if isinstance(node, ast.BinOp):
        left = _linear(node.left, variables, namespaces)
        right = _linear(node.right, variables, namespaces)
        if isinstance(node.op, ast.Add):
            return left.add(right)
        if isinstance(node.op, ast.Sub):
            return left.add(right.scale(Fraction(-1)))
        if isinstance(node.op, ast.Mult):
            if not right.terms:
                return left.scale(right.constant)
            if not left.terms:
                return right.scale(left.constant)
            raise InductionError("invariant arithmetic must be linear: variable products are unsupported")
        if isinstance(node.op, ast.Div):
            if right.terms or right.constant == 0:
                raise InductionError("linear division requires a nonzero numeric constant denominator")
            return left.scale(1 / right.constant)
    raise InductionError(f"unsupported linear arithmetic: {ast.unparse(node)}")


def _number(value: Fraction) -> Any:
    return z3.IntVal(value.numerator) if value.denominator == 1 else z3.RealVal(str(value))


def _z3_linear(expression: _Linear, symbols: Mapping[tuple[str, str], Any]) -> Any:
    result = _number(expression.constant)
    for key, coefficient in expression.terms.items():
        result = result + _number(coefficient) * symbols[key]
    return result


def _predicate(
    node: ast.expr,
    variables: Mapping[str, str],
    namespaces: set[str],
    symbols: Mapping[tuple[str, str], Any],
) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return z3.BoolVal(node.value)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        operands = [_predicate(value, variables, namespaces, symbols) for value in node.values]
        return z3.And(*operands) if isinstance(node.op, ast.And) else z3.Or(*operands)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return z3.Not(_predicate(node.operand, variables, namespaces, symbols))
    if isinstance(node, ast.Compare):
        expressions = [node.left, *node.comparators]
        terms = [_z3_linear(_linear(item, variables, namespaces), symbols) for item in expressions]
        comparisons = []
        for left, operator, right in zip(terms, node.ops, terms[1:], strict=False):
            if isinstance(operator, ast.Eq):
                comparisons.append(left == right)
            elif isinstance(operator, ast.NotEq):
                comparisons.append(left != right)
            elif isinstance(operator, ast.Lt):
                comparisons.append(left < right)
            elif isinstance(operator, ast.LtE):
                comparisons.append(left <= right)
            elif isinstance(operator, ast.Gt):
                comparisons.append(left > right)
            elif isinstance(operator, ast.GtE):
                comparisons.append(left >= right)
            else:
                raise InductionError("invariant comparisons must use ==, !=, <, <=, >, or >=")
        return z3.And(*comparisons)
    raise InductionError(f"unsupported predicate: {ast.unparse(node)}")


def _symbols(variables: Mapping[str, str], namespaces: set[str]) -> dict[tuple[str, str], Any]:
    return {
        (namespace, name): (z3.Int if kind == "int" else z3.Real)(f"{namespace}.{name}")
        for namespace in sorted(namespaces) for name, kind in variables.items()
    }


def _exact_fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise InductionError(f"{label} must contain exactly {sorted(expected)}")
    return value


def _binding(value: Any, namespace: str) -> str:
    node = _parse(value, "state field binding")
    if (
        not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name)
        or node.value.id != namespace or node.attr.startswith("__")
    ):
        raise InductionError(f"state binding must identify {namespace}.<numeric_field>")
    return node.attr


def parse_induction_spec(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the finite schema and non-executable linear predicate grammar."""
    _exact_fields(row, {
        "id", "kind", "variables", "initial", "invariant", "transitions", "assumption", "metadata",
    }, "relational_invariant")
    if row["kind"] != "relational_invariant":
        raise InductionError("induction kind must be relational_invariant")
    if not isinstance(row["id"], str) or not row["id"].strip():
        raise InductionError("induction id must be nonempty text")
    if not isinstance(row["metadata"], Mapping):
        raise InductionError("induction metadata must be an object")
    if not isinstance(row["assumption"], str) or not row["assumption"].strip():
        raise InductionError(
            "invariant requires an explicit initial-state and complete mutation-scope assumption",
        )
    variables = row["variables"]
    if not isinstance(variables, Mapping) or not variables:
        raise InductionError("invariant variables must be a nonempty name/type object")
    for name, kind in variables.items():
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("__"):
            raise InductionError("state variable names must be non-dunder identifiers")
        if not isinstance(kind, str) or kind not in {"int", "real"}:
            raise InductionError("state variable types must be int or real, not arbitrary booleans")
    state_symbols = _symbols(variables, {"state"})
    for name in ("initial", "invariant"):
        _predicate(_parse(row[name], name), variables, {"state"}, state_symbols)
    transitions = row["transitions"]
    if not isinstance(transitions, list) or not transitions:
        raise InductionError("invariant requires nonempty source-bound transitions")
    transition_symbols = _symbols(variables, {"before", "after"})
    seen: set[tuple[str, str]] = set()
    for transition in transitions:
        _exact_fields(transition, {"task", "outcome", "before", "after", "relation"}, "transition")
        for field in ("task", "outcome"):
            if not isinstance(transition[field], str) or not transition[field].strip():
                raise InductionError(f"transition {field} must be nonempty text")
        key = (transition["task"], transition["outcome"])
        if key in seen:
            raise InductionError(f"duplicate transition for task/outcome {key}")
        seen.add(key)
        for phase, namespace in (("before", "input"), ("after", "result")):
            bindings = _exact_fields(transition[phase], set(variables), f"transition {phase}")
            for path in bindings.values():
                _binding(path, namespace)
        _predicate(_parse(transition["relation"], "transition relation"), variables,
                   {"before", "after"}, transition_symbols)
    return {key: value for key, value in row.items() if key not in {"id", "kind", "metadata"}}


def induction_references(spec: Mapping[str, Any]) -> set[str]:
    return {f"task:{transition['task']}" for transition in spec["transitions"]}


def validate_induction_spec(spec: Mapping[str, Any], contract: Contract) -> None:
    """Check outcome completeness and source-extracted numeric field bindings."""
    parse_induction_spec({"id": "validation", "kind": "relational_invariant", "metadata": {}, **spec})
    declared: dict[str, set[str]] = {}
    tasks = contract.task_by_id
    for transition in spec["transitions"]:
        task_id, outcome = transition["task"], transition["outcome"]
        if task_id not in tasks:
            raise InductionError(f"invariant transition references unknown task {task_id!r}")
        task = tasks[task_id]
        if task.role != "operation" or task.implementation is None:
            raise InductionError(f"invariant transition {task_id!r} must be a source-owned operation")
        if not task.outcomes or outcome not in task.outcome_by_type:
            raise InductionError(f"invariant transition has unknown typed outcome {task_id}/{outcome}")
        declared.setdefault(task_id, set()).add(outcome)
        signature = task.source_signature
        if signature is None:
            continue  # Pure model checks remain distinct from source certification.
        if set(signature.outcome_types) != set(task.outcome_by_type):
            raise InductionError(f"task {task_id!r} outcome union disagrees with real source types")
        source_fields = {
            "before": dict(signature.input_fields),
            "after": dict(dict(signature.outcome_fields).get(outcome, ())),
        }
        for phase, namespace in (("before", "input"), ("after", "result")):
            for variable, path in transition[phase].items():
                field = _binding(path, namespace)
                actual_type = source_fields[phase].get(field)
                # Python int is unbounded mathematical integer arithmetic. A
                # real abstraction can safely embed integer-valued state.
                if signature.language != "python" or actual_type != "int":
                    raise InductionError(
                        f"{task_id}/{outcome} {path} must have a source-proved mathematical "
                        f"numeric type (Python int); observed {actual_type!r}. IEEE float/number "
                        "must not be silently interpreted as mathematical real",
                    )
    for task_id, outcomes in declared.items():
        expected = set(tasks[task_id].outcome_by_type)
        if outcomes != expected:
            raise InductionError(
                f"invariant must cover the complete typed outcome union of {task_id!r}; "
                f"missing {sorted(expected - outcomes)}",
            )


def validate_joint_initialization(claims: Iterable[StateClaim], contract: Contract) -> None:
    """Reject mutually contradictory initial states on shared source bindings.

    A task ID denotes one declared production instance. The same input field
    of that task cannot initially have two different values just because two
    claims renamed it. One invariant variable also links its participating
    transition fields. Equal field names on different task instances do not
    alias unless an invariant explicitly connects them. Output fields do not
    alias initial values: a transition may legitimately merge different inputs.
    """
    selected = [claim for claim in claims if claim.kind == "relational_invariant"]
    parents: dict[tuple[str, str], tuple[str, str]] = {}
    bindings: dict[tuple[str, str], tuple[str, str]] = {}
    kinds: dict[tuple[str, str], str] = {}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        root = node
        while parents[root] != root:
            root = parents[root]
        while parents[node] != node:
            previous = parents[node]
            parents[node] = root
            node = previous
        return root

    identifiers: set[str] = set()
    for claim in selected:
        if claim.id in identifiers:
            raise InductionError("joint initialization requires distinct state claim IDs")
        identifiers.add(claim.id)
        validate_induction_spec(claim.specification, contract)
        for variable, kind in claim.specification["variables"].items():
            node = (claim.id, variable)
            parents[node] = node
            kinds[node] = kind
        for transition in claim.specification["transitions"]:
            for variable, path in transition["before"].items():
                node = (claim.id, variable)
                binding = (transition["task"], path)
                previous = bindings.get(binding)
                if previous is None:
                    bindings[binding] = node
                else:
                    parents[find(node)] = find(previous)
    root_kinds: dict[tuple[str, str], str] = {}
    for node, kind in kinds.items():
        root = find(node)
        if kind == "int" or root not in root_kinds:
            root_kinds[root] = kind
    root_symbols = {
        root: (z3.Int if kind == "int" else z3.Real)(f"initial::{root[0]}::{root[1]}")
        for root, kind in root_kinds.items()
    }
    if not selected:
        return
    solver = z3.Solver()
    labels: dict[str, str] = {}
    for index, claim in enumerate(selected):
        symbols = {
            ("state", variable): root_symbols[find((claim.id, variable))]
            for variable in claim.specification["variables"]
        }
        initial = _predicate(_parse(claim.specification["initial"], "initial"),
                             claim.specification["variables"], {"state"}, symbols)
        label = f"dagcert_initial_claim_{index}"
        labels[label] = claim.id
        solver.assert_and_track(initial, z3.Bool(label))
    status = solver.check()
    if status == z3.unknown:
        raise InductionError(f"joint initialization satisfiability unknown: {solver.reason_unknown()}")
    if status == z3.unsat:
        conflicting = sorted(labels[str(item)] for item in solver.unsat_core())
        raise InductionError(
            "joint initial-state predicates contradict shared source bindings: " + ", ".join(conflicting),
        )


def _rename_state(node: ast.expr, phase: str) -> ast.expr:
    class Rename(ast.NodeTransformer):
        def visit_Name(self, item: ast.Name) -> ast.Name:
            return ast.copy_location(ast.Name(id=phase if item.id == "state" else item.id, ctx=ast.Load()), item)

    result = Rename().visit(ast.parse(ast.unparse(node), mode="eval").body)
    assert isinstance(result, ast.expr)
    return result


def _counterexample(solver: Any, symbols: Mapping[tuple[str, str], Any]) -> str:
    model = solver.model()
    return ", ".join(
        f"{namespace}.{name}={model.eval(symbol, model_completion=True)}"
        for (namespace, name), symbol in sorted(symbols.items())
    )


def prove_inductive_invariant(spec: Mapping[str, Any], contract: Contract) -> tuple[bool, str]:
    """Prove satisfiable initialization and preservation; report real witnesses."""
    try:
        validate_induction_spec(spec, contract)
        variables = spec["variables"]
        state_symbols = _symbols(variables, {"state"})
        invariant_node = _parse(spec["invariant"], "invariant")
        initial = _predicate(_parse(spec["initial"], "initial"), variables, {"state"}, state_symbols)
        invariant = _predicate(invariant_node, variables, {"state"}, state_symbols)
        solver = z3.Solver()
        solver.add(initial)
        result = solver.check()
        if result == z3.unknown:
            return False, f"initial satisfiability unknown: {solver.reason_unknown()}"
        if result != z3.sat:
            return False, "initial state predicate is unsatisfiable; refusing a vacuous invariant"
        solver.add(z3.Not(invariant))
        result = solver.check()
        if result == z3.unknown:
            return False, f"initial invariant check unknown: {solver.reason_unknown()}"
        if result == z3.sat:
            return False, f"initial state violates invariant: {_counterexample(solver, state_symbols)}"
        symbols = _symbols(variables, {"before", "after"})
        before = _predicate(_rename_state(invariant_node, "before"), variables, {"before", "after"}, symbols)
        after = _predicate(_rename_state(invariant_node, "after"), variables, {"before", "after"}, symbols)
        for transition in spec["transitions"]:
            relation = _predicate(_parse(transition["relation"], "transition relation"),
                                  variables, {"before", "after"}, symbols)
            solver = z3.Solver()
            solver.add(before, relation, z3.Not(after))
            result = solver.check()
            label = f"{transition['task']}/{transition['outcome']}"
            if result == z3.unknown:
                return False, f"transition {label} preservation unknown: {solver.reason_unknown()}"
            if result == z3.sat:
                return False, f"transition {label} violates invariant: {_counterexample(solver, symbols)}"
        return True, (
            "inductive invariant proved for every declared outcome, conditional on verified "
            "source transition relations, the initial-state predicate, and complete mutation scope"
        )
    except (InductionError, z3.Z3Exception) as exc:
        return False, str(exc)


def _integer_atom(expression: _Linear, bindings: Mapping[tuple[str, str], str]) -> ast.expr:
    """Clear rational denominators, avoiding Python float arithmetic in proof views."""
    denominator = lcm(expression.constant.denominator, *(value.denominator for value in expression.terms.values()))
    terms: list[ast.expr] = []
    for key, coefficient in sorted(expression.terms.items()):
        value = ast.parse(bindings[key], mode="eval").body
        multiplier = int(coefficient * denominator)
        terms.append(value if multiplier == 1 else ast.BinOp(ast.Constant(multiplier), ast.Mult(), value))
    constant = int(expression.constant * denominator)
    if constant or not terms:
        terms.append(ast.Constant(constant))
    result = terms[0]
    for term in terms[1:]:
        result = ast.BinOp(result, ast.Add(), term)
    return result


def _source_predicate(
    node: ast.expr, variables: Mapping[str, str], bindings: Mapping[tuple[str, str], str],
) -> ast.expr:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node
    if isinstance(node, ast.BoolOp):
        return ast.BoolOp(node.op, [_source_predicate(value, variables, bindings) for value in node.values])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return ast.UnaryOp(ast.Not(), _source_predicate(node.operand, variables, bindings))
    if isinstance(node, ast.Compare):
        values = [node.left, *node.comparators]
        comparisons: list[ast.expr] = []
        for left, operator, right in zip(values, node.ops, values[1:], strict=False):
            difference = _linear(left, variables, {"before", "after"}).add(
                _linear(right, variables, {"before", "after"}).scale(Fraction(-1)),
            )
            comparisons.append(ast.Compare(_integer_atom(difference, bindings), [operator], [ast.Constant(0)]))
        return comparisons[0] if len(comparisons) == 1 else ast.BoolOp(ast.And(), comparisons)
    raise InductionError("source obligation predicate was not validated")


def relation_source_obligations(spec: Mapping[str, Any], contract: Contract) -> list[SourceRelation]:
    """Return separately verified, outcome-conditioned real-code obligations."""
    from .relations import SourceRelation

    validate_induction_spec(spec, contract)
    result = []
    for index, transition in enumerate(spec["transitions"]):
        bindings = {
            (phase, variable): path
            for phase in ("before", "after") for variable, path in transition[phase].items()
        }
        predicate = _source_predicate(_parse(transition["relation"], "transition relation"),
                                      spec["variables"], bindings)
        source_predicate = ast.unparse(ast.fix_missing_locations(predicate))
        digest = sha256(source_predicate.encode("utf-8")).hexdigest()
        result.append(SourceRelation(
            f"induction:{transition['task']}:{transition['outcome']}:{index}:{digest}",
            transition["task"], transition["outcome"], source_predicate,
        ))
    return result
