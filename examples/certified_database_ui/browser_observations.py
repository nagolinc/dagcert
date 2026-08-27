"""Typed boundaries for browser-originated timing observations."""

from __future__ import annotations

from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True, slots=True)
class BrowserFeedbackInput:
    value_ms: float
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class BrowserFeedbackObserved:
    value_ms: float
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class BrowserRenderInput:
    value_ms: float
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class BrowserRenderObserved:
    value_ms: float
    metadata: dict[str, object]


@operation
def observe_feedback(request: BrowserFeedbackInput) -> BrowserFeedbackObserved:
    return BrowserFeedbackObserved(request.value_ms, request.metadata)


@operation
def observe_render(request: BrowserRenderInput) -> BrowserRenderObserved:
    return BrowserRenderObserved(request.value_ms, request.metadata)
