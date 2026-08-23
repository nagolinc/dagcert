# dag-certificate

`dagcert` issues exact-source certificates about four primitives: **workers, tasks, resources, and
timings**. That is the complete application model.

Tasks acquire, consume, and produce resources. Timings cover duration, arrival interval, waiting,
and age; they may be measured or explicitly assumed. That is enough to express and derive claims
such as supplied workers not being starved, declared tasks not being structurally blocked, and a
model remaining at most G generations behind—without adding special queue, UI, HTTP, ComfyUI,
blocked-state, staleness, or proof primitives.

Certification is observational by default. It is never permission to add a finite queue, timeout,
rate limit, rejection, retry, debounce, cancellation, or serialization point merely to pass. A
truthful failure is better than a certificate obtained by making the application worse.

## Quick start

```text
python -m pip install -e .
dagcert init path/to/app
dagcert lint path/to/app/dag_contract.json --requirements path/to/app/english_requirements.json
dagcert analyze path/to/app/dag_contract.json path/to/app/artifacts/timings.jsonl --requirements path/to/app/english_requirements.json --source-root path/to/app
dagcert issue --contract path/to/app/dag_contract.json --evidence path/to/app/artifacts/timings.jsonl --requirements path/to/app/english_requirements.json --source-root path/to/app --output path/to/app/artifacts/certificate.json
dagcert verify path/to/app/artifacts/certificate.json --contract path/to/app/dag_contract.json --evidence path/to/app/artifacts/timings.jsonl --requirements path/to/app/english_requirements.json --source-root path/to/app
```

`dagcert init` also copies the bundled getting-started skill into the application when policy
permits. (`pip install` alone must not modify an arbitrary working directory.) Start or reload the
agent session so it discovers the new skill, then say:

> Using dagcert, certify this app without changing product behavior merely to pass.

The skill already applies `<50ms` for recognizable non-streaming HTTP handling and `<16ms` for
visible local UI feedback unless the product deliberately specifies another requirement.
Run `python -m dagcert help` for the installed source-of-truth guides and example index.

## What is verified

For the exact source manifest, contract, and evidence named by a certificate, Dagcert verifies:

- a mandatory plain-English requirements document with stable claim IDs, assumptions, and exact
  references to the formal primitives and application checkers that support each promise;

- an acyclic task graph with valid worker/resource references;
- feasible resource acquisitions and flows;
- a duration timing for every declared task;
- measured timing coverage and safety-adjusted lower/upper bounds;
- explicit conditional assumptions for unmeasured external timing;
- derived structural progress for the declared DAG;
- exact bindings and passing status of every selected optional checker.

The requirements document is not a fifth application-model primitive. It is the mandatory,
human-readable statement of what the certificate promises. Its full contents and SHA-256 digest
are embedded in the certificate, and verification fails if even the wording changes.

Every issuance also runs and embeds a mandatory deterministic English-to-formal translation
audit. It rejects uncovered formal tasks or timings, unresolved references, missing required
application checkers, and assumed timings that have no explicit English assumption. This proves
mapping completeness and traceability. When the user requests the deeper independent semantic
review, the Luna workflow audits whether each English statement is actually faithful to the exact
implementation and evidence; it remains a user-invoked tool, not an automatic release gate.

The generic checker boundary lets applications add new derivations without adding new primitives.
See `examples/optional_flow_checker.py` for supply, blocked-state, and generation-lag guarantees.

## Optional viewer and helpers

`examples/stats_viewer` is a presentation-only artifact viewer modeled on the useful hierarchy of
the DSPPMG statistics page. It displays the DAG, resource flow, timing distributions, recent trends,
guarantees, and assumptions. Selenium-reviewed desktop and mobile screenshots are included.

Other optional examples provide a Mithril buffered-delta UI pattern, multi-page browser checking,
and sealed independent-audit handoffs from the active ChatGPT session to one fresh
`gpt-5.6-luna` subagent per claim. The browser helper includes an exact-projection check for the
common claim that application/database rows appear correctly in the real DOM; see
[`dagcert/docs/database-ui.md`](dagcert/docs/database-ui.md), or run
`python -m dagcert help database-ui` after installation.

That installed help topic points to `examples.certified_database_ui`, a complete SQLite, HTTP,
JavaScript, and Selenium application with certified insertion, deletion, sorting, pagination,
50 ms HTTP handling, 16 ms UI feedback/rendering, and one independent Luna audit per claim.

See [LIBRARY_SPEC.md](LIBRARY_SPEC.md) for precise semantics and design decisions.
