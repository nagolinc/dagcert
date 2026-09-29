from __future__ import annotations

from pathlib import Path

import pytest

from dagcert.proof_sources import (
    ProofSourceError,
    resolve_python_import_from_edges,
    resolve_python_proof_sources,
)


def _manifest(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_recursive_application_imports_are_proof_only_not_roots(tmp_path: Path):
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text('"""Application package."""\n', encoding="utf-8")
    (package / "leaf.py").write_text(
        "def normalize(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    (package / "helper.py").write_text(
        "from app.leaf import normalize\n\n"
        "def prepare(value: str) -> str:\n    return normalize(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "worker.py").write_text(
        "from app.helper import prepare\n\n"
        "def run(value: str) -> str:\n    return prepare(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "unrelated.py").write_text("raise RuntimeError()\n", encoding="utf-8")

    closure = resolve_python_proof_sources(
        tmp_path, ["worker.py"], _manifest(tmp_path)
    )

    assert closure.roots == ("worker.py",)
    assert closure.proof_only_files == (
        "app/__init__.py",
        "app/helper.py",
        "app/leaf.py",
    )
    assert "unrelated.py" not in closure.files
    explicit_edges = [edge for edge in closure.edges if edge.kind == "source-import"]
    assert [
        (edge.importer_path, edge.module, edge.provider_path)
        for edge in explicit_edges
    ] == [
        ("app/helper.py", "app.leaf", "app/leaf.py"),
        ("worker.py", "app.helper", "app/helper.py"),
    ]


def test_relative_import_and_parent_initializer_are_resolved(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (package / "worker.py").write_text(
        "from .helper import VALUE\n", encoding="utf-8"
    )

    closure = resolve_python_proof_sources(
        tmp_path, ["pkg/worker.py"], _manifest(tmp_path)
    )

    assert closure.proof_only_files == ("pkg/__init__.py", "pkg/helper.py")
    assert any(
        edge.module == "pkg.helper" and edge.provider_path == "pkg/helper.py"
        for edge in closure.edges
    )


@pytest.mark.parametrize("initializer", [True, False])
def test_package_member_import_includes_the_source_module(
    tmp_path: Path, initializer: bool
):
    package = tmp_path / "pkg"
    package.mkdir()
    if initializer:
        (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text(
        "from pkg import helper\n\nVALUE: int = helper.VALUE\n", encoding="utf-8"
    )

    closure = resolve_python_proof_sources(
        tmp_path, ["worker.py"], _manifest(tmp_path)
    )

    assert "pkg/helper.py" in closure.proof_only_files
    assert any(
        edge.module == "pkg.helper" and edge.provider_path == "pkg/helper.py"
        for edge in closure.edges
    )


def test_package_member_import_reports_the_bound_child_module_provider(
    tmp_path: Path,
):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (package / "helper.py").write_text("VALUE: int = 2\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text(
        "from pkg import helper\n\nVALUE: int = helper.VALUE\n", encoding="utf-8"
    )

    edges = resolve_python_import_from_edges(
        tmp_path, ["pkg/__init__.py", "pkg/helper.py", "worker.py"]
    )

    assert [
        (edge.importer_path, edge.module, edge.provider_path, edge.imported_symbols)
        for edge in edges
    ] == [("worker.py", "pkg.helper", "pkg/helper.py", ())]


def test_package_value_import_still_reports_the_initializer_symbol(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text("from pkg import VALUE\n", encoding="utf-8")

    edges = resolve_python_import_from_edges(
        tmp_path, ["pkg/__init__.py", "worker.py"]
    )

    assert [
        (edge.importer_path, edge.module, edge.provider_path, edge.imported_symbols)
        for edge in edges
    ] == [("worker.py", "pkg", "pkg/__init__.py", ("VALUE",))]


def test_ambiguous_application_module_refuses(tmp_path: Path):
    (tmp_path / "worker.py").write_text("from shared import value\n", encoding="utf-8")
    (tmp_path / "shared.py").write_text("value: int = 1\n", encoding="utf-8")
    package = tmp_path / "shared"
    package.mkdir()
    (package / "__init__.py").write_text("value: int = 2\n", encoding="utf-8")

    with pytest.raises(ProofSourceError, match="ambiguous"):
        resolve_python_proof_sources(tmp_path, ["worker.py"], _manifest(tmp_path))


def test_external_import_is_not_mislabeled_application_source(tmp_path: Path):
    (tmp_path / "worker.py").write_text(
        "from urllib.parse import urlsplit\n", encoding="utf-8"
    )

    closure = resolve_python_proof_sources(
        tmp_path, ["worker.py"], _manifest(tmp_path)
    )

    assert closure.proof_only_files == ()
    assert closure.edges == ()


def test_imported_application_file_cannot_be_excluded_from_manifest(tmp_path: Path):
    (tmp_path / "worker.py").write_text(
        "from ignored_helper import prepare\n", encoding="utf-8"
    )
    (tmp_path / "ignored_helper.py").write_text(
        "def prepare() -> int:\n    return 1\n", encoding="utf-8"
    )

    with pytest.raises(ProofSourceError, match="outside the exact manifest"):
        resolve_python_proof_sources(tmp_path, ["worker.py"], ["worker.py"])


def test_package_member_source_cannot_be_excluded_from_manifest(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text(
        "from pkg import helper\n", encoding="utf-8"
    )

    with pytest.raises(ProofSourceError, match="outside the exact manifest"):
        resolve_python_proof_sources(
            tmp_path, ["worker.py"], ["worker.py", "pkg/__init__.py"]
        )
