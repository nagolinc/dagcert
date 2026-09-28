# Imported helpers stay inside one task

Use this shape when one scheduled worker invocation calls application-owned helper functions in
other Python modules. A source-file or function-call boundary is not automatically a DAG task.

```python
# worker_operation.py -- the only contract task
from dagcert.runtime import operation
from pipeline.prepare import prepare

@operation
def run_once(request: WorkRequest) -> WorkCompleted | WorkRejected:
    prepared = prepare(request)
    if isinstance(prepared, WorkRejected):
        return prepared
    return WorkCompleted(prepared.value)
```

Dagcert starts with `worker_operation.py` as a proof root. It resolves `pipeline.prepare` and every
application-owned Python module reachable from it against the exact source manifest. Those modules
are sent to Maledictus as proof-only sources with no task-bound symbol. Maledictus proves their
complete supported bodies and returns their exact hashes and source-import edges. The certificate's
`source_verification.proof_source_closure` separately records:

- task-bound proof roots;
- proof-only imported files and SHA-256 digests;
- explicit import edges and implicit package-initializer edges.

The contract still contains one task. Add another task only when production has another scheduled
invocation, queue, retry, or handoff. Do not copy helper code into the root operation, leave helper
glue unproved, or create a task per imported function.

An application source import excluded from the exact manifest is an error; exclusion cannot relabel
it as an external library. Imports that resolve only through the certification interpreter remain
external and require either a backend model or an explicit external contract. Unsupported import
or helper syntax fails closed.
