"""Issue and verify certificates over workers, tasks, resources, timings, and optional checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
from time import time
from typing import Any, Iterable, cast
import json

from .analysis import analyze_contract
from .checks import CheckResult, load_check_result
from .contract import Contract, load_contract
from .evidence import load_evidence
from .requirements import audit_translation, load_requirements


class CertificateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CertificateVerification:
    valid: bool
    problems: tuple[str, ...]


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_result_digests(paths: Iterable[str | Path]) -> list[str]:
    """Bind check-result contents without binding machine-local path spellings."""
    return [sha256_file(path) for path in paths]


def _check_result_digests_match(stored: object, expected: list[str]) -> bool:
    if isinstance(stored, list):
        return stored == expected
    if isinstance(stored, dict):
        # Early v2 certificates emitted {path: digest}. Compare their contents so
        # moving a project or changing relative/absolute spelling stays valid.
        values = list(stored.values())
        return all(isinstance(value, str) for value in values) and sorted(values) == sorted(expected)
    return False


def source_manifest(root: str | Path, *, exclude: Iterable[str] = ()) -> dict[str, str]:
    base = Path(root).resolve()
    excluded = {str(item).replace("\\", "/").rstrip("/") for item in exclude}
    ignore = base / ".dagcertignore"
    if ignore.is_file():
        excluded.update(
            line.strip().replace("\\", "/").rstrip("/")
            for line in ignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    ignored_parts = {".git", ".dagcert", "artifacts", "dist", "build", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}
    result: dict[str, str] = {}

    def excluded_path(relative: str) -> bool:
        return any(
            relative == item
            or relative.startswith(item + "/")
            or PurePosixPath(relative).match(item)
            for item in excluded
        )

    def raise_walk_error(error: OSError) -> None:
        raise error

    files: list[Path] = []
    for current, directories, names in os.walk(
        base, topdown=True, onerror=raise_walk_error, followlinks=False
    ):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in directories:
            relative = (current_path / name).relative_to(base).as_posix()
            if name.lower() in ignored_parts or name.lower() in {"venv", ".venv", "env"} or name.lower().endswith("venv"):
                continue
            # A literal directory exclusion covers every descendant. Glob
            # matches are still evaluated per file because matching a directory
            # does not necessarily mean that the pattern matches its contents.
            if any(relative == item or relative.startswith(item + "/") for item in excluded):
                continue
            kept_directories.append(name)
        directories[:] = kept_directories
        files.extend(
            path for name in names
            if (path := current_path / name).is_file()
        )

    for path in sorted(files):
        relative = path.relative_to(base).as_posix()
        if excluded_path(relative):
            continue
        result[relative] = sha256_file(path)
    return result


def source_fingerprint(root: str | Path, *, exclude: Iterable[str] = ()) -> str:
    return sha256(canonical_json(source_manifest(root, exclude=exclude))).hexdigest()


def _primitive_refs(contract: Contract) -> set[str]:
    refs = {f"worker:{item.id}" for item in contract.workers}
    refs.update(f"task:{item.id}" for item in contract.tasks)
    refs.update(f"resource:{item.id}" for item in contract.resources)
    refs.update(f"timing:{task.id}/{case}" for task in contract.tasks for case in task.timings)
    return refs


def _serialized_primitives(contract: Contract, analysis_mapping: dict[str, Any]) -> dict[str, Any]:
    """Return the exact JSON shape stored in a certificate (tuples become arrays)."""
    value = {
        "workers": [asdict(item) for item in contract.workers],
        "tasks": [asdict(item) for item in contract.tasks],
        "resources": [asdict(item) for item in contract.resources],
        "timings": analysis_mapping["timings"],
    }
    return cast(dict[str, Any], json.loads(canonical_json(value)))


def _validate_checks(
    contract: Contract, paths: Iterable[str | Path], *, fingerprint: str,
    contract_sha256: str, evidence_sha256: str, requirements_sha256: str,
) -> tuple[tuple[CheckResult, ...], list[str]]:
    results = tuple(load_check_result(path) for path in paths)
    problems: list[str] = []
    names = [item.checker for item in results]
    if any(not item for item in names) or len(names) != len(set(names)):
        problems.append("checker names must be nonempty and unique")
    valid_refs = _primitive_refs(contract)
    for result in results:
        if not result.passed:
            problems.append(f"checker {result.checker} failed")
        if result.source_fingerprint != fingerprint:
            problems.append(f"checker {result.checker} is bound to another source")
        if result.contract_sha256 != contract_sha256 or result.evidence_sha256 != evidence_sha256:
            problems.append(f"checker {result.checker} is bound to another contract/evidence set")
        if result.requirements_sha256 != requirements_sha256:
            problems.append(f"checker {result.checker} is bound to other English requirements")
        unknown = set(result.primitive_refs) - valid_refs
        if unknown:
            problems.append(f"checker {result.checker} cites unknown primitives: {sorted(unknown)}")
    return results, problems


def issue_certificate(
    contract_path: str | Path,
    evidence_path: str | Path,
    output_path: str | Path,
    *,
    requirements_path: str | Path,
    source_root: str | Path = ".",
    check_result_paths: Iterable[str | Path] = (),
    source_exclude: Iterable[str] = (),
) -> dict[str, Any]:
    check_result_paths = tuple(check_result_paths)
    source_exclude = tuple(source_exclude)
    root = Path(source_root).resolve()
    output = Path(output_path).resolve()
    exclusions = list(source_exclude)
    for candidate in [output, Path(contract_path).resolve(), Path(evidence_path).resolve(), Path(requirements_path).resolve(), *(Path(item).resolve() for item in check_result_paths)]:
        try:
            exclusions.append(candidate.relative_to(root).as_posix())
        except ValueError:
            pass
    manifest = source_manifest(root, exclude=exclusions)
    fingerprint = sha256(canonical_json(manifest)).hexdigest()
    contract = load_contract(contract_path)
    requirements = load_requirements(requirements_path)
    evidence = load_evidence(evidence_path)
    analysis = analyze_contract(contract, evidence, source_fingerprint=fingerprint)
    if not analysis.passed:
        detail = "; ".join(f"[{item.subject}] {item.code}: {item.message}" for item in analysis.findings)
        raise CertificateError("certificate refused: " + detail)
    contract_hash = sha256_file(contract_path)
    evidence_hash = sha256_file(evidence_path)
    requirements_hash = sha256_file(requirements_path)
    checks, check_problems = _validate_checks(
        contract, check_result_paths, fingerprint=fingerprint,
        contract_sha256=contract_hash, evidence_sha256=evidence_hash,
        requirements_sha256=requirements_hash,
    )
    translation_audit = audit_translation(
        requirements, contract, selected_checkers=(check.checker for check in checks)
    )
    check_problems.extend(translation_audit.findings)
    if check_problems:
        raise CertificateError("certificate refused: " + "; ".join(check_problems))
    document: dict[str, Any] = {
        "schema": "dagcert-certificate/v4",
        "issued_at": time(),
        "source_manifest": manifest,
        "source_fingerprint": fingerprint,
        "source_exclude": sorted(set(source_exclude)),
        "contract_sha256": contract_hash,
        "evidence_sha256": evidence_hash,
        "requirements_sha256": requirements_hash,
        "english_requirements": requirements.to_mapping(),
        "translation_audit": translation_audit.to_mapping(),
        "primitives": _serialized_primitives(contract, analysis.to_mapping()),
        "analysis": analysis.to_mapping(),
        "checks": [item.to_mapping() for item in checks],
        "check_result_sha256": _check_result_digests(check_result_paths),
    }
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(canonical_json(document) + b"\n")
    temporary.replace(output)
    return document


def verify_certificate(
    certificate_path: str | Path,
    *,
    contract_path: str | Path,
    evidence_path: str | Path,
    requirements_path: str | Path,
    source_root: str | Path = ".",
    check_result_paths: Iterable[str | Path] = (),
    source_exclude: Iterable[str] = (),
) -> CertificateVerification:
    check_result_paths = tuple(check_result_paths)
    source_exclude = tuple(source_exclude)
    try:
        raw = json.loads(Path(certificate_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CertificateVerification(False, (f"certificate cannot be read: {exc}",))
    if not isinstance(raw, dict) or raw.get("schema") != "dagcert-certificate/v4":
        return CertificateVerification(False, ("certificate schema must be dagcert-certificate/v4",))
    expected_fields = {
        "schema", "issued_at", "source_manifest", "source_fingerprint", "source_exclude",
        "contract_sha256", "evidence_sha256", "requirements_sha256",
        "english_requirements", "translation_audit", "primitives", "analysis", "checks",
        "check_result_sha256", "certificate_sha256",
    }
    if set(raw) != expected_fields:
        unexpected = sorted(set(raw) - expected_fields)
        missing = sorted(expected_fields - set(raw))
        return CertificateVerification(False, (
            f"certificate fields mismatch: unexpected={unexpected}, missing={missing}",
        ))
    problems: list[str] = []
    claimed = raw.pop("certificate_sha256", None)
    if claimed != sha256(canonical_json(raw)).hexdigest():
        problems.append("certificate digest mismatch")
    root = Path(source_root).resolve()
    exclusions = list(source_exclude)
    for candidate in [Path(certificate_path).resolve(), Path(contract_path).resolve(), Path(evidence_path).resolve(), Path(requirements_path).resolve(), *(Path(item).resolve() for item in check_result_paths)]:
        try:
            exclusions.append(candidate.relative_to(root).as_posix())
        except ValueError:
            pass
    manifest = source_manifest(root, exclude=exclusions)
    fingerprint = sha256(canonical_json(manifest)).hexdigest()
    if raw.get("source_exclude") != sorted(set(source_exclude)):
        problems.append("source exclusions mismatch")
    if raw.get("source_manifest") != manifest or raw.get("source_fingerprint") != fingerprint:
        problems.append("source identity mismatch")
    contract_hash, evidence_hash = sha256_file(contract_path), sha256_file(evidence_path)
    requirements_hash = sha256_file(requirements_path)
    if raw.get("contract_sha256") != contract_hash:
        problems.append("contract digest mismatch")
    if raw.get("evidence_sha256") != evidence_hash:
        problems.append("evidence digest mismatch")
    if raw.get("requirements_sha256") != requirements_hash:
        problems.append("English requirements digest mismatch")
    try:
        contract = load_contract(contract_path)
        requirements = load_requirements(requirements_path)
        if raw.get("english_requirements") != requirements.to_mapping():
            problems.append("serialized English requirements no longer match")
        evidence = load_evidence(evidence_path)
        analysis = analyze_contract(contract, evidence, source_fingerprint=fingerprint)
        if not analysis.passed or raw.get("analysis") != analysis.to_mapping():
            problems.append("primitive analysis no longer matches")
        expected_primitives = _serialized_primitives(contract, analysis.to_mapping())
        if raw.get("primitives") != expected_primitives:
            problems.append("serialized primitives no longer match")
        checks, check_problems = _validate_checks(
            contract, check_result_paths, fingerprint=fingerprint,
            contract_sha256=contract_hash, evidence_sha256=evidence_hash,
            requirements_sha256=requirements_hash,
        )
        problems.extend(check_problems)
        translation_audit = audit_translation(
            requirements, contract, selected_checkers=(check.checker for check in checks)
        )
        problems.extend(translation_audit.findings)
        if raw.get("translation_audit") != translation_audit.to_mapping():
            problems.append("English-to-formal translation audit no longer matches")
        if raw.get("checks") != [item.to_mapping() for item in checks]:
            problems.append("checker results mismatch")
        expected_check_hashes = _check_result_digests(check_result_paths)
        if not _check_result_digests_match(raw.get("check_result_sha256"), expected_check_hashes):
            problems.append("checker result digests mismatch")
    except (OSError, ValueError) as exc:
        problems.append(f"current inputs are invalid: {exc}")
    return CertificateVerification(not problems, tuple(problems))
