"""Bind declared Python requirements to installed bytes and import resolution."""
from __future__ import annotations

import base64
from hashlib import new as hash_new, sha256
from importlib import metadata
from importlib.machinery import PathFinder
import json
from pathlib import Path
import platform
import sys
import tomllib
from typing import Iterable, Mapping
from urllib.parse import parse_qs, urldefrag

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


class DependencyError(ValueError):
    pass


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _project_requirements(path: Path) -> list[str]:
    project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    if "dependencies" in project.get("dynamic", []):
        raise DependencyError("dynamic project dependencies need an explicit requirements file")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
        raise DependencyError("project.dependencies must be a list of requirement strings")
    return dependencies


def _read_requirements(
    root: Path, relative: str, manifest: Mapping[str, str], inputs: dict[str, str],
) -> list[Requirement]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.relative_to(root).as_posix() not in manifest:
        raise DependencyError(f"dependency file must be included in the source manifest: {relative}")
    name = path.relative_to(root).as_posix()
    if name in inputs:
        return []
    inputs[name] = sha256(path.read_bytes()).hexdigest()
    if inputs[name] != manifest[name]:
        raise DependencyError(f"dependency file changed during checking: {name}")
    lines = _project_requirements(path) if path.name == "pyproject.toml" else path.read_text(encoding="utf-8-sig").splitlines()
    result: list[Requirement] = []
    for raw in lines:
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            included = path.parent / line.split(None, 1)[1]
            result.extend(_read_requirements(root, str(included), manifest, inputs))
            continue
        try:
            result.append(Requirement(line))
        except ValueError as exc:
            raise DependencyError(f"unsupported dependency declaration in {name}: {line}") from exc
    return result


def _check_requirement(requirement: Requirement, dist: metadata.Distribution) -> dict[str, object] | None:
    if requirement.specifier and not requirement.specifier.contains(dist.version, prereleases=True):
        raise DependencyError(f"{requirement}: installed version is {dist.version}")
    provenance_text = dist.read_text("direct_url.json")
    provenance = json.loads(provenance_text) if provenance_text else None
    if isinstance(provenance, dict) and provenance.get("dir_info", {}).get("editable"):
        raise DependencyError(f"{requirement.name}: editable installs do not bind installed runtime bytes")
    if not requirement.url:
        return provenance
    url, fragment = urldefrag(requirement.url)
    repository, separator, commit = url.removeprefix("git+").rpartition("@")
    if not url.startswith("git+") or not separator or len(commit) not in (40, 64) or any(c not in "0123456789abcdef" for c in commit.lower()):
        raise DependencyError(f"{requirement.name}: URL dependencies require an immutable full Git commit")
    subdirectory = parse_qs(fragment).get("subdirectory", [None])[0]
    if fragment and set(parse_qs(fragment)) != {"subdirectory"}:
        raise DependencyError(f"{requirement.name}: unsupported Git URL fragment")
    vcs = provenance.get("vcs_info", {}) if isinstance(provenance, dict) else {}
    if not isinstance(provenance, dict) or provenance.get("url") != repository or vcs.get("vcs") != "git" or vcs.get("commit_id") != commit or provenance.get("subdirectory") != subdirectory:
        raise DependencyError(f"{requirement.name}: installed Git provenance does not match {repository}@{commit}")
    return provenance


def _installed_files(dist: metadata.Distribution) -> tuple[dict[str, str], set[Path], set[str]]:
    files = dist.files
    if not files:
        raise DependencyError(f"{dist.name}: installed file records are missing")
    hashes: dict[str, str] = {}
    owned: set[Path] = set()
    modules: set[str] = set()
    for entry in files:
        relative = Path(str(entry))
        if not relative.parts or relative.parts[0] == ".." or any(p.endswith((".dist-info", ".egg-info")) or p == "__pycache__" for p in relative.parts):
            continue
        if relative.suffix in {".pyc", ".pyo"}:
            continue
        path = Path(str(dist.locate_file(entry))).resolve()
        if not entry.hash or not path.is_file():
            raise DependencyError(f"{dist.name}: missing file or RECORD hash for {entry}")
        data = path.read_bytes()
        actual = base64.urlsafe_b64encode(hash_new(entry.hash.mode, data).digest()).rstrip(b"=").decode()
        if actual != entry.hash.value:
            raise DependencyError(f"{dist.name}: installed file differs from RECORD: {entry}")
        hashes[relative.as_posix()] = sha256(data).hexdigest()
        owned.add(path)
        if relative.suffix in {".py", ".pyd", ".so"}:
            top = relative.parts[0].split(".", 1)[0] if len(relative.parts) == 1 else relative.parts[0]
            if top.isidentifier():
                modules.add(top)
    if not hashes:
        raise DependencyError(f"{dist.name}: no installed runtime files were bound")
    return hashes, owned, modules


