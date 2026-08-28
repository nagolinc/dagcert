# Certified database-to-UI reference application

This is a real SQLite, HTTP, JavaScript, and Selenium reference application. See
[artifacts/STATUS.md](artifacts/STATUS.md) for the latest retained certification result. The workflow
below is reproducible; do not retry-to-pass or widen a bound when rebuilding it.

The workflow is designed to exercise and independently audit three narrow promises:

- exact row membership and ordering across initial load, ascending/descending sorting, and
  next/previous pagination;
- insertion through the real browser, HTTP endpoint, and SQLite path, followed by exact rendering;
- deletion through the real browser, HTTP endpoint, and SQLite path, followed by exact rendering.

The ordinary non-streaming HTTP deadlines are 50 ms. Immediate browser DOM feedback and local row
rendering use the 16 ms defaults. The browser checks compare application-owned read-only SQL
projections with Selenium observations using stable semantic row keys and visible fields.

The SQLite list/insert/delete operations are real v5 Python task boundaries used by the production
HTTP handlers. Dagcert extracts their named input and outcome classes and runs strict mypy. These
tasks are explicitly observational instrumentation: the certificate does not claim Nagini proved
SQLite, browser JavaScript, or Selenium. Browser
DOM timings are explicitly modeled as typed instrumentation; the certificate does not pretend that
Python type-checks the JavaScript implementation. The real Selenium/HTTP/SQLite projection checker
supports those observed browser claims.

## Attempt certification

From the Dagcert repository root, collect fresh evidence through real HTTP and Selenium boundaries:

```text
py -m examples.certified_database_ui.certify collect
```

Prepare three independently sealed audit handoffs. All three projection results are supplied to
every auditor so it can inspect the semantic browser evidence relevant to its one claim:

```text
py -m examples.optional_openai_luna_audit prepare \
  --contract examples/certified_database_ui/dag_contract.json \
  --evidence examples/certified_database_ui/artifacts/timings.jsonl \
  --requirements examples/certified_database_ui/english_requirements.json \
  --source-root examples/certified_database_ui \
  --check-result examples/certified_database_ui/artifacts/browse-projection.json \
  --check-result examples/certified_database_ui/artifacts/insertion-projection.json \
  --check-result examples/certified_database_ui/artifacts/deletion-projection.json \
  --output-directory examples/certified_database_ui/artifacts/independent-audit
```

For each `claim-NNN`, the active ChatGPT/Codex agent must launch a different fresh built-in
`spawn_agent` worker with `model="gpt-5.6-luna"`, `fork_turns="none"`, and the complete contents of
that claim's `worker-prompt.txt`. Save each final JSON to its `worker-response.json`. Do not batch
claims and do not replace the subscription-backed worker with an API-key call.

Accept the sealed responses with the same three check-result inputs:

```text
py -m examples.optional_openai_luna_audit accept \
  --contract examples/certified_database_ui/dag_contract.json \
  --evidence examples/certified_database_ui/artifacts/timings.jsonl \
  --requirements examples/certified_database_ui/english_requirements.json \
  --source-root examples/certified_database_ui \
  --check-result examples/certified_database_ui/artifacts/browse-projection.json \
  --check-result examples/certified_database_ui/artifacts/insertion-projection.json \
  --check-result examples/certified_database_ui/artifacts/deletion-projection.json \
  --handoff-directory examples/certified_database_ui/artifacts/independent-audit \
  --output examples/certified_database_ui/artifacts/independent-audit-result.json
```

Finally issue and immediately verify a certificate that requires the projection checks. Attach the
accepted independent audit only when that optional audit was freshly requested and completed:

```text
py -m examples.certified_database_ui.certify issue

py -m examples.certified_database_ui.certify issue \
  --audit-result artifacts/independent-audit-result.json
```

Collecting again changes the evidence digest and intentionally invalidates prior audit responses.
Never reuse an audit response or certificate after collection or source changes.

No queue, queue limit, runtime timeout, rate limit, retry, debounce, rejection policy, or reduced
application behavior exists merely to make the certificate pass. Selenium waits are test-harness
guards derived from the declared interaction under test and do not change the application.
