"""Real-backend final-return semantics, including cleanup after return evaluation.

Set DAGCERT_MALEDICTUS_EXECUTABLE and DAGCERT_MALEDICTUS_SHA256 to run these
implementation controls. A generic heap success is not a joint Dagcert proof.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from dagcert.relations import SourceRelation, build_relation_proof_view


@pytest.fixture
def cleanup_backend() -> tuple[Path, str]:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("real cleanup proof requires a digest-pinned Maledictus executable")
    assert executable is not None and digest is not None
    path = Path(executable)
    assert sha256(path.read_bytes()).hexdigest() == digest
    return path, digest


def _native_response(
    tmp_path: Path, backend: tuple[Path, str], source: str,
    predicate: str, *, external_provider: str | None = None,
    relations: list[SourceRelation] | None = None,
) -> dict[str, Any]:
    view, _ = build_relation_proof_view(
        source, "work", relations if relations is not None else [
            SourceRelation("final-return", "work", "Completed", predicate),
        ],
        backend_postconditions=True,
    )
    source_path = tmp_path / "app.py"
    source_path.write_text(view, encoding="utf-8")
    overlays: list[dict[str, str]] = []
    if external_provider is not None:
        (tmp_path / "provider_contract.py").write_text(external_provider, encoding="utf-8")
        overlays.append({
            "adapter_path": "app.py", "module": "provider", "stub_path": "provider_contract.py",
            "exception_policy": "declared-by-exsures" if "Exsures(" in external_provider else "assume-no-exception",
        })
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({
        "schema": "maledictus-verification-request/v5",
        "source_root": str(tmp_path), "source_fingerprint": sha256(view.encode("utf-8")).hexdigest(),
        "proof_obligation": "no-undeclared-exceptional-exit",
        "files": [{"path": "app.py", "language": "python", "symbols": ["work"]}],
        "external_contract_overlays": overlays, "python_callable_bindings": [],
        "embedded_external_calls": [], "cross_language_bindings": [],
    }, indent=2), encoding="utf-8")
    completed = subprocess.run([str(backend[0]), "verify", "--request", str(request_path)],
                               text=True, capture_output=True, timeout=120, check=False)
    response = json.loads(completed.stdout)
    assert isinstance(response, dict), completed.stderr
    (tmp_path / "response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
    # Include the complete response in test diagnostics instead of reporting a
    # generic failure or accepting a frontend rejection as positive semantics.
    return response


def _operation(body: str) -> str:
    return (
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\nclass Request:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Completed:\n    value: int\n\n"
        "@operation\ndef work(request: Request) -> Completed:\n" + body
    )


def _joint_proved(response: dict[str, Any]) -> None:
    assert response["status"] == "proved", response
    files = response["files"]
    assert len(files) == 1
    assert files[0]["fragment"] == "dagcert-closed-typed-operations+semantic-postconditions/v1", response
    assert any("postcondition" in obligation["id"] for obligation in response["obligations"]), response


def test_finally_return_override_is_checked_after_cleanup(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    source = _operation(
        "    try:\n        return Completed(0)\n"
        "    finally:\n        return Completed(request.value + 1)\n"
    )
    _joint_proved(_native_response(tmp_path, cleanup_backend, source,
                                   "result.value == input.value + 1"))


def test_finally_override_cannot_certify_the_original_return(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    source = _operation(
        "    try:\n        return Completed(1)\n"
        "    finally:\n        return Completed(-1)\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, "result.value > 0")
    assert response["status"] == "refuted", response


def test_constant_finally_override_is_not_blocked_by_input_permissions(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    source = _operation(
        "    try:\n        return Completed(1)\n"
        "    finally:\n        return Completed(7)\n"
    )
    _joint_proved(_native_response(tmp_path, cleanup_backend, source, "result.value == 7"))


@pytest.mark.parametrize("final_return", ["Completed(7)", "Failed('explicit failure')"])
def test_finalizer_can_change_the_nominal_outcome_before_guarded_postconditions(
    tmp_path: Path, cleanup_backend: tuple[Path, str], final_return: str,
) -> None:
    source = _operation(
        "    try:\n        return Completed(1)\n"
        f"    finally:\n        return {final_return}\n"
    )
    source = source.replace("@operation", "@dataclass(frozen=True)\nclass Failed:\n    reason: str\n\n@operation")
    source = source.replace("-> Completed:", "-> Completed | Failed:")
    _joint_proved(_native_response(tmp_path, cleanup_backend, source, "result.value == 7"))


def test_throwing_finalizer_cannot_satisfy_a_vacuous_normal_return_claim(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    source = _operation(
        "    try:\n        return Completed(1)\n"
        "    finally:\n        raise ValueError()\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, "result.value > 0")
    assert response["status"] != "proved", response


@pytest.mark.parametrize("cleanup", [False, True])
@pytest.mark.parametrize("wrong_alternate", [False, True])
def test_union_result_projections_share_the_actual_final_return(
    tmp_path: Path, cleanup_backend: tuple[Path, str], cleanup: bool,
    wrong_alternate: bool,
) -> None:
    body = (
        "    try:\n        return Completed(1)\n"
        "    finally:\n        return Alternate(2)\n"
        if cleanup else
        "    if request.value > 0:\n        return Completed(1)\n"
        "    return Alternate(2)\n"
    )
    source = _operation(body).replace(
        "@operation", "@dataclass(frozen=True)\nclass Alternate:\n    value: int\n\n@operation",
    ).replace("-> Completed:", "-> Completed | Alternate:")
    response = _native_response(tmp_path, cleanup_backend, source, "unused", relations=[
        SourceRelation("completed", "work", "Completed", "result.value == 1"),
        SourceRelation("alternate", "work", "Alternate",
                       "result.value == 1" if wrong_alternate else "result.value == 2"),
    ])
    if wrong_alternate:
        assert response["status"] == "refuted", response
        assert any(row["status"] == "refuted" for row in response["obligations"]), response
    else:
        _joint_proved(response)


@pytest.mark.parametrize("length", [2, 1])
@pytest.mark.parametrize("cleanup", [True, False])
def test_unsupported_returned_list_alias_is_never_proved_with_stale_contents(
    tmp_path: Path, cleanup_backend: tuple[Path, str], length: int,
    cleanup: bool,
) -> None:
    source = (
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\nclass Request:\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Completed:\n    values: list[int]\n\n"
        "@operation\ndef work(request: Request) -> Completed:\n"
        "    values = [1]\n    returned = Completed(values)\n"
    )
    source += (
        "    try:\n        return returned\n    finally:\n        values.append(2)\n"
        if cleanup else "    values.append(2)\n    return returned\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, f"len(result.values) == {length}")
    # Mutable list fields are not admitted by the closed-operation type fragment.
    # These end-to-end cases must report that actual boundary, not pretend that
    # they reached the heap alias checker. Maledictus's heap_record_list_aliases
    # controls separately exercise the shared-identity guard inside heap lowering.
    # In particular, the stale-length predicate must never receive a proof.
    assert response["status"] == "refused", response
    assert any(
        row["code"] == "frontend.python.dagcert.type-unsupported"
        for row in response["diagnostics"]
    ), response
    assert response["obligations"] == [], response


def _context_provider() -> str:
    return (
        "from nagini_contracts.contracts import ContractOnly, Ensures, Result\n\n"
        "class Resource:\n"
        "    @ContractOnly\n    def __enter__(self) -> 'Resource':\n"
        "        Ensures(Result() is self)\n        ...\n"
        "    @ContractOnly\n    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:\n        ...\n\n"
        "@ContractOnly\ndef open_resource() -> Resource:\n    ...\n"
    )


@pytest.mark.parametrize("binding", ["", " as resource"])
def test_with_cleanup_preserves_final_return_under_explicit_external_contract(
    tmp_path: Path, cleanup_backend: tuple[Path, str], binding: str,
) -> None:
    source = "from provider import open_resource\n" + _operation(
        f"    with open_resource(){binding}:\n        return Completed(request.value + 1)\n"
    )
    _joint_proved(_native_response(tmp_path, cleanup_backend, source,
                                   "result.value == input.value + 1", external_provider=_context_provider()))


def test_external_cleanup_does_not_hide_a_false_postcondition(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    source = "from provider import open_resource\n" + _operation(
        "    with open_resource():\n        return Completed(request.value + 1)\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source,
                               "result.value == input.value + 2", external_provider=_context_provider())
    assert response["status"] == "refuted", response
    assert any("postcondition" in row["id"] and row["status"] == "refuted"
               for row in response["obligations"]), response


def test_throwing_external_cleanup_invalidates_the_normal_return_claim(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    provider = _context_provider().replace(
        "ContractOnly, Ensures, Result", "ContractOnly, Ensures, Result, Exsures",
    ).replace("tb: object) -> None:\n        ...", "tb: object) -> None:\n        Exsures(Exception, True)\n        ...")
    source = "from provider import open_resource\n" + _operation(
        "    with open_resource():\n        return Completed(7)\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, "result.value == 7", external_provider=provider)
    assert response["status"] == "refuted", response
    assert any("exception-undeclared" in row["id"] and row["status"] == "refuted"
               for row in response["obligations"]), response


@pytest.mark.parametrize("exception", ["Exception", "BaseException"])
def test_external_cleanup_does_not_swallow_unexpected_exception(
    tmp_path: Path, cleanup_backend: tuple[Path, str], exception: str,
) -> None:
    source = "from provider import open_resource\n" + _operation(
        "    with open_resource():\n"
        f"        if request.value < 0:\n            raise {exception}()\n"
        "        return Completed(7)\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, "result.value == 7", external_provider=_context_provider())
    if exception == "BaseException":
        # BaseException construction is outside the current heap source fragment.
        # Keep this as an explicit refusal control, not a claimed semantic proof.
        assert response["status"] == "refused", response
        assert any(row["code"] == "frontend.python.heap.raise-expression-unsupported"
                   for row in response["diagnostics"]), response
        assert response["obligations"] == [], response
        return
    assert response["status"] == "refuted", response
    assert any("exception-undeclared" in row["id"] and row["status"] == "refuted"
               for row in response["obligations"]), response


def test_external_provider_preconditions_are_checked_at_the_actual_call(
    tmp_path: Path, cleanup_backend: tuple[Path, str],
) -> None:
    provider = _context_provider().replace(
        "ContractOnly, Ensures, Result", "ContractOnly, Ensures, Result, Requires",
    ).replace("def open_resource() -> Resource:\n    ...", "def open_resource() -> Resource:\n    Requires(False)\n    ...")
    source = "from provider import open_resource\n" + _operation(
        "    with open_resource():\n        return Completed(7)\n"
    )
    response = _native_response(tmp_path, cleanup_backend, source, "result.value == 7", external_provider=provider)
    assert response["status"] == "refuted", response
    assert any("precondition" in row["id"] and row["status"] == "refuted"
               for row in response["obligations"]), response


@pytest.mark.parametrize("case", ["while", "recursion", "mutual", "requires", "missing-return"])
def test_joint_external_semantics_do_not_expand_totality_by_assumption(
    tmp_path: Path, cleanup_backend: tuple[Path, str], case: str,
) -> None:
    bodies = {
        "while": "    with open_resource():\n        if request.value < 0:\n            while True:\n                pass\n        return Completed(7)\n",
        "recursion": "    with open_resource():\n        return work(request)\n",
        "mutual": "    with open_resource():\n        return again(request)\n",
        "requires": "    Requires(False)\n    with open_resource():\n        return Completed(7)\n",
        "missing-return": "    if request.value > 0:\n        with open_resource():\n            return Completed(7)\n",
    }
    source = "from provider import open_resource\n" + _operation(bodies[case])
    if case == "mutual":
        source += "\n@operation\ndef again(request: Request) -> Completed:\n    return work(request)\n"
    if case == "requires":
        source = "from nagini_contracts.contracts import Requires\n" + source
    response = _native_response(tmp_path, cleanup_backend, source, "result.value == 7", external_provider=_context_provider())
    assert response["status"] in {"refused", "refuted"}, response
    assert response["diagnostics"], response
