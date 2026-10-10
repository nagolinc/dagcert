"""Composable LRA obligations with source facts and retained envelope premises.

The solver checks mathematics; this module tracks where its hypotheses came
from. A proved lemma is an implication, never permission to discard its
assumptions. Mathematical lemmas and source-bound application claims are
deliberately distinct.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
import json
from typing import Any, Mapping, TYPE_CHECKING

from .linear_logic import LinearLogicError, prove_implication, substitute_formula, validate_formula
from .relations import SourceRelation

if TYPE_CHECKING:
    from .contract import Contract


class TheoremError(ValueError):
    pass


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise TheoremError(f"{label} must contain exactly {sorted(expected)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TheoremError(f"{label} must be nonempty text")
    return value


def _number(value: Any, label: str) -> Fraction:
    if isinstance(value, bool):
        raise TheoremError(f"{label} must be rational")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise TheoremError(f"{label} must be rational") from exc


def variable_sorts(spec: Mapping[str, Any]) -> dict[str, str]:
    return {name: row["sort"] for name, row in spec["variables"].items()}


def parse_theorem_spec(row: Mapping[str, Any]) -> Mapping[str, Any]:
    _fields(row, {"id", "kind", "mode", "variables", "premises", "lemmas", "uses",
                  "conclusion", "horizon_ms", "metadata"}, "LRA theorem")
    if row["kind"] != "lra_theorem" or row["mode"] not in {"mathematical", "source"}:
        raise TheoremError("LRA theorem needs kind lra_theorem and mode mathematical or source")
    _text(row["id"], "theorem id")
    if not isinstance(row["metadata"], Mapping):
        raise TheoremError("theorem metadata must be an object")
    variables = row["variables"]
    if not isinstance(variables, Mapping):
        raise TheoremError("theorem variables must be an object")
    for name, descriptor in variables.items():
        _text(name, "variable name")
        _fields(descriptor, {"sort", "unit", "binding"}, "theorem variable")
        if descriptor["sort"] not in {"real", "bool"}:
            raise TheoremError("the LRA family has real and Boolean variables")
        _text(descriptor["unit"], "variable unit")
        if descriptor["sort"] == "bool" and descriptor["unit"] != "boolean":
            raise TheoremError("Boolean variables use the boolean unit")
        if descriptor["binding"] is not None:
            binding = _fields(descriptor["binding"], {"task", "invocation", "outcome", "field"}, "source binding")
            for value in binding.values():
                _text(value, "source binding component")
    if row["mode"] == "mathematical" and any(v["binding"] is not None for v in variables.values()):
        raise TheoremError("mathematical lemmas cannot silently acquire application source bindings")
    horizon = row["horizon_ms"]
    if horizon is not None and _number(horizon, "theorem horizon") < 0:
        raise TheoremError("theorem horizon must be nonnegative or null for all time")
    for key in ("premises", "lemmas", "uses"):
        if not isinstance(row[key], list):
            raise TheoremError(f"theorem {key} must be an array")
    seen: set[str] = set()
    sorts = variable_sorts(row)
    for premise in row["premises"]:
        if not isinstance(premise, Mapping):
            raise TheoremError("theorem premise must be an object")
        kind = premise.get("kind")
        if not isinstance(kind, str):
            raise TheoremError("theorem premise kind must be a string")
        expected = {
            "envelope": {"formula", "assumption", "event", "horizon_ms", "failure_probability_upper", "primitive_refs"},
            "source": {"task", "invocation", "outcome", "predicate"},
            "theorem": {"claim", "substitutions"},
            "fact": {"formula"},
        }.get(kind)
        if expected is None:
            raise TheoremError(f"unknown LRA premise kind {kind!r}")
        _fields(premise, {"id", "kind"} | expected, "theorem premise")
        identifier = _text(premise["id"], "premise id")
        if identifier in seen:
            raise TheoremError(f"duplicate theorem fact {identifier}")
        seen.add(identifier)
        if kind in {"envelope", "fact"}:
            validate_formula(_text(premise["formula"], "premise formula"), sorts)
        if kind == "fact" and row["mode"] != "mathematical":
            raise TheoremError("source claims require source facts or disclosed engineering envelopes, not arbitrary facts")
        if row["mode"] == "mathematical" and kind in {"source", "envelope"}:
            raise TheoremError("mathematical lemmas use logical facts; application source/envelopes belong to source theorems")
        if kind == "envelope":
            _text(premise["assumption"], "envelope assumption")
            _text(premise["event"], "envelope event")
            probability = _number(premise["failure_probability_upper"], "envelope probability")
            if not 0 <= probability <= 1:
                raise TheoremError("envelope probability must be in [0,1]")
            declared = premise["horizon_ms"]
            if declared is not None and (_number(declared, "envelope horizon") < 0 or horizon is None
                                         or _number(declared, "envelope horizon") < _number(horizon, "theorem horizon")):
                raise TheoremError("envelope does not cover the theorem horizon")
            if not isinstance(premise["primitive_refs"], list):
                raise TheoremError("envelope primitive_refs must be an array")
        if kind == "theorem":
            _text(premise["claim"], "referenced theorem")
            if not isinstance(premise["substitutions"], Mapping):
                raise TheoremError("theorem substitutions must be an object")
    for lemma in row["lemmas"]:
        _fields(lemma, {"id", "uses", "conclusion"}, "local lemma")
        identifier = _text(lemma["id"], "lemma id")
        if identifier in seen:
            raise TheoremError(f"duplicate theorem fact {identifier}")
        seen.add(identifier)
        if not isinstance(lemma["uses"], list):
            raise TheoremError("lemma uses must be an array")
        validate_formula(lemma["conclusion"], sorts)
    validate_formula(_text(row["conclusion"], "theorem conclusion"), sorts)
    for item in [*row["lemmas"], {"uses": row["uses"]}]:
        for reference in item["uses"]:
            if not isinstance(reference, str) or reference not in seen:
                raise TheoremError(f"unknown local theorem fact {reference!r}")
    return {key: value for key, value in row.items() if key not in {"id", "kind", "metadata"}}


@dataclass(frozen=True)
class TheoremProof:
    conclusion: str
    hypotheses: tuple[str, ...]
    environment_hypotheses: tuple[str, ...]
    events: Mapping[str, Mapping[str, Any]]
    source_relations: tuple[SourceRelation, ...]
    references: frozenset[str]
    checks: tuple[Mapping[str, Any], ...]

    @property
    def failure_probability_upper(self) -> Fraction:
        return min(Fraction(1), sum((_number(item["failure_probability_upper"], "event probability")
                                    for item in self.events.values()), Fraction(0)))


def _binding_identity(binding: Mapping[str, Any]) -> dict[str, Any]:
    # Inputs and completion belong to the invocation, not to one of its exits.
    identity = dict(binding)
    if binding["field"].startswith("input.") or binding["field"] == "$completed":
        identity.pop("outcome")
    return identity


def _canonical_event(premise: Mapping[str, Any], variables: Mapping[str, Any], formula: str) -> str:
    # Alias-renamed copies of the same source projection denote the same event.
    # Different invocation scopes stay different even if the human event name matches.
    from .linear_logic import substitute_formula

    sorts = {name: row["sort"] for name, row in variables.items()}
    substitutions: dict[str, str] = {}
    canonical_sorts: dict[str, str] = {}
    for name, row in variables.items():
        identity = _binding_identity(row["binding"]) if row["binding"] is not None else {"parameter": name, "sort": row["sort"], "unit": row["unit"]}
        key = "s_" + sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        substitutions[name] = key
        canonical_sorts[key] = row["sort"]
    canonical = substitute_formula(formula, sorts, substitutions, result_variables=canonical_sorts)
    identity = {"event": premise["event"], "horizon_ms": premise["horizon_ms"], "formula": canonical}
    return sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _merge_events(target: dict[str, Mapping[str, Any]], values: Mapping[str, Mapping[str, Any]]) -> None:
    for identifier, value in values.items():
        if identifier in target and any(target[identifier][key] != value[key] for key in (
            "event", "horizon_ms", "failure_probability_upper",
        )):
            raise TheoremError("the same scoped envelope event has contradictory declarations")
        target.setdefault(identifier, value)


class TheoremChecker:
    def __init__(self, contract: Contract) -> None:
        self.contract = contract
        self.active: set[str] = set()
        self.proved: dict[str, TheoremProof] = {}

    def prove(self, identifier: str) -> TheoremProof:
        if identifier in self.proved:
            return self.proved[identifier]
        if identifier in self.active:
            raise TheoremError(f"circular theorem dependency at {identifier}")
        claim = self.contract.state_claim_by_id.get(identifier)
        if claim is None or claim.kind != "lra_theorem":
            raise TheoremError(f"unknown LRA theorem {identifier}")
        self.active.add(identifier)
        try:
            proof = self._prove_spec(identifier, claim.specification)
        finally:
            self.active.remove(identifier)
        self.proved[identifier] = proof
        return proof

    def _prove_spec(self, identifier: str, spec: Mapping[str, Any]) -> TheoremProof:
        from .theorem_sources import source_binding_constraints, source_fact

        parse_theorem_spec({"id": identifier, "kind": "lra_theorem", "metadata": {}, **spec})
        variables, sorts = spec["variables"], variable_sorts(spec)
        constraints = source_binding_constraints(variables, self.contract)
        facts: dict[str, TheoremProof] = {}
        for premise in spec["premises"]:
            kind = premise["kind"]
            events: dict[str, Mapping[str, Any]] = {}
            sources: tuple[SourceRelation, ...] = ()
            refs: set[str] = set()
            checks: tuple[Mapping[str, Any], ...] = ()
            hypotheses: tuple[str, ...]
            environment_hypotheses: tuple[str, ...] = ()
            if kind == "source":
                formula, relation = source_fact(premise, variables, self.contract)
                hypotheses = (formula,)
                sources = (replace(relation, id=f"{identifier}/{relation.id}"),)
                refs.add(f"task:{premise['task']}")
            elif kind in {"envelope", "fact"}:
                formula = premise["formula"]
                hypotheses = (formula,)
                environment_hypotheses = hypotheses
                if kind == "envelope":
                    refs.update(premise["primitive_refs"])
                    _validate_primitive_refs(refs, self.contract)
                    event_key = _canonical_event(premise, variables, formula)
                    events[event_key] = {key: premise[key] for key in (
                        "event", "formula", "assumption", "horizon_ms", "failure_probability_upper", "primitive_refs",
                    )}
            else:
                child_id = premise["claim"]
                child = self.prove(child_id)
                child_spec = self.contract.state_claim_by_id[child_id].specification
                mapping = premise["substitutions"]
                _validate_instantiation(child_spec, spec, mapping)
                child_sorts = variable_sorts(child_spec)

                def instantiate(text: str) -> str:
                    return substitute_formula(text, child_sorts, mapping, result_variables=sorts)

                formula = instantiate(child.conclusion)
                hypotheses = tuple(instantiate(item) for item in child.hypotheses)
                environment_hypotheses = tuple(instantiate(item) for item in child.environment_hypotheses)
                if child_spec["mode"] == "mathematical":
                    # A general lemma proves H => C. Instantiation must not make
                    # its arbitrary hypotheses H into physical assumptions.
                    antecedent = "(and " + " ".join(hypotheses) + ")" if hypotheses else "true"
                    formula = f"(=> {antecedent} {formula})"
                    hypotheses = ()
                    environment_hypotheses = ()
                for event in child.events.values():
                    instance = {**event, "formula": instantiate(event["formula"])}
                    key = _canonical_event(instance, variables, instance["formula"])
                    _merge_events(events, {key: instance})
                sources, checks = child.source_relations, child.checks
                refs.update(child.references)
                refs.add(f"state-claim:{child_id}")
            facts[premise["id"]] = TheoremProof(formula, hypotheses, environment_hypotheses, events, sources, frozenset(refs), checks)
        lemmas = {item["id"]: item for item in spec["lemmas"]}
        visiting: set[str] = set()

        def derive(name: str, uses: list[str], conclusion: str) -> TheoremProof:
            premises: list[str] = list(constraints)
            hypotheses: list[str] = list(constraints)
            environment_hypotheses: list[str] = list(constraints)
            events: dict[str, Mapping[str, Any]] = {}
            source_rows: list[SourceRelation] = []
            references: set[str] = set()
            checks: list[Mapping[str, Any]] = []
            for reference in uses:
                if reference not in facts:
                    if reference in visiting:
                        raise TheoremError(f"circular local lemma dependency at {reference}")
                    visiting.add(reference)
                    lemma = lemmas[reference]
                    facts[reference] = derive(reference, lemma["uses"], lemma["conclusion"])
                    visiting.remove(reference)
                fact = facts[reference]
                # Imported statements are conditional: retain both source/engineering
                # hypotheses and the theorem result instead of laundering a lemma.
                premises.extend((*fact.hypotheses, fact.conclusion))
                hypotheses.extend(fact.hypotheses)
                environment_hypotheses.extend(fact.environment_hypotheses)
                _merge_events(events, fact.events)
                source_rows.extend(fact.source_relations)
                references.update(fact.references)
                checks.extend(fact.checks)
            result = prove_implication(sorts, list(dict.fromkeys(premises)), conclusion)
            if result.status != "valid":
                raise TheoremError(f"theorem {identifier}/{name}: {result.status}; {result.reason}; counterexample={result.counterexample}")
            checks.append({"lemma": f"{identifier}/{name}", **result.as_dict()})
            return TheoremProof(conclusion, tuple(dict.fromkeys(hypotheses)),
                                tuple(dict.fromkeys(environment_hypotheses)), events,
                                tuple(dict.fromkeys(source_rows)), frozenset(references), tuple(checks))

        result = derive("conclusion", spec["uses"], spec["conclusion"])
        # Explicit mode prevents a pure math lemma from being presented as an
        # application certificate merely because an irrelevant task was listed.
        if spec["mode"] == "source" and not result.source_relations:
            raise TheoremError("source theorem must use an actual backend-proved source relation")
        if spec["mode"] == "source":
            dependence = prove_implication(sorts, result.environment_hypotheses, result.conclusion)
            if dependence.status != "invalid":
                raise TheoremError(
                    "source theorem must depend on source behavior, not merely assume its conclusion; "
                    f"without source facts: {dependence.status}; {dependence.reason}"
                )
        return result


def _validate_primitive_refs(refs: set[str], contract: Contract) -> None:
    valid = {f"task:{item.id}" for item in contract.tasks}
    valid.update(f"worker:{item.id}" for item in contract.workers)
    valid.update(f"resource:{item.id}" for item in contract.resources)
    valid.update(f"timing:{task.id}/{name}" for task in contract.tasks for name in task.timings)
    valid.update(f"external-handoff:{item.id}" for item in contract.external_handoffs)
    valid.update(f"external-contract:{task.id}" for task in contract.tasks if task.external_contract is not None)
    if refs - valid:
        raise TheoremError(f"envelope cites unknown primitives {sorted(refs - valid)}")


def _validate_instantiation(child: Mapping[str, Any], parent: Mapping[str, Any], mapping: Mapping[str, Any]) -> None:
    if set(mapping) != set(child["variables"]):
        raise TheoremError("theorem instantiation must substitute every declared variable")
    if child["horizon_ms"] is not None and (
        parent["horizon_ms"] is None or _number(parent["horizon_ms"], "parent horizon") > _number(child["horizon_ms"], "child horizon")
    ):
        raise TheoremError("imported theorem does not cover the requested horizon")
    invocation_map: dict[tuple[str, str], str] = {}
    for name, descriptor in child["variables"].items():
        binding = descriptor["binding"]
        if binding is None:
            continue  # Mathematical parameters support arbitrary checked LRA terms.
        target = parent["variables"].get(mapping[name]) if isinstance(mapping[name], str) else None
        if target is None or target["binding"] is None or target["sort"] != descriptor["sort"] or target["unit"] != descriptor["unit"]:
            raise TheoremError(f"source-bound variable {name} must retain its actual typed projection")
        actual = target["binding"]
        expected_identity = _binding_identity(binding)
        actual_identity = _binding_identity(actual)
        if any(expected_identity[key] != actual_identity.get(key) for key in expected_identity if key != "invocation"):
            raise TheoremError(f"source-bound variable {name} was relabeled as another source value")
        scope = (binding["task"], binding["invocation"])
        if scope in invocation_map and invocation_map[scope] != actual["invocation"]:
            raise TheoremError("one source invocation cannot be split across unrelated calls")
        invocation_map[scope] = actual["invocation"]


def prove_theorem(identifier: str, contract: Contract) -> TheoremProof:
    try:
        return TheoremChecker(contract).prove(identifier)
    except (LinearLogicError, ValueError) as exc:
        if isinstance(exc, TheoremError):
            raise
        raise TheoremError(str(exc)) from exc


def theorem_relations(identifier: str, contract: Contract) -> tuple[SourceRelation, ...]:
    return prove_theorem(identifier, contract).source_relations


def theorem_references(identifier: str, contract: Contract) -> frozenset[str]:
    return prove_theorem(identifier, contract).references
