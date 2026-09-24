# Example: bounded buffer

This example contains one producer, one finite inventory, and one consumer. It proves only a
declared finite horizon; it is not unrestricted temporal logic.

```json
{
  "id": "work-remains",
  "kind": "bounded_non_starvation",
  "inventory_resources": ["ready", "running"],
  "producer": {"task": "prepare", "timing": "duration"},
  "consumer": {"task": "deliver", "timing": "duration"},
  "horizon": 5,
  "metadata": {}
}
```

The producer timing needs a certified upper bound; the consumer timing needs a certified lower
bound. Dagcert uses worker concurrency, the initial inventory, and every typed outcome's resource
delta. A producer counts only if every possible outcome replenishes the selected inventory.

The separate dispatch claim avoids hiding scheduler fairness:

```json
{
  "id": "dispatch-bounded",
  "kind": "bounded_response",
  "trigger_resource": "ready",
  "response_task": "deliver",
  "response_timing": "dispatch",
  "upper_ms": 5,
  "metadata": {}
}
```

`deliver/dispatch` must be a certified `wait` timing, and `deliver` must consume `ready` in its
start effects. If inventory can reach zero, the error reports the consumer completion, elapsed
time, guaranteed production, maximum consumption, and remaining inventory.

This proof has a finite horizon and uses the declared work-conserving producer/service envelope.
It does not claim unrestricted temporal liveness. The runnable conditional example is
`examples/certified_structured_pipeline`.
