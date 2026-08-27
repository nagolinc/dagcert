"""Minimal public API for DAG certificates."""

from ._version import VERSION

from .analysis import AnalysisReport, Finding, StructuralProgress, TimingResult, analyze_contract
from .certificate import (
    CertificateError,
    CertificateVerification,
    issue_certificate,
    sha256_file,
    source_manifest,
    source_fingerprint,
    verify_certificate,
)
from .checks import (
    CheckContext,
    CheckFinding,
    Checker,
    CheckResult,
    load_check_result,
    run_checker,
    write_check_result,
)
from .contract import (
    Composition, CompositionStep, Contract, ContractError, Implementation, Resource, ResourceEffect,
    Task, TaskOutcome, Timing, TypedDependency, Worker, load_contract,
)
from .evidence import EvidenceError, EvidenceRecorder, TimingSample, load_evidence
from .runtime import OperationTypeViolation, UnhandledException, operation, outcome_type
from .source_types import SourceSignature, SourceTypeError
from .requirements import (
    EnglishClaim,
    EnglishRequirements,
    RequirementsError,
    TranslationAudit,
    audit_translation,
    load_requirements,
)

__all__ = [
    "AnalysisReport", "CertificateError", "CertificateVerification", "CheckContext",
    "CheckFinding", "Checker", "CheckResult", "Composition", "CompositionStep",
    "Contract", "ContractError", "Implementation",
    "EnglishClaim", "EnglishRequirements", "EvidenceError", "EvidenceRecorder", "Finding",
    "RequirementsError", "Resource", "ResourceEffect",
    "StructuralProgress", "Task", "TaskOutcome", "Timing", "TimingResult", "TimingSample", "TranslationAudit", "TypedDependency",
    "OperationTypeViolation", "SourceSignature", "SourceTypeError", "UnhandledException", "Worker", "analyze_contract", "audit_translation", "issue_certificate",
    "load_check_result", "load_contract", "load_evidence", "load_requirements", "run_checker", "sha256_file",
    "operation", "outcome_type", "source_fingerprint", "source_manifest", "verify_certificate", "write_check_result",
]

__version__ = VERSION
