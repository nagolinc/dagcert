"""Production state transitions for five small timing-sensitive systems.

These are executable policies, not observers or entire application proofs.
Platform work, scheduling envelopes, and the persistence of returned states
must be bound by the surrounding certificate. Time values are integer
milliseconds; sequence numbers identify actual content, not invocation counts.
"""

from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class AVJoinRequest:
    next_sequence: int
    audio_sequence: int
    video_sequence: int
    audio_ms: int
    video_ms: int
    reserve_ms: int
    capacity_ms: int


@dataclass(frozen=True)
class AVJoined:
    next_sequence: int
    reserve_ms: int
    added_ms: int
    capacity_ms: int


@dataclass(frozen=True)
class AVDeferred:
    next_sequence: int
    reserve_ms: int
    capacity_ms: int


@dataclass(frozen=True)
class AVReserveFull:
    next_sequence: int
    reserve_ms: int
    capacity_ms: int


@operation
def join_av(request: AVJoinRequest) -> Union[AVJoined, AVDeferred, AVReserveFull]:
    """Admit only the next matching complete A/V segment; retain other work."""
    if (
        request.next_sequence < 0
        or request.reserve_ms < 0
        or request.capacity_ms < request.reserve_ms
        or request.audio_ms <= 0
        or request.audio_ms != request.video_ms
        or request.audio_sequence != request.next_sequence
        or request.video_sequence != request.next_sequence
    ):
        return AVDeferred(request.next_sequence, request.reserve_ms, request.capacity_ms)
    if request.reserve_ms + request.audio_ms > request.capacity_ms:
        return AVReserveFull(request.next_sequence, request.reserve_ms, request.capacity_ms)
    return AVJoined(
        request.next_sequence + 1,
        request.reserve_ms + request.audio_ms,
        request.audio_ms,
        request.capacity_ms,
    )


@dataclass(frozen=True)
class BatchDispatchRequest:
    now_ms: int
    busy_until_ms: int
    interactive_count: int
    background_count: int
    interactive_oldest_ms: int
    background_oldest_ms: int
    batch_target: int
    batch_timeout_ms: int


@dataclass(frozen=True)
class InteractiveBatch:
    count: int
    remaining_interactive: int
    remaining_background: int


@dataclass(frozen=True)
class BackgroundBatch:
    count: int
    remaining_interactive: int
    remaining_background: int


@dataclass(frozen=True)
class WorkerBusy:
    release_ms: int
    remaining_interactive: int
    remaining_background: int


@dataclass(frozen=True)
class BatchWaiting:
    deadline_ms: int
    remaining_interactive: int
    remaining_background: int


@dataclass(frozen=True)
class WorkerIdle:
    now_ms: int
    remaining_interactive: int
    remaining_background: int


@dataclass(frozen=True)
class DispatchRejected:
    now_ms: int
    remaining_interactive: int
    remaining_background: int


@operation
def dispatch_batch(
    request: BatchDispatchRequest,
) -> Union[InteractiveBatch, BackgroundBatch, WorkerBusy, BatchWaiting, WorkerIdle, DispatchRejected]:
    """Choose a priority batch without pretending in-flight work can preempt.

    Priority is strict: sustained interactive arrivals may starve background
    work. A background service guarantee therefore needs a justified residual
    service/arrival envelope; this operation does not manufacture fairness.
    """
    if (
        request.now_ms < 0
        or request.busy_until_ms < 0
        or request.interactive_count < 0
        or request.background_count < 0
        or request.interactive_oldest_ms < 0
        or request.background_oldest_ms < 0
        or request.batch_target <= 0
        or request.batch_timeout_ms < 0
        or request.interactive_oldest_ms > request.now_ms
        or request.background_oldest_ms > request.now_ms
    ):
        return DispatchRejected(request.now_ms, request.interactive_count, request.background_count)
    if request.now_ms < request.busy_until_ms:
        return WorkerBusy(request.busy_until_ms, request.interactive_count, request.background_count)
    if request.interactive_count > 0:
        deadline = request.interactive_oldest_ms + request.batch_timeout_ms
        if request.interactive_count < request.batch_target and request.now_ms < deadline:
            return BatchWaiting(deadline, request.interactive_count, request.background_count)
        taken = request.interactive_count
        if taken > request.batch_target:
            taken = request.batch_target
        return InteractiveBatch(taken, request.interactive_count - taken, request.background_count)
    if request.background_count > 0:
        deadline = request.background_oldest_ms + request.batch_timeout_ms
        if request.background_count < request.batch_target and request.now_ms < deadline:
            return BatchWaiting(deadline, request.interactive_count, request.background_count)
        taken = request.background_count
        if taken > request.batch_target:
            taken = request.batch_target
        return BackgroundBatch(taken, request.interactive_count, request.background_count - taken)
    return WorkerIdle(request.now_ms, request.interactive_count, request.background_count)


@dataclass(frozen=True)
class ChunkAckRequest:
    durable_chunks: int
    durable_bytes: int
    chunk_index: int
    chunk_bytes: int
    acknowledged: bool


@dataclass(frozen=True)
class ChunkCommitted:
    durable_chunks: int
    durable_bytes: int


@dataclass(frozen=True)
class ChunkDuplicate:
    durable_chunks: int
    durable_bytes: int


@dataclass(frozen=True)
class ChunkDeferred:
    durable_chunks: int
    durable_bytes: int
    chunk_index: int
    chunk_bytes: int


@dataclass(frozen=True)
class ChunkFailed:
    durable_chunks: int
    durable_bytes: int


@dataclass(frozen=True)
class ChunkRejected:
    durable_chunks: int
    durable_bytes: int


