from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def _collect_with(
    safe_cache: Path, *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_workspace_hygiene.py",
            "-o",
            f"cache_dir={safe_cache}",
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pytest_rejects_repository_root_cache_override(tmp_path: Path) -> None:
    polluted = ROOT / ".pytest-hygiene-cache-probe"
    assert not polluted.exists()
    result = _collect_with(tmp_path / "cache", "-o", f"cache_dir={polluted}")
    assert result.returncode != 0
    assert "cache_dir must be outside the repository or below .cache" in result.stderr
    assert not polluted.exists()


def test_pytest_rejects_repository_basetemp_override(tmp_path: Path) -> None:
    polluted = ROOT / ".pytest-hygiene-temp-probe"
    assert not polluted.exists()
    result = _collect_with(tmp_path / "cache", f"--basetemp={polluted}")
    assert result.returncode != 0
    assert "--basetemp must use the operating-system temporary directory" in result.stderr
    assert not polluted.exists()
