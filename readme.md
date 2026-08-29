# DOES YOUR LLM ALSO STRUGGLE WITH QUEUE THEORY?

Your app compiles. The happy-path tests pass. Then real users discover that a worker can starve, a
resource can never become available, work arrives faster than it completes, derived state becomes
permanently stale, or an “async” action quietly blocks the UI.

Dagcert helps an LLM prove that the exact application performs and keeps making progress. It turns
plain-English product promises into a formal task/resource model, measures the real implementation,
and produces a certificate bound to the exact source and evidence.

It is designed to catch a large class of failures involving:

- queues, arrival rates, throughput, and service capacity;
- blocked states, impossible dependencies, and unavailable resources;
- worker starvation and insufficient upstream work;
- stale models, summaries, caches, and other derived state;
- tasks that never actually execute or were never timed;
- functions receiving or returning the wrong application type;
- endpoints and user actions that miss responsiveness deadlines; and
- application/database state that never appears correctly in the real UI.

Dagcert does not claim to eliminate every bug or race condition. It produces narrow, inspectable
guarantees for named source, measurements, assumptions, and application checks. Change any bound
input and verification fails.

## Quickstart: tell your LLM to certify the app

Give the LLM building or maintaining your app this instruction:

> **Certify this app with https://github.com/nagolinc/dagcert. Measure the real application, and do
> not change product behavior merely to make the certificate pass.**

That is the intended interface. The agent can install Dagcert, read its installed help, initialize
the focused agent guide, inspect the complete examples, instrument the real runtime boundaries, and
return both a certificate and an honest account of anything it could not prove.

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, THE AGENT MUST USE DAGCERT'S SUPPLIED `/stats`
> VIEWER AND DISMISSIBLE RED VIOLATION BANNER LITERALLY. THEY ARE APPLICATION APIS, NOT EXAMPLE CODE
> TO COPY OR MODIFY.** Call `stats(app, certificate=...)` and `banner(app)`, then include exactly
> `<script src="/dagcert/banner.js"></script>` on every user-facing app shell. Never serve the
> bundled three-task demo as an application's `/stats` data.

The equivalent manual start is:

```text
python -m pip install git+https://github.com/nagolinc/dagcert.git
python -m dagcert help
dagcert init path/to/app
```

`dagcert init` copies the focused getting-started skill into the app when policy permits. Start or
reload the agent session so it discovers the skill, then give it the instruction above. Installed
`dagcert help` is the detailed source of truth; the skill is a short agent entry point into it.

Recognizable non-streaming HTTP work defaults to `<50ms`, and visible local UI feedback defaults to
`<16ms`. You do not need to specify those deadlines unless the product has a deliberate, documented
reason to use different ones.

### Rule 0: certification must improve the user experience

Certification is observational by default. It is not permission to add arbitrary finite queues,
timeouts, rate limits, rejection, automatic retry, debounce delays, cancellation, or serialization
points merely to obtain a passing certificate. A truthful failure is better than a certificate
obtained by breaking the app.

## The core library and what it can certify

The formal application model contains only four primitives:

- **workers** perform work and have declared concurrency;
- **tasks** bind real source callables whose compiler-checked input and closed outcome-union types
  form typed dependency edges;
- **resources** have capacity and state that tasks acquire, consume, or produce; and
- **timings** describe duration, arrival interval, waiting, or age, using measurements or explicit
  assumptions.

Those primitives are enough to express conditional statements such as:

- every declared task has successful completion evidence;
- every declared task has a feasible worker/resource path;
- the declared graph has no structural blocked state;
- task X receives enough work to avoid starvation after warm-up;
- available workers provide enough service capacity for the arrival rate;
- model X is never more than G generations out of date; and
- a handler or visible action completes within its declared deadline.

New v10 issuance separates real `operation`, `external`, and `instrumentation` tasks and supports finite,
source-typed multi-operation paths. Every v6 composition step names the source outcome traversed,
and consecutive steps must match a real typed dependency edge. A composition has no stopwatch of its own: Dagcert computes its
bound from exact leaf duration cases. Claims are `observed` (retained executions only), `derived`
(a fixed-algebra deterministic formula), or `chance` (a finite-composition union bound over explicit
engineering error budgets). Derived and chance claims cannot delegate proof to an arbitrary checker
boolean.

