from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import json
import os
import sys

import pytest
from mypy import api as mypy_api

from dagcert import CertificateError, ContractError, TimingSample, analyze_contract, issue_certificate, load_contract, load_evidence, operation
from dagcert.source_types import SourceSignature, check_python_sources


@dataclass(frozen=True)
class RuntimeInput:
    value: int


@dataclass(frozen=True)
class RuntimeOutcome:
    value: int


def test_pytyped_public_api_is_visible_to_standard_strict_mypy(tmp_path: Path):
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from dagcert import CheckContext, Contract, issue_certificate\n\n"
        "def keep_types(context: CheckContext, contract: Contract) -> tuple[CheckContext, Contract]:\n"
        "    return context, contract\n\n"
        "ISSUER = issue_certificate\n",
        encoding="utf-8",
    )
    stdout, stderr, status = mypy_api.run([
        str(consumer), "--strict", "--no-incremental", "--python-executable", sys.executable,
    ])
    assert status == 0, "\n".join(item for item in (stdout, stderr) if item)


def test_source_checker_keeps_bundled_stubs_out_of_an_in_tree_venv(
    tmp_path: Path, monkeypatch,
):
    root = tmp_path / "application"
    site_packages = root / ".venv" / "Lib" / "site-packages"
    installed_package = site_packages / "dagcert"
    bundled_stubs = installed_package / "mypy_stubs" / "dagcert"
    bundled_stubs.mkdir(parents=True)
    (bundled_stubs / "__init__.pyi").write_text(
        "from .runtime import operation as operation\n", encoding="utf-8",
    )
    (bundled_stubs / "runtime.pyi").write_text(
        "def operation(function): ...\n", encoding="utf-8",
    )
    root.mkdir(exist_ok=True)
    (root / "app.py").write_text("def work(value: int) -> int:\n    return value\n")
    nested_python = root / ".venv" / "Scripts" / "python.exe"
    captured: dict[str, object] = {}

    def fake_mypy_run(arguments):
        mypy_path = os.environ["MYPYPATH"].split(os.pathsep)
        captured["arguments"] = arguments
        captured["mypy_path"] = mypy_path
        captured["stub"] = (
            Path(mypy_path[0]) / "dagcert" / "runtime.pyi"
        ).read_text(encoding="utf-8")
        assert Path(mypy_path[0]).is_dir()
        return "", "", 0

    monkeypatch.setattr("dagcert.source_types.__file__", installed_package / "source_types.py")
    monkeypatch.setattr("dagcert.source_types.sys.executable", str(nested_python))
    monkeypatch.setattr("mypy.api.run", fake_mypy_run)

    result = check_python_sources(
        root,
        [
            SourceSignature(
                language="python", path="app.py", symbol="work",
                input_type="int", outcome_types=("int",), line=1,
            )
        ],
        prove_exceptions=False,
    )

    mypy_path = captured["mypy_path"]
    assert isinstance(mypy_path, list)
    assert str(root.resolve()) in mypy_path
    assert not any(
        Path(item).resolve().is_relative_to((root / ".venv").resolve())
        for item in mypy_path
    )
    assert captured["stub"] == "def operation(function): ...\n"
    arguments = captured["arguments"]
    assert isinstance(arguments, list)
    assert arguments[arguments.index("--python-executable") + 1] == str(nested_python)
    assert result["mode"] == "strict"


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
    with pytest.raises(ContractError, match="current Python provider certifies only synchronous"):
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


def test_local_operation_decorator_cannot_impersonate_dagcert(project):
    source = Path(project["root"]) / "app.py"
    text = source.read_text(encoding="utf-8").replace(
        "from dagcert.runtime import operation",
        "def operation(function):\n    return function",
    )
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="must use @dagcert.runtime.operation"):
        load_contract(project["contract"], source_root=project["root"])


def test_local_dataclass_decorator_cannot_create_fake_variants(project):
    source = Path(project["root"]) / "app.py"
    text = source.read_text(encoding="utf-8").replace(
        "from dataclasses import dataclass",
        "def dataclass(*args, **kwargs):\n"
        "    def decorate(value):\n        return value\n"
        "    return decorate",
    )
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="explicit dataclass variant"):
        load_contract(project["contract"], source_root=project["root"])


@pytest.mark.parametrize("module_name", ["dagcert.py", "dataclasses.py"])
def test_source_tree_cannot_shadow_trusted_decorator_modules(project, module_name: str):
    (Path(project["root"]) / module_name).write_text("# shadow\n", encoding="utf-8")
    with pytest.raises(ContractError, match="is shadowed"):
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


