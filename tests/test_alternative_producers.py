from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Callable

import pytest

from dagcert import (
    Contract, ContractError, EvidenceError, EvidenceRecorder, ExternalContract,
    ExternalEvidenceMonitor, ExternalProvider, Resource, Task, TaskErrorBudget,
    TaskOutcome, Timing, Worker, analyze_contract, load_contract, load_evidence,
)
from dagcert.runtime import ExternalBoundaryEvent
from dagcert.certificate import external_source_contracts
from dagcert.contract import TypedDependency, dependencies_satisfied


def _write_project(root: Path) -> Path:
    (root / "app.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\nclass Request:\n    value: str\n\n"
        "@dataclass(frozen=True)\nclass Produced:\n    value: str\n\n"
        "@dataclass(frozen=True)\nclass Consumed:\n    value: str\n\n"
        "@operation\ndef startup(request: Request) -> Produced:\n"
        "    return Produced(request.value)\n\n"
        "@operation\ndef submitted(request: Request) -> Produced:\n"
        "    return Produced(request.value)\n\n"
        "@operation\ndef consume(request: Produced) -> Consumed:\n"
        "    return Consumed(request.value)\n",
        encoding="utf-8",
    )
    def task(
        identifier: str, symbol: str, outcome: str,
        dependencies: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
        "id": identifier,
        "role": "operation",
        "worker": "worker",
        "implementation": {"language": "python", "path": "app.py", "symbol": symbol},
        "outcomes": [{"type": outcome, "resources": {}, "metadata": {}}],
        "error_budget": None,
        "external_contract": None,
        "start_resources": {},
        "depends_on": dependencies,
        "timings": {
            "call": {
                "metric": "duration", "upper_ms": 10, "evidence": "assumed",
                "minimum_samples": 0, "policy": "max", "safety_factor": 1,
            }
        },
        }
    contract = {
        "schema": "dagcert-contract/v10",
        "workers": [{"id": "worker", "concurrency": 2}],
        "resources": [{"id": "worker-slot", "capacity": 2, "initial": 2}],
        "tasks": [
            task("startup", "startup", "Produced", []),
            task("submitted", "submitted", "Produced", []),
            task("consume", "consume", "Consumed", [
                {
                    "task": "startup", "outcome_type": "Produced",
                    "alternative_group": "request-source",
                },
                {
                    "task": "submitted", "outcome_type": "Produced",
                    "alternative_group": "request-source",
                },
            ]),
        ],
        "channels": [],
        "external_handoffs": [],
        "compositions": [],
        "state_claims": [],
        "metadata": {},
    }
    path = root / "dag_contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return path


def test_one_of_producers_reaches_consumer_without_conjoining_call_sites(
    tmp_path: Path,
) -> None:
    path = _write_project(tmp_path)
    contract = load_contract(path, source_root=tmp_path)

    assert contract.topological_tasks() == ("startup", "submitted", "consume")
    report = analyze_contract(contract, (), source_fingerprint="f" * 64)
    assert report.passed
    assert "consume" in report.structural_progress.must_reachable_tasks


def test_ungrouped_edges_and_distinct_alternative_groups_remain_conjunctive() -> None:
    required_join = Task(
        "join", "worker", "JoinInput", "Joined",
        typed_dependencies=(
            TypedDependency("left", "Left", "left"),
            TypedDependency("right", "Right", "right"),
        ),
    )
    assert not dependencies_satisfied(required_join, {"left"})
    assert dependencies_satisfied(required_join, {"left", "right"})

    grouped_join = Task(
        "grouped-join", "worker", "JoinInput", "Joined",
        typed_dependencies=(
            TypedDependency("left-a", "Left", "left", "left-source"),
            TypedDependency("left-b", "Left", "left", "left-source"),
            TypedDependency("right-a", "Right", "right", "right-source"),
            TypedDependency("right-b", "Right", "right", "right-source"),
        ),
    )
    assert not dependencies_satisfied(grouped_join, {"left-a"})
    assert dependencies_satisfied(grouped_join, {"left-a", "right-b"})


