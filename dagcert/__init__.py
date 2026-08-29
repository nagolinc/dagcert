"""Minimal public API for DAG certificates."""

from ._version import VERSION

from .analysis import (
    AnalysisReport, ErrorBudgetResult, Finding, StructuralProgress, TimingResult,
    analyze_contract,
)
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
    Composition, CompositionStep, Contract, ContractError, ExternalContract, ExternalProvider,
    Implementation, Resource, ResourceEffect,
    Task, TaskErrorBudget, TaskOutcome, Timing, TypedDependency, Worker, load_contract,
)
from .evidence import ExternalEvidenceMonitor, EvidenceError, EvidenceRecorder, TimingSample, load_evidence
from .runtime import (
    ExternalBoundaryEvent, ExternalMonitorError, ExternalRaised, ExternalSuccess,
    ExternalTypeViolation, OperationTypeViolation, UnhandledException,
    clear_runtime_violations, external_boundary, monitor_external_boundaries, operation,
    outcome_type, runtime_violations,
)
from .source_types import SourceSignature, SourceTypeError, check_python_sources
from .surfaces import SurfaceBinding, SurfaceError, banner, stats
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
    "Contract", "ContractError", "ExternalContract", "ExternalProvider", "Implementation",
    "EnglishClaim", "EnglishRequirements", "ErrorBudgetResult", "EvidenceError", "EvidenceRecorder", "ExternalEvidenceMonitor", "Finding",
    "RequirementsError", "Resource", "ResourceEffect", "SurfaceBinding", "SurfaceError",
    "StructuralProgress", "Task", "TaskErrorBudget", "TaskOutcome", "Timing", "TimingResult", "TimingSample", "TranslationAudit", "TypedDependency",
    "ExternalBoundaryEvent", "ExternalMonitorError", "ExternalRaised", "ExternalSuccess", "ExternalTypeViolation",
    "OperationTypeViolation", "SourceSignature", "SourceTypeError", "UnhandledException", "Worker", "analyze_contract", "audit_translation", "issue_certificate",
    "load_check_result", "load_contract", "load_evidence", "load_requirements", "run_checker", "sha256_file",
    "banner", "check_python_sources", "clear_runtime_violations", "external_boundary", "monitor_external_boundaries", "operation", "outcome_type", "runtime_violations", "source_fingerprint", "source_manifest", "stats", "verify_certificate", "write_check_result",
]

__version__ = VERSION
