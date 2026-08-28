from pathlib import Path
import json

from dagcert import (
    CertificateError, CheckContext, CheckResult, issue_certificate, load_check_result, load_contract, load_evidence,
    load_requirements, run_checker, sha256_file, verify_certificate,
)
from dagcert.certificate import canonical_json, source_manifest
from hashlib import sha256
import pytest


def test_source_manifest_prunes_ignored_directories(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("print('bound')\n", encoding="utf-8")
    (tmp_path / ".dagcertignore").write_text("static\n", encoding="utf-8")
    ignored = tmp_path / "static" / "large-tree"
    ignored.mkdir(parents=True)
    (ignored / "asset.bin").write_bytes(b"unrelated")
    generated = tmp_path / "node_modules" / "package"
    generated.mkdir(parents=True)
    (generated / "index.js").write_text("ignored\n", encoding="utf-8")

    import os

    scanned: list[Path] = []
    original_scandir = os.scandir

    def recording_scandir(path):
        scanned.append(Path(path).resolve())
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", recording_scandir)
    manifest = source_manifest(tmp_path)

    assert set(manifest) == {".dagcertignore", "app.py"}
    assert ignored.parent.resolve() not in scanned
    assert generated.parent.resolve() not in scanned


def test_source_manifest_preserves_glob_exclusions(tmp_path):
    assets = tmp_path / "static" / "nested"
    assets.mkdir(parents=True)
    (tmp_path / "static" / "top.bin").write_bytes(b"excluded")
    (assets / "nested.bin").write_bytes(b"included")

    manifest = source_manifest(tmp_path, exclude=["static/*.bin"])

    assert set(manifest) == {"static/nested/nested.bin"}


def _set_checker_refs(project, *checker_names: str):
    path = Path(project["requirements"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["claims"][0]["checker_refs"] = list(checker_names)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_requirements(path)


def test_issue_verify_and_source_tamper(project):
    certificate = Path(project["root"]) / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=project["root"],
    )
    result = verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=project["root"],
    )
    assert result.valid
    (Path(project["root"]) / "app.py").write_text("def work(value): return value + 2\n", encoding="utf-8")
    assert not verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=project["root"],
    ).valid


def test_certificate_embeds_and_digest_binds_plain_english_requirements(project):
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    document = issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=root,
    )
    requirements = load_requirements(project["requirements"])
    assert document["english_requirements"] == requirements.to_mapping()
    assert document["requirements_sha256"] == sha256_file(project["requirements"])
    assert document["translation_audit"]["schema"] == "dagcert-translation-audit/v1"
    assert document["translation_audit"]["passed"] is True
    assert document["translation_audit"]["covered_tasks"] == ["task:work"]
    assert document["translation_audit"]["covered_timings"] == ["timing:work/normal"]
    assert document["schema"] == "dagcert-certificate/v9"
    assert document["type_enforcement"]["operation_marker"] == "type-preserving/v1"
    assert document["type_enforcement"]["mypy_import_surface"] == "sealed-type-preserving-dagcert-stub/v1"
    assert document["type_enforcement"]["exception_verification"] == "nagini-viper-total-no-axioms/v2"
    assert document["type_enforcement"]["chance_composition"] == "finite-union-bound-exact-path/v2"
    assert set(document["type_enforcement"]["kernel_manifest"]) >= {
        "analysis.py", "certificate.py", "contract.py", "runtime.py", "source_types.py",
    }
    assert len(document["type_enforcement"]["kernel_sha256"]) == 64
    verification = document["source_verification"]
    assert verification["type_checker"]["checker"] == "mypy"
    assert verification["type_checker"]["mode"] == "strict"
    assert verification["type_checker"]["dagcert_import_surface"] == "sealed-type-preserving-stub"
    assert verification["exception_verifier"]["checker"] == "nagini"
    assert verification["exception_verifier"]["files"][0]["result"] == "proved"
    assert verification["signatures"][0]["input_type"] == "WorkInput"
    assert verification["signatures"][0]["outcome_types"] == ["WorkCompleted"]
    assert document["claim_analysis"] == [{
        "claim_id": "work-completes",
        "basis": "observed",
        "passed": True,
        "scope": "retained evidence only",
        "formula": None,
        "composition_refs": [],
        "primitive_refs": ["task:work", "timing:work/normal"],
    }]

    raw = json.loads(Path(project["requirements"]).read_text(encoding="utf-8"))
    raw["claims"][0]["statement"] = "A different promise that was never certified."
    Path(project["requirements"]).write_text(json.dumps(raw), encoding="utf-8")
    result = verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=root,
    )
    assert not result.valid
    assert "English requirements digest mismatch" in result.problems


