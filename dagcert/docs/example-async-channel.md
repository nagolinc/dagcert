# Example: typed asynchronous channel

Use an `async_handoff` when independently scheduled producer and consumer workers communicate
through a real queue. Do not invent a synchronous dependency from the produced value to the
consumer's queue-poll request.

The channel binds three facts:

- the successful enqueue outcome is the compiler-extracted payload type;
- that outcome produces exactly one token in the queue resource; and
- the successful dequeue outcome consumes exactly one token, while a named field of its real
  source input has the same compiler-extracted payload type.

```json
{
  "channels": [
    {
      "id": "prepared-jobs",
      "resource": "prepared-job-count",
      "payload_type": "PreparedJob",
      "enqueue": {
        "task": "job.enqueue.confirm",
        "outcome_type": "PreparedJob"
      },
      "dequeue": {
        "task": "job.dequeue.classify",
        "outcome_type": "JobTaken",
        "input_field": "job"
      },
      "metadata": {}
    }
  ]
}
```

The dequeue classifier might receive a record such as this. The payload is supplied by the queue,
not by the worker's earlier polling request:

```python
@dataclass(frozen=True)
class QueueTakeResponse:
    job: PreparedJob
    status: str
```

Join the independently valid producer and consumer subgraphs with the channel:

```json
{
  "kind": "async_handoff",
  "channel": "prepared-jobs",
  "producer": {
    "kind": "leaf",
    "task": "job.enqueue.confirm",
    "timing": "completion",
    "outcome_type": "PreparedJob"
  },
  "consumer": {
    "kind": "sequence",
    "children": [
      {
        "kind": "leaf",
        "task": "queue.take",
        "timing": "residence",
        "outcome_type": "QueueTakeResponse"
      },
      {
        "kind": "leaf",
        "task": "job.dequeue.classify",
        "timing": "completion",
        "outcome_type": "JobTaken"
      }
    ]
  }
}
```

Dagcert validates each child using the ordinary typed workflow rules, validates the handoff against
the real source annotations and resource effects, then flattens this one finite message path for
timing and union-bound accounting. The English claim must cite both the composition and
`channel:prepared-jobs`.

This primitive does not claim infinite liveness, FIFO ordering, or queue fairness. Those require
the relevant state claim or an explicit bounded assumption. It also does not permit combining
unrelated compositions: the producer must end at the declared enqueue outcome and the consumer
must traverse the declared dequeue outcome exactly once.
