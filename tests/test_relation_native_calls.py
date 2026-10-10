"""Real native expressions keep their effects inside a joint operation proof."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from dagcert.relations import SourceRelation, build_relation_proof_view


_PATH_CONTRACT = '''from io import TextIOWrapper
from nagini_contracts.contracts import ContractOnly, Exsures, Requires

class Path:
    @ContractOnly
    def __init__(self, path: str) -> None:
        Exsures(Exception, True)
        ...

    @ContractOnly
    def __truediv__(self, child: str) -> 'Path':
        Exsures(Exception, True)
        ...

    @ContractOnly
    def open(self, mode: str = 'r', buffering: int = -1,
             encoding: str | None = None, errors: str | None = None,
             newline: str | None = None) -> TextIOWrapper:
        Requires(mode == 'r' or mode == 'w' or mode == 'a' or mode == 'x')
        Exsures(Exception, True)
        ...
'''

_IO_CONTRACT = '''from types import TracebackType
from nagini_contracts.contracts import ContractOnly, Ensures, Exsures, Result

class TextIOWrapper:
    @ContractOnly
    def __enter__(self) -> 'TextIOWrapper':
        Ensures(Result() is self)
        Exsures(Exception, True)
        ...

    @ContractOnly
    def write(self, value: str) -> int:
        Exsures(Exception, True)
        ...

    @ContractOnly
    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        Exsures(Exception, True)
        ...
'''

_RECORDS = '''from dataclasses import dataclass
from pathlib import Path
from dagcert.runtime import operation

@dataclass(frozen=True)
class Request:
    path: str
    text: str

@dataclass(frozen=True)
class Completed:
    value: int

@dataclass(frozen=True)
class Failed:
    value: int

@operation
def work(request: Request) -> Completed | Failed:
'''


def _verify(tmp_path: Path, source: str, predicate: str) -> dict[str, Any]:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("native call integration requires a digest-pinned backend")
    assert executable is not None and digest is not None, "set both backend variables"
    assert sha256(Path(executable).read_bytes()).hexdigest() == digest.lower()
    view, _ = build_relation_proof_view(
        source, "work", [
            SourceRelation("completed", "work", "Completed", predicate),
            SourceRelation("failed", "work", "Failed", "result.value == -1"),
        ], backend_postconditions=True,
    )
    (tmp_path / "app.py").write_text(view, encoding="utf-8")
    contracts = {
        "pathlib": _PATH_CONTRACT,
        "io": _IO_CONTRACT,
        "types": "class TracebackType:\n    pass\n",
    }
    for module, contract in contracts.items():
        (tmp_path / f"{module}_contract.py").write_text(contract, encoding="utf-8")
    request = {
        "schema": "maledictus-verification-request/v5",
        "source_root": str(tmp_path),
        "source_fingerprint": sha256(view.encode()).hexdigest(),
        "proof_obligation": "no-undeclared-exceptional-exit",
        "files": [{"path": "app.py", "language": "python", "symbols": ["work"]}],
        "external_contract_overlays": [{
            "adapter_path": "app.py", "module": module,
            "stub_path": f"{module}_contract.py",
            "exception_policy": "assume-no-exception" if module == "types" else "declared-by-exsures",
        } for module in contracts],
        "python_callable_bindings": [], "embedded_external_calls": [],
        "cross_language_bindings": [],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    completed = subprocess.run(
        [executable, "verify", "--request", str(request_path)],
        text=True, capture_output=True, timeout=120, check=False,
    )
    (tmp_path / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    response = json.loads(completed.stdout)
    assert isinstance(response, dict), completed.stderr
    (tmp_path / "response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
    assert response["verifier_identity"]["executable_sha256"] == digest.lower(), response
    return response


@pytest.mark.parametrize("joined", [False, True])
@pytest.mark.parametrize("correct", [False, True])
def test_inline_native_context_has_joint_semantics(
    tmp_path: Path, joined: bool, correct: bool,
) -> None:
    path = "(Path(request.path) / 'events.jsonl')" if joined else "Path(request.path)"
    source = _RECORDS + f'''    try:
        with {path}.open('a', encoding='utf-8') as stream:
            count = stream.write(request.text)
        return Completed(1)
    except Exception:
        return Failed(-1)
'''
    # The native write count is not assumed equal to requested text length.
    # This relation describes the source's return, not successful file delivery.
    response = _verify(tmp_path, source, f"result.value == {1 if correct else 2}")
    assert response["status"] == ("proved" if correct else "refuted"), response
    if correct:
        assert response["files"][0]["fragment"] == "dagcert-closed-typed-operations+semantic-postconditions/v1"
        assert all(item["status"] == "proved" for item in response["obligations"]), response
    else:
        assert any(":postcondition:" in item["id"] and item["status"] != "proved"
                   for item in response["obligations"]), response


def test_native_cleanup_outside_handler_is_semantically_refuted(tmp_path: Path) -> None:
    source = _RECORDS + '''    try:
        path = Path(request.path)
        stream = path.open('a', encoding='utf-8')
        entered = stream.__enter__()
        entered.write(request.text)
    except Exception:
        return Failed(-1)
    stream.__exit__(None, None, None)
    return Completed(1)
'''
    response = _verify(tmp_path, source, "result.value == 1")
    assert response["status"] == "refuted", response
    assert any("exception-undeclared" in item["id"] and item["status"] != "proved"
               for item in response["obligations"]), response
