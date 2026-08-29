"""Repository-wide pytest workspace-hygiene guard."""

from pathlib import Path

import pytest


def _resolved_pytest_path(root: Path, value: object) -> Path:
    path = Path(str(value))
    return (path if path.is_absolute() else root / path).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    """Refuse pytest overrides that create disposable trees in the repository."""
    root = Path(str(config.rootpath)).resolve()
    cache_path = _resolved_pytest_path(root, config.getini("cache_dir"))
    safe_cache_root = (root / ".cache").resolve()
    if _is_within(cache_path, root) and not _is_within(cache_path, safe_cache_root):
        raise pytest.UsageError(
            "pytest cache_dir must be outside the repository or below .cache; "
            f"refusing {cache_path}"
        )

    basetemp = getattr(config.option, "basetemp", None)
    if basetemp is not None:
        basetemp_path = _resolved_pytest_path(root, basetemp)
        if _is_within(basetemp_path, root):
            raise pytest.UsageError(
                "pytest --basetemp must use the operating-system temporary directory, "
                f"not the repository; refusing {basetemp_path}"
            )
