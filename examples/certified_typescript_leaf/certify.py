"""Issue and verify the TypeScript-leaf example with pinned Maledictus."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from dagcert import issue_certificate, verify_certificate
from dagcert.source_types import SourceProofBackend


def main(executable: Path, root: Path | None = None) -> int:
    app_root = (root or Path(__file__).resolve().parent).resolve()
    artifacts = app_root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    evidence = artifacts / "timings.jsonl"
    evidence.write_text("", encoding="utf-8")
    backend = SourceProofBackend.maledictus(
        executable,
        sha256(executable.read_bytes()).hexdigest(),
    )
    certificate = artifacts / "certificate.json"
    contract = app_root / "dag_contract.json"
    requirements = app_root / "english_requirements.json"
    issue_certificate(
        contract,
        evidence,
        certificate,
        requirements_path=requirements,
        source_root=app_root,
        proof_backend=backend,
    )
    verification = verify_certificate(
        certificate,
        contract_path=contract,
        evidence_path=evidence,
        requirements_path=requirements,
        source_root=app_root,
        proof_backend=backend,
    )
    return 0 if verification.valid else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m examples.certified_typescript_leaf.certify PATH")
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
