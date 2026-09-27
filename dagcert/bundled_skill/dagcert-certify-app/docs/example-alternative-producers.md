# Example: alternative producers and contextual external calls

The complete passing reference certificate is installed under
`examples/certified_alternative_producers`.

Use `alternative_group` when several real call sites can independently supply the same input to a
task. Dependencies without a group remain ordinary all-of prerequisites. Every named group is a
one-of prerequisite: at least one member must be reachable.

```json
{
  "id": "request.build",
  "depends_on": [
    {
      "task": "startup.request.reserve",
      "outcome_type": "ReservedRequest",
      "alternative_group": "request-source"
    },
    {
      "task": "ambient.request.reserve",
      "outcome_type": "ReservedRequest",
      "alternative_group": "request-source"
    },
    {
      "task": "submitted.request.reserve",
      "outcome_type": "ReservedRequest",
      "alternative_group": "request-source"
    }
  ]
}
```

This means `(startup OR ambient OR submitted)`, not `startup AND ambient AND submitted`. Dagcert
does not infer this from matching types. A group must contain at least two edges, all members must
feed the same source input slot, and that slot cannot also have an ungrouped dependency. Separate
input fields and separate group names remain conjunctive.

For repeated calls to one external adapter, put a canonical `boundary_id` in each contextual
external task's `external_contract`. It must match the adapter's `@external_boundary(...)` value.
V10 evidence retains both the contextual `task_id` and canonical `boundary_id`; execute a shared
adapter call inside `monitor.task_context(task_id)` when several tasks share the boundary.
A missing or mismatched boundary makes the sample unusable and fails analysis.
