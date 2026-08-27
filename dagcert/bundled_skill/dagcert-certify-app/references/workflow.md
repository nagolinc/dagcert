# Dagcert command and artifact reference

## Commands

```text
dagcert init APP_ROOT
dagcert lint APP_ROOT/dag_contract.json --requirements APP_ROOT/english_requirements.json
dagcert fingerprint APP_ROOT --exclude dag_contract.json --exclude english_requirements.json
dagcert analyze APP_ROOT/dag_contract.json APP_ROOT/artifacts/timings.jsonl --requirements APP_ROOT/english_requirements.json --source-root APP_ROOT
dagcert issue --contract APP_ROOT/dag_contract.json --evidence APP_ROOT/artifacts/timings.jsonl --requirements APP_ROOT/english_requirements.json --source-root APP_ROOT --output APP_ROOT/artifacts/certificate.json
dagcert verify APP_ROOT/artifacts/certificate.json --contract APP_ROOT/dag_contract.json --evidence APP_ROOT/artifacts/timings.jsonl --requirements APP_ROOT/english_requirements.json --source-root APP_ROOT
```

Repeat `--check-result PATH` on both `issue` and `verify` to attach optional checker results.
Repeat `--exclude PATTERN` identically when project-specific source exclusions are necessary.

## Contract

The hardened `dagcert-contract/v3` JSON or YAML object contains `workers`, `tasks`, `resources`,
task-local `timings`, finite `compositions`, and metadata. A task's `input_type` and `output_type` are stable
application type identifiers; Dagcert records them but does not import or execute application code.
Task resource effects contain `acquire`, `consume`, and `produce` amounts. Resources contain
`capacity`, `initial`, and `unit`. Every task has a duration timing; other timing metrics may be
`interval`, `wait`, or `age`. An `assumed` timing requires zero samples and makes results conditional.

Every task is either an `operation` or `instrumentation`. A composition contains at least two
connected operation tasks and names the exact duration case and finite execution count for each.
Instrumentation cannot be included. The kernel computes a conservative serial upper bound from
the certified leaf bounds; a composition never declares its own measured timing.

## Timing evidence

Evidence is JSON Lines. Each line contains `task_id`, `case`, `value_ms`, `worker_id`,
`source_fingerprint`, `succeeded`, and `recorded_at`. It may also contain
`observed_worker_concurrency`, `observed_input_type`, `observed_output_type`,
`resource_acquired`, `resource_consumed`, `resource_produced`, `resource_levels`, and `metadata`.
Successful duration samples must report matching types and every declared resource effect. Any
retained failed attempt makes analysis fail; it cannot be discarded in favor of a later passing retry.

## Mandatory English requirements

`dagcert-english-requirements/v2` is required for new issuance.
Each claim has a stable ID, complete plain-English statement, exact primitive and required-checker
references, explicit assumptions, a basis (`observed` or `derived`), and a formula. Observed claims
use a null formula and describe retained executions. Derived claims use the fixed kernel algebra
and cannot cite application checkers as proof. The certificate embeds both its normalized content and exact
file digest. This is the source of truth for what the certificate means; it is not a separate audit
input and cannot be reconstructed from checker output.

`dagcert lint` and issuance run the mandatory deterministic translation audit. All formal tasks and
timings must be covered by the English claims; primitive references must resolve; assumed timings
must have explicit English assumptions; and issuance requires every checker named by a claim.
`dagcert-certificate/v5` embeds that recomputable audit and kernel claim analysis. The Luna workflow below is the optional,
user-requested semantic audit and never replaces this always-on coverage check.

## Optional checker result

A `dagcert-check-result/v2` document contains a unique `checker`, boolean `passed`, exact
`source_fingerprint`, `contract_sha256`, `evidence_sha256`, `requirements_sha256`, optional
`primitive_refs`, findings, and free-form facts. Valid references are `worker:ID`, `task:ID`, `resource:ID`, and
`timing:TASK/CASE`.

Checkers are ordinary application tools. Dagcert does not register checker kinds or interpret
their free-form facts; it validates their identity bindings, result, and primitive references.
They may support observed application facts but cannot prove a derived formula.

