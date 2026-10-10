"""Replayable mathematical certificates, distinct from application certificates.

These artifacts certify a linear-real implication from explicit premises. They
do not assert that a program satisfies those premises or that measurements are
universal bounds. Verification checks the sealed inputs/backend and reruns the
actual arithmetic decision; a recorded ``valid`` flag is never evidence alone.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import linear_logic
from .linear_logic import LinearLogicError, LinearProofResult, prove_implication


SCHEMA = "dagcert-mathematical-certificate/v1"
LOGIC = "SMT-LIB/LRA"


class MathCertificateError(ValueError):
    """A mathematical artifact is malformed or cannot be issued/verified."""

    def __init__(self, message: str, *, result: LinearProofResult | None = None) -> None:
        super().__init__(message)
        self.result = result


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise MathCertificateError(f"mathematical certificate is not canonical JSON data: {exc}") from exc
    return sha256(encoded.encode("utf-8")).hexdigest()


def _backend(result: LinearProofResult) -> dict[str, Any]:
    modules = (Path(linear_logic.__file__), Path(__file__))
    return {
        "solver": dict(result.solver_metadata),
        "kernel_sources": {path.name: sha256(path.read_bytes()).hexdigest() for path in modules},
    }


def issue_math_certificate(
    variables: Mapping[str, str], assumptions: Sequence[str], conclusion: str,
) -> dict[str, Any]:
    """Issue only when satisfiable explicit premises entail the conclusion."""
    try:
        result = prove_implication(variables, assumptions, conclusion)
    except LinearLogicError as exc:
        raise MathCertificateError(f"invalid mathematical proof request: {exc}") from exc
    if result.status != "valid":
        raise MathCertificateError(
            f"mathematical certificate refused ({result.status}): {result.reason}", result=result,
        )
    backend = _backend(result)
    certificate = {
        "schema": SCHEMA,
        "logic": LOGIC,
        "variables": dict(sorted(variables.items())),
        "assumptions": list(assumptions),
        "conclusion": conclusion,
        "decision": result.as_dict(),
        "backend": backend,
        "backend_sha256": _digest(backend),
    }
    certificate["certificate_sha256"] = _digest(certificate)
    return certificate


def verify_math_certificate(document: Mapping[str, Any]) -> LinearProofResult:
    """Verify integrity and recompute the decision instead of trusting a flag.

    Malformed or modified artifacts raise ``MathCertificateError``. A correctly
    resealed but false assertion returns the solver's actual invalid result and
    counterexample; resealing cannot manufacture a successful verification.
    """
    required = {
        "schema", "logic", "variables", "assumptions", "conclusion", "decision",
        "backend", "backend_sha256", "certificate_sha256",
    }
    if not isinstance(document, Mapping) or set(document) != required:
        raise MathCertificateError("mathematical certificate has missing or unexpected fields")
    if document["schema"] != SCHEMA or document["logic"] != LOGIC:
        raise MathCertificateError("unsupported mathematical certificate schema or logic")
    payload = {key: value for key, value in document.items() if key != "certificate_sha256"}
    if document["certificate_sha256"] != _digest(payload):
        raise MathCertificateError("mathematical certificate SHA-256 does not match its contents")
    if document["backend_sha256"] != _digest(document["backend"]):
        raise MathCertificateError("mathematical proof backend SHA-256 does not match its descriptor")
    variables = document["variables"]
    assumptions = document["assumptions"]
    conclusion = document["conclusion"]
    if not isinstance(variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in variables.items()):
        raise MathCertificateError("mathematical certificate variables must be a string-to-sort object")
    if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
        raise MathCertificateError("mathematical certificate assumptions must be a list of formulas")
    if not isinstance(conclusion, str):
        raise MathCertificateError("mathematical certificate conclusion must be a formula")
    decision = document["decision"]
    if not isinstance(decision, dict) or decision.get("status") != "valid":
        raise MathCertificateError("an issued mathematical certificate must record a valid decision")

    try:
        result = prove_implication(variables, assumptions, conclusion)
    except LinearLogicError as exc:
        raise MathCertificateError(f"invalid formula in mathematical certificate: {exc}") from exc
    if document["backend"] != _backend(result):
        raise MathCertificateError("mathematical proof backend differs from the sealed solver/kernel")
    if result.status == "valid" and decision != result.as_dict():
        raise MathCertificateError("recorded mathematical decision differs from its recomputed descriptor")
    return result