def test_one_reachable_alternative_breaks_a_false_dependency_cycle(tmp_path: Path) -> None:
    path = _write_project(tmp_path)
    app = tmp_path / "app.py"
    app.write_text(
        app.read_text(encoding="utf-8")
        + "\n@operation\ndef recycle(request: Consumed) -> Produced:\n"
        "    return Produced(request.value)\n",
        encoding="utf-8",
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    recycle = dict(raw["tasks"][0])
    recycle["id"] = "recycle"
    recycle["implementation"] = {
        "language": "python", "path": "app.py", "symbol": "recycle",
    }
    recycle["depends_on"] = [
        {"task": "consume", "outcome_type": "Consumed"}
    ]
    raw["tasks"].append(recycle)
    raw["tasks"][2]["depends_on"][0]["task"] = "recycle"
    path.write_text(json.dumps(raw), encoding="utf-8")

    contract = load_contract(path, source_root=tmp_path)
    order = contract.topological_tasks()
    assert order.index("submitted") < order.index("consume") < order.index("recycle")


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda raw: raw["tasks"][2]["depends_on"].pop(), "at least two producer edges"),
        (
            lambda raw: raw["tasks"][2]["depends_on"][1].update(input_field="other"),
            "exactly one input slot",
        ),
        (
            lambda raw: raw["tasks"][2]["depends_on"].append(
                {"task": "startup", "outcome_type": "Produced"}
            ),
            "mixes required and alternative",
        ),
    ],
)
def test_malformed_alternative_groups_fail_closed(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], message: str,
) -> None:
    path = _write_project(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    mutation(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match=message):
        load_contract(path, source_root=tmp_path)


@dataclass(frozen=True)
class _ExternalResult:
    value: str


def _aliased_external_contract() -> Contract:
    external = ExternalContract(
        "provider_contract.py", "provider returns the declared value",
        ExternalProvider("provider", ("read",)), "_ExternalResult", "call",
        "provider.read",
    )
    tasks = tuple(
        Task(
            task_id, "worker", "Request",
            "_ExternalResult | dagcert.runtime.ExternalRaised | dagcert.runtime.ExternalTypeViolation",
            timings={"call": Timing("duration", upper_ms=10, minimum_samples=1)},
            role="external",
            outcomes=(
                TaskOutcome("_ExternalResult"),
                TaskOutcome("dagcert.runtime.ExternalRaised"),
                TaskOutcome("dagcert.runtime.ExternalTypeViolation"),
            ),
            error_budget=TaskErrorBudget(
                "engineering_assumption", "call", ("_ExternalResult",), 0, 1,
            ),
            external_contract=external,
        )
        for task_id in ("startup.provider.read", "refresh.provider.read")
    )
    return Contract(
        "dagcert-contract/v10", (Worker("worker", 1),), tasks,
        (Resource("slot", 1, 1),),
    )


def test_contextual_external_tasks_retain_canonical_boundary_identity(
    tmp_path: Path,
) -> None:
    contract = _aliased_external_contract()
    evidence_path = tmp_path / "evidence.jsonl"
    monitor = ExternalEvidenceMonitor(
        contract, EvidenceRecorder(evidence_path), source_fingerprint="f" * 64,
    )
    event = ExternalBoundaryEvent(
        boundary_id="provider.read", elapsed_ms=1.0,
        outcome_type="_ExternalResult", succeeded=True, recorded_at=1.0,
        expected_type="_ExternalResult", observed_type="_ExternalResult",
    )

    with pytest.raises(EvidenceError, match="task_context"):
        monitor(event)
    with monitor.task_context("startup.provider.read"):
        monitor(event)
    sample = load_evidence(evidence_path)[0]
    assert sample.task_id == "startup.provider.read"
    assert sample.boundary_id == "provider.read"

    wrong = ExternalBoundaryEvent(
        boundary_id="other.read", elapsed_ms=1.0,
        outcome_type="_ExternalResult", succeeded=True, recorded_at=1.0,
        expected_type="_ExternalResult", observed_type="_ExternalResult",
    )
    with pytest.raises(EvidenceError, match="binds canonical boundary"):
        monitor.record_for_task("startup.provider.read", wrong)


def test_v10_external_evidence_with_wrong_boundary_is_not_usable(tmp_path: Path) -> None:
    contract = _aliased_external_contract()
    from dagcert import TimingSample

    sample = TimingSample(
        "startup.provider.read", "call", 1, "worker", "f" * 64,
        boundary_id="other.read", outcome_type="_ExternalResult",
    )
    report = analyze_contract(contract, (sample,), source_fingerprint="f" * 64)
    assert not report.passed
    assert any(finding.code == "wrong-external-boundary" for finding in report.findings)


def test_v10_contextual_external_tasks_bind_one_real_source_boundary(
    tmp_path: Path,
) -> None:
    (tmp_path / "adapter.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import external_boundary\n\n"
        "@dataclass(frozen=True)\nclass ReadRequest:\n    key: str\n\n"
        "@dataclass(frozen=True)\nclass ReadValue:\n    value: str\n\n"
        "@external_boundary('provider.read')\n"
        "def read(request: ReadRequest) -> ReadValue:\n"
        "    return ReadValue(request.key)\n",
        encoding="utf-8",
    )
    (tmp_path / "adapter_contract.py").write_text(
        "from dataclasses import dataclass\n"
        "from nagini_contracts.contracts import ContractOnly, Ensures, Result\n\n"
        "@dataclass(frozen=True)\nclass ReadRequest:\n    key: str\n\n"
        "@dataclass(frozen=True)\nclass ReadValue:\n    value: str\n\n"
        "@ContractOnly\ndef read(request: ReadRequest) -> ReadValue:\n"
        "    Ensures(Result() is not None)\n",
        encoding="utf-8",
    )
    external = {
        "boundary_id": "provider.read",
        "stub_path": "adapter_contract.py",
        "assumption": "provider read returns the declared value",
        "provider": {"module": "provider", "symbols": ["read"]},
        "success_outcome": "ReadValue",
        "evidence_case": "call",
    }
    task = {
        "role": "external",
        "worker": "worker",
        "implementation": {"language": "python", "path": "adapter.py", "symbol": "read"},
        "outcomes": [
            {"type": "ReadValue", "resources": {}, "metadata": {}},
            {"type": "dagcert.runtime.ExternalRaised", "resources": {}, "metadata": {}},
            {
                "type": "dagcert.runtime.ExternalTypeViolation",
                "resources": {}, "metadata": {},
            },
        ],
        "error_budget": {
            "basis": "engineering_assumption", "evidence_case": "call",
            "good_outcomes": ["ReadValue"], "bad_event_probability_upper": 0,
            "minimum_observations": 1,
        },
        "external_contract": external,
        "start_resources": {},
        "depends_on": [],
        "timings": {
            "call": {"metric": "duration", "upper_ms": 10, "minimum_samples": 1}
        },
    }
    contract_path = tmp_path / "external.json"
    contract_path.write_text(json.dumps({
        "schema": "dagcert-contract/v10",
        "workers": [{"id": "worker", "concurrency": 1}],
        "resources": [{"id": "slot", "capacity": 1, "initial": 1}],
        "tasks": [
            {"id": "startup.provider.read", **task},
            {"id": "refresh.provider.read", **task},
        ],
        "channels": [], "external_handoffs": [], "compositions": [],
        "state_claims": [], "metadata": {},
    }), encoding="utf-8")

    contract = load_contract(contract_path, source_root=tmp_path)
    assert all(item.external_contract is not None for item in contract.tasks)
    assert [
        item.external_contract.boundary_id
        for item in contract.tasks
        if item.external_contract is not None
    ] == ["provider.read", "provider.read"]
    bindings = external_source_contracts(contract)
    assert len(bindings) == 1
    assert bindings[0].boundary_id == "provider.read"
