from hashlib import sha256
import base64
import importlib
import json
from pathlib import Path
import sys

import pytest

from dagcert import CertificateError, issue_certificate, verify_certificate
from dagcert.certificate import canonical_json, source_manifest, source_fingerprint
from dagcert.python_dependencies import DependencyError, check_python_dependencies


COMMIT = "a" * 40
GIT_REQUIREMENT = f"microdep @ git+https://example.test/microdep.git@{COMMIT}"


@pytest.fixture
def package(tmp_path, monkeypatch):
    site = tmp_path / "site"
    code = site / "microdep/__init__.py"
    code.parent.mkdir(parents=True)
    code.write_text("VALUE = 1\n", encoding="utf-8")
    info = site / "microdep-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: microdep\nVersion: 1.0\n", encoding="utf-8")
    checksum = base64.urlsafe_b64encode(sha256(code.read_bytes()).digest()).rstrip(b"=").decode()
    (info / "RECORD").write_text(f"microdep/__init__.py,sha256={checksum},{code.stat().st_size}\n", encoding="utf-8")
    origin = {"url": "https://example.test/microdep.git", "vcs_info": {"vcs": "git", "commit_id": COMMIT}}
    (info / "direct_url.json").write_text(json.dumps(origin), encoding="utf-8")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.delitem(sys.modules, "microdep", raising=False)
    yield code, info
    sys.modules.pop("microdep", None)


def declare(root, text=GIT_REQUIREMENT):
    (root / "requirements.txt").write_text(text + "\n", encoding="utf-8")


def check(root, **kwargs):
    return check_python_dependencies(root, source_manifest(root), **kwargs)


def test_records_matching_git_identity_and_bytes(tmp_path, package):
    declare(tmp_path)
    identity = check(tmp_path)
    assert identity["distributions"]["microdep"]["version"] == "1.0"
    assert identity["distributions"]["microdep"]["provenance"]["vcs_info"]["commit_id"] == COMMIT
    assert identity["distributions"]["microdep"]["runtime_file_count"] == 1


@pytest.mark.parametrize("requirement,match", [
    ("microdep==2.0", "installed version"),
    (GIT_REQUIREMENT.replace(COMMIT, "b" * 40), "Git provenance"),
    (GIT_REQUIREMENT.replace("example.test", "another.test"), "Git provenance"),
    (GIT_REQUIREMENT.replace(COMMIT, "master"), "immutable full Git commit"),
    ("missing-dagcert-dependency==1", "not installed"),
])
def test_rejects_wrong_or_missing_dependency(tmp_path, package, requirement, match):
    declare(tmp_path, requirement)
    with pytest.raises(DependencyError, match=match):
        check(tmp_path)


