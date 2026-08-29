# Required Dagcert application surfaces

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THESE LITERALLY. THEY ARE SHIPPED APPLICATION
> SURFACES, NOT EXAMPLE CODE TO MODIFY.**

Certification work includes two default user-facing integrations:

1. Copy `examples/stats_viewer` unchanged and serve its `index.html`, `style.css`, `app.js`, and
   `sample-data.js` at `/stats`.
2. Copy `examples/violation_banner/dagcert-violation-banner.js` unchanged, serve it as
   `/dagcert-violation-banner.js`, and include this exact tag on every user-facing app shell:

```html
<script src="/dagcert-violation-banner.js"></script>
```

The banner expects `GET /dagcert/runtime-events` to return:

```json
{
  "violation_count": 1,
  "last_violation": {
    "recorded_at": 1787952000.0,
    "message": "image presentation exceeded its certified bound"
  }
}
```

Return `{"violation_count": 0, "last_violation": null}` when no violation has been observed. Feed
Dagcert's `runtime_violations()` records and any application-level certified-premise failures into
that same retained event stream. Do not present a violation as success, and do not erase the
persistent record when the user dismisses the banner.

When a violation identifies a task through `task_id`, `task`, `node_id`, or a `task:` primitive
reference, the banner links to `/stats?task=<task-id>#graph`. The literal viewer scrolls to and
highlights that failing DAG node. If the event does not identify a task, it links to `/stats#graph`
without guessing.

Framework glue may map routes and serialize events. It must not redesign, restyle, inline, rename,
or reimplement the shipped viewer or banner. Verify both surfaces in the real browser: `/stats`
loads, a forced violation produces the red warning, × dismisses the current warning, and a later
violation makes it reappear.

These surfaces do not change whether a certificate passes. They make the certificate and runtime
failures visible. Omit either surface only when the user explicitly asks not to include it, and
record that opt-out in the final certification handoff.
