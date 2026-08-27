# Certification status

The current source-typed v4 model was collected once after its implementation and documentation
changed. That run passed the unchanged bounds and produced verified v7 certificate
`202355d78fc6130d9da508140d656c26570c221c44c3a0e654d9a25fe3a0ac0e`, bound to source fingerprint
`ab52fec94cb41f24c6447a09a5d23fdef8a1fda9bf40c2f45b4b5eec637c8cfe`.

Its production SQLite operations are compiler-checked source bindings. Browser timings are typed
instrumentation and the browser/HTTP/SQLite promise remains observed through the real projection
checkers; it is not presented as a Python-derived JavaScript DAG.

The preceding rollback-journal run remains part of the engineering record: `items.insert/http`
observed 39.862 ms and certified to 51.821 ms under the unchanged 1.3 safety factor, outside the
50 ms bound. It was not retried unchanged and was not represented as certified.
