# `/stats` certificate dashboard

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THIS DIRECTORY LITERALLY. IT IS A SHIPPED
> APPLICATION SURFACE, NOT EXAMPLE CODE TO MODIFY.**

This default application surface turns Dagcert artifacts into a useful browser dashboard: the task DAG,
worker ownership, resource flow, per-task timing histograms, throughput/staleness trends,
guarantees, assumptions, and source identity. It is presentation-only code. It does not run during
certification and introduces no Dagcert primitive or guarantee.

Serve this directory with any static server, for example:

```text
py -m http.server 8765 --directory examples/stats_viewer
```

Open `http://127.0.0.1:8765/`. Copy these assets unchanged and serve them at `/stats`; do not
redesign, restyle, inline, rename, or reimplement the viewer unless the user explicitly asks. The
page starts with representative data and can load a
`dagcert-contract/v6` JSON file, timing-evidence JSONL, and `dagcert-certificate/v10` JSON file from
the browser. It visualizes the task DAG, resource flow, per-task distributions, recent normalized
timings, derived guarantees, and conditional assumptions.
