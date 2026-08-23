from pathlib import Path
import json
import sqlite3

from dagcert import (
    CheckContext,
    issue_certificate,
    load_requirements,
    run_checker,
    sha256_file,
    verify_certificate,
)
from examples.optional_browser_checker import (
    ProjectionRow,
    ProjectionCase,
    check_exact_projection,
    check_exact_projection_cases,
    check_rendered_actions,
    observe_dom_projection,
    read_sql_projection,
)


def test_browser_checker_preserves_pages_and_repeated_controls(project):
    context = CheckContext(
        contract=project["loaded_contract"],
        timings=project["loaded_evidence"],
        source_root=project["root"],
        source_fingerprint=project["fingerprint"],
        contract_sha256=sha256_file(project["contract"]),
        evidence_sha256=sha256_file(project["evidence"]),
        requirements=project["loaded_requirements"],
        requirements_sha256=sha256_file(project["requirements"]),
    )
    passed = check_rendered_actions(
        context,
        rendered_by_page={"/one": ["vote", "vote"], "/two": ["save"]},
        expected_by_page={"/one": ["vote", "vote"], "/two": ["save"]},
        primitive_refs=["task:work"],
    )
    assert passed.passed
    assert passed.facts["instances"] == 3

    failed = check_rendered_actions(
        context,
        rendered_by_page={"/one": ["vote"], "/two": ["save"]},
        expected_by_page={"/one": ["vote", "vote"], "/two": ["save"]},
        primitive_refs=["task:work"],
    )
    assert not failed.passed
    assert "'vote': 1" in failed.findings[0].message


def test_exact_projection_checks_identity_duplicates_and_visible_fields(project):
    context = CheckContext(
        contract=project["loaded_contract"],
        timings=project["loaded_evidence"],
        source_root=project["root"],
        source_fingerprint=project["fingerprint"],
        contract_sha256="0" * 64,
        evidence_sha256="0" * 64,
        requirements=project["loaded_requirements"],
        requirements_sha256="0" * 64,
    )
    expected = (
        ProjectionRow("job-1", {"title": "First", "status": "ready"}),
        ProjectionRow("job-2", {"title": "Second", "status": "running"}),
    )
    passed = check_exact_projection(
        context,
        expected=expected,
        observed=reversed(expected),
        primitive_refs=("task:work",),
    )
    assert passed.passed
    assert passed.facts is not None
    assert passed.facts["expected_sha256"] == passed.facts["observed_sha256"]

    wrong_order = check_exact_projection(
        context,
        expected=expected,
        observed=reversed(expected),
        primitive_refs=("task:work",),
        require_order=True,
    )
    assert not wrong_order.passed
    assert [finding.code for finding in wrong_order.findings] == ["rendered-order-mismatch"]

    failed = check_exact_projection(
        context,
        expected=expected,
        observed=(
            ProjectionRow("job-1", {"title": "Wrong", "status": "ready"}),
            ProjectionRow("job-1", {"title": "First", "status": "ready"}),
            ProjectionRow("job-3", {"title": "Extra", "status": "ready"}),
        ),
        primitive_refs=("task:work",),
    )
    assert not failed.passed
    assert {finding.code for finding in failed.findings} == {
        "duplicate-observed-key",
        "missing-rendered-row",
        "unexpected-rendered-row",
        "rendered-field-mismatch",
    }


def test_exact_projection_result_is_required_by_certificate(project):
    root = Path(project["root"])
    raw = json.loads(Path(project["requirements"]).read_text(encoding="utf-8"))
    raw["claims"][0]["checker_refs"] = ["test.database-ui/v1"]
    Path(project["requirements"]).write_text(json.dumps(raw), encoding="utf-8")
    requirements = load_requirements(project["requirements"])
    context = CheckContext(
        contract=project["loaded_contract"],
        timings=project["loaded_evidence"],
        source_root=root,
        source_fingerprint=project["fingerprint"],
        contract_sha256=sha256_file(project["contract"]),
        evidence_sha256=sha256_file(project["evidence"]),
        requirements=requirements,
        requirements_sha256=sha256_file(project["requirements"]),
    )
    rows = (ProjectionRow("job-1", {"title": "First"}),)
    check_path = root / "artifacts" / "database-ui.json"
    run_checker(
        lambda current: check_exact_projection(
            current,
            expected=rows,
            observed=rows,
            primitive_refs=("task:work",),
            checker="test.database-ui/v1",
        ),
        context,
        check_path,
    )
    certificate_path = root / "artifacts" / "certificate.json"
    issue_certificate(
        project["contract"],
        project["evidence"],
        certificate_path,
        source_root=root,
        requirements_path=project["requirements"],
        check_result_paths=(check_path,),
    )
    verification = verify_certificate(
        certificate_path,
        contract_path=project["contract"],
        evidence_path=project["evidence"],
        requirements_path=project["requirements"],
        source_root=root,
        check_result_paths=(check_path,),
    )
    assert verification.valid

    missing = verify_certificate(
        certificate_path,
        contract_path=project["contract"],
        evidence_path=project["evidence"],
        requirements_path=project["requirements"],
        source_root=root,
        check_result_paths=(),
    )
    assert not missing.valid
    assert "checker results mismatch" in missing.problems
    assert "checker result digests mismatch" in missing.problems


def test_database_and_dom_adapters_produce_the_same_projection(tmp_path: Path):
    database = tmp_path / "app.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs (id TEXT, title TEXT, status TEXT)")
        connection.executemany(
            "INSERT INTO jobs VALUES (?, ?, ?)",
            (("job-1", "First", "ready"), ("job-2", "Second", "running")),
        )
    expected = read_sql_projection(
        database,
        query="SELECT id AS row_key, title, status FROM jobs ORDER BY id",
        key_column="row_key",
        field_columns=("title", "status"),
    )

    class FakeField:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeRow:
        def __init__(self, key: str, fields: dict[str, str]) -> None:
            self.key = key
            self.fields = fields

        def get_attribute(self, name: str) -> str | None:
            return self.key if name == "data-row-key" else None

        def find_element(self, strategy: str, selector: str) -> FakeField:
            assert strategy == "css selector"
            return FakeField(self.fields[selector])

    class FakeDriver:
        def find_elements(self, strategy: str, selector: str) -> list[FakeRow]:
            assert strategy == "css selector"
            assert selector == "[data-result-row]"
            return [
                FakeRow("job-1", {".title": "First", ".status": "ready"}),
                FakeRow("job-2", {".title": "Second", ".status": "running"}),
            ]

    observed = observe_dom_projection(
        FakeDriver(),
        row_selector="[data-result-row]",
        key_attribute="data-row-key",
        field_selectors={"title": ".title", "status": ".status"},
    )
    assert observed == expected


def test_named_projection_cases_preserve_case_identity(project):
    context = CheckContext(
        contract=project["loaded_contract"],
        timings=project["loaded_evidence"],
        source_root=project["root"],
        source_fingerprint=project["fingerprint"],
        contract_sha256="0" * 64,
        evidence_sha256="0" * 64,
        requirements=project["loaded_requirements"],
        requirements_sha256="0" * 64,
    )
    first = ProjectionRow("1", {"title": "First"})
    result = check_exact_projection_cases(
        context,
        cases=(
            ProjectionCase("initial", (first,), (first,), True),
            ProjectionCase("after-delete", (), (first,), True),
        ),
        primitive_refs=("task:work",),
        checker="test.cases/v1",
    )
    assert not result.passed
    assert result.findings[0].subject == "after-delete/1"