def test_certificate_binds_the_type_enforcement_kernel(project):
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=root,
    )
    raw = json.loads(certificate.read_text(encoding="utf-8"))
    raw["type_enforcement"]["operation_marker"] = "weaker-marker/v0"
    raw.pop("certificate_sha256")
    raw["certificate_sha256"] = sha256(canonical_json(raw)).hexdigest()
    certificate.write_bytes(canonical_json(raw) + b"\n")

    result = verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=root,
    )
    assert not result.valid
    assert "source/runtime type enforcement kernel no longer matches" in result.problems


def test_issue_rejects_unknown_primitive_in_english_claim(project):
    raw = json.loads(Path(project["requirements"]).read_text(encoding="utf-8"))
    raw["claims"][0]["primitive_refs"] = ["task:does-not-exist"]
    Path(project["requirements"]).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CertificateError, match="unknown primitives"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


@pytest.mark.parametrize(
    ("remaining_refs", "message"),
    [
        (["timing:work/normal"], "formal tasks lack an English claim"),
        (["task:work"], "formal timings lack an English claim"),
    ],
)
def test_issue_rejects_incomplete_english_to_formal_coverage(
    project, remaining_refs, message
):
    raw = json.loads(Path(project["requirements"]).read_text(encoding="utf-8"))
    raw["claims"][0]["primitive_refs"] = remaining_refs
    Path(project["requirements"]).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CertificateError, match=message):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


def test_assumed_timing_requires_an_explicit_english_assumption(project):
    contract = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    timing = contract["tasks"][0]["timings"]["normal"]
    timing["evidence"] = "assumed"
    timing["minimum_samples"] = 0
    Path(project["contract"]).write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(CertificateError, match="lack explicit English assumptions"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


def test_issue_rejects_required_checker_that_was_not_run(project):
    _set_checker_refs(project, "application.projection/v1")
    with pytest.raises(CertificateError, match="unselected checkers"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=project["requirements"], source_root=project["root"],
        )


def test_derived_claim_cannot_delegate_proof_to_checker(project):
    path = Path(project["requirements"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    claim = raw["claims"][0]
    claim["basis"] = "derived"
    claim["formula"] = {
        "lte": [{"timing_upper_ms": "timing:work/normal"}, 10]
    }
    claim["checker_refs"] = ["application.says-pass/v1"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CertificateError, match="cannot delegate proof to arbitrary checkers"):
        issue_certificate(
            project["contract"], project["evidence"],
            Path(project["root"]) / "artifacts" / "certificate.json",
            requirements_path=path, source_root=project["root"],
        )


def test_generic_checker_is_exactly_bound(project):
    root = Path(project["root"])
    requirements = _set_checker_refs(project, "example/v1")
    check_path = root / "artifacts" / "app-check.json"
    context = CheckContext(
        contract=load_contract(project["contract"]), timings=load_evidence(project["evidence"]),
        source_root=root, source_fingerprint=project["fingerprint"],
        contract_sha256=sha256_file(project["contract"]), evidence_sha256=sha256_file(project["evidence"]),
        requirements=requirements, requirements_sha256=sha256_file(project["requirements"]),
    )
    run_checker(lambda ctx: CheckResult(
        checker="example/v1", passed=True, source_fingerprint=ctx.source_fingerprint,
        contract_sha256=ctx.contract_sha256, evidence_sha256=ctx.evidence_sha256,
        requirements_sha256=ctx.requirements_sha256,
        primitive_refs=("task:work",), facts={"application_owned": True},
    ), context, check_path)
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate, source_root=root,
        requirements_path=project["requirements"],
        check_result_paths=[check_path],
    )
    assert verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"],
        source_root=root, check_result_paths=[check_path],
    ).valid


def test_checker_digest_binding_is_independent_of_path_spelling(project, monkeypatch):
    root = Path(project["root"])
    requirements = _set_checker_refs(project, "example/v1")
    check_path = root / "artifacts" / "app-check.json"
    context = CheckContext(
        contract=load_contract(project["contract"]), timings=load_evidence(project["evidence"]),
        source_root=root, source_fingerprint=project["fingerprint"],
        contract_sha256=sha256_file(project["contract"]), evidence_sha256=sha256_file(project["evidence"]),
        requirements=requirements, requirements_sha256=sha256_file(project["requirements"]),
    )
    run_checker(lambda ctx: CheckResult(
        checker="example/v1", passed=True, source_fingerprint=ctx.source_fingerprint,
        contract_sha256=ctx.contract_sha256, evidence_sha256=ctx.evidence_sha256,
        requirements_sha256=ctx.requirements_sha256,
        primitive_refs=("task:work",),
    ), context, check_path)
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate, source_root=root,
        requirements_path=project["requirements"],
        check_result_paths=[check_path.resolve()],
    )
    monkeypatch.chdir(root)
    assert verify_certificate(
        certificate, contract_path="dag_contract.json", evidence_path="artifacts/timings.jsonl",
        requirements_path="english_requirements.json",
        source_root=".", check_result_paths=["artifacts/app-check.json"],
    ).valid


