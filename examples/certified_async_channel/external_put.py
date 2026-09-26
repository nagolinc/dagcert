"""Checked boundary around the standard-library queue put."""

import queue

from dagcert.runtime import external_boundary

from app import QueuePutRequest, QueuePutResponse
from queue_state import work_queue


@external_boundary("stdlib.queue.put")
def put_job(request: QueuePutRequest) -> QueuePutResponse:
    try:
        queue.Queue.put_nowait(work_queue, request.job)
        return QueuePutResponse("queued", request.job, "")
    except queue.Full:
        return QueuePutResponse("full", request.job, "work queue is full")
    except Exception as exc:
        return QueuePutResponse("failed", request.job, str(exc))
