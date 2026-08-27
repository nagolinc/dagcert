# Certification status

The current source-typed v4 model was collected once after its implementation and documentation
changed. That run passed the unchanged bounds and produced verified v6 certificate
`d3bc2b9e801b6f4b431819b2a359adf94d8b41560b6e350e58a7e451930a7ffd`, bound to source fingerprint
`832044b60c53929b0766b99122e10cd69b6f21e5465fc7150497a7ff3f861c37`.

Its production SQLite operations are compiler-checked source bindings. Browser timings are typed
instrumentation and the browser/HTTP/SQLite promise remains observed through the real projection
checkers; it is not presented as a Python-derived JavaScript DAG.

The preceding rollback-journal run remains part of the engineering record: `items.insert/http`
observed 39.862 ms and certified to 51.821 ms under the unchanged 1.3 safety factor, outside the
50 ms bound. It was not retried unchanged and was not represented as certified.
