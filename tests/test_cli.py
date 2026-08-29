from pathlib import Path
import json

from dagcert.cli import main


def test_cli_lint_analyze_issue_verify(project, capsys):
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


def test_cli_lint_rejects_incomplete_translation(project, capsys):
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
        return {"exception_verifier": {"result": "not-applicable"}}

    monkeypatch.setattr("dagcert.cli.check_python_sources", fake_source_verification)
    assert main([
        "lint", str(root / "dag_contract.json"),
        "--requirements", str(root / "english_requirements.json"),
    ]) == 0
    assert captured["source_manifest_paths"]
    assert len(captured["external_contracts"]) == 1
    assert "source verification" in capsys.readouterr().out


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
