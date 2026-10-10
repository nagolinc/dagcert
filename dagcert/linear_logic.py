"""A decision backend for first-order linear real arithmetic with Booleans.

The language is standard SMT-LIB: rational constants, declared Real/Bool
constants, Boolean connectives, comparisons, linear arithmetic, ``ite``, and
arbitrarily nested ``forall``/``exists`` over Real/Bool. Z3 parses and type-checks
the input, eliminates quantifiers, and decides the resulting QF_LRA query.
Dagcert only checks membership in this advertised mathematical fragment.

There are no application-specific expression categories or bounds on formula
size, nesting, quantifier alternation, or solver execution time. A solver error
or incomplete elimination is an explicit ``unknown``, never a certificate.
Real arithmetic here is exact mathematics, not Python/JavaScript floating-point
arithmetic. Linking formulas to production behavior is a separate obligation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

import z3  # type: ignore[import-untyped]


VariableSort = Literal["real", "bool"]
ProofStatus = Literal["valid", "invalid", "inconsistent", "unknown"]


class LinearLogicError(ValueError):
    """A formula is malformed, ill-typed, or outside linear real arithmetic."""


@dataclass(frozen=True)
class CheckedFormula:
    """A parsed formula descriptor, not evidence that its assertion is true."""

    text: str
    variables: tuple[tuple[str, str], ...]
    free_variables: tuple[str, ...]
    quantified: bool


@dataclass(frozen=True)
class LinearProofResult:
    status: ProofStatus
    counterexample: dict[str, str | bool] | None
    solver_metadata: dict[str, str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "counterexample": self.counterexample,
            "solver_metadata": dict(self.solver_metadata),
            "reason": self.reason,
        }


# Let Z3 infer numeral sorts in the standard LRA logic, while disabling its
# permissive Bool/Int/Real coercions. In particular ``(= real_value true)`` must
# be a real parser type error, not silently become ``real_value = 1``.
_PARSER_PREFIX = "(set-logic LRA)(set-option :int-real-coercions false)"


def _symbols(variables: Mapping[str, str], *, context: Any) -> dict[str, Any]:
    if not isinstance(variables, Mapping):
        raise LinearLogicError("variables must map names to real or bool sorts")
    result = {}
    for name, sort in variables.items():
        if not isinstance(name, str) or not name:
            raise LinearLogicError("variable names must be nonempty strings")
        if sort not in ("real", "bool"):
            raise LinearLogicError(f"variable {name!r} has unsupported sort {sort!r}; use real or bool")
        result[name] = z3.Real(name, ctx=context) if sort == "real" else z3.Bool(name, ctx=context)
    return result


def _term_boundary(text: str) -> None:
    """Keep one SMT term inside its assertion; Z3 handles syntax and types.

    This is just delimiter framing, not an SMT parser. In particular it cannot
    be bypassed by a closing parenthesis followed by solver configuration or
    declarations. Quoted SMT symbols and line comments retain their standard
    meaning. String values are outside this Real/Bool language.
    """
    if not isinstance(text, str) or not text.strip():
        raise LinearLogicError("formula must be a nonempty SMT-LIB expression")
    depth = 0
    quoted = False
    comment = False
    for char in text:
        if comment:
            if char in "\r\n":
                comment = False
            continue
        if quoted:
            if char == "|":
                quoted = False
            continue
        if char == ";":
            comment = True
        elif char == "|":
            quoted = True
        elif char == '"':
            raise LinearLogicError("string literals are outside linear real arithmetic")
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise LinearLogicError("expected one SMT-LIB term, not solver commands")
    if depth or quoted:
        raise LinearLogicError("unbalanced SMT-LIB expression")


def _constant_number(expression: Any) -> bool:
    simplified = z3.simplify(expression)
    return bool(z3.is_rational_value(simplified) or z3.is_int_value(simplified))


def _fragment(expression: Any, symbols: Mapping[str, Any]) -> tuple[tuple[str, ...], bool]:
    """Check the actual typed AST, including bodies expanded from SMT ``let``."""
    allowed_constants = {symbol.get_id(): name for name, symbol in symbols.items()}
    free: set[str] = set()
    quantified = False
    seen: set[int] = set()
    pending = [expression]
    simple_operations = {
        z3.Z3_OP_TRUE, z3.Z3_OP_FALSE, z3.Z3_OP_AND, z3.Z3_OP_OR,
        z3.Z3_OP_NOT, z3.Z3_OP_IMPLIES, z3.Z3_OP_IFF, z3.Z3_OP_XOR,
        z3.Z3_OP_EQ, z3.Z3_OP_DISTINCT, z3.Z3_OP_ITE,
        z3.Z3_OP_ADD, z3.Z3_OP_SUB, z3.Z3_OP_UMINUS,
        z3.Z3_OP_LE, z3.Z3_OP_LT, z3.Z3_OP_GE, z3.Z3_OP_GT,
        z3.Z3_OP_TO_REAL,
    }
    while pending:
        node = pending.pop()
        if node.get_id() in seen:
            continue
        seen.add(node.get_id())
        if z3.is_quantifier(node):
            if not (node.is_forall() or node.is_exists()):
                raise LinearLogicError("only forall/exists quantifiers are supported")
            for index in range(node.num_vars()):
                if node.var_sort(index).kind() not in (z3.Z3_REAL_SORT, z3.Z3_BOOL_SORT):
                    raise LinearLogicError("quantified variables must have sort Real or Bool")
            quantified = True
            pending.append(node.body())
            continue
        sort = node.sort().kind()
        if sort not in (z3.Z3_REAL_SORT, z3.Z3_BOOL_SORT, z3.Z3_INT_SORT):
            raise LinearLogicError(f"unsupported expression sort {node.sort()}")
        if z3.is_var(node):
            if sort == z3.Z3_INT_SORT:
                raise LinearLogicError("integer variables are outside linear real arithmetic")
            continue
        if z3.is_rational_value(node) or z3.is_int_value(node):
            continue
        if not z3.is_app(node):
            raise LinearLogicError(f"unsupported SMT expression {node.sexpr()}")
        operation = node.decl().kind()
        if operation == z3.Z3_OP_UNINTERPRETED:
            if node.num_args() or node.get_id() not in allowed_constants:
                raise LinearLogicError(f"undeclared constant or uninterpreted function {node.sexpr()}")
            free.add(allowed_constants[node.get_id()])
            continue
        if operation == z3.Z3_OP_MUL:
            if sum(not _constant_number(child) for child in node.children()) > 1:
                raise LinearLogicError("nonlinear variable products are outside linear real arithmetic")
        elif operation == z3.Z3_OP_DIV:
            denominator = node.arg(1)
            if not _constant_number(denominator):
                raise LinearLogicError("division requires a nonzero rational constant denominator")
            if z3.is_true(z3.simplify(denominator == 0)):
                raise LinearLogicError("division by zero is outside linear real arithmetic")
        elif operation not in simple_operations:
            raise LinearLogicError(f"unsupported linear-real operation {node.decl().name()!r}")
        pending.extend(node.children())
    return tuple(sorted(free)), quantified


def _parse(text: str, symbols: Mapping[str, Any], *, context: Any) -> Any:
    _term_boundary(text)
    try:
        assertions = z3.parse_smt2_string(
            f"{_PARSER_PREFIX}(assert {text}\n)", decls=dict(symbols), ctx=context,
        )
    except z3.Z3Exception as exc:
        raise LinearLogicError(f"Z3 rejected the SMT-LIB formula: {exc}") from exc
    if len(assertions) != 1:
        raise LinearLogicError("expected exactly one Boolean SMT-LIB expression")
    expression = assertions[0]
    if not z3.is_bool(expression):
        raise LinearLogicError("formula must have Boolean sort")
    _fragment(expression, symbols)
    return expression


def _safe_sexpr(expression: Any, symbols: Mapping[str, Any]) -> str:
    """Alpha-rename bound variables before printing a capture-free Z3 AST.

    Z3 substitutions use de Bruijn indices correctly, but its SMT printer can
    print a free constant and a bound variable with the same name identically.
    Rebinding with fresh, deterministic names through Z3's own substitution API
    makes serialization preserve the AST's actual meaning on the next parse.
    """
    unavailable = set(symbols)
    next_name = 0
    rewritten: dict[int, Any] = {}
    pending = [(expression, False)]
    while pending:
        node, visited = pending.pop()
        if node.get_id() in rewritten:
            continue
        children = [node.body()] if z3.is_quantifier(node) else list(node.children())
        if not visited:
            pending.append((node, True))
            pending.extend((child, False) for child in children)
            continue
        if z3.is_quantifier(node):
            bound = []
            for index in range(node.num_vars()):
                while f"__dagcert_bound_{next_name}" in unavailable:
                    next_name += 1
                name = f"__dagcert_bound_{next_name}"
                unavailable.add(name)
                next_name += 1
                bound.append(z3.Const(name, node.var_sort(index)))
            body = z3.substitute_vars(rewritten[node.body().get_id()], *reversed(bound))
            rewritten[node.get_id()] = z3.ForAll(bound, body) if node.is_forall() else z3.Exists(bound, body)
        else:
            pairs = [(child, rewritten[child.get_id()]) for child in children]
            rewritten[node.get_id()] = z3.substitute(node, *pairs) if pairs else node
    return str(rewritten[expression.get_id()].sexpr())


def validate_formula(text: str, variables: Mapping[str, str]) -> CheckedFormula:
    """Parse/type-check with Z3 and reject anything outside the exact fragment."""
    context = z3.Context()
    symbols = _symbols(variables, context=context)
    expression = _parse(text, symbols, context=context)
    free, quantified = _fragment(expression, symbols)
    return CheckedFormula(_safe_sexpr(expression, symbols), tuple(sorted(variables.items())), free, quantified)


def _contains_quantifier(expression: Any) -> bool:
    pending = [expression]
    seen: set[int] = set()
    while pending:
        node = pending.pop()
        if node.get_id() in seen:
            continue
        seen.add(node.get_id())
        if z3.is_quantifier(node):
            return True
        if z3.is_app(node):
            pending.extend(node.children())
    return False


def _eliminate(expression: Any) -> Any:
    result = z3.simplify(expression)
    if _contains_quantifier(result):
        result = z3.Tactic("qe", ctx=expression.ctx)(result).as_expr()
    if _contains_quantifier(result):
        result = z3.Tactic("qe2", ctx=expression.ctx)(result).as_expr()
    if _contains_quantifier(result):
        raise z3.Z3Exception("quantifier elimination left an unresolved quantifier")
    return z3.simplify(result)


def _counterexample(model: Any, symbols: Mapping[str, Any]) -> dict[str, str | bool]:
    values: dict[str, str | bool] = {}
    for name, symbol in sorted(symbols.items()):
        value = model.eval(symbol, model_completion=True)
        values[name] = z3.is_true(value) if z3.is_bool(value) else str(value)
    return values


def prove_implication(
    variables: Mapping[str, str], assumptions: Sequence[str], conclusion: str,
) -> LinearProofResult:
    """Decide satisfiable-premises entailment, rejecting vacuous consistency.

    ``invalid`` means a real counterexample exists; ``inconsistent`` means the
    premises themselves have no model. These are not interchangeable outcomes.
    An invalid closed quantified sentence has an empty free-variable witness;
    this function does not invent witnesses for its internally bound variables.
    """
    if not isinstance(assumptions, Sequence) or isinstance(assumptions, (str, bytes)):
        raise LinearLogicError("assumptions must be a sequence of formula strings")
    context = z3.Context()
    symbols = _symbols(variables, context=context)
    premises = [_parse(text, symbols, context=context) for text in assumptions]
    target = _parse(conclusion, symbols, context=context)
    metadata = {
        "backend": "z3",
        "version": str(z3.get_full_version()),
        "logic": "first-order linear real arithmetic with Booleans",
        "decision": "qe / qe2 followed by QF_LRA",
        "arithmetic": "exact rational constants and mathematical reals",
    }
    try:
        premise_formula = _eliminate(z3.And(*premises) if premises else z3.BoolVal(True, ctx=context))
        solver = z3.SolverFor("QF_LRA", ctx=context)
        solver.add(premise_formula)
        consistency = solver.check()
        if consistency == z3.unsat:
            return LinearProofResult("inconsistent", None, metadata, "the assumptions are jointly unsatisfiable")
        if consistency != z3.sat:
            return LinearProofResult("unknown", None, metadata, solver.reason_unknown())
        target_formula = _eliminate(target)
        solver.add(z3.Not(target_formula))
        result = solver.check()
        if result == z3.unsat:
            return LinearProofResult("valid", None, metadata, "the satisfiable assumptions entail the conclusion")
        if result == z3.sat:
            return LinearProofResult(
                "invalid", _counterexample(solver.model(), symbols), metadata,
                "the assumptions hold but the conclusion does not",
            )
        return LinearProofResult("unknown", None, metadata, solver.reason_unknown())
    except z3.Z3Exception as exc:
        return LinearProofResult("unknown", None, metadata, f"Z3 could not complete the decision: {exc}")


def _replacement(text: str, expected_sort: Any, symbols: Mapping[str, Any]) -> Any:
    _term_boundary(text)
    marker_name = "__dagcert_linear_term_sort__"
    while marker_name in symbols:
        marker_name += "_"
    marker = z3.Const(marker_name, expected_sort)
    try:
        assertions = z3.parse_smt2_string(
            f"{_PARSER_PREFIX}(assert (= {marker.sexpr()} {text}\n))",
            decls={**symbols, marker_name: marker},
            ctx=expected_sort.ctx,
        )
    except z3.Z3Exception as exc:
        raise LinearLogicError(f"Z3 rejected the substitution term: {exc}") from exc
    if len(assertions) != 1 or not z3.is_eq(assertions[0]) or not assertions[0].arg(0).eq(marker):
        raise LinearLogicError("expected one term of the substituted variable's sort")
    term = assertions[0].arg(1)
    if not term.sort().eq(expected_sort):
        raise LinearLogicError("substitution must preserve the declared variable sort")
    _fragment(term, symbols)
    return term


def substitute_formula(
    text: str,
    variables: Mapping[str, str],
    substitutions: Mapping[str, str],
    *,
    result_variables: Mapping[str, str] | None = None,
) -> str:
    """Simultaneously instantiate free constants using capture-free Z3 substitution.

    The replacements are arbitrary terms in the same fragment, not string
    replacements or sequential rewrites. Quantified names may shadow declared
    constants; bound occurrences remain untouched and cannot capture newly
    introduced free constants.
    """
    context = z3.Context()
    original_symbols = _symbols(variables, context=context)
    expression = _parse(text, original_symbols, context=context)
    result_symbols = _symbols(variables if result_variables is None else result_variables, context=context)
    replacements = []
    for name, term in substitutions.items():
        if name not in original_symbols:
            raise LinearLogicError(f"cannot substitute undeclared variable {name!r}")
        original = original_symbols[name]
        replacements.append((original, _replacement(term, original.sort(), result_symbols)))
    result = z3.substitute(expression, *replacements) if replacements else expression
    _fragment(result, result_symbols)
    return _safe_sexpr(result, result_symbols)
