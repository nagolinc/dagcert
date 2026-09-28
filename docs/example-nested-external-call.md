# One task containing an external call

Use this shape when an external-library call is an ordinary function call inside one unit of
application work. It is not a separate DAG task unless the application actually schedules,
queues, retries, or hands off that work separately.

The complete runnable example is in `examples/certified_nested_external_call`. Its contract has
exactly one task, `url.normalize`. The task declares `external_calls` containing
`stdlib.url.unquote`; the reusable `external_boundaries` entry binds that ID to the real decorated
adapter, provider module, provider symbols, and proof overlay.

Maledictus checks all of the following before Dagcert can issue:

- the task implementation imports the declared adapter from the declared source file;
- the declared operation directly calls it;
- the adapter uses the matching literal `@external_boundary` ID;
- strict mypy sees the real `ExternalSuccess | ExternalRaised | ExternalTypeViolation` result;
- every reachable outcome is handled before the operation returns its own typed outcome;
- the adapter body is checked against the hash-bound external provider overlay.

Local preprocessing and postprocessing remain ordinary statements in the same operation. Do not
split them into artificial DAG nodes merely because the middle statement calls external code.

Heap-returning libraries follow the same rule. For example, this remains one application task:

```python
with builtins.open(path, "r", encoding="utf-8") as handle:
    content = handle.read()
return classify(content)
```

The external contract declares `open(...) -> TextIO`, the permissions granted on `Result()`, and
the contracts for `TextIO.__enter__`, `read`, and `__exit__`. If `__enter__` returns the same object,
the stub must say `Ensures(Result() is self)`; neither Python's annotation nor Maledictus guesses
that identity. Maledictus proves the complete factory/enter/body/exit composition inside the one
source-bound operation, and Dagcert hash-seals the reported factory and heap type.
