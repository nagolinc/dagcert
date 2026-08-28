# Certification status

The current v5 source-bound observational model was collected once after its implementation and
documentation changed. That run passed the unchanged bounds and produced a verified certificate
`2be5f21145eb92a61a983490447abc8a0a7a0728fab8485cb505160792309d21`, bound to source fingerprint
`c385804fa1402c6f5382b6334b77261b6d0844c934b0c8d5c9e62d7225e3e3f5`.

Its production SQLite boundaries are strict-mypy-checked source bindings. Every task is explicitly
observational instrumentation, so Nagini is sealed as not applicable and the browser/HTTP/SQLite
promise remains observed through the real projection checkers; it is not presented as a proved
Python or JavaScript DAG.

The preceding rollback-journal run remains part of the engineering record: `items.insert/http`
observed 39.862 ms and certified to 51.821 ms under the unchanged 1.3 safety factor, outside the
50 ms bound. It was not retried unchanged and was not represented as certified.
