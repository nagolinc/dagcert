"""Small extension boundary for application-specific certificate checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
import json
import re

from .contract import Contract
from .evidence import TimingSample
from .requirements import EnglishRequirements


@dataclass(frozen=True, slots=True)
class CheckFinding:
    code: str
    subject: str
    message: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    checker: str
    passed: bool
    source_fingerprint: str
    contract_sha256: str
    evidence_sha256: str
    requirements_sha256: str
    primitive_refs: tuple[str, ...] = ()
    findings: tuple[CheckFinding, ...] = ()
    facts: Mapping[str, Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": "dagcert-check-result/v2",
            "checker": self.checker,
            "passed": self.passed,
            "source_fingerprint": self.source_fingerprint,
            "contract_sha256": self.contract_sha256,
            "evidence_sha256": self.evidence_sha256,
            "requirements_sha256": self.requirements_sha256,
            "primitive_refs": list(self.primitive_refs),
            "findings": [asdict(item) for item in self.findings],
            "facts": dict(self.facts) if self.facts is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CheckContext:
    contract: Contract
    timings: tuple[TimingSample, ...]
    source_root: Path
    source_fingerprint: str
    contract_sha256: str
    evidence_sha256: str
    requirements: EnglishRequirements
    requirements_sha256: str


class Checker(Protocol):
    def __call__(self, context: CheckContext) -> CheckResult: ...


def run_checker(checker: Checker, context: CheckContext, output_path: str | Path) -> CheckResult:
    result = checker(context)
    if result.source_fingerprint != context.source_fingerprint:
        raise ValueError("checker returned the wrong source fingerprint")
    if result.contract_sha256 != context.contract_sha256 or result.evidence_sha256 != context.evidence_sha256:
        raise ValueError("checker returned the wrong contract/evidence binding")
    if result.requirements_sha256 != context.requirements_sha256:
        raise ValueError("checker returned the wrong English requirements binding")
    write_check_result(result, output_path)
    return result


def write_check_result(result: CheckResult, output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    # Write exact UTF-8/LF bytes so a checker result has the same digest on
    # Windows, in a Git checkout, and in an installed wheel.
    temporary.write_bytes(
        json.dumps(result.to_mapping(), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    temporary.replace(output)


def load_check_result(path: str | Path) -> CheckResult:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "dagcert-check-result/v2":
        raise ValueError("check result schema must be dagcert-check-result/v2")
    expected_fields = {
        "schema", "checker", "passed", "source_fingerprint", "contract_sha256",
        "evidence_sha256", "requirements_sha256", "primitive_refs", "findings", "facts",
    }
    if set(raw) != expected_fields:
        raise ValueError("check result has unexpected or missing fields")
    if not isinstance(raw["checker"], str) or not raw["checker"].strip():
        raise ValueError("check result checker must be a nonempty string")
    if not isinstance(raw["passed"], bool):
        raise ValueError("check result passed must be boolean")
    for field in (
        "source_fingerprint", "contract_sha256", "evidence_sha256", "requirements_sha256",
    ):
        value = raw[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"check result {field} must be a lowercase SHA-256 digest")
    primitive_refs = raw["primitive_refs"]
    if (
        not isinstance(primitive_refs, list)
        or not all(isinstance(item, str) and item.strip() for item in primitive_refs)
        or len(primitive_refs) != len(set(primitive_refs))
    ):
        raise ValueError("check result primitive_refs must be unique nonempty strings")
    findings = raw.get("findings", ())
    if not isinstance(findings, list):
        raise ValueError("check result findings must be an array")
    parsed_findings: list[CheckFinding] = []
    for item in findings:
        if not isinstance(item, dict) or set(item) != {"code", "subject", "message"}:
            raise ValueError("check result finding has unexpected fields")
        if not all(isinstance(item[field], str) and item[field].strip() for field in item):
            raise ValueError("check result finding fields must be nonempty strings")
        parsed_findings.append(CheckFinding(item["code"], item["subject"], item["message"]))
    if raw["facts"] is not None and not isinstance(raw["facts"], dict):
        raise ValueError("check result facts must be an object or null")
    return CheckResult(
        checker=raw["checker"], passed=raw["passed"],
        source_fingerprint=raw["source_fingerprint"],
        contract_sha256=raw["contract_sha256"],
        evidence_sha256=raw["evidence_sha256"],
        requirements_sha256=raw["requirements_sha256"],
        primitive_refs=tuple(primitive_refs),
        findings=tuple(parsed_findings),
        facts=dict(raw["facts"]) if raw["facts"] is not None else None,
    )
