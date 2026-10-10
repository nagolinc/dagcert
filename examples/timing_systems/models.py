"""Build inspectable contracts from actual operation signatures, not copy-pasted labels."""

from __future__ import annotations

from typing import Any

from dagcert.source_types import read_python_signature

from .invariants import SOURCE_ROOT, invariant_rows, policy_relations, task_definitions


def _curve(rate: int | str, delay: int = 0, burst: int = 0) -> dict[str, Any]:
    points = [[0, burst]] if delay == 0 else [[0, burst], [delay, burst]]
    return {"points": points, "tail_slope": rate}


def _premise(identifier: str, kind: str, assumption: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier, "kind": kind, "assumption": assumption,
        # This is one engineering budget for the WHOLE all-time envelope,
        # never a per-request failure rate promoted to an infinite guarantee.
        "horizon_ms": None, "failure_probability_upper": "1/10000", **fields,
    }


def _streaming_invariant() -> dict[str, Any]:
    fields = {"reserve_ms": "int", "capacity_ms": "int"}
    transitions = []
    for task, outcomes in (
        ("av.join", ("AVJoined", "AVDeferred", "AVReserveFull")),
        ("stream.consume", ("Consumed", "BufferEmpty")),
        ("stream.refill", ("RefillDecision",)),
    ):
        for outcome in outcomes:
            output = "remaining_ms" if task == "stream.consume" else "reserve_ms"
            if outcome == "AVJoined":
                relation = "before.reserve_ms <= after.reserve_ms <= before.capacity_ms"
            elif outcome == "Consumed":
                relation = "0 <= after.reserve_ms < before.reserve_ms"
            else:
                relation = "after.reserve_ms == before.reserve_ms"
            transitions.append({
                "task": task, "outcome": outcome,
                "before": {name: f"input.{name}" for name in fields},
                "after": {"reserve_ms": f"result.{output}", "capacity_ms": "result.capacity_ms"},
                "relation": f"({relation}) and after.capacity_ms == before.capacity_ms",
            })
    return {
        "id": "stream.buffer-capacity", "kind": "relational_invariant",
        "variables": fields,
        "initial": "state.reserve_ms == 5000 and state.capacity_ms == 15000",
        "invariant": "0 <= state.reserve_ms <= state.capacity_ms",
        "transitions": transitions,
        "assumption": "The reserve starts with 5000 ms in a 15000 ms buffer. These are the only atomic reserve mutators; each next input uses the previous returned reserve and capacity. Rendering does not alter reserve before keyed join admission.",
        "metadata": {},
    }


def streaming_bound() -> dict[str, Any]:
    """An infinite busy-period deficit bound, not unbounded accumulated output."""
    relations = [
        {"id": item.id, "task": item.task_id, "outcome": item.outcome_type, "predicate": item.predicate}
        for item in policy_relations()
    ]
    relations.extend([
        {
            "id": "stream.quantity-and-identity", "task": "stream.produce", "outcome": "SegmentProduced",
            "predicate": "result.duration_ms == input.duration_ms and result.sequence == input.sequence and input.provider_succeeded",
        },
        {
            "id": "stream.refill-policy", "task": "stream.refill", "outcome": "RefillDecision",
            "predicate": "not (0 <= input.reserve_ms <= input.capacity_ms and input.low_water_ms > 0 and input.maximum_piece_ms > 0 and input.low_water_ms + input.maximum_piece_ms <= input.capacity_ms) or result.refill == (input.reserve_ms < input.low_water_ms)",
        },
    ])
    envelopes = [
        _premise(
            "playback", "arrival", "In every interval of t ms, atomic playback callbacks consume at most 100+t media-ms; one callback consumes at most 100ms. The leading burst includes the callback crossing low water. The buffer epoch begins above that mark.",
            task="stream.consume", input_field="duration_ms", unit="media_ms", window="interval",
            lower=_curve(0), upper=_curve(1, burst=100),
        ),
        _premise(
            "renderer", "worker", "While refill is active and work is pending, the dedicated renderer supplies one effective worker-ms per elapsed ms; all external I/O, retry waits and contention are included, not hidden idle time.",
            worker="renderer", tasks=["stream.produce"], slots=1, availability=_curve(1),
        ),
        _premise(
            "variable-cost", "workload", "In EVERY backlogged interval, all work attributable to completed useful output plus failed/retried/duplicate/discarded work is <= 0.8 * produced media-ms + 1400 worker-ms; unfinished work is <=3000 worker-ms. Ordered matched admission is lossless with its delay included here. This allows individual 2s pieces to cost 3s, interleaved with 5s pieces costing 2s; it is not inferred from an observed average.",
            task="stream.produce", unit="media_ms",
            outcome_quantities={"SegmentProduced": "result.duration_ms", "SegmentFailed": 0},
            work_per_quantity="4/5", excess_work=1400, unfinished_work=3000,
        ),
        _premise(
            "refill-controller", "policy", "Each refill interval begins just before the <=100ms callback crossing the 5000ms low-water mark; that callback is included in the demand burst, not ignored or charged twice. The source-proved controller restarts within 100ms and maintains backlogged replenishment until this period ends; pause at high reserve never credits discarded work to later periods. A/V IDs denote the same ordered sequence and withheld work/delay is charged to the workload envelope.",
            task="stream.refill", mode="busy_period", restart_delay_ms=100,
        ),
    ]
    return {
        "id": "stream.infinite-reserve", "kind": "curve_bound",
        "network": {
            "envelopes": envelopes, "relations": relations,
            "invariants": [item["id"] for item in invariant_rows()] + ["stream.buffer-capacity"],
        },
        "expression": {"subtract": [
            {"constant": {"value": 5000, "unit": "media_ms"}},
            {"service_deficit": {
                "demand": {"arrival_upper": "playback"},
                "service": {"quantity_service": {
                    "work": {"worker_service": "renderer"}, "workload": "variable-cost",
                }},
                "policy": "refill-controller",
            }},
        ]},
        "operator": "gte", "bound": 400, "start_ms": 0, "end_ms": None,
        "metadata": {"scope": "All-time refill busy periods with four declared whole-horizon engineering failure budgets of 1/10000 each; NOT per-call probabilities or estimates of unknown future stochastic tails."},
    }


