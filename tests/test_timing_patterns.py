"""Executable application recipes composed from the public temporal algebra.

These tests exercise timing inference for already accepted operation nodes. Source proof
of those nodes belongs to the contract/source-proof tests; no application-specific timing
operator or callback is involved here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from dagcert.contract import Contract, Implementation, Task, TaskOutcome, Timing, TypedDependency, Worker
from dagcert.temporal import parse_temporal_spec, prove_temporal_bound


def _curve(points: list[list[int | str]], tail: int | str = 0) -> dict[str, Any]:
    return {"points": points, "tail_slope": tail}


def _operation(name: str, cost_ms: int = 4) -> Task:
    return Task(
        name,
        f"{name}-worker",
        "Request",
        "Completed",
        implementation=Implementation("python", "production.py", name),
        outcomes=(TaskOutcome("Completed"),),
        timings={
            "execute": Timing("duration", upper_ms=cost_ms / 2, evidence="assumed", minimum_samples=0),
            "dispatch": Timing("wait", upper_ms=cost_ms / 2, evidence="assumed", minimum_samples=0),
        },
    )


def _model(tasks: tuple[Task, ...]) -> tuple[Contract, dict[str, Any]]:
    contract = Contract(
        "dagcert-contract/v7",
        tuple(Worker(task.worker, 1) for task in tasks),
        tasks,
        (),
    )
    envelopes: list[dict[str, Any]] = []
    for task in tasks:
        envelopes.extend([
            {
                "id": f"{task.id}-arrivals",
                "kind": "arrival",
                "task": task.id,
                "assumption": "Invocation activations obey these count bounds in every time interval.",
                "horizon_ms": None,
                "failure_probability_upper": 0,
                "window": "interval",
                "lower": _curve([[0, 0], [10, 0]], "1/10"),
                "upper": _curve([[0, 1]], "1/10"),
            },
            {
                "id": f"{task.id}-service",
                "kind": "service",
                "task": task.id,
                "assumption": "The dedicated work-conserving lane supplies its stated effective worker time whenever work is backlogged.",
                "horizon_ms": None,
                "failure_probability_upper": 0,
                "slots": 1,
                "availability": _curve([[0, 0]], 1),
                "duration_timing": "execute",
                "dispatch_timing": "dispatch",
            },
        ])
    return contract, {
        "id": "timing-pattern",
        "kind": "curve_bound",
        "envelopes": envelopes,
        "flows": [
            {"task": task.id, "input": {"arrival": f"{task.id}-arrivals"}, "service": f"{task.id}-service"}
            for task in tasks
        ],
        "expression": {"departures_lower": tasks[-1].id},
        "operator": "gte",
        "bound": 0,
        "start_ms": 0,
        "end_ms": None,
        "metadata": {},
    }


def _assert_result(contract: Contract, row: dict[str, Any], expected: bool) -> None:
    passed, reason = prove_temporal_bound(parse_temporal_spec(row), contract)
    assert passed is expected, reason


@pytest.mark.parametrize("bound,expected", [("32/5", True), ("63/10", False)])
def test_api_burst_has_a_bounded_backlog(bound: str, expected: bool) -> None:
    """Burst 6, rate 0.1/ms and service latency 4 ms imply backlog <= 6.4."""
    contract, row = _model((_operation("request"),))
    row["envelopes"][0]["upper"] = _curve([[0, 6]], "1/10")
    row.update(
        expression={"deconvolve": [
            {"arrivals_upper": "request"}, {"service_lower": "request"},
        ]},
        operator="lte",
        bound=bound,
        end_ms=0,
    )
    _assert_result(contract, row, expected)


@pytest.mark.parametrize("deadline_ms,expected", [(24, True), (23, False)])
def test_count_deadline_is_expressed_by_looking_ahead(deadline_ms: int, expected: bool) -> None:
    """D(t+24) >= A(t); identifying individual job deadlines additionally needs FIFO."""
    contract, row = _model((_operation("thumbnail"),))
    row["expression"] = {"subtract": [
        {"advance": [{"departures_lower": "thumbnail"}, deadline_ms]},
        {"arrivals_upper": "thumbnail"},
    ]}
    _assert_result(contract, row, expected)


@pytest.mark.parametrize("window_ms,expected", [(44, True), (43, False)])
def test_every_rolling_window_contains_at_least_two_updates(window_ms: int, expected: bool) -> None:
    """D_lower(t+W)-D_upper(t) bounds completed updates throughout every window."""
    contract, row = _model((_operation("refresh"),))
    row.update(
        expression={"subtract": [
            {"advance": [{"departures_lower": "refresh"}, window_ms]},
            {"departures_upper": "refresh"},
        ]},
        bound=2,
    )
    _assert_result(contract, row, expected)


@pytest.mark.parametrize("recovery_ms,expected", [(49, True), (48, False)])
def test_finite_batch_drains_after_a_bounded_service_outage(recovery_ms: int, expected: bool) -> None:
    """A six-job batch drains after an at-most-20 ms outage and packetization delay."""
    contract, row = _model((_operation("upload"),))
    arrival, service = row["envelopes"]
    arrival.update(
        window="prefix",
        assumption="Six invocations are activated by time 2 ms; the lower bound describes their admitted prefix.",
        lower=_curve([[0, 0], [1, 0], [2, 6]]),
        upper=_curve([[0, 6]]),
    )
    service.update(
        assumption="Every backlogged interval loses at most 20 worker-ms to the outage; remaining service is work-conserving.",
        availability=_curve([[0, 0], [20, 0]], 1),
    )
    row.update(
        expression={"subtract": [
            {"arrivals_upper": "upload"}, {"departures_lower": "upload"},
        ]},
        operator="lte",
        start_ms=recovery_ms,
    )
    _assert_result(contract, row, expected)


@pytest.mark.parametrize("bound,expected", [("83/5", True), ("167/10", False)])
def test_two_request_sources_feed_one_shared_writer(bound: str, expected: bool) -> None:
    """Alternative producers merge through bounded routing into one serialized writer."""
    first, second, writer = _operation("interactive"), _operation("scheduled"), _operation("write", cost_ms=1)
    writer = replace(
        writer,
        depends_on=(first.id, second.id),
        typed_dependencies=(
            TypedDependency(first.id, "Completed", alternative_group="requests"),
            TypedDependency(second.id, "Completed", alternative_group="requests"),
        ),
    )
    contract, row = _model((first, second, writer))
    row["envelopes"] = [item for item in row["envelopes"] if item["id"] != "write-arrivals"]
    row["flows"][-1]["input"] = {"merge": [
        {
            "task": task.id,
            "delay_ms": 2,
            "assumption": "Each Completed result activates the writer exactly once within 2 ms.",
            "horizon_ms": None,
            "failure_probability_upper": 0,
        }
        for task in (first, second)
    ]}
    row.update(bound=bound, start_ms=100, end_ms=100)
    _assert_result(contract, row, expected)