@operation
def acknowledge_chunk(
    request: ChunkAckRequest,
) -> Union[ChunkCommitted, ChunkDuplicate, ChunkDeferred, ChunkFailed, ChunkRejected]:
    """Advance a durable prefix once; preserve out-of-order acks for replay."""
    if (
        request.durable_chunks < 0
        or request.durable_bytes < 0
        or request.chunk_index < 0
        or request.chunk_bytes <= 0
    ):
        return ChunkRejected(request.durable_chunks, request.durable_bytes)
    if not request.acknowledged:
        return ChunkFailed(request.durable_chunks, request.durable_bytes)
    if request.chunk_index < request.durable_chunks:
        return ChunkDuplicate(request.durable_chunks, request.durable_bytes)
    if request.chunk_index > request.durable_chunks:
        return ChunkDeferred(
            request.durable_chunks, request.durable_bytes, request.chunk_index, request.chunk_bytes,
        )
    return ChunkCommitted(request.durable_chunks + 1, request.durable_bytes + request.chunk_bytes)


@dataclass(frozen=True)
class SearchChangeRequest:
    current_generation: int
    visible_generation: int
    active_generation: int


@dataclass(frozen=True)
class SearchChanged:
    current_generation: int
    visible_generation: int
    cancel_generation: int


@dataclass(frozen=True)
class SearchChangeRejected:
    current_generation: int
    visible_generation: int


@operation
def change_search_input(request: SearchChangeRequest) -> Union[SearchChanged, SearchChangeRejected]:
    """Invalidate old results and REQUEST cancellation, without assuming it ran."""
    if (
        request.current_generation < 0
        or request.visible_generation < 0
        or request.active_generation < 0
        or request.visible_generation > request.current_generation
        or request.active_generation > request.current_generation
    ):
        return SearchChangeRejected(request.current_generation, request.visible_generation)
    return SearchChanged(
        request.current_generation + 1, request.visible_generation, request.active_generation,
    )


@dataclass(frozen=True)
class SearchPublishRequest:
    current_generation: int
    result_generation: int
    visible_generation: int
    completed: bool


@dataclass(frozen=True)
class SearchPublished:
    visible_generation: int
    current_generation: int


@dataclass(frozen=True)
class SearchStale:
    visible_generation: int
    current_generation: int


@dataclass(frozen=True)
class SearchFailed:
    visible_generation: int
    current_generation: int


@dataclass(frozen=True)
class SearchPublishRejected:
    visible_generation: int
    current_generation: int


@operation
def publish_search_result(
    request: SearchPublishRequest,
) -> Union[SearchPublished, SearchStale, SearchFailed, SearchPublishRejected]:
    """A late result cannot overwrite a newer visible generation."""
    if (
        request.current_generation < 0
        or request.result_generation < 0
        or request.visible_generation < 0
        or request.result_generation > request.current_generation
        or request.visible_generation > request.current_generation
    ):
        return SearchPublishRejected(request.visible_generation, request.current_generation)
    if request.result_generation != request.current_generation:
        return SearchStale(request.visible_generation, request.current_generation)
    if not request.completed:
        return SearchFailed(request.visible_generation, request.current_generation)
    return SearchPublished(request.result_generation, request.current_generation)


@dataclass(frozen=True)
class WindowRequest:
    window_id: int
    window_started_ms: int
    window_duration_ms: int
    now_ms: int
    count: int
    total: int
    last_sequence: int
    has_reading: bool
    reading_sequence: int
    reading_window: int
    reading_value: int


@dataclass(frozen=True)
class WindowAccumulated:
    window_id: int
    count: int
    total: int
    last_sequence: int


@dataclass(frozen=True)
class WindowIgnored:
    window_id: int
    count: int
    total: int
    last_sequence: int


@dataclass(frozen=True)
class WindowWaiting:
    deadline_ms: int
    count: int
    last_sequence: int


@dataclass(frozen=True)
class WindowFlushed:
    window_id: int
    count: int
    total: int
    last_sequence: int
    next_window_id: int
    next_window_started_ms: int
    unconsumed_reading: bool
    next_count: int


@dataclass(frozen=True)
class WindowRejected:
    window_id: int
    count: int
    last_sequence: int


@operation
def update_window(
    request: WindowRequest,
) -> Union[WindowAccumulated, WindowIgnored, WindowWaiting, WindowFlushed, WindowRejected]:
    """Deduplicate ordered readings and flush partial processing-time windows.

    Sequence numbers are monotone on this input channel: an older sequence
    is a replay, not a newly admitted out-of-order reading. Event-time window
    assignment and arbitrary reordering would need additional source state.
    Flushing returns whether the caller must retain and replay its input.
    """
    if (
        request.window_id < 0
        or request.window_started_ms < 0
        or request.window_duration_ms <= 0
        or request.now_ms < request.window_started_ms
        or request.count < 0
        or request.last_sequence < -1
        or (request.has_reading and request.reading_sequence < 0)
    ):
        return WindowRejected(request.window_id, request.count, request.last_sequence)
    deadline = request.window_started_ms + request.window_duration_ms
    if request.now_ms >= deadline:
        return WindowFlushed(
            request.window_id, request.count, request.total, request.last_sequence,
            request.window_id + 1, deadline, request.has_reading, 0,
        )
    if not request.has_reading:
        return WindowWaiting(deadline, request.count, request.last_sequence)
    if request.reading_window != request.window_id or request.reading_sequence <= request.last_sequence:
        return WindowIgnored(request.window_id, request.count, request.total, request.last_sequence)
    return WindowAccumulated(
        request.window_id, request.count + 1, request.total + request.reading_value,
        request.reading_sequence,
    )
