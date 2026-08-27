from __future__ import annotations

from pathlib import Path
import json

import pytest

from dagcert import CertificateError, ContractError, TimingSample, UnhandledException, analyze_contract, issue_certificate, load_contract, load_evidence, operation


def _contract(project: dict[str, object]) -> dict[str, object]:
    return json.loads(Path(project["contract"]).read_text(encoding="utf-8"))


def test_v4_contract_cannot_restate_or_invent_task_types(project, tmp_path: Path):
    raw = _contract(project)
    raw["tasks"][0]["output_type"] = "PretendSuccess"  # type: ignore[index]
    path = tmp_path / "invented-type.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="unexpected"):
        load_contract(path, source_root=project["root"])


def test_contract_must_cover_the_real_closed_return_union(project):
    source = Path(project["root"]) / "app.py"
    text = source.read_text(encoding="utf-8")
    text = text.replace(
        "@operation\ndef work",
        "@dataclass(frozen=True)\nclass WorkFailed:\n    reason: str\n\n@operation\ndef work",
    ).replace("-> WorkCompleted:", "-> WorkCompleted | WorkFailed:")
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="exactly match source return union"):
        load_contract(project["contract"], source_root=project["root"])


def test_any_is_not_a_certifiable_task_boundary(project):
    source = Path(project["root"]) / "app.py"
    text = source.read_text(encoding="utf-8").replace(
        "from dataclasses import dataclass", "from dataclasses import dataclass\nfrom typing import Any"
    ).replace("request: WorkInput", "request: Any")
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="must not contain Any"):
        load_contract(project["contract"], source_root=project["root"])


def test_async_boundary_is_rejected_until_its_exception_effect_is_guarded(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace("def work(", "async def work("),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="currently certifies only synchronous"):
        load_contract(project["contract"], source_root=project["root"])


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "return WorkCompleted(request.value + 1)",
            "return 'wrong'  # type: ignore[return-value]",
            "type-check suppression",
        ),
        (
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\nfrom typing import cast",
            "uses typing.cast",
        ),
    ],
)
def test_bound_source_cannot_override_the_checker(project, old: str, new: str, message: str):
    source = Path(project["root"]) / "app.py"
    text = source.read_text(encoding="utf-8").replace(old, new)
    if "typing import cast" in new:
        text = text.replace(
            "return WorkCompleted(request.value + 1)",
            "return cast(WorkCompleted, 'wrong')",
        )
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match=message):
        load_contract(project["contract"], source_root=project["root"])


def test_task_variant_fields_cannot_hide_any(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\nfrom typing import Any",
        ).replace("class WorkCompleted:\n    value: int", "class WorkCompleted:\n    value: Any"),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="field must not contain Any"):
        load_contract(project["contract"], source_root=project["root"])


