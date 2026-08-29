# Required Dagcert application surfaces

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE DAGCERT'S SUPPLIED STATS AND BANNER APIS
> LITERALLY. DO NOT COPY, MODIFY, OR REIMPLEMENT THEIR FRONTEND CODE.**

There is no second installer. The normal `pip install dagcert` provides both functions. For Flask:

```python
from dagcert import banner, stats

stats(app, certificate="artifacts/certificate.json", evidence="artifacts/timings.jsonl")
banner(app)
```

`stats(...)` registers `/stats` and binds its initial data to that exact certificate. It must show
one DAG node per sealed task, the sealed workers/resources, matching source fingerprint, available
evidence, recent violations first, and obvious red/green task and worker health. If `evidence` is
omitted, Dagcert uses `timings.jsonl` beside the certificate when present.

`banner(...)` registers `/dagcert/banner.js` and `/dagcert/runtime-events`, serving the packaged
`dagcert-violation-banner.js` component. It does not inject or rewrite HTML responses. Include the
supplied component on every user-facing shell with this literal tag unless the user explicitly opts
out:

```html
<script src="/dagcert/banner.js"></script>
```

The banner defaults to the top. Set `?position=bottom`, `left`, or `right` on the script URL when the
user requests another edge. The supplied component handles the layout—do not fork its CSS.

The banner polls the supplied feed, appears as a dismissible red warning, and links a task-bearing
violation to `/stats?task=<task-id>#graph`. `banner(..., extra_events=callable)` can merge retained
application-level premise failures into Dagcert's own `runtime_violations()` records.

The files under `examples/stats_viewer` and `examples/violation_banner` are the packaged UI source
and standalone preview. In particular, `sample-data.js` is a visual demo only. Never copy it into an
application, never expose its three demo tasks as real stats, and never hand-build substitute route
or banner behavior when these APIs are available.

Verify the installed integration in the real browser: `/stats` has exactly the sealed task IDs; a
forced violation makes the matching task and worker red; the banner appears; its dismiss button
hides only the current violation; and a later violation makes it reappear. Omit either surface only
on explicit user request and record that opt-out in the certification handoff.
