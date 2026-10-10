"""A source-bound timed release proof using generic LRA, not a quorum operator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dagcert.source_types import read_python_signature


SOURCE_ROOT = Path(__file__).resolve().parent
TASK_ID = "acknowledgement.release"
THEOREM_ID = "acknowledgement.release-deadline"
ENVELOPE_ID = "release-dispatch-and-application"
DEFAULT_HORIZON_MS = 60_000
DEFAULT_FAILURE_PROBABILITY = "1/1000"


def _binding(field: str, sort: str, unit: str) -> dict[str, Any]:
    return {
        "sort": sort, "unit": unit,
        "binding": {
            "task": TASK_ID, "invocation": "release-attempt",
            "outcome": "ReleaseDecision", "field": field,
        },
    }


def _source_readiness() -> str:
    valid = {
        slot: f"(input.{slot}_present and input.{slot}_replica >= 0 "
        f"and input.{slot}_version == input.expected_version "
        f"and 0 <= input.{slot}_arrived_ms <= input.now_ms)"
        for slot in ("a", "b", "c")
    }
    return "(" + " or ".join(
        f"({valid[left]} and {valid[right]} and input.{left}_replica != input.{right}_replica)"
        for left, right in (("a", "b"), ("a", "c"), ("b", "c"))
    ) + ")"


def ready_by_deadline() -> str:
    """Any pair, not a fixed pair or all three; absent acknowledgements do not count."""
    valid = {
        slot: f"(and {slot}_present (>= {slot}_replica 0) "
        f"(= {slot}_version expected_version) "
        f"(>= {slot}_arrived_ms 0) (<= {slot}_arrived_ms deadline))"
        for slot in ("a", "b", "c")
    }
    return "(or " + " ".join(
        f"(and {valid[left]} {valid[right]} (not (= {left}_replica {right}_replica)))"
        for left, right in (("a", "b"), ("a", "c"), ("b", "c"))
    ) + ")"


def theorem_document(
    *, horizon_ms: int = DEFAULT_HORIZON_MS,
    failure_probability: str = DEFAULT_FAILURE_PROBABILITY,
) -> dict[str, Any]:
    signature = read_python_signature(SOURCE_ROOT, "operations.py", "decide_release")
    variables: dict[str, Any] = {}
    for field, annotation in signature.input_fields:
        sort = "bool" if annotation == "bool" else "real"
        unit = "boolean" if annotation == "bool" else (
            "ms" if field.endswith("_ms") else "version" if "version" in field else "replica_id"
        )
        variables[field] = _binding(f"input.{field}", sort, unit)
    variables.update({
        "released": _binding("result.released", "bool", "boolean"),
        "release_ms": _binding("result.release_ms", "real", "ms"),
        "done": _binding("$completed", "bool", "boolean"),
        "deadline": {"sort": "real", "unit": "ms", "binding": None},
        "dispatch_allowance": {"sort": "real", "unit": "ms", "binding": None},
    })
    window = f"(and (>= deadline 0) (>= dispatch_allowance 0) (<= (+ deadline dispatch_allowance) {horizon_ms}))"
    trigger = f"(and {window} {ready_by_deadline()})"
    return {
        "id": THEOREM_ID, "kind": "lra_theorem", "mode": "source",
        "variables": variables,
        "premises": [
            {
                "id": "source-ready", "kind": "source", "task": TASK_ID,
                "invocation": "release-attempt", "outcome": "ReleaseDecision",
                "predicate": f"result.released == {_source_readiness()}",
            },
            {
                "id": "source-timestamp", "kind": "source", "task": TASK_ID,
                "invocation": "release-attempt", "outcome": "ReleaseDecision",
                "predicate": "not result.released or result.release_ms == input.now_ms",
            },
            {
                "id": ENVELOPE_ID, "kind": "envelope", "event": ENVELOPE_ID,
                "formula": f"(=> {trigger} (and done (>= now_ms deadline) (<= now_ms (+ deadline dispatch_allowance))))",
                "assumption": (
                    "The acknowledgement snapshot contains the actual delivered replica identities, versions and arrival "
                    "times. For every applicable release attempt in this window, after two distinct matching acknowledgements "
                    "arrive by D, the scheduler executes and atomically applies this policy at a monotonic timestamp "
                    "now_ms in [D,D+dispatch_allowance], and that invocation completes. The timestamp denotes the atomic "
                    "transition, not an earlier stopwatch sample. Dispatch, policy execution and application delay are "
                    "all included. The declared probability bounds failure of this whole envelope over the window."
                ),
                "horizon_ms": horizon_ms,
                "failure_probability_upper": failure_probability,
                "primitive_refs": [f"task:{TASK_ID}", "worker:release-worker"],
            },
        ],
        "lemmas": [{
            "id": "ready-policy-releases", "uses": ["source-ready", ENVELOPE_ID],
            "conclusion": f"(=> {trigger} released)",
        }],
        "uses": ["ready-policy-releases", "source-timestamp", ENVELOPE_ID],
        "conclusion": f"(=> {trigger} (and released (<= release_ms (+ deadline dispatch_allowance))))",
        "horizon_ms": horizon_ms,
        "metadata": {
            "scope": "A real release policy under explicit platform dispatch/application assumptions, not an entire document store.",
        },
    }


def contract_document(
    *, horizon_ms: int = DEFAULT_HORIZON_MS,
    failure_probability: str = DEFAULT_FAILURE_PROBABILITY,
) -> dict[str, Any]:
    signature = read_python_signature(SOURCE_ROOT, "operations.py", "decide_release")
    return {
        "schema": "dagcert-contract/v12",
        "workers": [{"id": "release-worker", "concurrency": 1}],
        "tasks": [{
            "id": TASK_ID, "role": "operation", "worker": "release-worker",
            "implementation": {"language": "python", "path": "operations.py", "symbol": "decide_release"},
            "outcomes": [{"type": outcome, "resources": {}, "metadata": {}} for outcome in signature.outcome_types],
            "depends_on": [], "start_resources": {}, "timings": {},
            "error_budget": None, "external_contract": None,
        }],
        "resources": [], "channels": [], "external_handoffs": [], "external_boundaries": [],
        "compositions": [], "state_claims": [theorem_document(
            horizon_ms=horizon_ms, failure_probability=failure_probability,
        )], "metadata": {},
    }


def requirements_document(contract: dict[str, Any]) -> dict[str, Any]:
    from fractions import Fraction

    theorem = contract["state_claims"][0]
    envelope = next(item for item in theorem["premises"] if item["kind"] == "envelope")
    success = Fraction(1) - Fraction(envelope["failure_probability_upper"])
    return {
        "schema": "dagcert-english-requirements/v2",
        "claims": [{
            "id": "timed-distinct-acknowledgement-release",
            "statement": (
                "Under the disclosed whole-window dispatch, snapshot-integrity and atomic-application envelope, "
                "any two distinct replicas acknowledging the requested version by deadline D enable the actual "
                "release policy, whose release transition timestamp is at most D+dispatch_allowance. A missing "
                "third acknowledgement is not required, duplicates and other versions do not count. The modeled "
                "failure probability is the declared envelope budget, not a measured success fraction. This certifies "
                "the toy policy and its timing implication, not a complete storage cluster or unconditional network liveness."
            ),
            "basis": "chance", "primitive_refs": [f"task:{TASK_ID}", "worker:release-worker", f"state-claim:{THEOREM_ID}"],
            "checker_refs": [], "assumptions": [envelope["assumption"]],
            "formula": {"gte": [{"state_claim_success_probability_lower": f"state-claim:{THEOREM_ID}"}, float(success)]},
        }], "metadata": {},
    }
