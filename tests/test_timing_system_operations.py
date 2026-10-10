"""Exercise real policy decisions, including adversarial event orderings."""

from dataclasses import replace

import pytest

from examples.timing_systems.operations import (
    AVDeferred,
    AVJoined,
    AVJoinRequest,
    AVReserveFull,
    BackgroundBatch,
    BatchDispatchRequest,
    BatchWaiting,
    ChunkAckRequest,
    ChunkCommitted,
    ChunkDeferred,
    ChunkDuplicate,
    ChunkFailed,
    DispatchRejected,
    InteractiveBatch,
    SearchChanged,
    SearchChangeRequest,
    SearchFailed,
    SearchPublished,
    SearchPublishRequest,
    SearchStale,
    WindowAccumulated,
    WindowFlushed,
    WindowIgnored,
    WindowRequest,
    WindowWaiting,
    WorkerBusy,
    WorkerIdle,
    acknowledge_chunk,
    change_search_input,
    dispatch_batch,
    join_av,
    publish_search_result,
    update_window,
)


def test_av_join_requires_matching_identity_and_contiguous_prefix() -> None:
    request = AVJoinRequest(8, 8, 8, 2500, 2500, 4000, 10000)
    assert join_av(request) == AVJoined(9, 6500, 2500, 10000)
    assert join_av(replace(request, video_sequence=9)) == AVDeferred(8, 4000, 10000)
    assert join_av(replace(request, audio_sequence=9, video_sequence=9)) == AVDeferred(8, 4000, 10000)
    assert join_av(replace(request, video_ms=2400)) == AVDeferred(8, 4000, 10000)


def test_finite_av_reserve_defers_full_segment_and_resumes_after_playback() -> None:
    request = AVJoinRequest(4, 4, 4, 3000, 3000, 8000, 10000)
    assert join_av(request) == AVReserveFull(4, 8000, 10000)
    assert join_av(replace(request, reserve_ms=7000)) == AVJoined(5, 10000, 3000, 10000)


def test_shared_gpu_does_not_preempt_running_background_work() -> None:
    request = BatchDispatchRequest(100, 200, 5, 8, 80, 40, 4, 10)
    assert dispatch_batch(request) == WorkerBusy(200, 5, 8)
    # Once the actual running job ends, interactive work takes precedence.
    assert dispatch_batch(replace(request, now_ms=200)) == InteractiveBatch(4, 1, 8)
    assert dispatch_batch(replace(request, now_ms=200, interactive_count=0)) == BackgroundBatch(4, 0, 4)


def test_single_interactive_request_is_flushed_at_its_timer_without_a_full_batch() -> None:
    request = BatchDispatchRequest(109, 0, 1, 20, 100, 0, 8, 10)
    assert dispatch_batch(request) == BatchWaiting(110, 1, 20)
    assert dispatch_batch(replace(request, now_ms=110)) == InteractiveBatch(1, 0, 20)


def test_shared_dispatch_has_explicit_idle_and_invalid_state_results() -> None:
    request = BatchDispatchRequest(100, 0, 0, 0, 0, 0, 4, 10)
    assert dispatch_batch(request) == WorkerIdle(100, 0, 0)
    assert dispatch_batch(replace(request, batch_target=0)) == DispatchRejected(100, 0, 0)


def test_sync_acknowledgement_counts_unique_durable_bytes_only_once() -> None:
    request = ChunkAckRequest(0, 0, 0, 4096, True)
    assert acknowledge_chunk(request) == ChunkCommitted(1, 4096)
    after_commit = replace(request, durable_chunks=1, durable_bytes=4096)
    for _ in range(10):
        assert acknowledge_chunk(after_commit) == ChunkDuplicate(1, 4096)
    assert acknowledge_chunk(replace(after_commit, chunk_index=1, acknowledged=False)) == ChunkFailed(1, 4096)


def test_out_of_order_sync_ack_retains_payload_until_missing_prefix_arrives() -> None:
    request = ChunkAckRequest(0, 0, 1, 2048, True)
    assert acknowledge_chunk(request) == ChunkDeferred(0, 0, 1, 2048)
    assert acknowledge_chunk(replace(request, chunk_index=0, chunk_bytes=4096)) == ChunkCommitted(1, 4096)
    assert acknowledge_chunk(replace(request, durable_chunks=1, durable_bytes=4096)) == ChunkCommitted(2, 6144)


def test_latest_search_publish_cannot_be_overwritten_by_an_older_completion() -> None:
    changed = change_search_input(SearchChangeRequest(8, 7, 8))
    assert changed == SearchChanged(9, 7, 8)
    assert publish_search_result(SearchPublishRequest(9, 9, 7, True)) == SearchPublished(9, 9)
    assert publish_search_result(SearchPublishRequest(9, 8, 9, True)) == SearchStale(9, 9)
    assert publish_search_result(SearchPublishRequest(9, 9, 9, False)) == SearchFailed(9, 9)


def test_continuous_search_changes_invalidate_each_preceding_generation() -> None:
    for generation in range(20):
        assert change_search_input(SearchChangeRequest(generation, 0, generation)) == SearchChanged(
            generation + 1, 0, generation,
        )
        assert publish_search_result(SearchPublishRequest(generation + 1, generation, 0, True)) == SearchStale(0, generation + 1)


def test_telemetry_deduplicates_readings_and_does_not_combine_different_windows() -> None:
    request = WindowRequest(3, 100, 50, 110, 0, 0, -1, True, 40, 3, 9)
    assert update_window(request) == WindowAccumulated(3, 1, 9, 40)
    after_reading = replace(request, count=1, total=9, last_sequence=40)
    assert update_window(after_reading) == WindowIgnored(3, 1, 9, 40)
    assert update_window(replace(after_reading, reading_sequence=41, reading_window=4)) == WindowIgnored(3, 1, 9, 40)


def test_telemetry_flushes_partial_window_even_if_no_more_readings_arrive() -> None:
    request = WindowRequest(3, 100, 50, 149, 1, 9, 40, False, 0, 0, 0)
    assert update_window(request) == WindowWaiting(150, 1, 40)
    assert update_window(replace(request, now_ms=150)) == WindowFlushed(3, 1, 9, 40, 4, 150, False, 0)


@pytest.mark.parametrize("count,total", [(0, 0), (1, 9)])
def test_telemetry_timer_does_not_silently_discard_a_simultaneous_reading(count: int, total: int) -> None:
    request = WindowRequest(3, 100, 50, 150, count, total, 40, True, 41, 4, 12)
    assert update_window(request) == WindowFlushed(3, count, total, 40, 4, 150, True, 0)
