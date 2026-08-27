from pathlib import Path
import json

import pytest

from examples.optional_openai_luna_audit import (
    DEFAULT_MAX_AUDIT_PACKET_BYTES,
    accept_handoffs,
    build_context,
    prepare_handoffs,
)


LONG_ASSESSMENT = (
    "The supplied app.py implementation, contract declarations, timing samples, and analysis "
    "were compared directly. The assessment identifies what the evidence establishes, what remains "
    "conditional, and how those limits affect the user experience without treating a passing result "
    "as proof that the entire application is production ready or free from unrelated defects."
)


def _response(digest: str) -> dict:
    return {
        "audit_packet_sha256": digest,
        "passed": True,
        "summary": LONG_ASSESSMENT,
        "claim_reasoning": LONG_ASSESSMENT,
        "rule0_assessment": LONG_ASSESSMENT,
        "reviewed_files": ["app.py"],
        "strengths": [{
            "subject": "source binding", "evidence": "app.py is included in the packet",
            "impact": "the review can compare the promise with exact source",
        }],
        "weaknesses": [],
        "improvements": [],
        "test_fitting_risks": [],
        "evidence_gaps": [],
        "findings": [],
    }


def _two_claim_context(project):
    requirements = Path(project["requirements"])
    requirements.write_text(json.dumps({
        "schema": "dagcert-english-requirements/v1",
        "claims": [
            {
                "id": "timing",
                "statement": "Work completes under 10 ms.",
                "primitive_refs": ["timing:work/normal"],
                "checker_refs": ["optional.independent-semantic-audit/v3"],
                "assumptions": [],
            },
            {
                "id": "worker",
                "statement": "Work runs on the declared worker.",
                "primitive_refs": ["task:work", "worker:worker"],
                "checker_refs": ["optional.independent-semantic-audit/v3"],
                "assumptions": [],
            },
        ],
        "metadata": {},
    }), encoding="utf-8")
    return build_context(
        project["contract"], project["evidence"], requirements, project["root"]
    )


def test_each_claim_gets_a_separate_sealed_handoff_and_response(project):
    context = _two_claim_context(project)
    audit_root = Path(project["root"]) / "artifacts" / "audit"
    handoffs = prepare_handoffs(
        context,
        output_directory=audit_root,
    )
    assert len(handoffs) == 2
    assert handoffs[0].directory != handoffs[1].directory
    assert handoffs[0].packet_sha256 != handoffs[1].packet_sha256
    manifest = json.loads((audit_root / "audit-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["claims"]) == 2
    for handoff in handoffs:
        prompt = handoff.prompt_path.read_text(encoding="utf-8")
        packet = json.loads(handoff.packet_path.read_text(encoding="utf-8"))
        assert "RULE 0" in prompt
        assert "DAG and proof integrity" in prompt
        assert "synthetic observer, monitor, pipeline, batch, summary" in prompt
        assert "claim" in packet and "claims" not in packet
        assert packet["schema"] == "dagcert-semantic-audit-packet/v3"
        assert packet["source_files"]["app.py"]["content"].startswith("def work")
        assert packet["analysis"]["passed"] is True
        assert len(packet["timing_evidence"]) == 3
        handoff.response_path.write_text(
            json.dumps(_response(handoff.packet_sha256)),
            encoding="utf-8",
        )
    output = Path(project["root"]) / "artifacts" / "audit-result.json"
    result = accept_handoffs(context, handoff_directory=audit_root, output_path=output)
    assert result.passed
    assert result.facts["one_claim_per_packet"] is True
    assert len(result.facts["audits"]) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["checker"] == "optional.independent-semantic-audit/v3"


def test_oversized_claim_packet_refuses_entire_audit_before_writing(project):
    large_source = Path(project["root"]) / "repeated-proof-enumeration.py"
    large_source.write_text("WITNESS = " + repr("x" * DEFAULT_MAX_AUDIT_PACKET_BYTES), encoding="utf-8")
    context = _two_claim_context(project)
    audit_root = Path(project["root"]) / "artifacts" / "oversized-audit"

    with pytest.raises(ValueError, match=r"limit is 200,000 bytes.*Refusing.*content-addressed"):
        prepare_handoffs(context, output_directory=audit_root)

    assert not audit_root.exists()


def test_response_cannot_be_reused_for_another_claim_packet(project):
    context = _two_claim_context(project)
    audit_root = Path(project["root"]) / "artifacts" / "audit"
    first, second = prepare_handoffs(
        context,
        output_directory=audit_root,
    )
    reused = json.dumps(_response(first.packet_sha256))
    first.response_path.write_text(reused, encoding="utf-8")
    second.response_path.write_text(reused, encoding="utf-8")
    with pytest.raises(ValueError, match="another packet"):
        accept_handoffs(
            context,
            handoff_directory=audit_root,
            output_path=Path(project["root"]) / "artifacts" / "result.json",
        )


def test_handoff_claim_cannot_drift_from_mandatory_requirements(project):
    context = _two_claim_context(project)
    audit_root = Path(project["root"]) / "artifacts" / "audit"
    first, second = prepare_handoffs(context, output_directory=audit_root)
    packet = json.loads(first.packet_path.read_text(encoding="utf-8"))
    packet["claim"]["statement"] = "A weaker promise substituted after preparation."
    first.packet_path.write_text(json.dumps(packet), encoding="utf-8")
    first.response_path.write_text(json.dumps(_response(first.packet_sha256)), encoding="utf-8")
    second.response_path.write_text(json.dumps(_response(second.packet_sha256)), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match the English requirements"):
        accept_handoffs(
            context,
            handoff_directory=audit_root,
            output_path=Path(project["root"]) / "artifacts" / "result.json",
        )


def test_audit_instructions_live_in_a_text_template():
    root = Path(__file__).parents[1]
    source = (root / "examples" / "optional_openai_luna_audit.py").read_text(encoding="utf-8")
    template = (root / "examples" / "independent_audit_prompt.txt").read_text(encoding="utf-8")
    assert "RULE 0" not in source
    assert "RULE 0" in template
    assert "{{AUDIT_PACKET}}" in template


def test_missing_claim_directory_cannot_be_silently_accepted(project):
    context = _two_claim_context(project)
    audit_root = Path(project["root"]) / "artifacts" / "audit"
    first, second = prepare_handoffs(
        context,
        output_directory=audit_root,
    )
    first.response_path.write_text(json.dumps(_response(first.packet_sha256)), encoding="utf-8")
    second.response_path.write_text(json.dumps(_response(second.packet_sha256)), encoding="utf-8")
    second.packet_path.unlink()
    second.response_path.unlink()
    second.response_schema_path.unlink()
    second.prompt_path.unlink()
    second.directory.rmdir()
    with pytest.raises(ValueError, match="exactly match"):
        accept_handoffs(
            context,
            handoff_directory=audit_root,
            output_path=Path(project["root"]) / "artifacts" / "result.json",
        )
