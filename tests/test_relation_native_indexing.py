"""Native bracket syntax must preserve checked effects and semantic relations.

Set both DAGCERT_MALEDICTUS_EXECUTABLE and DAGCERT_MALEDICTUS_SHA256 to run.
These tests require the native-indexing backend, not a frontend refusal counted
as a proof. Both provider fixtures explicitly retain exceptional outcomes.
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
from dagcert.source_types import SourceProofBackend


_PATHLIB_CONTRACT = '''from nagini_contracts.contracts import ContractOnly, Exsures

class _PathParents:
    @ContractOnly
    def __getitem__(self, index: int) -> 'Path':
        Exsures(Exception, True)
        ...

class Path:
    @ContractOnly
    def __init__(self, path: str) -> None:
        Exsures(Exception, True)
        ...

    @property
    @ContractOnly
    def parents(self) -> _PathParents:
        Exsures(Exception, True)
        ...
'''

_INDEX_CONTRACT = '''from nagini_contracts.contracts import ContractOnly, Ensures, Exsures, Result

class IndexStore:
    @ContractOnly
    def __init__(self) -> None:
        Exsures(Exception, True)
        ...

    @ContractOnly
    def __getitem__(self, index: int) -> int:
        Ensures(Result() == index + 1)
        Exsures(Exception, True)
        ...
'''


@pytest.fixture
def native_indexing_backend() -> SourceProofBackend:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("native indexing integration requires a digest-pinned backend")
    assert executable is not None and digest is not None, "set both backend environment variables"
    assert sha256(Path(executable).read_bytes()).hexdigest() == digest.lower(), "backend executable differs from pin"
    return SourceProofBackend.maledictus(executable, digest)


def _source(
    provider: str, *, inline: bool = False, caught: bool = True,
    wrong_index: bool = False,
) -> str:
    imports = "from pathlib import Path" if provider == "pathlib" else "from index_provider import IndexStore"
    records = f'''{imports}
from dataclasses import dataclass
from dagcert.runtime import operation

@dataclass(frozen=True)
class Request:
    path: str
    index: {"str" if wrong_index else "int"}

@dataclass(frozen=True)
class Selected:
    value: int

@dataclass(frozen=True)
class Failed:
    value: int

@operation
def work(request: Request) -> Selected | Failed:
'''
    if inline:
        assert provider == "pathlib" and caught and not wrong_index
        return records + '''    try:
        selected = Path(request.path).parents[1]
        return Selected(request.index + 1)
    except Exception:
        return Failed(-1)
'''
    prepare = (
        "path = Path(request.path)\n        receiver = path.parents"
        if provider == "pathlib" else "receiver = IndexStore()"
    )
    # Catch construction/property effects independently. The uncaught variant
    # leaves only the actual __getitem__ call outside the exception handler.
    prefix = records + f'''    try:
        {prepare}
    except Exception:
        return Failed(-1)
    index = request.index
'''
    value = "0" if wrong_index else "request.index + 1" if provider == "pathlib" else "selected"
    if caught:
        return prefix + f'''    try:
        selected = receiver[index]
        return Selected({value})
    except Exception:
        return Failed(-1)
'''
    return prefix + f'''    selected = receiver[index]
    return Selected({value})
'''


def _prove(
    tmp_path: Path, backend: SourceProofBackend, provider: str, source: str,
    predicate: str,
) -> dict[str, Any]:
    view, _ = build_relation_proof_view(
        source, "work", [
            SourceRelation("selected-value", "work", "Selected", predicate),
            SourceRelation("failed-value", "work", "Failed", "result.value == -1"),
        ], backend_postconditions=True,
    )
    contract = _PATHLIB_CONTRACT if provider == "pathlib" else _INDEX_CONTRACT
    module = "pathlib" if provider == "pathlib" else "index_provider"
    (tmp_path / "app.py").write_text(view, encoding="utf-8")
    (tmp_path / "provider_contract.py").write_text(contract, encoding="utf-8")
    request = {
        "schema": "maledictus-verification-request/v5",
        "source_root": str(tmp_path), "source_fingerprint": sha256(view.encode("utf-8")).hexdigest(),
        "proof_obligation": "no-undeclared-exceptional-exit",
        "files": [{"path": "app.py", "language": "python", "symbols": ["work"]}],
        "external_contract_overlays": [{
            "adapter_path": "app.py", "module": module,
            "stub_path": "provider_contract.py", "exception_policy": "declared-by-exsures",
        }],
        "python_callable_bindings": [], "embedded_external_calls": [], "cross_language_bindings": [],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    assert backend.executable is not None
    completed = subprocess.run(
        [backend.executable, "verify", "--request", str(request_path)],
        text=True, capture_output=True, timeout=120, check=False,
    )
    (tmp_path / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    response = json.loads(completed.stdout)
    assert isinstance(response, dict), completed.stderr
    (tmp_path / "response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
    assert response["verifier_identity"]["executable_sha256"] == backend.executable_sha256, response
    return response


def _joint_proved(response: dict[str, Any]) -> None:
    assert response["status"] == "proved", response
    assert response["diagnostics"] == [], response
    assert len(response["files"]) == 1, response
    assert response["files"][0]["fragment"] == "dagcert-closed-typed-operations+semantic-postconditions/v1", response
    assert any(":postcondition:" in item["id"] for item in response["obligations"]), response
    assert all(item["status"] == "proved" for item in response["obligations"]), response
    assert response["external_contracts"][0]["exception_policy"] == "declared-by-exsures", response
    assert "Exception" in response["external_contracts"][0]["declared_exceptions"], response


@pytest.mark.parametrize("inline", [False, True])
def test_path_parents_bracket_index_proves_with_all_native_failures_caught(
    tmp_path: Path, native_indexing_backend: SourceProofBackend, inline: bool,
) -> None:
    _joint_proved(_prove(
        tmp_path, native_indexing_backend, "pathlib", _source("pathlib", inline=inline),
        "result.value == input.index + 1",
    ))


def test_generic_native_bracket_index_uses_the_actual_method_result_contract(
    tmp_path: Path, native_indexing_backend: SourceProofBackend,
) -> None:
    _joint_proved(_prove(
        tmp_path, native_indexing_backend, "generic", _source("generic"),
        "result.value == input.index + 1",
    ))


@pytest.mark.parametrize("provider", ["pathlib", "generic"])
def test_wrong_index_result_relation_reaches_semantic_refutation(
    tmp_path: Path, native_indexing_backend: SourceProofBackend, provider: str,
) -> None:
    response = _prove(tmp_path, native_indexing_backend, provider, _source(provider),
                      "result.value == input.index + 2")
    assert response["status"] == "refuted", response
    assert any(":postcondition:" in item["id"] and item["status"] == "refuted"
               for item in response["obligations"]), response


@pytest.mark.parametrize("provider", ["pathlib", "generic"])
def test_uncaught_native_index_exception_is_a_semantic_totality_failure(
    tmp_path: Path, native_indexing_backend: SourceProofBackend, provider: str,
) -> None:
    response = _prove(tmp_path, native_indexing_backend, provider, _source(provider, caught=False),
                      "result.value == input.index + 1")
    assert response["status"] == "refuted", response
    assert any("exception-undeclared" in item["id"] and item["status"] == "refuted"
               for item in response["obligations"]), response


@pytest.mark.parametrize("provider", ["pathlib", "generic"])
def test_native_index_requires_the_real_declared_argument_type(
    tmp_path: Path, native_indexing_backend: SourceProofBackend, provider: str,
) -> None:
    response = _prove(tmp_path, native_indexing_backend, provider, _source(provider, wrong_index=True), "True")
    assert response["status"] == "refused", response
    assert any(item["code"] in {
        "frontend.python.typecheck.index", "frontend.python.typecheck.arg-type",
        # Full pinned typeshed exposes Sequence's integer/slice overloads.
        "frontend.python.typecheck.call-overload",
    } for item in response["diagnostics"]), response
    assert response["obligations"] == [], response