For Python, each v6 task points to the production source file and symbol. Dagcert reads the real
one-input annotation and closed return union, rejects `Any` throughout those boundary variants,
runs strict mypy over the real implementation body itself, and requires a digest-pinned
Nagini/Viper container to prove the complete bound file has no undeclared exceptional exit. The
JSON contract cannot invent `input_type` or `output_type` labels.
Decorator provenance is resolved from imports: a same-named local decorator or a shadowing local
`dagcert`/`dataclasses` module is rejected. The operation marker preserves the callable's exact
type; expected failures must be explicit return variants and unexpected exceptions fail proof.
Task operations cannot narrow their declared input with Nagini `Requires`, and executable application
modules cannot use `Assume` or `ContractOnly` to make verification vacuous. An external task may
name a separate, source-owned `ContractOnly` proof stub for a real adapter. Dagcert overlays only
that file during proof, seals the adapter/stub/provider identities, and checks every production
return or exception through a Typeguard-backed runtime boundary. Wrong types and exceptions are
retained violation outcomes, not silently trusted successes.
Provider ownership follows the active certification interpreter: modules resolved beneath its
standard-library, `purelib`, or `platlib` paths are external environment code even when a project
virtualenv is physically beneath `source_root`. Distribution metadata is sealed when available but
is not required for that classification. Only non-environment providers are compared with the
application manifest; excluding an ordinary app module does not relabel it external.
The proof-only stub is restricted to the canonical `Ensures(Result() is not None)` contract, so it
cannot inject an impossible postcondition to make an application proof vacuous.
The v10 certificate seals strict-mypy output, the pinned verifier image digest and proof scope, and
a manifest hash of the source-verification kernel and typing stubs,
so verification also detects a changed type-enforcement kernel rather than trusting a version label.
Every dependency names an upstream outcome that must exactly match the downstream callable's source
input, and resource derivations use the minimum effect across every explicit outcome. Missing
Docker/image, unsupported syntax, verifier crash, translation failure, timeout, or failed proof
refuses issuance. Instrumentation is strict-mypy checked but cannot enter a derived composition.

This provider is deliberately language-specific. Python `operation` tasks require strict mypy plus
Nagini. JavaScript and TypeScript have no approved exception/totality verifier in this release, so
Dagcert refuses to bind them as operations; they may appear only behind explicitly observational
instrumentation and cannot support derived DAG claims. `tsc --strict` alone is not misrepresented
as an exception-freedom proof.

Dagcert separately reports may-reachability and must-reachability. A success-only downstream branch
is structurally reachable but outcome-conditional; it is not mislabeled blocked and cannot be used
as an unconditional supply guarantee. Optional task error budgets classify a nonempty source-derived
subset of outcomes as good for one canonical duration stream. That subset may include every real
outcome; Dagcert does not require or invent a semantically bad branch. A
chance path requires that set to equal the exact typed outcome selected at each step. Chance claims
directly compare the finite path's union-bound result with a literal probability; boolean fallback
branches are rejected. The kernel sums finite invocation budgets, so correlation and burstiness
cannot make the result falsely tighter.
Retained observations only check consistency with those engineering assumptions; they do not
statistically establish rare-event rates.

The core also provides a small checker protocol. Applications can record case-bounded semantic
facts—such as database rows matching the visible DOM—without adding database, browser, queue, or UI
concepts to the core ontology. These support observed claims; they do not establish derived system
properties.

### From a plain-English requirement to a formal certificate

The English requirements are the source of truth, not documentation added after the proof:

```text
english_requirements.json
        |
        | each claim declares observed/derived/chance basis, assumptions, and references
        v
dag_contract.json: workers + tasks + resources + timings + compositions
        |
        | deterministic analysis + measurements of the exact app
        v
timing evidence + optional application checker results
        |
        | exact source/content binding + translation audit
        v
certificate.json
```

1. `english_requirements.json` states every promised behavior in ordinary language. Each claim has
   a stable ID, observed/derived/chance basis, explicit assumptions, and exact references. Derived
   and chance claims have kernel formulas and cannot cite a checker as proof.
2. `dag_contract.json` is the formal translation using the four primitives.
3. Runtime evidence records real task executions, timings, worker identity, actual runtime outcome
   variants, concurrency, resource effects, and failures. Source types never come from evidence.
4. Deterministic analysis checks graph/resource feasibility, timing coverage and bounds, retained
   failures, explicit assumptions, structural progress, and derived formulas.
5. Every issuance performs a mandatory deterministic translation audit. It rejects uncovered formal
   tasks or timings, unresolved English references, absent required checkers, and assumed timings
   without a matching English assumption.
6. `certificate.json` embeds the complete English requirements, source type extraction and compiler
   result, formal primitives and compositions, primitive and claim analysis, and checker results,
   with bindings to exact source and evidence.

The core modules are deliberately limited to contract loading, evidence recording, deterministic
analysis, English/formal traceability, the checker boundary, and certificate issue/verification.
Framework integrations, UI patterns, visualization, and domain-specific checks are optional
supporting code rather than new primitives.

