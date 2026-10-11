"""Check the recipe through Dagcert's public source-verification API."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from dagcert import load_contract, source_fingerprint, source_manifest
from dagcert.certificate import external_source_contracts, maledictus_embedded_external_calls
from dagcert.source_types import SourceProofBackend, check_python_sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".cache/structured-llm-output/source-proof.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    contract = load_contract(root / "dag_contract.json", source_root=root)
    manifest = source_manifest(root)
    backend = SourceProofBackend.maledictus(
        args.backend.resolve(), sha256(args.backend.read_bytes()).hexdigest(),
    )
    result = check_python_sources(
        root,
        (task.source_signature for task in contract.tasks if task.source_signature is not None),
        source_fingerprint=source_fingerprint(root),
        source_manifest_paths=manifest,
        external_contracts=external_source_contracts(contract),
        embedded_external_calls=maledictus_embedded_external_calls(
            contract, root, source_manifest_paths=manifest,
        ),
        proof_backend=backend,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Source proof accepted: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
