# One task with an internal external call

This example proves one logical application task. The task strips its input, calls the real
`urllib.parse.unquote` adapter, handles every typed boundary outcome, and lowercases the decoded
path. The external call is a sealed effect inside `url.normalize`; it is not a second DAG task.

Run it with a pinned Maledictus executable:

```text
python -m examples.certified_nested_external_call.certify PATH_TO_MALEDICTUS
```

