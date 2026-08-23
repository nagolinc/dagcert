# Optional certificate artifact viewer

This is presentation-only example code. It does not run during certification and introduces no
Dagcert primitive or guarantee.

Serve this directory with any static server, for example:

```text
py -m http.server 8765 --directory examples/stats_viewer
```

Open `http://127.0.0.1:8765/`. The page starts with representative data and can load a
`dagcert-contract/v2` JSON file, timing-evidence JSONL, and `dagcert-certificate/v4` JSON file from
the browser. It visualizes the task DAG, resource flow, per-task distributions, recent normalized
timings, derived guarantees, and conditional assumptions.
