from pathlib import Path
import json

from dagcert import SourceProofBackend
from dagcert.cli import main


def _proved_source_verification(*_args, **_kwargs):
    return {
        "typechecker": {
            "checker": "mypy",
            "version": "test",
            "mode": "strict",
            "files": ["app.py"],
        },
        "exception_verifier": {
            "checker": "nagini",
            "version": "test",
            "result": "proved",
            "scope": "test-double",
        },
        "external_contracts": [],
        "signatures": [],
    }


def test_cli_lint_analyze_issue_verify(project, capsys, monkeypatch):
    monkeypatch.setattr(
        "dagcert.cli.check_python_sources", _proved_source_verification,
    )
    monkeypatch.setattr(
        "dagcert.certificate.check_python_sources", _proved_source_verification,
    )
    root = Path(project["root"])
    certificate = root / "artifacts" / "certificate.json"
    assert main(["lint", str(project["contract"]), "--requirements", str(project["requirements"])]) == 0
    assert "English-to-formal coverage audit: passed" in capsys.readouterr().out
    assert main([
        "analyze", str(project["contract"]), str(project["evidence"]),
        "--requirements", str(project["requirements"]), "--source-root", str(root),
    ]) == 0
    assert main(["issue", "--contract", str(project["contract"]), "--evidence", str(project["evidence"]), "--requirements", str(project["requirements"]), "--source-root", str(root), "--output", str(certificate)]) == 0
    assert main(["verify", str(certificate), "--contract", str(project["contract"]), "--evidence", str(project["evidence"]), "--requirements", str(project["requirements"]), "--source-root", str(root)]) == 0


def test_cli_lint_rejects_incomplete_translation(project, capsys, monkeypatch):
    monkeypatch.setattr(
        "dagcert.cli.check_python_sources", _proved_source_verification,
    )
    requirements = Path(project["requirements"])
    raw = json.loads(requirements.read_text(encoding="utf-8"))
    raw["claims"][0]["primitive_refs"] = ["task:work"]
    requirements.write_text(json.dumps(raw), encoding="utf-8")
    assert main([
        "lint", str(project["contract"]), "--requirements", str(requirements)
    ]) == 2
    assert "formal timings lack an English claim" in capsys.readouterr().err


def test_cli_lint_checks_external_contracts_with_the_exact_manifest(
    monkeypatch, capsys,
):
    root = Path(__file__).parents[1] / "examples" / "certified_external_url"
    captured = {}

    def fake_source_verification(_root, _signatures, **kwargs):
        captured.update(kwargs)
        return {
            "exception_verifier": {
                "checker": "nagini", "result": "not-applicable",
            },
        }

    monkeypatch.setattr("dagcert.cli.check_python_sources", fake_source_verification)
    assert main([
        "lint", str(root / "dag_contract.json"),
        "--requirements", str(root / "english_requirements.json"),
    ]) == 0
    assert captured["source_manifest_paths"]
    assert len(captured["external_contracts"]) == 1
    assert "source verification" in capsys.readouterr().out


def test_cli_requires_an_executable_and_digest_for_maledictus(project, capsys):
    assert main([
        "lint", str(project["contract"]), "--requirements", str(project["requirements"]),
        "--proof-backend", "maledictus",
    ]) == 2
    assert "requires --proof-backend-executable" in capsys.readouterr().err


def test_cli_passes_explicit_maledictus_backend_to_source_verification(
    project, monkeypatch, capsys,
):
    captured = {}

    def fake_source_verification(_root, _signatures, **kwargs):
        captured.update(kwargs)
        return {
            "exception_verifier": {
                "checker": "maledictus", "version": "0.1.0", "result": "proved",
            },
        }

    executable = Path(project["root"]) / "maledictus.exe"
    executable.write_bytes(b"fake executable")
    monkeypatch.setattr("dagcert.cli.check_python_sources", fake_source_verification)
    assert main([
        "lint", str(project["contract"]), "--requirements", str(project["requirements"]),
        "--proof-backend", "maledictus",
        "--proof-backend-executable", str(executable),
        "--proof-backend-sha256", "a" * 64,
    ]) == 0
    assert captured["proof_backend"] == SourceProofBackend.maledictus(
        executable, "a" * 64,
    )
    assert "maledictus 0.1.0 passed" in capsys.readouterr().out


def test_init_is_non_destructive(tmp_path: Path):
    root = tmp_path / "new-app"
    assert main(["init", str(root)]) == 0
    original = (root / "dag_contract.json").read_text(encoding="utf-8")
    original_requirements = (root / "english_requirements.json").read_text(encoding="utf-8")
    assert main(["init", str(root)]) == 0
    assert (root / "dag_contract.json").read_text(encoding="utf-8") == original
    assert (root / "english_requirements.json").read_text(encoding="utf-8") == original_requirements


def test_installed_help_lists_and_reads_database_ui_guide(capsys):
    assert main(["help"]) == 0
    listing = capsys.readouterr().out
    assert "use the shipped /stats viewer" in listing
    assert "app-surfaces" in listing
    assert "database-ui" in listing

    assert main(["help", "app-surfaces"]) == 0
    surfaces = capsys.readouterr().out
    assert "dagcert-violation-banner.js" in surfaces
    assert "/dagcert/runtime-events" in surfaces

    assert main(["help", "database-ui"]) == 0
    guide = capsys.readouterr().out
    assert "database entries appear correctly in the UI" in guide
    assert "examples.optional_browser_checker" in guide
    assert "examples.certified_database_ui" in guide
    assert "insertion" in guide and "pagination" in guide
    assert "--check-result" in guide


def test_installed_help_exposes_generic_structured_workflow_examples(capsys):
    assert main(["help"]) == 0
    listing = capsys.readouterr().out
    for topic in (
        "fork-join",
        "reservation-lifecycle",
        "bounded-buffer",
        "finite-confidence",
        "external-verified-leaf",
        "composed-worker-pipeline",
    ):
        assert topic in listing

    assert main(["help", "fork-join"]) == 0
    assert "parallel_all" in capsys.readouterr().out
    assert main(["help", "bounded-buffer"]) == 0
    assert "bounded_non_starvation" in capsys.readouterr().out
    assert main(["help", "finite-confidence"]) == 0
    confidence = capsys.readouterr().out
    assert "union bound" in confidence
    assert "finite_repeat" in confidence
