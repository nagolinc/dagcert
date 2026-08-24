"""Optional one-claim-per-worker semantic-audit handoff.

The active ChatGPT/Codex agent prepares sealed claim directories, gives each
worker-prompt.txt to a different fresh Luna subagent, saves each final JSON as
worker-response.json, and accepts the directory. Nothing runs automatically at
build, release, issuance, or startup.
"""

from __future__ import annotations

from argparse import ArgumentParser
from base64 import b64encode
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

from dagcert import (
    CheckContext,
    CheckFinding,
    CheckResult,
    analyze_contract,
    load_check_result,
    load_contract,
    load_evidence,
    load_requirements,
    sha256_file,
    source_manifest,
    write_check_result,
)
from dagcert.certificate import canonical_json


DEFAULT_MAX_AUDIT_PACKET_BYTES = 200_000


RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "audit_packet_sha256", "passed", "summary", "claim_reasoning",
        "rule0_assessment", "reviewed_files", "strengths", "weaknesses",
        "improvements", "test_fitting_risks", "evidence_gaps", "findings",
    ],
    "properties": {
        "audit_packet_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "passed": {"type": "boolean"},
        "summary": {"type": "string", "minLength": 200},
        "claim_reasoning": {"type": "string", "minLength": 200},
        "rule0_assessment": {"type": "string", "minLength": 200},
        "reviewed_files": {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "strengths": {"type": "array", "items": {"$ref": "#/$defs/observation"}},
        "weaknesses": {"type": "array", "items": {"$ref": "#/$defs/observation"}},
        "improvements": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["priority", "subject", "recommendation", "rationale"],
                "properties": {
                    "priority": {"enum": ["high", "medium", "low"]},
                    "subject": {"type": "string", "minLength": 1},
                    "recommendation": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
        },
        "test_fitting_risks": {"type": "array", "items": {"$ref": "#/$defs/observation"}},
        "evidence_gaps": {"type": "array", "items": {"$ref": "#/$defs/observation"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "subject", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "subject": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    },
    "$defs": {
        "observation": {
            "type": "object", "additionalProperties": False,
            "required": ["subject", "evidence", "impact"],
            "properties": {
                "subject": {"type": "string", "minLength": 1},
                "evidence": {"type": "string", "minLength": 1},
                "impact": {"type": "string", "minLength": 1},
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class AuditContext(CheckContext):
    source_manifest_entries: Mapping[str, str]
    source_files: Mapping[str, Mapping[str, str]]
    check_results: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AuditHandoff:
    claim_index: int
    directory: Path
    packet_path: Path
    prompt_path: Path
    response_schema_path: Path
    response_path: Path
    packet_sha256: str


def prepare_handoffs(
    context: CheckContext,
    *,
    output_directory: str | Path,
    max_packet_bytes: int = DEFAULT_MAX_AUDIT_PACKET_BYTES,
) -> tuple[AuditHandoff, ...]:
    """Create one sealed directory and prompt for each independent claim audit."""
    if isinstance(max_packet_bytes, bool) or not isinstance(max_packet_bytes, int) or max_packet_bytes < 1:
        raise ValueError("max_packet_bytes must be a positive integer")
    output = Path(output_directory)
    shared = _shared_packet(context)
    prepared: list[tuple[int, dict[str, Any], bytes, str, str]] = []
    for index, claim_value in enumerate(context.requirements.claims, 1):
        claim = claim_value.to_mapping()
        packet = {
            "schema": "dagcert-semantic-audit-packet/v3",
            "claim_index": index,
            "claim": dict(claim),
            **shared,
        }
        packet_bytes = canonical_json(packet)
        packet_digest = sha256(packet_bytes).hexdigest()
        prompt = _worker_prompt(packet, packet_digest)
        _enforce_handoff_size(index, "packet", len(packet_bytes), max_packet_bytes)
        _enforce_handoff_size(index, "worker prompt", len(prompt.encode("utf-8")), max_packet_bytes)
        prepared.append((index, packet, packet_bytes, packet_digest, prompt))

    # Preflight every claim before creating anything. One oversized claim aborts
    # the entire audit instead of leaving launchable partial handoffs behind.
    output.mkdir(parents=True, exist_ok=True)
    handoffs: list[AuditHandoff] = []
    for index, _packet, packet_bytes, packet_digest, prompt in prepared:
        claim_directory = output / f"claim-{index:03d}"
        claim_directory.mkdir(parents=True, exist_ok=True)
        packet_path = claim_directory / "audit-packet.json"
        schema_path = claim_directory / "response-schema.json"
        prompt_path = claim_directory / "worker-prompt.txt"
        response_path = claim_directory / "worker-response.json"
        packet_path.write_bytes(packet_bytes + b"\n")
        schema_path.write_text(json.dumps(RESPONSE_SCHEMA, indent=2) + "\n", encoding="utf-8")
        prompt_path.write_text(prompt, encoding="utf-8")
        handoffs.append(AuditHandoff(
            index,
            claim_directory,
            packet_path,
            prompt_path,
            schema_path,
            response_path,
            packet_digest,
        ))
    manifest = {
        "schema": "dagcert-semantic-audit-manifest/v1",
        "source_fingerprint": context.source_fingerprint,
        "contract_sha256": context.contract_sha256,
        "evidence_sha256": context.evidence_sha256,
        "requirements_sha256": context.requirements_sha256,
        "claims": [
            {
                "claim_index": item.claim_index,
                "directory": item.directory.name,
                "packet_sha256": item.packet_sha256,
            }
            for item in handoffs
        ],
    }
    (output / "audit-manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    return tuple(handoffs)


def _enforce_handoff_size(claim_index: int, artifact: str, size: int, limit: int) -> None:
    if size <= limit:
        return
    raise ValueError(
        f"claim {claim_index} audit {artifact} is {size:,} bytes; the limit is {limit:,} bytes. "
        "Refusing to materialize or launch this audit. Oversized handoffs usually mean source, "
        "evidence, checker output, or a proof/reachability enumeration was duplicated. Store the "
        "large object once in a content-addressed artifact, keep timing samples to compact facts "
        "and digests, and reference the shared object by SHA-256. Do not raise the limit merely "
        "to obtain an audit."
    )


def _shared_packet(context: CheckContext) -> dict[str, Any]:
    if not isinstance(context, AuditContext):
        raise ValueError("audit preparation requires build_context() so exact source is included")
    return {
        "source_fingerprint": context.source_fingerprint,
        "contract_sha256": context.contract_sha256,
        "evidence_sha256": context.evidence_sha256,
        "requirements_sha256": context.requirements_sha256,
        "source_manifest": dict(context.source_manifest_entries),
        "source_files": dict(context.source_files),
        "analysis": analyze_contract(
            context.contract,
            context.timings,
            source_fingerprint=context.source_fingerprint,
        ).to_mapping(),
        "timing_evidence": [item.to_mapping() for item in context.timings],
        "application_check_results": [dict(item) for item in context.check_results],
        "contract": {
            "workers": [asdict(item) for item in context.contract.workers],
            "tasks": [asdict(item) for item in context.contract.tasks],
            "resources": [asdict(item) for item in context.contract.resources],
        },
        "english_requirements": context.requirements.to_mapping(),
    }


def _validate_claim(claim: Mapping[str, Any], index: int) -> None:
    if set(claim) != {"id", "statement", "primitive_refs", "checker_refs", "assumptions"}:
        raise ValueError(f"claim {index} does not match the English requirements schema")
    if not isinstance(claim.get("id"), str) or not str(claim["id"]).strip():
        raise ValueError(f"claim {index} requires a stable ID")
    if not isinstance(claim.get("statement"), str) or not str(claim["statement"]).strip():
        raise ValueError(f"claim {index} requires a nonempty English statement")


def _worker_prompt(packet: Mapping[str, Any], packet_digest: str) -> str:
    template = Path(__file__).with_name("independent_audit_prompt.txt").read_text(encoding="utf-8")
    return (
        template.replace("{{AUDIT_PACKET_SHA256}}", packet_digest)
        .replace("{{RESPONSE_SCHEMA}}", json.dumps(RESPONSE_SCHEMA, ensure_ascii=False, indent=2))
        .replace("{{AUDIT_PACKET}}", json.dumps(packet, ensure_ascii=False, indent=2))
    )


def accept_handoffs(
    context: CheckContext,
    *,
    handoff_directory: str | Path,
    output_path: str | Path,
) -> CheckResult:
    """Validate every per-claim response and aggregate them into one optional check result."""
    root = Path(handoff_directory)
    manifest_path = root / "audit-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("handoff directory is missing audit-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = _validate_audit_manifest(manifest, context)
    expected_names = {str(item["directory"]) for item in entries}
    actual_names = {path.name for path in root.glob("claim-*") if path.is_dir()}
    if actual_names != expected_names:
        raise ValueError("claim directories do not exactly match the audit manifest")
    refs: set[str] = set()
    findings: list[CheckFinding] = []
    audits: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for manifest_entry in entries:
        directory = root / str(manifest_entry["directory"])
        packet_path = directory / "audit-packet.json"
        response_path = directory / "worker-response.json"
        if not response_path.is_file():
            raise ValueError(f"missing independent response: {response_path}")
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        _validate_packet_binding(packet, context)
        index = int(packet["claim_index"])
        if index in seen_indices:
            raise ValueError(f"duplicate claim index {index}")
        seen_indices.add(index)
        expected_digest = sha256(canonical_json(packet)).hexdigest()
        if expected_digest != manifest_entry["packet_sha256"]:
            raise ValueError(f"packet digest does not match audit manifest: {directory.name}")
        response = json.loads(response_path.read_text(encoding="utf-8"))
        _validate_response(response, expected_digest, packet)
        claim = packet["claim"]
        refs.update(str(reference) for reference in claim["primitive_refs"])
        findings.extend(
            CheckFinding(item["code"], f"claim-{index:03d}/{item['subject']}", item["message"])
            for item in response["findings"]
        )
        audits.append({
            "claim_index": index,
            "claim_id": claim["id"],
            "english": claim["statement"],
            "packet_sha256": expected_digest,
            "passed": response["passed"],
            "summary": response["summary"],
            "claim_reasoning": response["claim_reasoning"],
            "rule0_assessment": response["rule0_assessment"],
            "reviewed_files": response["reviewed_files"],
            "strengths": response["strengths"],
            "weaknesses": response["weaknesses"],
            "improvements": response["improvements"],
            "test_fitting_risks": response["test_fitting_risks"],
            "evidence_gaps": response["evidence_gaps"],
        })
    audits.sort(key=lambda item: item["claim_index"])
    result = CheckResult(
        checker="optional.independent-semantic-audit/v3",
        passed=all(item["passed"] is True for item in audits) and not findings,
        source_fingerprint=context.source_fingerprint,
        contract_sha256=context.contract_sha256,
        evidence_sha256=context.evidence_sha256,
        requirements_sha256=context.requirements_sha256,
        primitive_refs=tuple(sorted(refs)),
        findings=tuple(findings),
        facts={"worker_model": "gpt-5.6-luna", "one_claim_per_packet": True, "audits": audits},
    )
    write_check_result(result, output_path)
    return result


def _validate_audit_manifest(raw: Any, context: CheckContext) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("schema") != "dagcert-semantic-audit-manifest/v1":
        raise ValueError("invalid audit manifest")
    for field, expected in (
        ("source_fingerprint", context.source_fingerprint),
        ("contract_sha256", context.contract_sha256),
        ("evidence_sha256", context.evidence_sha256),
        ("requirements_sha256", context.requirements_sha256),
    ):
        if raw.get(field) != expected:
            raise ValueError(f"audit manifest has wrong {field}")
    entries = raw.get("claims")
    if not isinstance(entries, list) or not entries:
        raise ValueError("audit manifest contains no claims")
    indices: set[int] = set()
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "claim_index", "directory", "packet_sha256",
        }:
            raise ValueError("audit manifest claim entry is invalid")
        index = entry["claim_index"]
        name = entry["directory"]
        digest = entry["packet_sha256"]
        if (
            not isinstance(index, int) or index < 1 or index in indices
            or not isinstance(name, str) or name != f"claim-{index:03d}" or name in names
            or not isinstance(digest, str) or len(digest) != 64
        ):
            raise ValueError("audit manifest claim identity is invalid")
        indices.add(index)
        names.add(name)
    return entries


def _validate_packet_binding(packet: Any, context: CheckContext) -> None:
    if not isinstance(packet, dict) or packet.get("schema") != "dagcert-semantic-audit-packet/v3":
        raise ValueError("invalid per-claim audit packet")
    expected = {
        "source_fingerprint": context.source_fingerprint,
        "contract_sha256": context.contract_sha256,
        "evidence_sha256": context.evidence_sha256,
        "requirements_sha256": context.requirements_sha256,
    }
    for field, value in expected.items():
        if packet.get(field) != value:
            raise ValueError(f"audit packet has wrong {field}")
    if packet.get("english_requirements") != context.requirements.to_mapping():
        raise ValueError("audit packet does not contain the exact English requirements")
    index = packet.get("claim_index")
    if not isinstance(index, int) or index < 1 or index > len(context.requirements.claims):
        raise ValueError("audit packet has invalid claim index")
    expected_claim = context.requirements.claims[index - 1].to_mapping()
    if packet.get("claim") != expected_claim:
        raise ValueError("audit packet claim does not exactly match the English requirements")
    manifest = packet.get("source_manifest")
    files = packet.get("source_files")
    if not isinstance(manifest, dict) or not isinstance(files, dict):
        raise ValueError("audit packet must include exact source files")
    if sha256(canonical_json(manifest)).hexdigest() != context.source_fingerprint:
        raise ValueError("audit packet source manifest does not match its fingerprint")
    if set(files) != set(manifest):
        raise ValueError("audit packet source files do not match its manifest")
    for path, entry in files.items():
        if not isinstance(entry, dict) or set(entry) != {"sha256", "encoding", "content"}:
            raise ValueError(f"invalid source file entry: {path}")
        if entry["sha256"] != manifest[path]:
            raise ValueError(f"wrong source hash in audit packet: {path}")
        if entry["encoding"] == "utf-8":
            content = str(entry["content"]).encode("utf-8")
        elif entry["encoding"] == "base64":
            from base64 import b64decode
            content = b64decode(str(entry["content"]), validate=True)
        else:
            raise ValueError(f"unknown source encoding in audit packet: {path}")
        if sha256(content).hexdigest() != manifest[path]:
            raise ValueError(f"source content does not match manifest: {path}")
    _validate_claim(packet["claim"], index)


def _validate_response(raw: Any, expected_digest: str, packet: Mapping[str, Any]) -> None:
    expected_fields = set(RESPONSE_SCHEMA["required"])
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise ValueError("audit response has unexpected fields")
    if raw["audit_packet_sha256"] != expected_digest:
        raise ValueError("audit response is for another packet")
    if not isinstance(raw["passed"], bool):
        raise ValueError("audit response passed must be boolean")
    for field in ("summary", "claim_reasoning", "rule0_assessment"):
        if not isinstance(raw[field], str) or len(raw[field].strip()) < 200:
            raise ValueError(f"audit response {field} must contain at least 200 characters")
    reviewed = raw["reviewed_files"]
    if (
        not isinstance(reviewed, list) or not reviewed
        or not all(isinstance(path, str) and path in packet["source_files"] for path in reviewed)
        or len(reviewed) != len(set(reviewed))
    ):
        raise ValueError("audit response reviewed_files must name unique supplied source files")
    for field in ("strengths", "weaknesses", "test_fitting_risks", "evidence_gaps"):
        _validate_observations(raw[field], field)
    if not isinstance(raw["improvements"], list):
        raise ValueError("audit response improvements must be an array")
    for item in raw["improvements"]:
        if not isinstance(item, dict) or set(item) != {
            "priority", "subject", "recommendation", "rationale",
        }:
            raise ValueError("audit improvement has unexpected fields")
        if item["priority"] not in {"high", "medium", "low"} or not all(
            isinstance(item[key], str) and item[key].strip()
            for key in ("subject", "recommendation", "rationale")
        ):
            raise ValueError("audit improvement fields are invalid")
    if not isinstance(raw["findings"], list):
        raise ValueError("audit response findings must be an array")
    for item in raw["findings"]:
        if not isinstance(item, dict) or set(item) != {"code", "subject", "message"}:
            raise ValueError("audit finding has unexpected fields")
        if not all(
            isinstance(item[key], str) and item[key].strip()
            for key in ("code", "subject", "message")
        ):
            raise ValueError("audit finding fields must be nonempty strings")
    if raw["passed"] and raw["findings"]:
        raise ValueError("a passing audit must not contain findings")


def _validate_observations(raw: Any, field: str) -> None:
    if not isinstance(raw, list):
        raise ValueError(f"audit response {field} must be an array")
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"subject", "evidence", "impact"}:
            raise ValueError(f"audit response {field} has unexpected fields")
        if not all(
            isinstance(item[key], str) and item[key].strip()
            for key in ("subject", "evidence", "impact")
        ):
            raise ValueError(f"audit response {field} fields must be nonempty strings")


def build_context(
    contract_path: str | Path,
    evidence_path: str | Path,
    requirements_path: str | Path,
    source_root: str | Path,
    check_result_paths: Sequence[str | Path] = (),
) -> AuditContext:
    root = Path(source_root).resolve()
    contract_file = Path(contract_path).resolve()
    evidence_file = Path(evidence_path).resolve()
    requirements_file = Path(requirements_path).resolve()
    exclusions: list[str] = []
    for path in (contract_file, evidence_file, requirements_file):
        try:
            exclusions.append(path.relative_to(root).as_posix())
        except ValueError:
            pass
    manifest = source_manifest(root, exclude=exclusions)
    files: dict[str, dict[str, str]] = {}
    for relative, digest in manifest.items():
        content = (root / relative).read_bytes()
        try:
            rendered = content.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            rendered = b64encode(content).decode("ascii")
            encoding = "base64"
        files[relative] = {"sha256": digest, "encoding": encoding, "content": rendered}
    fingerprint = sha256(canonical_json(manifest)).hexdigest()
    contract_digest = sha256_file(contract_file)
    evidence_digest = sha256_file(evidence_file)
    requirements_digest = sha256_file(requirements_file)
    check_results = tuple(load_check_result(path) for path in check_result_paths)
    for result in check_results:
        if not result.passed:
            raise ValueError(f"audit input checker failed: {result.checker}")
        if result.source_fingerprint != fingerprint:
            raise ValueError(f"audit input checker is bound to another source: {result.checker}")
        if result.contract_sha256 != contract_digest or result.evidence_sha256 != evidence_digest:
            raise ValueError(
                f"audit input checker is bound to another contract/evidence set: {result.checker}"
            )
        if result.requirements_sha256 != requirements_digest:
            raise ValueError(
                f"audit input checker is bound to other English requirements: {result.checker}"
            )
    return AuditContext(
        contract=load_contract(contract_file),
        timings=load_evidence(evidence_file),
        source_root=root,
        source_fingerprint=fingerprint,
        contract_sha256=contract_digest,
        evidence_sha256=evidence_digest,
        requirements=load_requirements(requirements_file),
        requirements_sha256=requirements_digest,
        source_manifest_entries=manifest,
        source_files=files,
        check_results=tuple(result.to_mapping() for result in check_results),
    )


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Prepare or accept independent per-claim Dagcert audits")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "accept"):
        command = commands.add_parser(name)
        command.add_argument("--contract", required=True)
        command.add_argument("--evidence", required=True)
        command.add_argument("--requirements", required=True)
        command.add_argument("--source-root", required=True)
        command.add_argument("--check-result", action="append", default=[])
    prepare = commands.choices["prepare"]
    prepare.add_argument("--output-directory", required=True)
    prepare.add_argument(
        "--max-packet-bytes",
        type=int,
        default=DEFAULT_MAX_AUDIT_PACKET_BYTES,
        help="refuse any per-claim packet or rendered prompt above this byte count (default: 200000)",
    )
    accept = commands.choices["accept"]
    accept.add_argument("--handoff-directory", required=True)
    accept.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    context = build_context(
        args.contract,
        args.evidence,
        args.requirements,
        args.source_root,
        check_result_paths=args.check_result,
    )
    if args.command == "prepare":
        handoffs = prepare_handoffs(
            context,
            output_directory=args.output_directory,
            max_packet_bytes=args.max_packet_bytes,
        )
        print(json.dumps([
            {
                "claim_index": item.claim_index,
                "prompt": str(item.prompt_path),
                "response": str(item.response_path),
                "packet_sha256": item.packet_sha256,
            }
            for item in handoffs
        ], indent=2))
        return 0
    result = accept_handoffs(
        context,
        handoff_directory=args.handoff_directory,
        output_path=args.output,
    )
    print(f"accepted {len(result.facts['audits'])} independent claim audits: passed={result.passed}")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
