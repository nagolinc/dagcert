from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from dagcert.analysis import analyze_contract
from dagcert.contract import (
    CompositionExpression, ContractError, TaskErrorBudget, composition_steps, load_contract,
)
from dagcert.evidence import TimingSample
from dagcert.formula import FormulaError, evaluate_formula
from dagcert.source_types import SourceTypeError, check_python_sources


APP_SOURCE = '''from dataclasses import dataclass

from dagcert.runtime import operation

@dataclass(frozen=True)
class Input:
    value: str

@dataclass(frozen=True)
class Prepared:
    value: str

@dataclass(frozen=True)
class Validated:
    value: str

@dataclass(frozen=True)
class Checksummed:
    value: str

@dataclass(frozen=True)
class ChecksumAfterValidationInput:
    prepared: Prepared
    validation: Validated

@dataclass(frozen=True)
class JoinInput:
    validation: Validated
    checksum: Checksummed

@dataclass(frozen=True)
class Published:
    value: str

@dataclass(frozen=True)
class RawWork:
    value: str

@dataclass(frozen=True)
class PreparedWork:
    value: str

@dataclass(frozen=True)
class Delivered:
    value: str

@operation
def prepare(request: Input) -> Prepared:
    return Prepared(request.value)

@operation
def validate(request: Prepared) -> Validated:
    return Validated(request.value)

@operation
def checksum(request: Prepared) -> Checksummed:
    return Checksummed(request.value)

@operation
def checksum_after_validation(request: ChecksumAfterValidationInput) -> Checksummed:
    return Checksummed(request.prepared.value + request.validation.value)

@operation
def publish(request: JoinInput) -> Published:
    return Published(request.validation.value + request.checksum.value)

@operation
def prepare_work(request: RawWork) -> PreparedWork:
    return PreparedWork(request.value)

@operation
def deliver(request: PreparedWork) -> Delivered:
    return Delivered(request.value)
'''


def _task(
    identifier: str,
    worker: str,
    symbol: str,
    outcome: str,
    duration: int,
    dependencies: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "id": identifier,
        "role": "operation",
        "worker": worker,
        "implementation": {"language": "python", "path": "app.py", "symbol": symbol},
        "outcomes": [{"type": outcome, "resources": {}, "metadata": {}}],
        "error_budget": None,
        "external_contract": None,
        "start_resources": {},
        "depends_on": dependencies,
        "timings": {
            "duration": {
                "metric": "duration",
                "upper_ms": duration + 1,
                "minimum_samples": 1,
                "safety_factor": 1,
            }
        },
    }


