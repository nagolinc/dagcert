"""Proof inputs must not replace executable code or discard requested obligations."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from dagcert.native_proof_support import annotation_view, native_proof_view


def test_annotation_view_preserves_generated_and_existing_obligations():
    source = "from nagini_contracts.contracts import Ensures\ndef f(x: int) -> int:\n    Ensures(x > 0)\n    return x\n"
    annotated = "from nagini_contracts.contracts import Assert\ndef f(x: int) -> int:\n    Assert(x == x)\n    return x\n"
    view = annotation_view(source, annotated)
    # Execute with an explicitly supplied contract implementation to observe
    # both proof calls, rather than checking source strings.
    import ast
    tree = ast.parse(view)
    tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom)]
    called = []
    scope = {"Ensures": lambda x: called.append(("post", x)),
             "Assert": lambda x: called.append(("assert", x))}
    exec(compile(tree, "proof", "exec"), scope)
    assert scope["f"](2) == 2
    assert sorted(called) == [("assert", True), ("post", True)]


@pytest.mark.parametrize("annotated", [
    "def f(x: int) -> int:\n    return 0\n",
    "from nagini_contracts.contracts import Assume\ndef f(x: int) -> int:\n    Assume(False)\n    return x\n",
    "from nagini_contracts.contracts import ContractOnly\n@ContractOnly\ndef f(x: int) -> int:\n    return x\n",
    "from nagini_contracts.contracts import Ensures as E\ndef f(x: int) -> int:\n    E(True)\n    return x\n",
])
def test_rejects_replacement_or_trusted_application_body(annotated):
    with pytest.raises(ValueError):
        annotation_view("def f(x: int) -> int:\n    return x\n", annotated)


def test_rejects_erasure_of_shadowed_executable_call():
    source = "def Assert(x):\n    raise RuntimeError()\ndef f(x):\n    Assert(x)\n    return x\n"
    with pytest.raises(ValueError, match="shadowed"):
        annotation_view(source, source.replace("    Assert(x)\n", ""))


def support(tmp_path: Path, original: str, proof: str):
    (tmp_path / "app.py").write_text(original, encoding="utf-8")
    p = tmp_path / "annotated.py"
    p.write_text(proof, encoding="utf-8")
    config = tmp_path / "support.json"
    config.write_text(json.dumps({"schema": "dagcert-native-proof-support/v1", "native_contracts": [],
        "annotations": {"app.py": {"path": str(p), "sha256": sha256(p.read_bytes()).hexdigest()}}}), encoding="utf-8")
    return config


@pytest.mark.parametrize('operations', [{'app.py': ('f',)}, {}])
def test_closed_operation_cannot_gain_a_precondition(tmp_path, operations):
    source = "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n@dataclass(frozen=True)\nclass V:\n    x: int\n@operation\ndef f(v: V) -> V:\n    return v\n"
    proof = "from nagini_contracts.contracts import Requires\n" + source.replace("    return v", "    Requires(False)\n    return v")
    config = support(tmp_path, source, proof)
    with pytest.raises(ValueError, match="Requires"):
        with native_proof_view(tmp_path, ("app.py",), str(config), frozenset({"app.py"}), operations):
            pytest.fail("closed operation was restricted")


def test_support_bytes_and_live_sources_are_rechecked(tmp_path):
    source = "def f(x: int) -> int:\n    return x\n"
    config = support(tmp_path, source, source)
    (tmp_path / "annotated.py").write_text(source + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        with native_proof_view(tmp_path, ("app.py",), str(config), frozenset({"app.py"}), {}):
            pytest.fail("changed support accepted")
    config = support(tmp_path, source, source)
    with pytest.raises(ValueError, match="source changed"):
        with native_proof_view(tmp_path, ("app.py",), str(config), frozenset({"app.py"}), {}):
            (tmp_path / "app.py").write_text(source.replace("return x", "return 0"), encoding="utf-8")


def test_mutex_predicate_can_be_added_but_not_called_by_runtime_code():
    source = "class Guard:\n    pass\n"
    annotated = "from nagini_contracts.contracts import Predicate\nclass Guard:\n    @Predicate\n    def invariant(self) -> bool:\n        return True\n"
    annotation_view(source, annotated)
    caller = "\ndef consume(g: Guard) -> bool:\n    return g.invariant()\n"
    with pytest.raises(ValueError, match="referenced by executable"):
        annotation_view(source + caller, annotated + caller)


def test_component_bundle_requires_disjoint_complete_coverage(tmp_path, monkeypatch):
    from dagcert.native_proof_support import check_native_bundle
    from dagcert.source_types import SourceProofBackend, SourceSignature, SourceTypeError
    import dagcert.source_types as api
    signature = SourceSignature("python", "app.py", "f", "Input", ("Ready",), 1)
    leaf = tmp_path / "leaf.json"
    leaf.write_text(json.dumps({"schema": "dagcert-native-proof-support/v1", "annotations": {}, "native_contracts": []}), encoding="utf-8")
    row = {"operations": [{"path": "app.py", "symbol": "f"}], "support": "leaf.json", "sha256": sha256(leaf.read_bytes()).hexdigest()}
    bundle = tmp_path / "bundle.json"
    backend = SourceProofBackend.maledictus("backend", "a" * 64, native_proof_support=bundle)
    calls = []
    def verified(root, signatures, **kwargs):
        calls.append(tuple(signatures))
        return {"signatures": [{"path": "app.py", "symbol": "f"}], "exception_verifier": {"result": "proved"}}
    monkeypatch.setattr(api, "check_python_sources", verified)
    options = dict(source_fingerprint="a" * 64, source_manifest_paths=("app.py",),
        external_contracts=(), callable_bindings=(), embedded_external_calls=(), required_postcondition_files=())
    for rows, error in [([], "omits"), ([row, row], "overlaps")]:
        bundle.write_text(json.dumps({"schema": "dagcert-native-proof-bundle/v1", "components": rows}), encoding="utf-8")
        with pytest.raises(SourceTypeError, match=error):
            check_native_bundle(tmp_path, (signature,), (signature,), backend, **options)
    calls.clear()
    bundle.write_text(json.dumps({"schema": "dagcert-native-proof-bundle/v1", "components": [row]}), encoding="utf-8")
    result = check_native_bundle(tmp_path, (signature,), (signature,), backend, **options)
    assert result['exception_verifier']['result'] == 'proved'
    assert calls == [(signature,)]
    leaf.write_text(json.dumps({"schema": "dagcert-native-proof-bundle/v1", "components": []}), encoding="utf-8")
    row['sha256'] = sha256(leaf.read_bytes()).hexdigest()
    bundle.write_text(json.dumps({"schema": "dagcert-native-proof-bundle/v1", "components": [row]}), encoding="utf-8")
    with pytest.raises(SourceTypeError, match="leaves"):
        check_native_bundle(tmp_path, (signature,), (signature,), backend, **options)
