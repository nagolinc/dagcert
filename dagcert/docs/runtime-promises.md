# Runtime promises are executable and always logged

Use `dagcert.promises.PromiseMonitor` for numeric operating promises. Declare
each comparison once, with its stable promise ID, event, measured field, bound,
and (where needed) cohort/window size. The application supplies facts from its
real admission and worker boundaries; it does not decide whether to log them.

```python
from dagcert.promises import Promise, PromiseMonitor

monitor = PromiseMonitor([
    Promise("startup.prepared", "admission", "prepared_turns", ">=", 4),
    Promise("narration.turn", "narration", "elapsed_ms", "<=", 80000),
])
allowed = monitor.observe("admission", {"prepared_turns": 1},
    context={"story_id": "story-17", "epoch_id": "epoch-2"})
assert not allowed

work = monitor.start("narration", context={"story_id": "story-17", "turn_id": 5},
                     invocation_id="narration-attempt-9")
try:
    # Call the real narrator here. Its deadline is monitored while it runs.
    pass
finally:
    work.finish()
```

There is no enable flag, environment variable, observer registration, logger
configuration, or separate violation-logging call. Failures automatically go
to the Python error log, `.dagcert/violations.jsonl`, and the Dagcert banner feed.
An application can select its existing data directory in the constructor.
External-boundary failures also persist automatically. Persistence errors are
not silently discarded. Clearing the process feed does not delete saved logs.

Every event includes the promise ID, expected comparison and bound, actual
value, timestamp, invocation ID, and supplied story/turn/epoch identity. Missing,
non-finite, or incorrectly typed measurements fail. Rolling windows are separated
by `group_by` (default `story_id`); set `rolling=False` for aligned cohorts.
Deadlines report unfinished work and suppress a duplicate report at completion.

For certificates, retain the declarations in a source-bound JSON file with
`schema: "dagcert-runtime-promises/v1"` and a `promises` array of the fields above;
load it with `PromiseMonitor.from_file`. Include that same declaration in the
certificate contract and check its identity in the application's certification
workflow. A declaration in English is not an executable runtime check.

Enforce controllable premises at admission. Observe native-service promises
during execution, including failed attempts and actual committed output. A
monitor detects a failed assumption; it cannot make an external service meet a
latency bound. Never present an assumption-violating run as certified.

The executable examples and failure regressions are in
`tests/test_runtime_promises.py`, including a blocked worker, a missed startup
condition, rolling costs, missing measurements, and the banner route.