def contract_document() -> dict[str, Any]:
    tasks = task_definitions()
    for identifier, symbol, worker in (
        ("stream.produce", "produce_segment", "renderer"),
        ("stream.consume", "consume", "policy-worker"),
        ("stream.refill", "decide_refill", "policy-worker"),
    ):
        signature = read_python_signature(SOURCE_ROOT, "streaming.py", symbol)
        tasks.append({
            "id": identifier, "role": "operation", "worker": worker,
            "implementation": {"language": "python", "path": "streaming.py", "symbol": symbol},
            "outcomes": [{"type": outcome, "resources": {}, "metadata": {}} for outcome in signature.outcome_types],
            "depends_on": [], "start_resources": {}, "timings": {},
            "error_budget": None, "external_contract": None,
        })
    return {
        "schema": "dagcert-contract/v12",
        "workers": [{"id": "renderer", "concurrency": 1}, {"id": "policy-worker", "concurrency": 1}],
        "tasks": tasks, "resources": [], "channels": [], "external_handoffs": [],
        "external_boundaries": [], "compositions": [],
        "state_claims": invariant_rows() + [_streaming_invariant(), streaming_bound()],
        "metadata": {},
    }


def requirements_document(contract: dict[str, Any]) -> dict[str, Any]:
    refs = [f"state-claim:{item['id']}" for item in contract["state_claims"]]
    refs += [f"task:{item['id']}" for item in contract["tasks"]]
    return {
        "schema": "dagcert-english-requirements/v2",
        "claims": [{
            "id": "five-source-policies-and-variable-stream",
            "statement": "Under the explicit initialization and atomic-state ownership premises, the five example policies preserve their stated safety invariants and local accounting relations. Given each of the four whole-horizon engineering envelopes has failure probability at most 1/10000, the probability of retaining at least 400ms of reserve in every refill busy period for all time is at least 0.9996; the probability of any streaming interruption in that modeled lifetime is at most 0.0004. Output lengths and production times vary, and some pieces take longer to produce than to play. This is not a certificate of five complete deployed applications.",
            "basis": "chance", "primitive_refs": refs, "checker_refs": [],
            "assumptions": [
                "Every declared initialization and mutation-scope premise holds; no unmodeled code mutates the retained state.",
                "For each of the four network envelopes, the probability that it fails anywhere over the entire unbounded modeled lifetime is at most 1/10000. These are explicit engineering assumptions, not per-call failure rates or statistically inferred measurements. They need not be independent. Failed attempts and zero-output outcomes remain included in the workload envelope.",
                "The interval workload relation, not a per-job stopwatch maximum, bounds production. Scheduler restart delay is included explicitly.",
                "The example constructs segment descriptors; an application must replace platform rendering, queue persistence and callback execution with its own source-bound paths and explicit platform contracts.",
            ],
            "formula": {"gte": [{"state_claim_success_probability_lower": "state-claim:stream.infinite-reserve"}, 0.9996]},
        }], "metadata": {},
    }