def _check_imports(root: Path, owned: set[Path], modules: set[str]) -> None:
    # Check fresh resolution AND already-loaded modules: sys.modules can retain
    # a checkout import even after PYTHONPATH/sys.path has been corrected.
    for name in sorted(modules):
        spec = PathFinder.find_spec(name, [str(root), *sys.path])
        if spec is None:
            raise DependencyError(f"{name}: installed module cannot be resolved")
        if spec.origin and Path(spec.origin).resolve() not in owned:
            raise DependencyError(f"{name}: import shadowing; resolved outside installed distribution: {spec.origin}")
        if spec.origin is None:
            for location in spec.submodule_search_locations or ():
                if not any(p.is_relative_to(Path(location).resolve()) for p in owned):
                    raise DependencyError(f"{name}: namespace import outside installed distributions: {location}")
    for name, module in tuple(sys.modules.items()):
        if name.split(".", 1)[0] not in modules or module is None:
            continue
        origin = getattr(module, "__file__", None)
        if origin and Path(origin).resolve() not in owned:
            raise DependencyError(f"{name}: loaded module is outside installed distribution: {origin}")


def check_python_dependencies(
    root: Path, manifest: Mapping[str, str], requirements: Iterable[str] | None = None,
) -> dict[str, object] | None:
    """Fail closed on ambiguous environments, pin drift, modified or shadowed packages.

    No declaration means no dependency-environment claim. Once a requirements
    file or static project declaration exists, issuance cannot silently skip it.
    """
    root = root.resolve()
    candidates = sorted(p.name for p in root.glob("requirements*.txt"))
    project = root / "pyproject.toml"
    if project.is_file():
        declaration = tomllib.loads(project.read_text(encoding="utf-8")).get("project", {})
        if declaration.get("dependencies") or "dependencies" in declaration.get("dynamic", []):
            candidates.append(project.name)
    selected = list(requirements) if requirements is not None else candidates
    if requirements is None and len(candidates) > 1:
        raise DependencyError("multiple Python dependency declarations; select python_requirements / --python-requirements explicitly")
    if not selected:
        if candidates:
            raise DependencyError("declared Python dependencies cannot be skipped")
        return None
    inputs: dict[str, str] = {}
    pending: list[tuple[Requirement, frozenset[str]]] = []
    for path in selected:
        pending.extend((r, frozenset()) for r in _read_requirements(root, path, manifest, inputs))
    records: dict[str, object] = {}
    processed: set[tuple[str, frozenset[str]]] = set()
    owned: set[Path] = set()
    modules: set[str] = set()
    while pending:
        requirement, parent_extras = pending.pop()
        if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in {"", *parent_extras}):
            continue
        name = canonicalize_name(requirement.name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            raise DependencyError(f"{requirement.name}: required package is not installed") from exc
        provenance = _check_requirement(requirement, dist)
        key = name, frozenset(requirement.extras)
        if key in processed:
            continue
        processed.add(key)
        if name not in records:
            hashes, package_files, package_modules = _installed_files(dist)
            owned.update(package_files)
            modules.update(package_modules)
            records[name] = {"version": dist.version, "provenance": provenance,
                             "runtime_files_sha256": _digest(hashes), "runtime_file_count": len(hashes)}
        pending.extend((Requirement(r), key[1]) for r in dist.requires or ())
    _check_imports(root, owned, modules)
    return {"schema": "dagcert-python-dependencies/v1", "requirements": sorted(selected),
            "input_sha256": inputs, "distributions": records,
            "python": {"implementation": platform.python_implementation(), "version": platform.python_version(), "platform": sys.platform}}
