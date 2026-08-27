"""CLI for the minimal dagcert certificate kernel."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from importlib.resources import files
from pathlib import Path
from shutil import copytree, rmtree
import json
import sys

from . import __version__
from .analysis import analyze_contract
from .certificate import CertificateError, issue_certificate, source_fingerprint, verify_certificate
from .checks import load_check_result
from .contract import ContractError, load_contract
from .evidence import EvidenceError, load_evidence
from .requirements import RequirementsError, audit_translation, load_requirements
from .source_types import check_python_sources


CONTRACT_TEMPLATE = """{
  "schema": "dagcert-contract/v4",
  "workers": [
    {"id": "app", "concurrency": 1}
  ],
  "resources": [
    {"id": "replace_me", "capacity": 1, "initial": 0, "unit": "slots"}
  ],
  "tasks": [
    {
      "id": "replace_me",
      "role": "operation",
      "worker": "app",
      "implementation": {"language": "python", "path": "app.py", "symbol": "replace_me"},
      "outcomes": [
        {"type": "ReplaceMeCompleted", "resources": {"replace_me": {"acquire": 1}}, "metadata": {}},
        {"type": "dagcert.runtime.UnhandledException", "resources": {}, "metadata": {}}
      ],
      "depends_on": [],
      "timings": {
        "replace_me": {"metric": "duration", "upper_ms": 1000, "minimum_samples": 10, "policy": "max", "safety_factor": 1.30}
      }
    }
  ],
  "compositions": [],
  "metadata": {}
}
"""

REQUIREMENTS_TEMPLATE = """{
  "schema": "dagcert-english-requirements/v2",
  "claims": [
    {
      "id": "replace_me",
      "statement": "Replace this with the exact plain-English behavior being certified.",
      "primitive_refs": ["task:replace_me", "timing:replace_me/replace_me"],
      "checker_refs": [],
      "assumptions": [],
      "basis": "observed",
      "formula": null
    }
  ],
  "metadata": {}
}
"""

APP_TEMPLATE = """from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class ReplaceMeInput:
    value: str


@dataclass(frozen=True)
class ReplaceMeCompleted:
    value: str


@operation
def replace_me(request: ReplaceMeInput) -> ReplaceMeCompleted:
    return ReplaceMeCompleted(request.value)
