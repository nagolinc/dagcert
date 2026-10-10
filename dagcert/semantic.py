"""Mandatory source-semantic proof gate shared by lint, issuance and verification."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .contract import Contract
from .relations import RelationError, SourceRelation, verify_source_relations
from .source_types import SourceProofBackend, SourceTypeError


def contract_relations(contract: Contract) -> tuple[SourceRelation, ...]:
    relations: list[SourceRelation] = []
    for claim in contract.state_claims:
        if claim.kind == "relational_invariant":
            from .induction import relation_source_obligations

            relations.extend(
                replace(item, id=f"{claim.id}/{item.id}")
                for item in relation_source_obligations(claim.specification, contract)
            )
        elif claim.kind == "curve_bound" and "network" in claim.specification:
            from .networks import network_relations

            relations.extend(
                replace(item, id=f"{claim.id}/{item.id}")
                for item in network_relations(claim.specification, contract)
            )
    return tuple(relations)


def verify_contract_relations(
    contract: Contract,
    source_root: str | Path,
    source_verification: dict[str, object],
    fingerprint: str,
    manifest: Iterable[str],
    backend: SourceProofBackend | None,
) -> None:
    """Never accept a caller's boolean in place of a source relation proof."""
    requested = contract_relations(contract)
    if not requested:
        return
    try:
        source_verification["relations"] = verify_source_relations(
            contract, source_root, requested, backend, fingerprint,
            source_manifest_paths=manifest,
        )
    except RelationError as exc:
        raise SourceTypeError(str(exc)) from exc
