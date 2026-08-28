"""Mandatory human-readable claims bound into every Dagcert certificate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping
import json

if TYPE_CHECKING:
    from .contract import Contract


class RequirementsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EnglishClaim:
    id: str
    statement: str
    primitive_refs: tuple[str, ...]
    checker_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    basis: str = "legacy"
    formula: Mapping[str, Any] | None = None

    def to_mapping(self, *, schema: str = "dagcert-english-requirements/v1") -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "statement": self.statement,
            "primitive_refs": list(self.primitive_refs),
            "checker_refs": list(self.checker_refs),
            "assumptions": list(self.assumptions),
        }
        if schema == "dagcert-english-requirements/v2":
            result["basis"] = self.basis
            result["formula"] = dict(self.formula) if self.formula is not None else None
        return result


@dataclass(frozen=True, slots=True)
class EnglishRequirements:
    schema: str
    claims: tuple[EnglishClaim, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claims": [claim.to_mapping(schema=self.schema) for claim in self.claims],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TranslationAudit:
    """Deterministic completeness audit of English claims against the formal contract."""

    passed: bool
    findings: tuple[str, ...]
    covered_tasks: tuple[str, ...]
    covered_timings: tuple[str, ...]
    required_checkers: tuple[str, ...]
    supplementary_checkers: tuple[str, ...]
    conditional_claims: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": "dagcert-translation-audit/v1",
            "passed": self.passed,
            "findings": list(self.findings),
            "covered_tasks": list(self.covered_tasks),
            "covered_timings": list(self.covered_timings),
            "required_checkers": list(self.required_checkers),
            "supplementary_checkers": list(self.supplementary_checkers),
            "conditional_claims": list(self.conditional_claims),
        }


def audit_translation(
    requirements: EnglishRequirements,
    contract: "Contract",
    *,
    selected_checkers: Iterable[str] | None = None,
) -> TranslationAudit:
    """Audit that every formal task and timing guarantee is represented in English.

    This mandatory deterministic audit checks traceability and completeness. The optional
    independent semantic audit judges whether the prose is faithful to the implementation.
    """
    valid_primitives = {f"worker:{item.id}" for item in contract.workers}
    valid_primitives.update(f"task:{item.id}" for item in contract.tasks)
    valid_primitives.update(f"resource:{item.id}" for item in contract.resources)
    valid_primitives.update(
        f"timing:{task.id}/{case}" for task in contract.tasks for case in task.timings
    )
    valid_primitives.update(f"composition:{item.id}" for item in contract.compositions)
    valid_primitives.update(
        f"error-budget:{task.id}" for task in contract.tasks
        if task.error_budget is not None
    )
    valid_primitives.update(
        f"external-contract:{task.id}" for task in contract.tasks
        if task.external_contract is not None
    )
    valid_primitives.update(
        f"guarantee:{task.id}/{kind}/{resource.id}"
        for task in contract.tasks
        for kind in ("produce", "consume")
        for resource in contract.resources
    )
    required_tasks = {f"task:{item.id}" for item in contract.tasks}
    required_timings = {
        f"timing:{task.id}/{case}" for task in contract.tasks for case in task.timings
    }
    assumed_timings = {
        f"timing:{task.id}/{case}"
        for task in contract.tasks
        for case, timing in task.timings.items()
        if timing.evidence == "assumed"
    }
    referenced_primitives = {
        reference for claim in requirements.claims for reference in claim.primitive_refs
    }
    coverage_primitives: set[str] = set()
    if requirements.schema == "dagcert-english-requirements/v2":
        from .formula import formula_references

        for claim in requirements.claims:
            if claim.basis in {"derived", "chance"} and claim.formula is not None:
                try:
                    coverage_primitives.update(formula_references(claim.formula))
                except ValueError:
                    # The formula-specific audit below reports the precise invalidity. Invalid
                    # prose references must not nevertheless count as formal coverage.
                    pass
            else:
                coverage_primitives.update(claim.primitive_refs)
    else:
        coverage_primitives.update(referenced_primitives)
    for composition in contract.compositions:
        if f"composition:{composition.id}" not in referenced_primitives:
            continue
        coverage_primitives.update(f"task:{step.task}" for step in composition.steps)
        coverage_primitives.update(
            f"timing:{step.task}/{step.timing}" for step in composition.steps
        )
    for task in contract.tasks:
        if f"external-contract:{task.id}" not in coverage_primitives:
            continue
        coverage_primitives.add(f"task:{task.id}")
        if task.external_contract is not None:
            coverage_primitives.add(
                f"timing:{task.id}/{task.external_contract.evidence_case}"
            )
    required_checkers = {
        reference for claim in requirements.claims for reference in claim.checker_refs
    }
    selected = set(selected_checkers) if selected_checkers is not None else None
    findings: list[str] = []

    unknown_primitives = referenced_primitives - valid_primitives
    if unknown_primitives:
        findings.append(f"English claims cite unknown primitives: {sorted(unknown_primitives)}")
    uncovered_tasks = required_tasks - coverage_primitives
    if uncovered_tasks:
        findings.append(f"formal tasks lack an English claim: {sorted(uncovered_tasks)}")
    uncovered_timings = required_timings - coverage_primitives
    if uncovered_timings:
        findings.append(f"formal timings lack an English claim: {sorted(uncovered_timings)}")
    if selected is not None:
        missing_checkers = required_checkers - selected
        if missing_checkers:
            findings.append(
                f"English claims cite unselected checkers: {sorted(missing_checkers)}"
            )

    if requirements.schema == "dagcert-english-requirements/v2":
        from .formula import (
            FormulaError, formula_references, formula_uses_error_budgets,
            validate_claim_formula,
        )

        for claim in requirements.claims:
            if claim.basis in {"derived", "chance"}:
                if claim.checker_refs:
                    findings.append(
                        f"{claim.basis} claim {claim.id} cannot delegate proof to arbitrary checkers"
                    )
                if claim.formula is None:
                    findings.append(f"{claim.basis} claim {claim.id} lacks a kernel formula")
                    continue
                try:
                    validate_claim_formula(claim.formula, basis=claim.basis)
                    formula_refs = set(formula_references(claim.formula))
                except FormulaError as exc:
                    findings.append(f"{claim.basis} claim {claim.id} has invalid formula: {exc}")
                    continue
                missing_formula_refs = formula_refs - set(claim.primitive_refs)
                if missing_formula_refs:
                    findings.append(
                        f"derived claim {claim.id} formula references are not declared: "
                        f"{sorted(missing_formula_refs)}"
                    )
                uses_budgets = formula_uses_error_budgets(claim.formula)
                if claim.basis == "chance" and not uses_budgets:
                    findings.append(
                        f"chance claim {claim.id} must use a finite composition error-budget operator"
                    )
                if claim.basis == "derived" and uses_budgets:
                    findings.append(
                        f"derived claim {claim.id} uses probabilistic error budgets; mark it chance"
                    )
                if claim.basis == "chance":
                    if not claim.assumptions:
                        findings.append(
                            f"chance claim {claim.id} must state its engineering assumptions"
                        )
                    composition_ids = {
                        reference.split(":", 1)[1]
                        for reference in formula_refs
                        if reference.startswith("composition:")
                    }
                    budget_refs: set[str] = set()
                    for composition_id in composition_ids:
                        referenced_composition = contract.composition_by_id.get(composition_id)
                        if referenced_composition is not None:
                            budget_refs.update(
                                f"error-budget:{step.task}"
                                for step in referenced_composition.steps
                            )
                    budget_refs.update(
                        f"error-budget:{reference.split(':', 1)[1]}"
                        for reference in formula_refs
                        if reference.startswith("external-contract:")
                    )
                    missing_budgets = budget_refs - set(claim.primitive_refs)
                    if missing_budgets:
                        findings.append(
                            f"chance claim {claim.id} omits error-budget references: "
                            f"{sorted(missing_budgets)}"
                        )
            elif claim.formula is not None:
                findings.append(
                    f"observed claim {claim.id} must not contain a derived formula"
                )

    assumption_gaps: list[str] = []
    for reference in sorted(assumed_timings):
        citing_claims = [
            claim for claim in requirements.claims if reference in claim.primitive_refs
        ]
        if not citing_claims or not any(claim.assumptions for claim in citing_claims):
            assumption_gaps.append(reference)
    if assumption_gaps:
        findings.append(
            f"assumed timings lack explicit English assumptions: {assumption_gaps}"
        )
    external_assumption_gaps = [
        f"external-contract:{task.id}"
        for task in contract.tasks
        if task.external_contract is not None
        and not any(
            f"external-contract:{task.id}" in claim.primitive_refs and claim.assumptions
            for claim in requirements.claims
        )
    ]
    if external_assumption_gaps:
        findings.append(
            "external contracts lack explicit English assumptions: "
            f"{external_assumption_gaps}"
        )

    supplementary = () if selected is None else tuple(sorted(selected - required_checkers))
    return TranslationAudit(
        passed=not findings,
        findings=tuple(findings),
        covered_tasks=tuple(sorted(required_tasks & coverage_primitives)),
        covered_timings=tuple(sorted(required_timings & coverage_primitives)),
        required_checkers=tuple(sorted(required_checkers)),
        supplementary_checkers=supplementary,
        conditional_claims=tuple(sorted(
            claim.id for claim in requirements.claims if claim.assumptions
        )),
    )


def load_requirements(path: str | Path) -> EnglishRequirements:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RequirementsError(f"invalid English requirements JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "claims", "metadata"}:
        raise RequirementsError(
            "English requirements must contain exactly schema, claims, and metadata"
        )
    schema = raw.get("schema")
    if schema not in {
        "dagcert-english-requirements/v1", "dagcert-english-requirements/v2",
    }:
        raise RequirementsError(
            "English requirements schema must be dagcert-english-requirements/v1 or v2"
        )
    if not isinstance(raw["metadata"], dict):
        raise RequirementsError("English requirements metadata must be an object")
    claim_rows = raw["claims"]
    if not isinstance(claim_rows, list) or not claim_rows:
        raise RequirementsError("English requirements must contain at least one claim")
    claims: list[EnglishClaim] = []
    for index, value in enumerate(claim_rows, 1):
        expected_fields = {
            "id", "statement", "primitive_refs", "checker_refs", "assumptions",
        }
        if schema == "dagcert-english-requirements/v2":
            expected_fields.update({"basis", "formula"})
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise RequirementsError(f"English claim {index} has unexpected or missing fields")
        identifier = _text(value["id"], f"English claim {index} id")
        statement = _text(value["statement"], f"English claim {identifier} statement")
        primitive_refs = _text_array(
            value["primitive_refs"], f"English claim {identifier} primitive_refs"
        )
        checker_refs = _text_array(
            value["checker_refs"], f"English claim {identifier} checker_refs"
        )
        assumptions = _text_array(
            value["assumptions"], f"English claim {identifier} assumptions"
        )
        basis = "legacy"
        formula: Mapping[str, Any] | None = None
        if schema == "dagcert-english-requirements/v2":
            basis = _text(value["basis"], f"English claim {identifier} basis")
            if basis not in {"observed", "derived", "chance"}:
                raise RequirementsError(
                    f"English claim {identifier} basis must be observed, derived, or chance"
                )
            formula_value = value["formula"]
            if formula_value is not None and not isinstance(formula_value, Mapping):
                raise RequirementsError(
                    f"English claim {identifier} formula must be an object or null"
                )
            formula = dict(formula_value) if formula_value is not None else None
            if basis in {"derived", "chance"} and formula is None:
                raise RequirementsError(
                    f"{basis} English claim {identifier} must contain a formula"
                )
            if basis == "observed" and formula is not None:
                raise RequirementsError(
                    f"observed English claim {identifier} formula must be null"
                )
        if not primitive_refs and not checker_refs:
            raise RequirementsError(
                f"English claim {identifier} must reference a primitive or checker"
            )
        claims.append(EnglishClaim(
            identifier,
            statement,
            primitive_refs,
            checker_refs,
            assumptions,
            basis,
            formula,
        ))
    identifiers = [claim.id for claim in claims]
    if len(identifiers) != len(set(identifiers)):
        raise RequirementsError("English claim IDs must be unique")
    return EnglishRequirements(
        schema=str(schema),
        claims=tuple(claims),
        metadata=dict(raw["metadata"]),
    )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequirementsError(f"{label} must be a nonempty string")
    return value.strip()


def _text_array(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RequirementsError(f"{label} must be an array")
    result = tuple(_text(item, label) for item in value)
    if len(result) != len(set(result)):
        raise RequirementsError(f"{label} must contain unique values")
    return result
