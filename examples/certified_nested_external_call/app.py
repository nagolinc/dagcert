from dataclasses import dataclass

from dagcert.runtime import ExternalRaised, ExternalSuccess, ExternalTypeViolation, operation

from boundary import decode_url_component


@dataclass(frozen=True)
class NormalizeRequest:
    value: str


@dataclass(frozen=True)
class UrlNormalized:
    value: str


@dataclass(frozen=True)
class UrlNormalizationFailed:
    reason: str


@operation
def normalize_url(request: NormalizeRequest) -> UrlNormalized | UrlNormalizationFailed:
    prepared = request.value.strip()
    decoded = decode_url_component(prepared)
    if isinstance(decoded, ExternalSuccess):
        return UrlNormalized(decoded.value.lower())
    if isinstance(decoded, ExternalRaised):
        return UrlNormalizationFailed(decoded.exception_type)
    if isinstance(decoded, ExternalTypeViolation):
        return UrlNormalizationFailed(decoded.observed_type)
    return UrlNormalizationFailed("unrecognized external outcome")

