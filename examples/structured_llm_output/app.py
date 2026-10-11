from dataclasses import dataclass

from dagcert.runtime import ExternalRaised, ExternalSuccess, ExternalTypeViolation, operation

from boundary import validate_plan


@dataclass(frozen=True)
class ModelResponse:
    text: str


@dataclass(frozen=True)
class PlanReady:
    plan_json: str


@dataclass(frozen=True)
class PlanFailed:
    reason: str


@operation
def accept_model_response(request: ModelResponse) -> PlanReady | PlanFailed:
    result = validate_plan(request.text)
    if isinstance(result, ExternalSuccess):
        if result.value:
            return PlanReady(request.text)
        return PlanFailed("response did not satisfy the schema")
    if isinstance(result, ExternalRaised):
        return PlanFailed(result.exception_type)
    if isinstance(result, ExternalTypeViolation):
        return PlanFailed(result.observed_type)
    return PlanFailed("unrecognized external outcome")
