# Example: fork-join

This example isolates structured parallel composition. One prepared value is validated and
checksummed concurrently. A final `publish` operation accepts a real source-owned join record with
two fields: `validation: Validated` and `checksum: Checksummed`.

```json
{
  "kind": "sequence",
  "children": [
    {
      "kind": "leaf",
      "task": "prepare",
      "timing": "duration",
      "outcome_type": "Prepared"
    },
    {
      "kind": "parallel_all",
      "children": [
        {
          "kind": "leaf",
          "task": "validate",
          "timing": "duration",
          "outcome_type": "Validated"
        },
        {
          "kind": "leaf",
          "task": "checksum",
          "timing": "duration",
          "outcome_type": "Checksummed"
        }
      ]
    },
    {
      "kind": "leaf",
      "task": "publish",
      "timing": "duration",
      "outcome_type": "Published"
    }
  ]
}
```

The `publish` dependencies bind each branch to the corresponding real input field:

```json
[
  {
    "task": "validate",
    "outcome_type": "Validated",
    "input_field": "validation"
  },
  {
    "task": "checksum",
    "outcome_type": "Checksummed",
    "input_field": "checksum"
  }
]
```

Dagcert derives `prepare + max(validate, checksum) + publish` only if worker concurrency and
acquired-resource capacity permit both branches to overlap. Otherwise it conservatively derives a
serial sum. A missing branch dependency or a field whose source annotation has the wrong type is a
contract error.

The complete runnable form is
`examples/certified_structured_pipeline/dag_contract.json`; its `PublishInput` is the real join
record. `parallel_all` also rejects a hidden dependency from one branch into another.