def test_certificate_runs_static_checker_over_real_function_body(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "return WorkCompleted(request.value + 1)", "return 'not a WorkCompleted'"
        ),
        encoding="utf-8",
    )
    with pytest.raises(CertificateError, match="failed strict mypy"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


def test_runtime_boundary_turns_exception_into_kernel_owned_outcome():
    @operation
    def fail(value: int) -> str:
        raise RuntimeError(f"bad {value}")

    result = fail(3)
    assert isinstance(result, UnhandledException)
    assert result.exception_type == "RuntimeError"


def test_runtime_boundary_also_closes_base_exception_exits():
    @operation
    def fail(value: int) -> str:
        raise KeyboardInterrupt(f"stop {value}")

    result = fail(3)
    assert isinstance(result, UnhandledException)
    assert result.exception_type == "KeyboardInterrupt"


def test_unhandled_exception_evidence_invalidates_analysis(project):
    samples = list(load_evidence(project["evidence"]))
    samples.append(TimingSample(
        task_id="work", case="normal", value_ms=1, worker_id="worker",
        source_fingerprint=project["fingerprint"],
        outcome_type="dagcert.runtime.UnhandledException",
    ))
    report = analyze_contract(
        load_contract(project["contract"]), samples,
        source_fingerprint=project["fingerprint"],
    )
    assert not report.passed
    assert "unhandled-operation-exception" in {item.code for item in report.findings}


def test_guaranteed_effect_is_minimum_across_all_source_outcomes(project, tmp_path: Path):
    raw = _contract(project)
    raw["tasks"][0]["outcomes"][0]["resources"] = {"state": {"produce": 1}}  # type: ignore[index]
    path = tmp_path / "outcome-effects.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    task = load_contract(path, source_root=project["root"]).tasks[0]
    assert task.resources["state"].produce == 1
    assert task.guaranteed_effect("state", "produce") == 0


def test_unhandled_exception_cannot_be_given_fabricated_resource_effects(project, tmp_path: Path):
    raw = _contract(project)
    raw["tasks"][0]["outcomes"][1]["resources"] = {"state": {"produce": 1}}  # type: ignore[index]
    path = tmp_path / "fake-unhandled-effects.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="cannot assign resource effects"):
        load_contract(path, source_root=project["root"])


def test_dependency_edges_must_connect_real_source_types(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert import operation\n\n"
        "@dataclass(frozen=True)\nclass Start:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Produced:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass WrongInput:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Finished:\n    value: int\n\n"
        "@operation\ndef produce(request: Start) -> Produced:\n    return Produced(request.value)\n\n"
        "@operation\ndef consume(request: WrongInput) -> Finished:\n    return Finished(request.value)\n",
        encoding="utf-8",
    )
    contract = {
        "schema": "dagcert-contract/v4",
        "workers": [{"id": "worker", "concurrency": 1}],
        "resources": [],
        "tasks": [
            {
                "id": "produce", "role": "operation", "worker": "worker",
                "implementation": {"language": "python", "path": "app.py", "symbol": "produce"},
                "outcomes": [
                    {"type": "Produced", "resources": {}, "metadata": {}},
                    {"type": "dagcert.runtime.UnhandledException", "resources": {}, "metadata": {}},
                ],
                "depends_on": [],
                "timings": {"duration": {"metric": "duration", "upper_ms": 10, "minimum_samples": 1}},
            },
            {
                "id": "consume", "role": "operation", "worker": "worker",
                "implementation": {"language": "python", "path": "app.py", "symbol": "consume"},
                "outcomes": [
                    {"type": "Finished", "resources": {}, "metadata": {}},
                    {"type": "dagcert.runtime.UnhandledException", "resources": {}, "metadata": {}},
                ],
                "depends_on": [{"task": "produce", "outcome_type": "Produced"}],
                "timings": {"duration": {"metric": "duration", "upper_ms": 10, "minimum_samples": 1}},
            },
        ],
        "compositions": [],
        "metadata": {},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ContractError, match="does not accept typed edge"):
        load_contract(path)


def test_compositions_must_be_real_typed_outcome_paths(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from dataclasses import dataclass\nfrom dagcert import operation\n\n"
        "@dataclass(frozen=True)\nclass Start:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Produced:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Finished:\n    value: int\n\n"
        "@operation\ndef produce(request: Start) -> Produced:\n    return Produced(request.value)\n\n"
        "@operation\ndef consume(request: Produced) -> Finished:\n    return Finished(request.value)\n",
        encoding="utf-8",
    )
    outcomes = lambda name: [  # noqa: E731
        {"type": name, "resources": {}, "metadata": {}},
        {"type": "dagcert.runtime.UnhandledException", "resources": {}, "metadata": {}},
    ]
    raw = {
        "schema": "dagcert-contract/v4",
        "workers": [{"id": "worker", "concurrency": 1}],
        "resources": [],
        "tasks": [
            {
                "id": "produce", "role": "operation", "worker": "worker",
                "implementation": {"language": "python", "path": "app.py", "symbol": "produce"},
                "outcomes": outcomes("Produced"), "depends_on": [],
                "timings": {"duration": {"metric": "duration", "upper_ms": 10, "minimum_samples": 1}},
            },
            {
                "id": "consume", "role": "operation", "worker": "worker",
                "implementation": {"language": "python", "path": "app.py", "symbol": "consume"},
                "outcomes": outcomes("Finished"),
                "depends_on": [{"task": "produce", "outcome_type": "Produced"}],
                "timings": {"duration": {"metric": "duration", "upper_ms": 10, "minimum_samples": 1}},
            },
        ],
        "compositions": [{
            "id": "fake-path",
            "steps": [
                {"task": "produce", "timing": "duration", "count": 1,
                 "outcome_type": "dagcert.runtime.UnhandledException"},
                {"task": "consume", "timing": "duration", "count": 1,
                 "outcome_type": "Finished"},
            ],
            "metadata": {},
        }],
        "metadata": {},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="not a real typed path"):
        load_contract(path)