def _structured_contract(tmp_path: Path, *, shared_branch_worker: bool = False):
    (tmp_path / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    branch_workers = ("branch", "branch") if shared_branch_worker else ("validator", "hasher")
    workers = sorted({"preparer", "publisher", *branch_workers})
    raw = {
        "schema": "dagcert-contract/v7",
        "workers": [{"id": worker, "concurrency": 1} for worker in workers],
        "resources": [],
        "tasks": [
            _task("prepare", "preparer", "prepare", "Prepared", 5, []),
            _task(
                "validate", branch_workers[0], "validate", "Validated", 10,
                [{"task": "prepare", "outcome_type": "Prepared"}],
            ),
            _task(
                "checksum", branch_workers[1], "checksum", "Checksummed", 20,
                [{"task": "prepare", "outcome_type": "Prepared"}],
            ),
            _task(
                "publish", "publisher", "publish", "Published", 3,
                [
                    {
                        "task": "validate",
                        "outcome_type": "Validated",
                        "input_field": "validation",
                    },
                    {
                        "task": "checksum",
                        "outcome_type": "Checksummed",
                        "input_field": "checksum",
                    },
                ],
            ),
        ],
        "compositions": [{
            "id": "publish-one",
            "expression": {
                "kind": "sequence",
                "children": [
                    {
                        "kind": "leaf", "task": "prepare", "timing": "duration",
                        "outcome_type": "Prepared",
                    },
                    {
                        "kind": "parallel_all",
                        "children": [
                            {
                                "kind": "leaf", "task": "validate",
                                "timing": "duration", "outcome_type": "Validated",
                            },
                            {
                                "kind": "leaf", "task": "checksum",
                                "timing": "duration", "outcome_type": "Checksummed",
                            },
                        ],
                    },
                    {
                        "kind": "leaf", "task": "publish", "timing": "duration",
                        "outcome_type": "Published",
                    },
                ],
            },
            "metadata": {},
        }],
        "state_claims": [],
        "metadata": {},
    }
    path = tmp_path / "dag_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    contract = load_contract(path, source_root=tmp_path)
    fingerprint = "f" * 64
    samples = tuple(
        TimingSample(
            task_id=task_id,
            case="duration",
            value_ms=value,
            worker_id=contract.task_by_id[task_id].worker,
            source_fingerprint=fingerprint,
            outcome_type=outcome,
        )
        for task_id, value, outcome in (
            ("prepare", 5, "Prepared"),
            ("validate", 10, "Validated"),
            ("checksum", 20, "Checksummed"),
            ("publish", 3, "Published"),
        )
    )
    return contract, analyze_contract(contract, samples, source_fingerprint=fingerprint)


def test_parallel_all_uses_max_for_disjoint_workers_and_real_join_fields(tmp_path: Path):
    contract, analysis = _structured_contract(tmp_path)

    evaluation = evaluate_formula(
        {"eq": [{"composition_upper_ms": "composition:publish-one"}, 28]},
        contract,
        analysis,
    )

    assert analysis.passed
    assert evaluation.passed


def test_parallel_all_serializes_when_worker_capacity_does_not_allow_overlap(
    tmp_path: Path,
):
    contract, analysis = _structured_contract(tmp_path, shared_branch_worker=True)

    evaluation = evaluate_formula(
        {"eq": [{"composition_upper_ms": "composition:publish-one"}, 38]},
        contract,
        analysis,
    )

    assert evaluation.passed


def test_finite_repeat_multiplies_parallel_union_bound_without_independence(
    tmp_path: Path,
):
    contract, _ = _structured_contract(tmp_path)
    budget_by_task = {"validate": 0.01, "checksum": 0.02}
    tasks = tuple(
        replace(
            task,
            error_budget=TaskErrorBudget(
                "engineering_assumption",
                "duration",
                (task.outcomes[0].type,),
                budget_by_task[task.id],
                1,
            ),
        )
        if task.id in budget_by_task
        else task
        for task in contract.tasks
    )
    composition = contract.compositions[0]
    assert composition.expression is not None
    repeated = CompositionExpression(
        "finite_repeat", children=(composition.expression,), count=10,
    )
    contract = replace(
        contract,
        tasks=tasks,
        compositions=(
            replace(composition, expression=repeated, steps=composition_steps(repeated)),
        ),
    )
    fingerprint = "f" * 64
    samples = tuple(
        TimingSample(
            task_id=task_id,
            case="duration",
            value_ms=value,
            worker_id=contract.task_by_id[task_id].worker,
            source_fingerprint=fingerprint,
            outcome_type=outcome,
        )
        for task_id, value, outcome in (
            ("prepare", 5, "Prepared"),
            ("validate", 10, "Validated"),
            ("checksum", 20, "Checksummed"),
            ("publish", 3, "Published"),
        )
    )
    analysis = analyze_contract(contract, samples, source_fingerprint=fingerprint)

    assert evaluate_formula(
        {"eq": [{"composition_upper_ms": "composition:publish-one"}, 280]},
        contract,
        analysis,
    ).passed
    assert evaluate_formula(
        {
            "eq": [
                {
                    "composition_failure_probability_upper":
                        "composition:publish-one"
                },
                0.3,
            ]
        },
        contract,
        analysis,
    ).passed


def test_join_dependency_must_match_the_real_source_input_field(tmp_path: Path):
    _structured_contract(tmp_path)
    path = tmp_path / "dag_contract.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    publish = next(task for task in raw["tasks"] if task["id"] == "publish")
    publish["depends_on"][0]["input_field"] = "checksum"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="expects 'Checksummed', not 'Validated'"):
        load_contract(path, source_root=tmp_path)


def test_structured_workflow_rejects_a_missing_parallel_join_edge(tmp_path: Path):
    _structured_contract(tmp_path)
    path = tmp_path / "dag_contract.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    publish = next(task for task in raw["tasks"] if task["id"] == "publish")
    publish["depends_on"] = publish["depends_on"][:1]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="does not feed publish"):
        load_contract(path, source_root=tmp_path)


