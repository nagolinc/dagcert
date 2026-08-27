"""Small source-typed vote application used by the Dagcert reference certificate."""

from __future__ import annotations

from dataclasses import dataclass

from dagcert import operation


@dataclass(frozen=True, slots=True)
class VoteRequest:
    current: int
    delta: int


@dataclass(frozen=True, slots=True)
class PreviewTotal:
    value: int


@dataclass(frozen=True, slots=True)
class CommittedTotal:
    value: int


@dataclass(frozen=True, slots=True)
class Generation:
    value: int


@dataclass(frozen=True, slots=True)
class SummaryGeneration:
    value: int


@dataclass(frozen=True, slots=True)
class VoteTotal:
    value: int


@dataclass(frozen=True, slots=True)
class TextSnapshot:
    value: str


@operation
def preview_vote_total(request: VoteRequest) -> PreviewTotal:
    """Return the proposed total without mutating authoritative state."""
    return PreviewTotal(request.current + request.delta)


@operation
def commit_vote_total(request: PreviewTotal) -> CommittedTotal:
    """Return the authoritative total for this pure in-process application."""
    return CommittedTotal(request.value)


@operation
def advance_summary_generation(request: CommittedTotal) -> SummaryGeneration:
    """Advance the application's summary-generation counter once."""
    return SummaryGeneration(request.value + 1)


@operation
def render_vote_snapshot(request: CommittedTotal) -> TextSnapshot:
    """Render the application's complete text snapshot for a vote total."""
    return TextSnapshot(f"votes:{request.value}")
