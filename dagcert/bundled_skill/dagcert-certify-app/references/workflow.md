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

## Required application surfaces

**UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THESE LITERALLY. THEY ARE SHIPPED APPLICATION
SURFACES, NOT EXAMPLE CODE TO MODIFY.**

Copy `examples/stats_viewer` unchanged and serve it at `/stats`. Copy
`examples/violation_banner/dagcert-violation-banner.js` unchanged, serve it as
`/dagcert-violation-banner.js`, include it on every user-facing application shell, and expose
`GET /dagcert/runtime-events` with `violation_count` and `last_violation`. Framework-specific route
glue is expected; redesigning, restyling, inlining, renaming, or reimplementing either shipped asset
is not. Verify `/stats`, violation appearance, × dismissal, and reappearance for a later violation
in the real browser. Omit either surface only after an explicit user opt-out and record that opt-out
in the certification handoff. Run `python -m dagcert help app-surfaces` for the installed contract.

## Contract

The hardened `dagcert-contract/v6` JSON or YAML object contains `workers`, `tasks`, `resources`,
task-local `timings`, finite typed-path `compositions`, and metadata. Each composition step names
the source outcome it traverses, and adjacent steps must match a real typed dependency edge.
Each task has an `implementation` binding
with `language`, source-root-relative `path`, and `symbol`. For Python, Dagcert parses that exact
callable, requires one explicit source-defined input class and an inline closed union of explicit
source-defined outcome classes, runs strict mypy itself, and seals the result. The contract contains
no authoritative `input_type` or `output_type` fields.
The current Python provider certifies synchronous operations only; async callables fail closed until
the approved external verifier can prove cancellation and awaited exception behavior.

Python operations use `@dagcert.runtime.operation`, a type-preserving source marker. Dagcert runs
strict mypy and then invokes a digest-pinned Nagini/Viper container with networking disabled and the
source mounted read-only. Nagini verifies the complete bound file and must prove that no undeclared
exceptional exit is reachable. Missing Docker/image, unsupported syntax, translation failure,
timeout, internal verifier error, or any failed proof refuses issuance. Expected failures are
explicit return variants; task operations may not declare `Exsures`. The contract's `outcomes`
array must cover the extracted union exactly and gives each variant its `acquire`, `consume`, and
`produce` effects. A derived resource
formula uses the minimum effect across all variants. Resources contain
`capacity`, `initial`, and `unit`. Every task has a duration timing; other timing metrics may be
`interval`, `wait`, or `age`. An `assumed` timing requires zero samples and makes results conditional.

Task operations also may not declare `Requires`, because a task must be total over its complete
source input type. Executable application modules may not use Nagini `Assume` or `ContractOnly`.
V6 external tasks are the sole exception: they name a separate source-owned `ContractOnly` proof
stub, a real executable adapter module, and the external provider module/symbols. Dagcert overlays
only that adapter path during Nagini verification, seals both digests and the provider identity,
and keeps `ContractOnly` out of production code. The adapter uses `external_boundary`, which checks
the real return annotation with Typeguard and publishes success, raised-exception, or wrong-type
events to `ExternalEvidenceMonitor`.
Resolve provider ownership with the active certification interpreter. Its standard-library,
`purelib`, and `platlib` modules are external even when a project virtualenv sits beneath the source
root. Seal distribution metadata when it exists, but do not require it. For non-environment code,
an ignore/exclusion does not by itself turn an application module into an external provider.
The proof stub may state only the canonical `Ensures(Result() is not None)` postcondition. Dagcert
rejects arbitrary axioms such as `Ensures(False)`; richer predicates belong in executable validators.

Dagcert resolves decorator provenance from imports and rejects locally defined lookalikes or local
modules shadowing `dagcert`/`dataclasses`. Strict mypy rejects `Any` at the source boundary. Keep all
claim-relevant input construction and transformation inside bound operations; a verified leaf does
not certify exception-producing glue that ran before the call.

