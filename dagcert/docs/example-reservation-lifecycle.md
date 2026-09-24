# Example: reservation lifecycle

This example isolates two-phase resource effects. Capacity is reserved when an operation starts,
not when it completes.

```json
{
  "id": "prepare",
  "start_resources": {
    "free": {"consume": 1},
    "preparing": {"produce": 1}
  },
  "outcomes": [
    {
      "type": "Prepared",
      "resources": {
        "preparing": {"consume": 1},
        "ready": {"produce": 1}
      },
      "metadata": {}
    },
    {
      "type": "PreparationFailed",
      "resources": {
        "preparing": {"consume": 1},
        "free": {"produce": 1}
      },
      "metadata": {}
    }
  ]
}
```

The corresponding conservation proof is deliberately affine and small:

```json
{
  "id": "slots-conserved",
  "kind": "linear_invariant",
  "expression": {
    "free": 1,
    "preparing": 1,
    "ready": 1,
    "running": 1
  },
  "operator": "eq",
  "bound": 5,
  "metadata": {}
}
```

Dagcert checks the initial value and every task-start and typed-outcome transition. If the failure
outcome omits its release, the proof returns the exact failing transition and affine delta.

V7 evidence records start effects separately as `start_resource_consumed`,
`start_resource_produced`, and `start_resource_acquired`; completion effects retain the existing
resource fields. A declared phase that is absent from retained runtime evidence fails analysis.

See `examples/certified_structured_pipeline` for a complete v11 certificate whose `prepare` and
`publish` tasks move slots through start and completion phases.