### Independent semantic audit

Deterministic translation auditing proves coverage and traceability. It cannot decide whether a
formally valid claim faithfully captures what a person actually meant in English. When the user
requests an independent audit, the app-building ChatGPT/Codex session runs the included audit tool.

The tool generates one sealed handoff packet **per English claim**. Each packet contains that claim,
the exact source, formal contract, evidence, deterministic analysis, assumptions, and checker
results. The active session hands each packet to a different fresh `gpt-5.6-luna` worker using the
user's OpenAI subscription—no API key or separate API billing.

Each worker acts as a skeptical senior engineer, not a rubber stamp. Its structured response covers
claim reasoning, reviewed files, real user-experience impact, strengths, weaknesses, improvements,
evidence gaps, best-practice concerns, and signs that code was overfit to passing. The responses are
digest-checked and accepted into an optional certificate-bound checker result.

Preparation atomically refuses the entire audit if any per-claim packet or rendered prompt exceeds
the 200,000-byte default. That is treated as duplicated or badly structured evidence to fix—not as
a reason to send a multi-megabyte prompt or silently raise the limit.

The audit is a tool the app-building agent runs only when the user asks for it. It is never an
automatic build or release gate. See [the independent-audit workflow](docs/REFERENCE_AUDIT.md) and
the [audit handoff implementation](examples/optional_openai_luna_audit.py).

## Default application surfaces and optional helpers

The `/stats` viewer and violation banner are default application integrations unless the user
explicitly opts out. They do not add core primitives or alter certificate semantics. Other helpers
in this section remain optional.

### `/stats`: understand the certificate instead of reading JSON

The [`/stats` viewer](examples/stats_viewer/README.md) turns the bound certificate, evidence, and
retained violations into a useful browser dashboard. It shows recent violations first, then:

- the task DAG and which worker performs each task;
- resource production, consumption, acquisition, capacity, and current flow;
- timing histograms for every measured task/case;
- recent timing trends, throughput, and staleness/age signals;
- which guarantees passed or failed;
- which conclusions are conditional on assumptions; and
- exact certificate/source identity.

It is presentation-only: viewing statistics cannot change or weaken the certificate. After the one
normal `pip install dagcert`, bind it to a Flask application with the supplied API:

```python
from dagcert import banner, stats

stats(app, certificate="artifacts/certificate.json", evidence="artifacts/timings.jsonl")
banner(app)
```

This makes `/stats` render one DAG node for every sealed task and serves the banner script and
retained event feed. The examples directory is only a standalone visual preview; its bundled
three-task dataset must never be served as application stats.

### Runtime violations: make failed guarantees impossible to miss

The supplied [`dagcert-violation-banner.js`](examples/violation_banner/README.md) component polls the
application's retained `/dagcert/runtime-events` stream. On a violation it inserts a centered red
warning stating that certified guarantees do not hold, links to `/stats`, and provides an accessible
× button. Dismissal applies only to the current violation; a later violation makes the banner
reappear. `banner(app)` serves it at `/dagcert/banner.js`; it deliberately does not rewrite HTML.
Unless the user explicitly declines it, include this exact tag in every user-facing shell:

```html
<script src="/dagcert/banner.js"></script>
```

The default is `position=top`; the same script URL accepts `bottom`, `left`, or `right` when a
different edge is wanted.

Do not replace it with logs, a toast, a status pill, or a custom redesign.
When a violation identifies a task, the link opens `/stats?task=<task-id>#graph`, where the literal
viewer scrolls to and highlights the failing DAG node. Otherwise it opens `/stats#graph` without
inventing a task mapping.

### Fast frontend, slow and unreliable backend

[`optional_mithril_buffered_delta.js`](examples/optional_mithril_buffered_delta.js) implements the
important “frontend fast, backend slow” pattern for Mithril applications:

- a click changes the visible optimistic value immediately;
- rapid changes are buffered and submitted as one delta after an explicit debounce interval;
- changes made while a request is in flight become the next delta;
- an authoritative server response reconciles the displayed value; and
- after failure, the optimistic delta remains visible, the error is exposed, and retry is an
  explicit application decision rather than an invented infinite retry policy.

Dagcert can certify the immediate UI task against the 16 ms default and the asynchronous server
task separately. The helper deliberately chooses no queue limit, request timeout, rate limit,
automatic retry, or rejection policy. Its executable tests are in
[`optional_mithril_buffered_delta.test.mjs`](examples/optional_mithril_buffered_delta.test.mjs).

### Reusable flow and browser checkers

