from dataclasses import replace

from dagcert.requirements import EnglishClaim, EnglishRequirements, audit_translation


def _requirements(formula, references=("timing:work/normal",)):
    return EnglishRequirements("dagcert-english-requirements/v2", (EnglishClaim(
        "work-bound", "The work task has the stated timing bound.", references,
        basis="derived", formula=formula,
    ),))


def test_single_task_timing_formula_covers_its_actual_owner(project):
    audit = audit_translation(
        _requirements({"lte": [{"timing_upper_ms": "timing:work/normal"}, 10]}),
        project["loaded_contract"],
    )
    assert audit.passed, audit.findings
    assert audit.covered_tasks == ("task:work",)
    assert audit.covered_timings == ("timing:work/normal",)


def test_unused_prose_task_and_timing_references_do_not_cover_a_second_task(project):
    contract = project["loaded_contract"]
    contract = replace(contract, tasks=(contract.tasks[0], replace(contract.tasks[0], id="uncited")))
    audit = audit_translation(
        _requirements(
            {"lte": [{"timing_upper_ms": "timing:work/normal"}, 10]},
            ("timing:work/normal", "task:uncited", "timing:uncited/normal"),
        ),
        contract,
    )
    assert not audit.passed
    assert audit.covered_tasks == ("task:work",)
    assert any("task:uncited" in finding for finding in audit.findings)


def test_nonexistent_timing_does_not_cover_an_existing_task(project):
    audit = audit_translation(
        _requirements(
            {"lte": [{"timing_upper_ms": "timing:work/missing"}, 10]},
            ("timing:work/missing",),
        ),
        project["loaded_contract"],
    )
    assert not audit.passed
    assert audit.covered_tasks == ()


def test_invalid_formula_still_refuses_even_when_it_mentions_a_real_timing(project):
    audit = audit_translation(
        _requirements({"not_a_proof": {"timing_upper_ms": "timing:work/normal"}}),
        project["loaded_contract"],
    )
    assert not audit.passed
    assert any("invalid formula" in finding for finding in audit.findings)