def test_parallel_all_rejects_a_hidden_cross_branch_dependency(tmp_path: Path):
    _structured_contract(tmp_path)
    path = tmp_path / "dag_contract.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    checksum = next(task for task in raw["tasks"] if task["id"] == "checksum")
    checksum["implementation"]["symbol"] = "checksum_after_validation"
    checksum["depends_on"] = [
        {
            "task": "prepare",
            "outcome_type": "Prepared",
            "input_field": "prepared",
        },
        {
            "task": "validate",
            "outcome_type": "Validated",
            "input_field": "validation",
        },
    ]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="parallel_all branches are not independent"):
        load_contract(path, source_root=tmp_path)


def test_state_claim_failure_reports_a_counterexample_trace(tmp_path: Path):
    contract, analysis = _structured_contract(tmp_path)
    raw = json.loads((tmp_path / "dag_contract.json").read_text(encoding="utf-8"))
    raw["resources"] = [{"id": "slots", "capacity": 2, "initial": 1}]
    raw["state_claims"] = [{
        "id": "slots-conserved",
        "kind": "linear_invariant",
        "expression": {"slots": 1},
        "operator": "eq",
        "bound": 1,
        "metadata": {},
    }]
    raw["tasks"][0]["start_resources"] = {"slots": {"consume": 1}}
    path = tmp_path / "state_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    contract = load_contract(path, source_root=tmp_path)
    samples = tuple(
        TimingSample(
            task_id=sample.task_id,
            case=sample.case,
            value_ms=sample.value_ms,
            worker_id=sample.worker_id,
            source_fingerprint="f" * 64,
            outcome_type=sample.outcome_type,
            start_resource_consumed={"slots": 1} if sample.task_id == "prepare" else {},
        )
        for sample in (
            TimingSample("prepare", "duration", 5, "preparer", "f" * 64, outcome_type="Prepared"),
            TimingSample("validate", "duration", 10, "validator", "f" * 64, outcome_type="Validated"),
            TimingSample("checksum", "duration", 20, "hasher", "f" * 64, outcome_type="Checksummed"),
            TimingSample("publish", "duration", 3, "publisher", "f" * 64, outcome_type="Published"),
        )
    )
    analysis = analyze_contract(contract, samples, source_fingerprint="f" * 64)

    with pytest.raises(FormulaError, match="counterexample:.*start:prepare"):
        evaluate_formula(
            {"eq": [{"state_claim_proved": "state-claim:slots-conserved"}, 1]},
            contract,
            analysis,
        )


