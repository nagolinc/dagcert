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
does not infer this from matching types: the group is explicit so an accidental missing join cannot
be weakened into an alternative. A group must contain at least two edges, all members must feed the
same source input slot, and that slot cannot also have an ungrouped dependency. Separate input
fields and separate group names remain conjunctive.

When the same external adapter is called in several contexts, keep the production decorator's
canonical identity stable and give each DAG task its contextual identity:

```python
@external_boundary("settings.read")
def read_settings(request: SettingsRequest) -> SettingsValue:
    return provider.read(request)
```

```json
{
  "id": "startup.settings.read",
  "role": "external",
  "implementation": {
    "language": "python",
    "path": "settings_adapter.py",
    "symbol": "read_settings"
  },
  "external_contract": {
    "boundary_id": "settings.read",
    "stub_path": "settings_contract.py",
    "assumption": "The pinned provider returns the declared SettingsValue.",
    "provider": {"module": "settings_provider", "symbols": ["read"]},
    "success_outcome": "SettingsValue",
    "evidence_case": "call"
  }
}
```

Another task such as `refresh.settings.read` may bind the same canonical boundary only when its
implementation and external contract are identical. At runtime, a boundary event is ambiguous
between those contexts, so record it with
the call in `monitor.task_context("startup.settings.read")` while the monitor is installed. The
context uses Python context-local state, so concurrent threads or async tasks do not overwrite one
another. V10 evidence retains both `task_id` and `boundary_id`; a missing or mismatched canonical
boundary makes the sample unusable and fails analysis.

```python
with monitor_external_boundaries(monitor):
    with monitor.task_context("startup.settings.read"):
        result = read_settings(request)
```

Do not create contextual aliases merely to make a composition connect. Each task ID must represent
a real execution context, and `alternative_group` describes real alternative producers—not retries,
fallback degradation, or several values required to construct one input record.
