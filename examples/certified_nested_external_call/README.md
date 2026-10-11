# One task with an internal external call

This example demonstrates source proof for one logical application task. The task strips its input, calls the real
`urllib.parse.unquote` adapter, handles every typed boundary outcome, and lowercases the decoded
path. The external call is a sealed effect inside `url.normalize`; it is not a second DAG task.

The task proof stops at the explicit `urllib.parse.unquote` contract; URL decoding internals are
not prerequisites. A structure builder should use the same boundary shape for an established
parser/schema validator: validated object or error, followed by the application's outcome
handling. See the [worked certification workflow](../../docs/CERTIFICATION_WORKFLOW.md) for the
typed example and mandatory stop rule before any dependency-internals or verifier work.

It is not an observation-only certificate example. Its historical requirements retain an
`observed` claim specifically so current Dagcert refuses issuance; a source-proof demonstration is
not by itself a system guarantee. Use the example for the nested external-call boundary shape, not
as a certificate template.

Run it with a pinned Maledictus executable:

```text
python -m examples.certified_nested_external_call.certify PATH_TO_MALEDICTUS
```