def test_certificate_refuses_a_mypy_clean_unexpected_exception(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "return WorkCompleted(request.value + 1)",
            "return WorkCompleted(10 // request.value)",
        ),
        encoding="utf-8",
    )
    with pytest.raises(CertificateError, match="Nagini could not prove"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


def test_operation_cannot_declare_an_exception_instead_of_an_outcome(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "from dagcert.runtime import operation",
            "from dagcert.runtime import operation\n"
            "from nagini_contracts.contracts import Exsures",
        ).replace(
            "def work(request: WorkInput) -> WorkCompleted:\n",
            "def work(request: WorkInput) -> WorkCompleted:\n"
            "    Exsures(ValueError, lambda error: True)\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="declares Exsures"):
        load_contract(project["contract"], source_root=project["root"])


@pytest.mark.parametrize(
    ("contract_name", "statement", "message"),
    [
        ("Assume", "Assume(False)", "may not introduce trusted axioms"),
        ("Requires", "Requires(False)", "must be total over its complete"),
    ],
)
def test_operation_cannot_make_exception_proof_vacuous_with_nagini_contract(
    project, contract_name: str, statement: str, message: str,
):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "from dagcert.runtime import operation",
            "from dagcert.runtime import operation\n"
            f"from nagini_contracts.contracts import {contract_name}",
        ).replace(
            "def work(request: WorkInput) -> WorkCompleted:\n",
            "def work(request: WorkInput) -> WorkCompleted:\n"
            f"    {statement}\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match=message):
        load_contract(project["contract"], source_root=project["root"])


def test_bound_module_cannot_hide_an_application_helper_behind_contract_only(project):
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "from dagcert.runtime import operation",
            "from dagcert.runtime import operation\n"
            "from nagini_contracts.contracts import ContractOnly\n\n"
            "@ContractOnly\n"
            "def hidden(value: int) -> int:\n"
            "    return value",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="must have a verified executable body"):
        load_contract(project["contract"], source_root=project["root"])


def test_operation_marker_preserves_the_declared_callable_and_exception_channel():
    @operation
    def fail(value: int) -> str:
        raise RuntimeError(f"bad {value}")

    with pytest.raises(RuntimeError, match="bad 3"):
        fail(3)


def test_operation_marker_does_not_hide_base_exception_exits():
    @operation
    def fail(value: int) -> str:
        raise KeyboardInterrupt(f"stop {value}")

    with pytest.raises(KeyboardInterrupt, match="stop 3"):
        fail(3)


def test_runtime_marker_does_not_claim_to_replace_static_verification():
    @operation
    def malformed(request: RuntimeInput) -> RuntimeOutcome:
        return RuntimeOutcome(request.value)

    object.__setattr__(bad_input := RuntimeInput(1), "value", "wrong")
    bad_input_result = malformed(bad_input)
    assert bad_input_result.value == "wrong"

    original = RuntimeOutcome

    @operation
    def malformed_output(request: RuntimeInput) -> RuntimeOutcome:
        result = original(request.value)
        object.__setattr__(result, "value", "wrong")
        return result

    bad_output_result = malformed_output(RuntimeInput(1))
    assert bad_output_result.value == "wrong"


def test_unexpected_exception_sentinel_is_always_fatal(project):
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
    source = Path(project["root"]) / "app.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "@operation\ndef work",
            "@dataclass(frozen=True)\nclass WorkRejected:\n    reason: str\n\n@operation\ndef work",
        ).replace("-> WorkCompleted:", "-> WorkCompleted | WorkRejected:"),
        encoding="utf-8",
    )
    raw = _contract(project)
    raw["tasks"][0]["outcomes"][0]["resources"] = {"state": {"produce": 1}}  # type: ignore[index]
    raw["tasks"][0]["outcomes"].append({  # type: ignore[index]
        "type": "WorkRejected", "resources": {}, "metadata": {},
    })
    path = tmp_path / "outcome-effects.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    task = load_contract(path, source_root=project["root"]).tasks[0]
    assert task.resources["state"].produce == 1
    assert task.guaranteed_effect("state", "produce") == 0


def test_v5_contract_cannot_reintroduce_a_catch_all_exception_outcome(project, tmp_path: Path):
    raw = _contract(project)
    raw["tasks"][0]["outcomes"].append({  # type: ignore[index]
        "type": "dagcert.runtime.UnhandledException",
        "resources": {"state": {"produce": 1}},
        "metadata": {},
    })
    path = tmp_path / "fake-unhandled-effects.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="do not exactly match source return union"):
        load_contract(path, source_root=project["root"])


def test_dependency_edges_must_connect_real_source_types(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
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
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n\n"
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