Each v6 dependency is `{"task": "UPSTREAM", "outcome_type": "Variant"}`. Dagcert verifies that the
variant is in the upstream source return union and exactly equals the downstream source input type.
This makes dependency arrows typed dataflow rather than documentation.

Every task is either an `operation` or `instrumentation`. A composition contains at least two
connected operation tasks and names the exact duration case and finite execution count for each.
Instrumentation cannot be included. The kernel computes a conservative serial upper bound from
the certified leaf bounds; a composition never declares its own measured timing.

Each v6 task also contains `error_budget`, either null or an object with basis
`engineering_assumption`, one canonical duration `evidence_case`, source-derived `good_outcomes`, a
`bad_event_probability_upper` in `[0,1)`, and positive `minimum_observations`. A finite chance
composition uses the union bound: sum `step.count` times each task
budget and cap at one. The kernel never multiplies success probabilities or assumes independence.
`good_outcomes` may include every real outcome; Dagcert never requires an invented failure branch.
For a chance path it must equal the exact single outcome selected by the step. A chance claim directly compares the composition
success lower bound or failure upper bound with a literal probability in `[0,1]`; `or`, `not`, and
implication escape branches are invalid. Observed outcomes merely check that the retained rate does
not already exceed the declared premise.

## Timing evidence

Evidence is JSON Lines. Each v6 line contains `task_id`, `case`, `value_ms`, `worker_id`,
`source_fingerprint`, `recorded_at`, and the actual runtime `outcome_type`. It may also contain
`observed_worker_concurrency`,
`resource_acquired`, `resource_consumed`, `resource_produced`, `resource_levels`, and `metadata`.
Evidence cannot declare task input/output types. Every duration sample is checked against its exact
source outcome's effects. An undeclared outcome, unexpected exception sentinel, or legacy evidence
type label makes analysis fail. Error budgets classify explicit task outcomes; they cannot turn an
undeclared exception into an acceptable probabilistic branch.

## Mandatory English requirements

`dagcert-english-requirements/v2` is required for new issuance.
Each claim has a stable ID, complete plain-English statement, exact primitive and required-checker
references, explicit assumptions, a basis (`observed`, `derived`, or `chance`), and a formula. Observed claims
use a null formula and describe retained executions. Derived claims use the fixed kernel algebra
and cannot cite application checkers as proof. The certificate embeds both its normalized content and exact
file digest. This is the source of truth for what the certificate means; it is not a separate audit
input and cannot be reconstructed from checker output.

Chance claims use a finite composition operator or
`external_failure_probability_upper`/`external_success_probability_lower`. They cite every
participating `error-budget:TASK` and state the simplified engineering probability premises in
English. These are conditional envelopes, not statistical estimates from the retained sample.

`dagcert lint` and issuance run the mandatory deterministic translation audit. All formal tasks and
timings must be covered by the English claims; primitive references must resolve; assumed timings
must have explicit English assumptions; and issuance requires every checker named by a claim.
`dagcert-certificate/v10` embeds source type extraction, strict-mypy result, the digest-pinned
Nagini/Viper proof result and scope, the exact source-verification descriptor plus its core-file
manifest hash, that recomputable audit, and kernel claim
analysis. The Luna workflow below is the optional,
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

Core structural progress rejects a task whose dependencies are unreachable on every typed outcome
or whose consumed resource has neither sufficient initial supply nor any reachable producer.
It separately reports may-reachable, must-reachable, and outcome-conditional tasks.
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
models that do not resemble the actual application graph. It also verifies that every implementation
binding is the production worker boundary, that dependency edges follow real source types, and that
failure/exception outcomes and their effects were not omitted or falsely assigned success production.

## Handoff

State the exact source fingerprint, certificate digest, included timing claims, selected checker
names, and any unsupported claims. Also disclose every application behavior change made while
certifying. If certification motivated an unapproved behavior regression, undo it and do not issue.
