# `/stats` certificate dashboard

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THE SUPPLIED `stats(...)` API LITERALLY. DO NOT
> COPY, MODIFY, OR REIMPLEMENT THIS FRONTEND IN AN APPLICATION.**

After the normal package installation, bind the viewer to the real sealed certificate:

```python
from dagcert import stats

stats(app, certificate="artifacts/certificate.json", evidence="artifacts/timings.jsonl")
```

The registered `/stats` page starts with recent violations, shows explicit worker and task health,
and renders one DAG node per task in the bound certificate. It also shows resource flow, timing
distributions, guarantees, assumptions, and source identity. Dagcert verifies the certificate
self-digest, the evidence file's sealed digest, and every sample's source fingerprint before it
registers the page. Omitting `evidence` requires a `timings.jsonl` beside the certificate. Missing,
substituted, or cross-source evidence is an error. A task with no retained runtime sample is shown
as neutral **not observed** rather than failed or healthy.

This directory is Dagcert's packaged frontend source and standalone visual preview. You may run the
preview directly while developing Dagcert:

```text
py -m http.server 8765 --directory examples/stats_viewer
```

Its `sample-data.js` contains three representative tasks for that preview only. It is not an
application certificate and must never be exposed as an application's `/stats` data.