@pytest.mark.parametrize("loaded", [False, True])
def test_rejects_shadow_even_when_metadata_matches(tmp_path, package, monkeypatch, loaded):
    root = tmp_path / "app"
    root.mkdir()
    declare(root)
    shadow = tmp_path / "checkout"
    shadow.mkdir()
    (shadow / "microdep.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(shadow))
    if loaded:
        importlib.import_module("microdep")
        sys.path.remove(str(shadow))
    with pytest.raises(DependencyError, match="outside installed distribution"):
        check(root)


def test_rejects_modified_installed_file(tmp_path, package):
    declare(tmp_path)
    package[0].write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(DependencyError, match="differs from RECORD"):
        check(tmp_path)


def test_checks_transitive_requirements(tmp_path, package):
    declare(tmp_path)
    metadata = package[1] / "METADATA"
    metadata.write_text(metadata.read_text() + "Requires-Dist: absent-transitive-dependency==1\n")
    with pytest.raises(DependencyError, match="absent-transitive-dependency"):
        check(tmp_path)


def test_ambiguous_and_excluded_declarations_cannot_be_silently_skipped(tmp_path, package):
    declare(tmp_path)
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    with pytest.raises(DependencyError, match="multiple Python"):
        check(tmp_path)
    with pytest.raises(DependencyError, match="cannot be skipped"):
        check(tmp_path, requirements=[])
    assert check(tmp_path, requirements=["requirements.txt"])
    (tmp_path / ".dagcertignore").write_text("requirements.txt\n")
    with pytest.raises(DependencyError, match="included in the source manifest"):
        check(tmp_path, requirements=["requirements.txt"])


def test_pyproject_and_included_requirements(tmp_path, package):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["microdep==1.0"]\n')
    assert check(tmp_path)["requirements"] == ["pyproject.toml"]
    (tmp_path / "requirements.txt").write_text("-r nested.txt\n")
    (tmp_path / "nested.txt").write_text(GIT_REQUIREMENT + "\n")
    result = check(tmp_path, requirements=["requirements.txt"])
    assert set(result["input_sha256"]) == {"requirements.txt", "nested.txt"}


def test_explicit_requirements_resolve_dynamic_project_dependencies(tmp_path, package):
    (tmp_path / "pyproject.toml").write_text('[project]\ndynamic = ["dependencies"]\n')
    declare(tmp_path)
    assert check(tmp_path, requirements=["requirements.txt"])
    with pytest.raises(DependencyError, match="dynamic project dependencies"):
        check(tmp_path, requirements=["pyproject.toml"])


@pytest.mark.parametrize("kind", ["version", "commit", "shadow", "tamper"])
def test_public_issuer_refuses_before_running_proofs(project, package, monkeypatch, kind):
    root = Path(project["root"])
    declare(root, "microdep==2.0" if kind == "version" else GIT_REQUIREMENT.replace(COMMIT, "b" * 40) if kind == "commit" else GIT_REQUIREMENT)
    if kind == "shadow":
        (root / "microdep.py").write_text("VALUE=2\n")
    if kind == "tamper":
        package[0].write_text("VALUE=2\n")
    def unexpected_proof(*args, **kwargs):
        pytest.fail("dependency mismatch reached the source prover")
    monkeypatch.setattr("dagcert.certificate.check_python_sources", unexpected_proof)
    with pytest.raises(CertificateError, match="Python dependencies"):
        issue_certificate(project["contract"], project["evidence"], root / "artifacts/certificate.json",
                          requirements_path=project["requirements"], source_root=root)


def test_public_verifier_rejects_environment_drift_and_stripped_binding(project, package, monkeypatch):
    root = Path(project["root"])
    declare(root)
    # These tests isolate the public environment gate; source proof behavior is
    # covered by the existing verifier suites, not replaced in production.
    monkeypatch.setattr("dagcert.certificate.check_python_sources", lambda *a, **k: {})
    fingerprint = source_fingerprint(root, exclude=["dag_contract.json", "english_requirements.json"])
    evidence = Path(project["evidence"])
    evidence.write_text(evidence.read_text().replace(project["fingerprint"], fingerprint))
    output = root / "artifacts/certificate.json"
    document = issue_certificate(project["contract"], evidence, output,
                                 requirements_path=project["requirements"], source_root=root)
    kwargs = {"contract_path": project["contract"], "evidence_path": evidence,
              "requirements_path": project["requirements"], "source_root": root}
    assert verify_certificate(output, **kwargs).valid
    provenance = package[1] / "direct_url.json"
    original = provenance.read_text()
    provenance.write_text(original.replace(COMMIT, "b" * 40))
    result = verify_certificate(output, **kwargs)
    assert not result.valid and any("Git provenance" in p for p in result.problems)
    provenance.write_text(original)
    metadata = package[1] / "METADATA"
    original_metadata = metadata.read_text()
    metadata.write_text(original_metadata.replace("Version: 1.0", "Version: 2.0"))
    assert not verify_certificate(output, **kwargs).valid
    metadata.write_text(original_metadata)
    with monkeypatch.context() as scoped:
        shadow = root.parent / "shadow"
        shadow.mkdir()
        (shadow / "microdep.py").write_text("VALUE=9\n")
        scoped.syspath_prepend(str(shadow))
        result = verify_certificate(output, **kwargs)
        assert not result.valid and any("import shadowing" in p for p in result.problems)
    original_source = package[0].read_bytes()
    package[0].write_bytes(b"VALUE=9\n")
    result = verify_certificate(output, **kwargs)
    assert not result.valid and any("differs from RECORD" in p for p in result.problems)
    package[0].write_bytes(original_source)
    del document["source_verification"]["python_dependencies"]
    del document["certificate_sha256"]
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    output.write_text(json.dumps(document))
    result = verify_certificate(output, **kwargs)
    assert not result.valid and any("lacks dependency binding" in p for p in result.problems)
