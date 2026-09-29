# Example: one worker with several external providers

One application invocation remains one Dagcert task even when its implementation reads an
environment value, calls a remote provider, and publishes to a standard-library queue. Those are
ordinary calls inside the worker, not separately scheduled DAG nodes.

The source shape is:

```python
from dagcert.runtime import ExternalSuccess, operation
from environment_adapter import model_name
from prompt_adapter import prepare
from queue_adapter import publish
from records import PreparedJob, PromptRequest, PromptResult


@operation
def prepare_and_publish(request: PromptRequest) -> PromptResult:
    model = model_name()
    if not isinstance(model, ExternalSuccess):
        return PromptResult("environment-failed")

    prepared = prepare(request.prompt, model.value)
    if not isinstance(prepared, ExternalSuccess):
        return PromptResult("provider-failed")

    published = publish(PreparedJob(prepared.value))
    if not isinstance(published, ExternalSuccess):
        return PromptResult("queue-failed")
    return PromptResult(published.value)
```

Each adapter has its own literal `@external_boundary` and sealed provider contract. The queue
contract preserves its actual payload type and declares its finite exceptional outcome:

```python
from typing import Generic, TypeVar
from nagini_contracts.contracts import ContractOnly, Exsures

T = TypeVar("T")


class Full(Exception):
    pass


class Queue(Generic[T]):
    @ContractOnly
    def put_nowait(self, item: T) -> None:
        Exsures(Full, True)
        ...
```

The source-owned queue adapter catches that declared outcome. It does not erase
`Queue[PreparedJob]` to `object` or move the call outside the proved operation:

```python
from dagcert.runtime import external_boundary
from queue_provider import Full
import queue_state
from records import PreparedJob


@external_boundary("stdlib.queue.prepared-put")
def publish(job: PreparedJob) -> str:
    destination = queue_state.prepared
    if destination is None:
        return "unconfigured"
    try:
        destination.put_nowait(job)
        return "enqueued"
    except Full:
        return "full"
```

Declare all three adapters in top-level `external_boundaries`, then bind all three calls to the one
task:

```json
{
  "id": "prompt.prepare-and-publish",
  "role": "operation",
  "worker": "prompt-worker",
  "implementation": {
    "language": "python",
    "path": "worker.py",
    "symbol": "prepare_and_publish"
  },
  "external_calls": [
    "environment.model.read",
    "provider.prompt.prepare",
    "stdlib.queue.prepared-put"
  ]
}
```

Maledictus proves the worker, every reachable source-owned adapter/helper/record module, all three
provider overlays, and every normal or declared exceptional path in one request. Dagcert
independently hash-seals the returned files, import edges, contracts, and task-to-adapter call
edges. It refuses:

- a provider call with no matching overlay;
- conflicting contracts for the same external module;
- an uncaught `Full` outcome;
- a queue payload other than `PreparedJob`;
- or a claimed adapter the worker does not actually call.

This proof establishes type and effect closure. Queue capacity, initialization order, retry policy,
timing, and liveness remain separate Dagcert resource/timing claims; the provider contract does not
invent those properties.