def test_verify_rejects_rehashed_fabricated_primitive_display(project):
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=root,
    )
    document = json.loads(certificate.read_text(encoding="utf-8"))
    document["primitives"]["workers"][0]["concurrency"] = 999
    document.pop("certificate_sha256")
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    certificate.write_bytes(canonical_json(document) + b"\n")
    result = verify_certificate(
        certificate,
        contract_path=project["contract"],
        evidence_path=project["evidence"],
        requirements_path=project["requirements"],
        source_root=root,
    )
    assert not result.valid
    assert "serialized primitives no longer match" in result.problems


def test_verify_rejects_rehashed_fabricated_translation_audit(project):
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=root,
    )
    document = json.loads(certificate.read_text(encoding="utf-8"))
    document["translation_audit"]["covered_tasks"] = []
    document.pop("certificate_sha256")
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    certificate.write_bytes(canonical_json(document) + b"\n")
    result = verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=root,
    )
    assert not result.valid
    assert "English-to-formal translation audit no longer matches" in result.problems


def test_verify_rejects_rehashed_extra_uncertified_claim_field(project):
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"], project["evidence"], certificate,
        requirements_path=project["requirements"], source_root=root,
    )
    document = json.loads(certificate.read_text(encoding="utf-8"))
    document["uncertified_claims"] = ["Everything always works."]
    document.pop("certificate_sha256")
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    certificate.write_bytes(canonical_json(document) + b"\n")
    result = verify_certificate(
        certificate, contract_path=project["contract"], evidence_path=project["evidence"],
        requirements_path=project["requirements"], source_root=root,
    )
    assert not result.valid
    assert result.problems == (
        "certificate fields mismatch: unexpected=['uncertified_claims'], missing=[]",
    )


def test_check_result_protocol_rejects_non_array_references(project):
    path = Path(project["root"]) / "artifacts" / "bad-check.json"
    path.write_text(json.dumps({
        "schema": "dagcert-check-result/v2",
        "checker": "bad/v1",
        "passed": True,
        "source_fingerprint": "0" * 64,
        "contract_sha256": "0" * 64,
        "evidence_sha256": "0" * 64,
        "requirements_sha256": "0" * 64,
        "primitive_refs": "task:work",
        "findings": [],
        "facts": None,
    }), encoding="utf-8")
    try:
        load_check_result(path)
    except ValueError as exc:
        assert "primitive_refs" in str(exc)
    else:
        raise AssertionError("invalid check result was accepted")
