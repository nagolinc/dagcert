from __future__ import annotations

import json
from pathlib import Path

from dagcert.cli import main


def test_math_commands_issue_replay_and_refuse_tampering(tmp_path: Path, capsys) -> None:
    request = tmp_path / "request.json"
    artifact = tmp_path / "theorem.json"
    request.write_text(json.dumps({
        "variables": {"x": "real"}, "assumptions": ["(>= x 0)"],
        "conclusion": "(forall ((y Real)) (=> (>= y x) (>= y 0)))",
    }), encoding="utf-8")
    assert main(["prove-math", str(request), "--output", str(artifact)]) == 0
    assert "not an application certificate" in capsys.readouterr().out
    assert main(["verify-math", str(artifact)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    changed = json.loads(artifact.read_text(encoding="utf-8"))
    changed["conclusion"] = "false"
    artifact.write_text(json.dumps(changed), encoding="utf-8")
    assert main(["verify-math", str(artifact)]) == 2
    assert "SHA-256" in capsys.readouterr().err


def test_math_command_refuses_false_theorem_without_issuing(tmp_path: Path, capsys) -> None:
    request = tmp_path / "request.json"
    artifact = tmp_path / "theorem.json"
    request.write_text(json.dumps({
        "variables": {"x": "real"}, "assumptions": ["(>= x 0)"],
        "conclusion": "(>= x 1)",
    }), encoding="utf-8")
    assert main(["prove-math", str(request), "--output", str(artifact)]) == 2
    assert not artifact.exists()
    assert "invalid" in capsys.readouterr().err


def test_general_family_help_is_discoverable(capsys) -> None:
    assert main(["help"]) == 0
    assert "timing-logic" in capsys.readouterr().out
    assert main(["help", "timing-logic"]) == 0
    guide = capsys.readouterr().out
    assert "first-order linear real" in guide
    assert "prove-math" in guide