The kernel not implementing a derivation does not make the behavior uncertifiable. For example,
“the database entries appear as the correct UI rows” is checked by comparing an application-defined
read-only database projection with Selenium observations and emitting a bound check result. See
`python -m dagcert help database-ui` and `examples.optional_browser_checker`. The application owns
the query, equivalence key, selectors, user/session setup, and test cases; Dagcert owns result
binding and certificate verification. Do not invent a new primitive for this structure.

Core structural progress rejects a task whose dependencies are unreachable or whose consumed
resource has neither sufficient initial supply for a first execution nor a reachable producer.
The result assumes reachable producer task types can recur, resource effects match runtime,
acquisition is atomic, and scheduling is fair. A timing-based checker may diagnose sustained
throughput, non-starvation, or bounded lag, but its boolean cannot prove those derived properties.
An unsupported derived formula remains uncertified.

## User-requested independent audit handoff

Run the optional example's `prepare` command with the exact mandatory English requirements file.
There is no second claims file that can diverge. It writes one `claim-NNN` directory per claim,
each with its own sealed packet,
exact worker prompt, response schema, and expected response path. The prompt is rendered from the
reviewable `examples/independent_audit_prompt.txt` template, and the packet embeds the exact source
manifest and source contents. For every directory, the active
ChatGPT/Codex agent performs a separate tool call (shown as its argument object):

`prepare` preflights every claim and refuses the entire audit if any packet or rendered prompt is
larger than the 200,000-byte default. Do not launch a worker and do not increase the limit merely to
silence that error. Remove repeated source/evidence/checker metadata, keep timing samples compact,
and store large enumerations once in a content-addressed artifact referenced by SHA-256. Override
`--max-packet-bytes` only for an explicit user-approved reason.

```text
py -m examples.optional_openai_luna_audit prepare \
  --contract APP_ROOT/dag_contract.json \
  --evidence APP_ROOT/artifacts/timings.jsonl \
  --source-root APP_ROOT \
  --requirements APP_ROOT/english_requirements.json \
  --output-directory APP_ROOT/artifacts/independent-audit
```

```json
{
  "task_name": "dagcert_semantic_audit_claim_NNN",
  "fork_turns": "none",
  "model": "gpt-5.6-luna",
  "message": "<the complete contents of claim-NNN/worker-prompt.txt>"
}
```

This is a call to the built-in `spawn_agent` collaboration tool, not a shell command or OpenAI API
request. It uses the active ChatGPT/Codex subscription session and requires no API key or separate
API billing. Use
`fork_turns="none"`, a fresh worker, and a unique task name for every claim; never batch claims into
one audit. Save each final JSON as that directory's `worker-response.json`, then run the example's
`accept --handoff-directory ...` command. Acceptance checks every sealed digest, binding, and strict
response shape before producing one aggregate `dagcert-check-result/v2`. Attach it to issuance only
if the user wants the audited claims included.

```text
py -m examples.optional_openai_luna_audit accept \
  --contract APP_ROOT/dag_contract.json \
  --evidence APP_ROOT/artifacts/timings.jsonl \
  --requirements APP_ROOT/english_requirements.json \
  --source-root APP_ROOT \
  --handoff-directory APP_ROOT/artifacts/independent-audit \
  --output APP_ROOT/artifacts/independent-audit-result.json
```

The worker response is a substantive engineering review, not a one-sentence verdict. It separately
records claim reasoning, a Rule 0 assessment, reviewed source files, strengths, weaknesses,
improvements, test-fitting risks, evidence gaps, and claim-invalidating findings. Passing one claim
does not erase weaknesses and does not certify the application as a whole.
The worker must reconstruct the execution DAG from source and compare it with the contract. It
fails synthetic observer/summary stopwatches presented as derivations, missing queues or
reservations, omitted failure transitions, average-rate substitutions for burst bounds, and proof
models that do not resemble the actual application graph.

## Handoff

State the exact source fingerprint, certificate digest, included timing claims, selected checker
names, and any unsupported claims. Also disclose every application behavior change made while
certifying. If certification motivated an unapproved behavior regression, undo it and do not issue.
