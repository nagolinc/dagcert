"""Small source-typed vote application used by the Dagcert reference certificate."""

from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class VoteRequest:
    current: int
    delta: int


@dataclass(frozen=True)
class PreviewTotal:
    value: int


@dataclass(frozen=True)
class PreviewRejected:
    reason: str


@dataclass(frozen=True)
class CommittedTotal:
    value: int


@dataclass(frozen=True)
class CommitRejected:
    reason: str


@dataclass(frozen=True)
class Generation:
    value: int


@dataclass(frozen=True)
class SummaryGeneration:
    value: int


@dataclass(frozen=True)
class VoteTotal:
    value: int


@dataclass(frozen=True)
class TextSnapshot:
    value: str


@operation
def preview_vote_total(request: VoteRequest) -> Union[PreviewTotal, PreviewRejected]:
    """Return the proposed total without mutating authoritative state."""
    if request.delta == 0:
        return PreviewRejected("zero delta")
    return PreviewTotal(request.current + request.delta)


@operation
def commit_vote_total(request: PreviewTotal) -> Union[CommittedTotal, CommitRejected]:
    """Return the authoritative total for this pure in-process application."""
    if request.value < 0:
        return CommitRejected("negative total")
    return CommittedTotal(request.value)


@operation
def advance_summary_generation(request: CommittedTotal) -> SummaryGeneration:
    """Advance the application's summary-generation counter once."""
    return SummaryGeneration(request.value + 1)


@operation
def render_vote_snapshot(request: CommittedTotal) -> TextSnapshot:
    """Render the application's complete text snapshot for a vote total."""
    return TextSnapshot(f"votes:{request.value}")
