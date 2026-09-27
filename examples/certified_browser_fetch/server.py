from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class AdmissionInput:
    requestAccepted: bool


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool


@operation
def admit(request: AdmissionInput) -> AdmissionResult:
    return AdmissionResult(request.requestAccepted)
