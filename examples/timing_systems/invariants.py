"""Reusable source-bound safety obligations for the five policy examples.

``source_contract`` reads real annotations without importing operation bodies.
Z3 checks initialization and inductive preservation; it does not prove these
functions implement the relations. The ordinary Dagcert semantic backend must
separately discharge ``source_obligations`` before certification. These safety
invariants are not queue liveness, deadline, or scheduler fairness proofs.
"""

from pathlib import Path
from typing import Any

from dagcert.contract import Contract, Implementation, Task, TaskOutcome, Worker
from dagcert.induction import parse_induction_spec, relation_source_obligations
from dagcert.relations import SourceRelation
from dagcert.source_types import read_python_signature


SOURCE_ROOT = Path(__file__).resolve().parent
SOURCE_TASKS = (
    ("av.join", "join_av"),
    ("worker.dispatch", "dispatch_batch"),
    ("sync.ack", "acknowledge_chunk"),
    ("search.change", "change_search_input"),
    ("search.publish", "publish_search_result"),
    ("telemetry.update", "update_window"),
)


def task_definitions() -> list[dict[str, Any]]:
    """Source-shape rows whose outcome unions come from real annotations.

    The certificate builder must add its explicitly declared policy timing
    bounds. This helper does not invent execution costs for application code.
    """
    rows = []
    for task_id, symbol in SOURCE_TASKS:
        signature = read_python_signature(SOURCE_ROOT, "operations.py", symbol)
        rows.append({
            "id": task_id,
            "role": "operation",
            "worker": "policy-worker",
            "implementation": {"language": "python", "path": "operations.py", "symbol": symbol},
            "outcomes": [
                {"type": outcome, "resources": {}, "metadata": {}}
                for outcome in signature.outcome_types
            ],
            "depends_on": [],
            "start_resources": {},
            "timings": {},
            "error_budget": None,
            "external_contract": None,
        })
    return rows


def source_contract() -> Contract:
    """A model-checking fixture, not an issued or source-proved certificate."""
    tasks = []
    for task_id, symbol in SOURCE_TASKS:
        signature = read_python_signature(SOURCE_ROOT, "operations.py", symbol)
        tasks.append(Task(
            task_id, "policy-worker", signature.input_type, " | ".join(signature.outcome_types),
            implementation=Implementation("python", "operations.py", symbol),
            outcomes=tuple(TaskOutcome(name) for name in signature.outcome_types),
            source_signature=signature,
        ))
    return Contract("dagcert-contract/v12", (Worker("policy-worker", 1),), tuple(tasks), ())