def _flow_contract(tmp_path: Path, *, producer_ms: int = 9):
    (tmp_path / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    raw = {
        "schema": "dagcert-contract/v7",
        "workers": [
            {"id": "producer", "concurrency": 2},
            {"id": "consumer", "concurrency": 1},
        ],
        "resources": [
            {"id": "free", "capacity": 5, "initial": 3},
            {"id": "preparing", "capacity": 5, "initial": 0},
            {"id": "ready", "capacity": 5, "initial": 2},
            {"id": "running", "capacity": 5, "initial": 0},
        ],
        "tasks": [
            {
                "id": "prepare", "role": "operation", "worker": "producer",
                "implementation": {
                    "language": "python", "path": "app.py", "symbol": "prepare_work",
                },
                "outcomes": [{
                    "type": "PreparedWork",
                    "resources": {
                        "preparing": {"consume": 1}, "ready": {"produce": 1},
                    },
                    "metadata": {},
                }],
                "error_budget": None, "external_contract": None,
                "start_resources": {
                    "free": {"consume": 1}, "preparing": {"produce": 1},
                },
                "depends_on": [],
                "timings": {"duration": {
                    "metric": "duration", "upper_ms": producer_ms + 1,
                    "minimum_samples": 1, "safety_factor": 1,
                }},
            },
            {
                "id": "deliver", "role": "operation", "worker": "consumer",
                "implementation": {
                    "language": "python", "path": "app.py", "symbol": "deliver",
                },
                "outcomes": [{
                    "type": "Delivered",
                    "resources": {
                        "running": {"consume": 1}, "free": {"produce": 1},
                    },
                    "metadata": {},
                }],
                "error_budget": None, "external_contract": None,
                "start_resources": {
                    "ready": {"consume": 1}, "running": {"produce": 1},
                },
                "depends_on": [
                    {"task": "prepare", "outcome_type": "PreparedWork"},
                ],
                "timings": {
                    "duration": {
                        "metric": "duration", "lower_ms": 8, "upper_ms": 20,
                        "minimum_samples": 1, "safety_factor": 1,
                    },
                    "dispatch": {
                        "metric": "wait", "upper_ms": 5,
                        "minimum_samples": 1, "safety_factor": 1,
                    },
                },
            },
        ],
        "compositions": [{
            "id": "one-job",
            "expression": {
                "kind": "sequence",
                "children": [
                    {
                        "kind": "leaf", "task": "prepare", "timing": "duration",
                        "outcome_type": "PreparedWork",
                    },
                    {
                        "kind": "leaf", "task": "deliver", "timing": "duration",
                        "outcome_type": "Delivered",
                    },
                ],
            },
            "metadata": {},
        }],
        "state_claims": [
            {
                "id": "slots-conserved", "kind": "linear_invariant",
                "expression": {"free": 1, "preparing": 1, "ready": 1, "running": 1},
                "operator": "eq", "bound": 5, "metadata": {},
            },
            {
                "id": "work-remains", "kind": "bounded_non_starvation",
                "inventory_resources": ["ready", "running"],
                "producer": {"task": "prepare", "timing": "duration"},
                "consumer": {"task": "deliver", "timing": "duration"},
                "horizon": 5, "metadata": {},
            },
            {
                "id": "dispatch-bounded", "kind": "bounded_response",
                "trigger_resource": "ready", "response_task": "deliver",
                "response_timing": "dispatch", "upper_ms": 5, "metadata": {},
            },
        ],
        "metadata": {},
    }
    path = tmp_path / "flow_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    contract = load_contract(path, source_root=tmp_path)
    fingerprint = "a" * 64
    samples = (
        TimingSample(
            "prepare", "duration", producer_ms, "producer", fingerprint,
            outcome_type="PreparedWork",
            start_resource_consumed={"free": 1},
            start_resource_produced={"preparing": 1},
            resource_consumed={"preparing": 1},
            resource_produced={"ready": 1},
        ),
        TimingSample(
            "deliver", "duration", 9, "consumer", fingerprint,
            outcome_type="Delivered",
            start_resource_consumed={"ready": 1},
            start_resource_produced={"running": 1},
            resource_consumed={"running": 1},
            resource_produced={"free": 1},
        ),
        TimingSample(
            "deliver", "dispatch", 2, "consumer", fingerprint,
            outcome_type="Delivered",
        ),
    )
    return contract, analyze_contract(contract, samples, source_fingerprint=fingerprint)


def test_lifecycle_conservation_non_starvation_and_dispatch_are_kernel_proofs(
    tmp_path: Path,
):
    contract, analysis = _flow_contract(tmp_path)

    for claim_id in ("slots-conserved", "work-remains", "dispatch-bounded"):
        evaluation = evaluate_formula(
            {"eq": [{"state_claim_proved": f"state-claim:{claim_id}"}, 1]},
            contract,
            analysis,
        )
        assert evaluation.passed


def test_non_starvation_refuses_when_the_timing_envelope_drains_the_buffer(
    tmp_path: Path,
):
    contract, analysis = _flow_contract(tmp_path, producer_ms=30)

    with pytest.raises(FormulaError, match="remaining_inventory=0"):
        evaluate_formula(
            {"eq": [{"state_claim_proved": "state-claim:work-remains"}, 1]},
            contract,
            analysis,
        )


def test_typescript_leaf_uses_a_backend_checked_interface_and_nagini_refuses_it(
    tmp_path: Path,
):
    (tmp_path / "present.ts").write_text(
        "export function present(value: string): string { return value; }\n",
        encoding="utf-8",
    )
    raw = {
        "schema": "dagcert-contract/v7",
        "workers": [{"id": "browser", "concurrency": 1}],
        "resources": [],
        "tasks": [{
            "id": "present", "role": "operation", "worker": "browser",
            "implementation": {
                "language": "typescript", "path": "present.ts", "symbol": "present",
            },
            "verified_interface": {
                "execution": "synchronous",
                "parameters": [{"name": "value", "type": "string"}],
                "return_type": "string",
            },
            "outcomes": [{"type": "string", "resources": {}, "metadata": {}}],
            "error_budget": None, "external_contract": None,
            "start_resources": {}, "depends_on": [],
            "timings": {"duration": {
                "metric": "duration", "upper_ms": 10,
                "minimum_samples": 1, "safety_factor": 1,
            }},
        }],
        "compositions": [], "state_claims": [], "metadata": {},
    }
    path = tmp_path / "typescript_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    contract = load_contract(path, source_root=tmp_path)
    signature = contract.tasks[0].source_signature

    assert signature is not None
    assert signature.language == "typescript"
    assert signature.input_fields == (("value", "string"),)
    assert contract.tasks[0].input_type == "string"
    with pytest.raises(SourceTypeError, match="require the explicit Maledictus backend"):
        check_python_sources(
            tmp_path,
            (signature,),
            source_fingerprint="f" * 64,
            proof_signatures=(signature,),
        )


def test_typescript_leaf_preserves_multi_parameter_interface_and_field_edges(
    tmp_path: Path,
):
    (tmp_path / "decision.ts").write_text(
        "export function seedText(value: string): string { return value; }\n"
        "export function seedNumber(value: number): number { return value; }\n"
        "export function decide(\n"
        "  left: string, right: string, limit: number, enabled: boolean\n"
        "): boolean { return enabled && left === right && limit > 0; }\n",
        encoding="utf-8",
    )

    def task(
        identifier: str,
        symbol: str,
        parameters: list[dict[str, str]],
        return_type: str,
        dependencies: list[dict[str, str]],
    ) -> dict[str, object]:
        return {
            "id": identifier,
            "role": "operation",
            "worker": "application",
            "implementation": {
                "language": "typescript",
                "path": "decision.ts",
                "symbol": symbol,
            },
            "verified_interface": {
                "execution": "synchronous",
                "parameters": parameters,
                "return_type": return_type,
            },
            "outcomes": [{"type": return_type, "resources": {}, "metadata": {}}],
            "error_budget": None,
            "external_contract": None,
            "start_resources": {},
            "depends_on": dependencies,
            "timings": {
                "duration": {
                    "metric": "duration",
                    "upper_ms": 10,
                    "minimum_samples": 1,
                    "safety_factor": 1,
                }
            },
        }

    raw = {
        "schema": "dagcert-contract/v7",
        "workers": [{"id": "application", "concurrency": 1}],
        "resources": [],
        "tasks": [
            task(
                "seed-text",
                "seedText",
                [{"name": "value", "type": "string"}],
                "string",
                [],
            ),
            task(
                "seed-number",
                "seedNumber",
                [{"name": "value", "type": "number"}],
                "number",
                [],
            ),
            task(
                "decide",
                "decide",
                [
                    {"name": "left", "type": "string"},
                    {"name": "right", "type": "string"},
                    {"name": "limit", "type": "number"},
                    {"name": "enabled", "type": "boolean"},
                ],
                "boolean",
                [
                    {
                        "task": "seed-text",
                        "outcome_type": "string",
                        "input_field": "left",
                    },
                    {
                        "task": "seed-text",
                        "outcome_type": "string",
                        "input_field": "right",
                    },
                    {
                        "task": "seed-number",
                        "outcome_type": "number",
                        "input_field": "limit",
                    },
                ],
            ),
        ],
        "compositions": [],
        "state_claims": [],
        "metadata": {},
    }
    path = tmp_path / "multi_input_typescript_contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    contract = load_contract(path, source_root=tmp_path)
    decision = contract.task_by_id["decide"]

    assert decision.source_signature is not None
    assert decision.source_signature.input_fields == (
        ("left", "string"),
        ("right", "string"),
        ("limit", "number"),
        ("enabled", "boolean"),
    )
    assert decision.depends_on == ("seed-text", "seed-number")
    assert len(decision.typed_dependencies) == 3

    raw["tasks"][2]["depends_on"][0].pop("input_field")
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="multi-parameter verified interface"):
        load_contract(path, source_root=tmp_path)
