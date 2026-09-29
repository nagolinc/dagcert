# JavaScript callback interface assertions

Dagcert's `verified_interface` declaration can describe synchronous or asynchronous
execution, primitive results, `void`, and closed record parameters. An asynchronous
return type describes the fulfilled value, not a `Promise` object. The task covers
the callback invocation through its completion; it is not completed merely because
the callback returned a pending promise.

```json
{
  "execution": "asynchronous",
  "parameters": [
    {
      "name": "snapshot",
      "type": {
        "kind": "record",
        "fields": [
          {"name": "readyToServe", "type_name": "number"},
          {"name": "revision", "type_name": "number"}
        ]
      }
    }
  ],
  "return_type": "void"
}
```

Primitive parameters retain their existing `{"name": "value", "type": "number"}`
form. Record fields are required, uniquely named, and primitive; their canonical
order is by name. Bare `object`, `any`, `unknown`, optional fields, dynamic keys,
and parameter type `void` are refused. These declarations describe only the
supported closed shapes; they cannot stand in for a richer application's payload.

Parsing this declaration is not source proof. The pinned backend must report the
same execution kind, fulfilled result, parameter order, and exact closed field
shape from proved source. A synchronous result cannot satisfy an async declaration.
Missing interfaces and altered or additional evidence are refused. Source and
toolchain hashes remain part of the normal proof boundary.

For record parameters the compiler result uses
`{"name": "snapshot", "descriptor": {"kind": "record", "fields": [...]}}`.
Primitive compiler results retain `{"name": "value", "type_name": "number"}`.
This bridge does not establish record provenance: arbitrary JavaScript objects may
contain getters or proxy effects, and the backend must reject a boundary whose
record provenance is not proved. It must likewise reject unsealed async callees,
platform calls, or application state effects.

The bridge alone does not prove browser callback closures, nested HTML or class
bindings, mutable application state, or DOM/fetch/audio/timer behavior. Those need
source and platform-effect proofs. A proof of a primitive helper must not be
presented as a proof of its enclosing callback.
