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

    def to_mapping(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "primitive_refs": list(self.primitive_refs),
            "checker_refs": list(self.checker_refs),
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True, slots=True)
class EnglishRequirements:
    schema: str
    claims: tuple[EnglishClaim, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claims": [claim.to_mapping() for claim in self.claims],
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
    required_checkers = {
        reference for claim in requirements.claims for reference in claim.checker_refs
    }
    selected = set(selected_checkers) if selected_checkers is not None else None
    findings: list[str] = []

    unknown_primitives = referenced_primitives - valid_primitives
    if unknown_primitives:
        findings.append(f"English claims cite unknown primitives: {sorted(unknown_primitives)}")
    uncovered_tasks = required_tasks - referenced_primitives
    if uncovered_tasks:
        findings.append(f"formal tasks lack an English claim: {sorted(uncovered_tasks)}")
    uncovered_timings = required_timings - referenced_primitives
    if uncovered_timings:
        findings.append(f"formal timings lack an English claim: {sorted(uncovered_timings)}")
    if selected is not None:
        missing_checkers = required_checkers - selected
        if missing_checkers:
            findings.append(
                f"English claims cite unselected checkers: {sorted(missing_checkers)}"
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

    supplementary = () if selected is None else tuple(sorted(selected - required_checkers))
    return TranslationAudit(
        passed=not findings,
        findings=tuple(findings),
        covered_tasks=tuple(sorted(required_tasks & referenced_primitives)),
        covered_timings=tuple(sorted(required_timings & referenced_primitives)),
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
    if raw.get("schema") != "dagcert-english-requirements/v1":
        raise RequirementsError(
            "English requirements schema must be dagcert-english-requirements/v1"
        )
    if not isinstance(raw["metadata"], dict):
        raise RequirementsError("English requirements metadata must be an object")
    claim_rows = raw["claims"]
    if not isinstance(claim_rows, list) or not claim_rows:
        raise RequirementsError("English requirements must contain at least one claim")
    claims: list[EnglishClaim] = []
    for index, value in enumerate(claim_rows, 1):
        if not isinstance(value, dict) or set(value) != {
            "id", "statement", "primitive_refs", "checker_refs", "assumptions",
        }:
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
        ))
    identifiers = [claim.id for claim in claims]
    if len(identifiers) != len(set(identifiers)):
        raise RequirementsError("English claim IDs must be unique")
    return EnglishRequirements(
        schema="dagcert-english-requirements/v1",
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