def _transition(
    task: str,
    outcome: str,
    fields: tuple[str, ...],
    relation: str,
    after_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    after = after_fields if after_fields is not None else {name: name for name in fields}
    return {
        "task": task,
        "outcome": outcome,
        "before": {name: f"input.{name}" for name in fields},
        "after": {name: f"result.{after[name]}" for name in fields},
        "relation": relation,
    }


def _row(
    name: str,
    fields: tuple[str, ...],
    initial: str,
    invariant: str,
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": name,
        "kind": "relational_invariant",
        "variables": {field: "int" for field in fields},
        "initial": initial,
        "invariant": invariant,
        "transitions": transitions,
        "assumption": (
            "This transition subsystem starts in the declared initial state, returned state "
            "is applied atomically, and the listed transitions cover mutations of these state "
            "fields. Other input fields may vary freely; malformed input is not assumed away. "
            "An embedding application must bind its other mutations before extending this scope."
        ),
        "metadata": {},
    }


def invariant_rows() -> list[dict[str, Any]]:
    """Five finite, source-field-bound safety arguments over all real outcomes."""
    av_fields = ("next_sequence", "reserve_ms", "capacity_ms")
    av_same = (
        "after.next_sequence == before.next_sequence and after.reserve_ms == before.reserve_ms "
        "and after.capacity_ms == before.capacity_ms"
    )
    av = _row(
        "av.finite-reserve", av_fields,
        "state.next_sequence == 0 and 0 <= state.reserve_ms <= state.capacity_ms and state.capacity_ms > 0",
        "state.next_sequence >= 0 and 0 <= state.reserve_ms <= state.capacity_ms", [
            _transition("av.join", "AVJoined", av_fields,
                        "after.next_sequence == before.next_sequence + 1 "
                        "and after.capacity_ms == before.capacity_ms "
                        "and before.reserve_ms < after.reserve_ms <= after.capacity_ms"),
            _transition("av.join", "AVDeferred", av_fields, av_same),
            _transition("av.join", "AVReserveFull", av_fields, av_same),
        ],
    )

    worker_fields = ("interactive_count", "background_count")
    worker_after = {
        "interactive_count": "remaining_interactive", "background_count": "remaining_background",
    }
    worker_same = (
        "after.interactive_count == before.interactive_count "
        "and after.background_count == before.background_count"
    )
    worker_transitions = [
        _transition("worker.dispatch", "InteractiveBatch", worker_fields,
                    "0 <= after.interactive_count < before.interactive_count "
                    "and after.background_count == before.background_count", worker_after),
        _transition("worker.dispatch", "BackgroundBatch", worker_fields,
                    "after.interactive_count == before.interactive_count "
                    "and 0 <= after.background_count < before.background_count", worker_after),
    ]
    worker_transitions.extend(
        _transition("worker.dispatch", outcome, worker_fields, worker_same, worker_after)
        for outcome in ("WorkerBusy", "BatchWaiting", "WorkerIdle", "DispatchRejected")
    )
    worker = _row(
        "worker.queue-conservation", worker_fields,
        "state.interactive_count >= 0 and state.background_count >= 0",
        "state.interactive_count >= 0 and state.background_count >= 0", worker_transitions,
    )

    sync_fields = ("durable_chunks", "durable_bytes")
    sync_same = (
        "after.durable_chunks == before.durable_chunks and after.durable_bytes == before.durable_bytes"
    )
    sync_transitions = [
        _transition("sync.ack", "ChunkCommitted", sync_fields,
                    "after.durable_chunks == before.durable_chunks + 1 "
                    "and after.durable_bytes >= before.durable_bytes + 1"),
    ]
    sync_transitions.extend(
        _transition("sync.ack", outcome, sync_fields, sync_same)
        for outcome in ("ChunkDuplicate", "ChunkDeferred", "ChunkFailed", "ChunkRejected")
    )
    sync = _row(
        "sync.durable-prefix", sync_fields,
        "state.durable_chunks == 0 and state.durable_bytes == 0",
        "0 <= state.durable_chunks <= state.durable_bytes", sync_transitions,
    )

    search_fields = ("current_generation", "visible_generation")
    search_same = (
        "after.current_generation == before.current_generation "
        "and after.visible_generation == before.visible_generation"
    )
    search_transitions = [
        _transition("search.change", "SearchChanged", search_fields,
                    "after.current_generation == before.current_generation + 1 "
                    "and after.visible_generation == before.visible_generation"),
        _transition("search.change", "SearchChangeRejected", search_fields, search_same),
        _transition("search.publish", "SearchPublished", search_fields,
                    "after.current_generation == before.current_generation "
                    "and after.visible_generation == before.current_generation"),
    ]
    search_transitions.extend(
        _transition("search.publish", outcome, search_fields, search_same)
        for outcome in ("SearchStale", "SearchFailed", "SearchPublishRejected")
    )
    search = _row(
        "search.latest-wins", search_fields,
        "state.current_generation == 0 and state.visible_generation == 0",
        "0 <= state.visible_generation <= state.current_generation", search_transitions,
    )

    window_fields = ("count", "last_sequence")
    window_same = "after.count == before.count and after.last_sequence == before.last_sequence"
    window_transitions = [
        _transition("telemetry.update", "WindowAccumulated", window_fields,
                    "after.count == before.count + 1 and after.last_sequence > before.last_sequence"),
        _transition("telemetry.update", "WindowFlushed", window_fields,
                    "after.count == 0 and after.last_sequence == before.last_sequence",
                    {"count": "next_count", "last_sequence": "last_sequence"}),
    ]
    window_transitions.extend(
        _transition("telemetry.update", outcome, window_fields, window_same)
        for outcome in ("WindowIgnored", "WindowWaiting", "WindowRejected")
    )
    telemetry = _row(
        "telemetry.window-accounting", window_fields,
        "state.count == 0 and state.last_sequence == -1",
        "0 <= state.count <= state.last_sequence + 1", window_transitions,
    )
    return [av, worker, sync, search, telemetry]


def policy_relations() -> list[SourceRelation]:
    """Local source facts; these do not need invented history or clock tasks."""
    return [
        SourceRelation(
            "av.matching-next-prefix", "av.join", "AVJoined",
            "input.audio_sequence == input.next_sequence "
            "and input.video_sequence == input.next_sequence "
            "and input.audio_ms == input.video_ms and result.added_ms == input.audio_ms "
            "and result.reserve_ms == input.reserve_ms + result.added_ms",
        ),
        SourceRelation(
            "worker.nonpreemptive-interactive", "worker.dispatch", "InteractiveBatch",
            "input.now_ms >= input.busy_until_ms and result.count > 0 "
            "and result.remaining_interactive + result.count == input.interactive_count "
            "and result.remaining_background == input.background_count",
        ),
        SourceRelation(
            "worker.nonpreemptive-background", "worker.dispatch", "BackgroundBatch",
            "input.now_ms >= input.busy_until_ms and input.interactive_count == 0 "
            "and result.count > 0 and result.remaining_background + result.count == input.background_count",
        ),
        SourceRelation(
            "worker.batch-timer", "worker.dispatch", "BatchWaiting",
            "input.now_ms < result.deadline_ms "
            "and (result.deadline_ms == input.interactive_oldest_ms + input.batch_timeout_ms "
            "or result.deadline_ms == input.background_oldest_ms + input.batch_timeout_ms)",
        ),
        SourceRelation(
            "sync.next-unique-chunk", "sync.ack", "ChunkCommitted",
            "input.acknowledged and input.chunk_index == input.durable_chunks "
            "and result.durable_bytes == input.durable_bytes + input.chunk_bytes",
        ),
        SourceRelation(
            "search.request-cancellation", "search.change", "SearchChanged",
            "result.cancel_generation == input.active_generation "
            "and result.current_generation == input.current_generation + 1",
        ),
        SourceRelation(
            "search.current-result-only", "search.publish", "SearchPublished",
            "input.completed and input.result_generation == input.current_generation "
            "and result.visible_generation == input.result_generation",
        ),
        SourceRelation(
            "telemetry.matching-unique-reading", "telemetry.update", "WindowAccumulated",
            "input.has_reading and input.reading_window == input.window_id "
            "and input.reading_sequence > input.last_sequence "
            "and result.total == input.total + input.reading_value",
        ),
        SourceRelation(
            "telemetry.partial-timer-flush", "telemetry.update", "WindowFlushed",
            "input.now_ms >= input.window_started_ms + input.window_duration_ms "
            "and result.total == input.total and result.count == input.count "
            "and result.next_count == 0 and result.unconsumed_reading == input.has_reading",
        ),
    ]


def source_obligations(contract: Contract | None = None) -> list[SourceRelation]:
    """All source assertions required in addition to the model/solver checks."""
    model = source_contract() if contract is None else contract
    relations = policy_relations()
    for row in invariant_rows():
        relations.extend(relation_source_obligations(parse_induction_spec(row), model))
    return relations
