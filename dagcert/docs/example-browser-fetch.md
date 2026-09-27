# Typed browser fetch boundary

Use `dagcert-contract/v9` `external_handoffs` when a source-proved application value crosses a
browser/HTTP platform boundary into a source-proved operation in another language. Do not create a
fake Python browser task and do not use an instrumentation timing as the transport proof.

The complete runnable example is installed at `examples/certified_browser_fetch`. It contains a
real JavaScript `fetch` request and JSON response. Its two handoffs bind:

- JavaScript `boolean` to Python `bool` through the exact `requestAccepted` JSON field.
- Python `bool` to JavaScript `boolean` through the exact `accepted` JSON field.

Each handoff names the source task/outcome, optional source outcome field, destination task/input
field, transport kind, wire field, platform assumption, latency upper bound, and engineering
bad-event probability. Dagcert checks the endpoint types extracted from the real source, permits
only its fixed representation-preserving mapping table, adds transport latency exactly once, and
includes the transport budget in the composition union bound.

`url_query` currently permits JavaScript/TypeScript `string` to Python `str`. A generic query
`boolean` to Python `bool` bridge is refused because URL query values are strings unless the
application defines and proves a codec.

Run the copied example with a digest-pinned Maledictus package:

```powershell
python -m examples.certified_browser_fetch.certify C:\proof-tools\maledictus.exe
```
