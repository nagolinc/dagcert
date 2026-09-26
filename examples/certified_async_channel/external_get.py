"""Checked boundary around the standard-library queue get."""

import queue

from dagcert.runtime import external_boundary

from app import PreparedJob, QueueTakeRequest, QueueTakeResponse
from queue_state import work_queue


@external_boundary("stdlib.queue.get")
def get_job(request: QueueTakeRequest) -> QueueTakeResponse:
    empty = PreparedJob("")
    try:
        job = queue.Queue.get(
            work_queue,
            block=request.blocking,
            timeout=0.01 if request.blocking else None,
        )
        return QueueTakeResponse("taken", job, "")
    except queue.Empty:
        return QueueTakeResponse("empty", empty, "work queue is empty")
    except Exception as exc:
        return QueueTakeResponse("failed", empty, str(exc))