| Helper | What it provides |
| --- | --- |
| [`optional_flow_checker.py`](examples/optional_flow_checker.py) | Conditional supply/non-starvation, service-capacity, bounded-generation-lag, and blocked-state checks using only workers, tasks, resources, and timings. |
| [`optional_browser_checker.py`](examples/optional_browser_checker.py) | Read-model/database to real Selenium DOM exact-projection checks, including semantic row keys, visible fields, ordering, pagination, and repeated cases. |
| [`optional_openai_luna_audit.py`](examples/optional_openai_luna_audit.py) | The sealed one-claim-per-worker independent audit workflow described above. |

These helpers demonstrate the extension boundary. An application remains responsible for choosing
its actual query, selectors, workload, assumptions, and product behavior.

## Complete examples and their certification status

The repository ships two current hardened example certificates. Historical audit artifacts remain
review material but are not proof for changed requirements.

### Certified vote and flow model

[`examples/certified_vote`](examples/certified_vote/README.md) is a deliberately narrow in-process
example showing how the core primitives express performance and conditional flow guarantees.

Its checked-in v10 certificate establishes:

- ten successful measured executions for every declared task;
- no structural blocked state under the stated scheduling/resource assumptions;
- `<16ms` in-process vote preview and `<50ms` in-process commit;
- strict-mypy-checked, Nagini-proved source-owned task boundaries; and
- dependency edges whose upstream outcome types match the downstream source input types.
- a 98% lower engineering success budget for one finite preview-to-commit path, conditional on two
  declared 1% leaf bad-event budgets and composed without an independence assumption.

Inspect its [plain-English requirements](examples/certified_vote/english_requirements.json),
[formal contract](examples/certified_vote/dag_contract.json), and
[certificate](examples/certified_vote/artifacts/certificate.json). The former unconditional flow
claims remain removed because explicit rejection outcomes make their guaranteed production zero.
The successful typed branches are reported as may-reachable, while the example's finite chance
claim makes its leaf failure assumptions explicit.

This example deliberately makes no browser, HTTP, database, or production worker-pool promise. Its
requirements state those limitations plainly.

### Database-to-UI certification example

[`examples/certified_database_ui`](examples/certified_database_ui/README.md) is a real SQLite, HTTP,
JavaScript, and Selenium application.

Its workflow checks:

- exact database-to-DOM membership and ordering on initial load;
- ascending and descending sorting;
- next/previous pagination;
- insertion through the browser, HTTP endpoint, SQLite commit, and final DOM;
- deletion through the same real boundaries;
- `<50ms` measured non-streaming HTTP work; and
- `<16ms` immediate browser feedback and local rendering for the measured workload.

Its first rollback-journal hardened run retained a safety-adjusted HTTP timing failure. After the
application changed to use SQLite WAL mode, the first new exact-source run passed the unchanged
bounds; the current artifacts are reissued as a verified [v10 certificate](examples/certified_database_ui/artifacts/certificate.json).
This example's tasks are observational instrumentation: strict mypy checks their source types, but
the certificate does not misstate SQLite, browser JavaScript, or Selenium behavior as Nagini-proved.
See the complete [status record](examples/certified_database_ui/artifacts/STATUS.md),
[plain-English requirements](examples/certified_database_ui/english_requirements.json), and
[formal contract](examples/certified_database_ui/dag_contract.json).
Run `python -m dagcert help database-ui` for the reusable certification workflow.

## Manual CLI workflow

Agents normally discover these commands through installed help. The underlying sequence is:

```text
dagcert lint APP/dag_contract.json --requirements APP/english_requirements.json
dagcert analyze APP/dag_contract.json APP/artifacts/timings.jsonl --requirements APP/english_requirements.json --source-root APP
dagcert issue --contract APP/dag_contract.json --evidence APP/artifacts/timings.jsonl --requirements APP/english_requirements.json --source-root APP --output APP/artifacts/certificate.json
dagcert verify APP/artifacts/certificate.json --contract APP/dag_contract.json --evidence APP/artifacts/timings.jsonl --requirements APP/english_requirements.json --source-root APP
```

Repeat `--check-result PATH` during both issuance and verification for every selected application
checker. See [LIBRARY_SPEC.md](LIBRARY_SPEC.md) for exact semantics and design decisions.

## Development workspace hygiene

The repository permits exactly one top-level disposable-output directory: `.cache/`. Pytest uses
`.cache/pytest`, mypy uses `.cache/mypy`, and any repository-local test/build scratch belongs under
that same tree. Test startup rejects `cache_dir` and `--basetemp` values elsewhere in the repository;
this prevents `.pytest-cache-*`, `.pytest-local-*`, and other ad-hoc siblings from accumulating.