"""

HELP_TOPICS = {
    "database-ui": (
        "certified SQLite/browser example plus reusable exact-projection workflow",
        "docs/database-ui.md",
    ),
}


def parser() -> ArgumentParser:
    root = ArgumentParser(
        prog="dagcert",
        description=(
            "Certificates binding plain-English claims to workers, tasks, resources, and timings"
        ),
    )
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create the minimal contract and optionally copy the agent skill")
    init.add_argument("directory", nargs="?", default=".")

    install = commands.add_parser("install-skill", help="copy or replace the bundled agent skill")
    install.add_argument("directory", nargs="?", default=".")
    install.add_argument("--force", action="store_true")

    help_command = commands.add_parser("help", help="show installed Dagcert guides and examples")
    help_command.add_argument("topic", nargs="?")

    lint = commands.add_parser("lint", help="validate the contract and mandatory English claims")
    lint.add_argument("contract")
    lint.add_argument("--requirements", required=True)

    fingerprint = commands.add_parser("fingerprint", help="print exact application source identity")
    fingerprint.add_argument("source_root", nargs="?", default=".")
    fingerprint.add_argument("--exclude", action="append", default=[])

    analyze = commands.add_parser("analyze", help="check timing evidence and primitive bounds")
    analyze.add_argument("contract")
    analyze.add_argument("evidence")
    analyze.add_argument("--requirements", required=True)
    analyze.add_argument("--source-root", default=".")
    analyze.add_argument("--exclude", action="append", default=[])
    analyze.add_argument("--output")

    check = commands.add_parser("check-result", help="validate one optional checker result artifact")
    check.add_argument("result")

    issue = commands.add_parser("issue", help="issue when primitive analysis and every selected checker pass")
    _certificate_arguments(issue)
    issue.add_argument("--output", required=True)

    verify = commands.add_parser("verify", help="verify exact source, primitives, timings, and checker results")
    _certificate_arguments(verify)
    verify.add_argument("certificate")
    return root


def _certificate_arguments(command: ArgumentParser) -> None:
    command.add_argument("--contract", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--requirements", required=True)
    command.add_argument("--source-root", default=".")
    command.add_argument("--check-result", action="append", default=[])
    command.add_argument("--exclude", action="append", default=[])


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "install-skill":
            return _install_skill(args)
        if args.command == "help":
            return _help(args)
        if args.command == "lint":
            contract = load_contract(args.contract)
            requirements = load_requirements(args.requirements)
            if contract.schema != "dagcert-contract/v4":
                raise ContractError("new certificate issuance requires dagcert-contract/v4")
            if requirements.schema != "dagcert-english-requirements/v2":
                raise RequirementsError(
                    "new certificate issuance requires dagcert-english-requirements/v2"
                )
            source_typing = check_python_sources(
                Path(args.contract).resolve().parent,
                (task.source_signature for task in contract.tasks if task.source_signature is not None),
            )
            translation_audit = audit_translation(requirements, contract)
            if not translation_audit.passed:
                raise RequirementsError("; ".join(translation_audit.findings))
            print(f"valid: {len(contract.workers)} workers, {len(contract.tasks)} tasks, {len(contract.resources)} resources, {sum(len(item.timings) for item in contract.tasks)} timings")
            print(f"human-readable requirements: {len(requirements.claims)} claims")
            print("English-to-formal coverage audit: passed")
            print(
                f"source typing: {source_typing['checker']} {source_typing['version']} "
                f"{source_typing['mode']} passed"
            )
            return 0
        if args.command == "fingerprint":
            print(source_fingerprint(args.source_root, exclude=args.exclude))
            return 0
        if args.command == "analyze":
            load_requirements(args.requirements)
            exclusions = _relative_inputs(
                args.source_root, [args.contract, args.evidence, args.requirements]
            ) + list(args.exclude)
            fingerprint = source_fingerprint(args.source_root, exclude=exclusions)
            report = analyze_contract(
                load_contract(args.contract, source_root=args.source_root),
                load_evidence(args.evidence), source_fingerprint=fingerprint,
            )
            encoded = json.dumps(report.to_mapping(), indent=2)
            if args.output:
                output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(encoded + "\n", encoding="utf-8")
            else:
                print(encoded)
            return 0 if report.passed else 2
        if args.command == "check-result":
            check_result = load_check_result(args.result)
            print(json.dumps(check_result.to_mapping(), indent=2))
            return 0 if check_result.passed else 2
        if args.command == "issue":
            document = issue_certificate(
                args.contract, args.evidence, args.output, source_root=args.source_root,
                requirements_path=args.requirements,
                check_result_paths=args.check_result, source_exclude=args.exclude,
            )
            print(f"issued {args.output}: {document['certificate_sha256']}")
            return 0
        if args.command == "verify":
            verification = verify_certificate(
                args.certificate, contract_path=args.contract, evidence_path=args.evidence,
                requirements_path=args.requirements,
                source_root=args.source_root, check_result_paths=args.check_result, source_exclude=args.exclude,
            )
            if not verification.valid:
                print("certificate invalid: " + "; ".join(verification.problems), file=sys.stderr)
                return 2
            print("certificate valid")
            return 0
    except (CertificateError, ContractError, EvidenceError, RequirementsError, OSError, ValueError) as exc:
        print(f"dagcert: {exc}", file=sys.stderr)
        return 2
    return 1


def _relative_inputs(root: str | Path, paths: list[str | Path]) -> list[str]:
    base = Path(root).resolve()
    result: list[str] = []
    for value in paths:
        try:
            result.append(Path(value).resolve().relative_to(base).as_posix())
        except ValueError:
            pass
    return result


def _help(args: Namespace) -> int:
    if args.topic is None:
        print("Installed Dagcert help topics:")
        for name, (description, _) in HELP_TOPICS.items():
            print(f"  {name:<16} {description}")
        print("\nRun: python -m dagcert help TOPIC")
        return 0
    if args.topic not in HELP_TOPICS:
        available = ", ".join(HELP_TOPICS)
        raise ValueError(f"unknown help topic {args.topic!r}; available topics: {available}")
    _, resource_name = HELP_TOPICS[args.topic]
    resource = files("dagcert").joinpath(resource_name)
    print(resource.read_text(encoding="utf-8"), end="")
    return 0


def _init(args: Namespace) -> int:
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    contract = root / "dag_contract.json"
    requirements = root / "english_requirements.json"
    application = root / "app.py"
    if contract.exists():
        load_contract(contract)
        print(f"existing contract retained: {contract}")
    else:
        contract.write_text(CONTRACT_TEMPLATE, encoding="utf-8", newline="\n")
        print(f"created {contract}")
    if not application.exists():
        application.write_text(APP_TEMPLATE, encoding="utf-8", newline="\n")
        print(f"created {application}")
    if requirements.exists():
        load_requirements(requirements)
        print(f"existing English requirements retained: {requirements}")
    else:
        requirements.write_text(REQUIREMENTS_TEMPLATE, encoding="utf-8", newline="\n")
        print(f"created {requirements}")
    try:
        _install_skill(Namespace(directory=str(root), force=False))
    except ValueError as exc:
        bundled = Path(__file__).with_name("bundled_skill") / "dagcert-certify-app" / "SKILL.md"
        print(f"skill copy skipped: {exc}; bundled skill remains available at {bundled}")
    return 0


def _install_skill(args: Namespace) -> int:
    root = Path(args.directory).resolve()
    bundled = Path(__file__).with_name("bundled_skill") / "dagcert-certify-app"
    installed = root / ".agents" / "skills" / "dagcert-certify-app"
    if installed.exists() and not args.force:
        print(f"existing skill retained: {installed}")
        return 0
    staging = installed.with_name(installed.name + ".installing")
    backup = installed.with_name(installed.name + ".previous")
    if staging.exists() or backup.exists():
        raise ValueError(f"stale skill installation staging exists beside {installed}")
    try:
        staging.parent.mkdir(parents=True, exist_ok=True)
        copytree(bundled, staging)
        if installed.exists():
            installed.replace(backup)
        staging.replace(installed)
        if backup.exists():
            rmtree(backup)
    except PermissionError as exc:
        if staging.exists():
            rmtree(staging)
        if backup.exists() and not installed.exists():
            backup.replace(installed)
        raise ValueError(f"workspace policy denied writing {installed}") from exc
    print(f"installed skill in {installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
