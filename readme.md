# DOES YOUR LLM ALSO STRUGGLE WITH QUEUE THEORY?

Your app compiles. The happy-path tests pass. Then real users discover that a worker can starve, a
resource can never become available, work arrives faster than it completes, derived state becomes
permanently stale, or an “async” action quietly blocks the UI.

Dagcert helps an LLM prove that the exact application performs and keeps making progress. It turns
plain-English product promises into a formal task/resource model, proves those guarantees from the
real execution DAG and explicit engineering premises, and binds the result to exact source and
supporting evidence.

## Calling an LLM and expecting structured output? Start here.

```text
dagcert --help structuredLLMOutput
```

**This is a standard recipe, not a new proof project.** Copy the
[working structured-output example](examples/structured_llm_output/README.md), change the
consumer's schema and application names, and run its source check immediately. It uses the existing
`@external_boundary` API: a real validator checks the response; the application returns a usable
plan or explicit failure. Failed attempts cost time and produce no useful output.

The [complete recipe](dagcert/docs/structured-llm-output.md) supplies the adapter, operation,
provider contract, DAG wiring, verifier command, behavior checks, and failure accounting.
`dagcert help structuredLLMOutput` is equivalent. **Agents: read this recipe as soon as you identify
an LLM structured-output task. Do not begin with JSON/parser proofs or verifier changes.**

## Start here: build the app into provable tasks

Start from the behavior the application must guarantee. **Refactoring actual production work
into clean tasks is expected certification work. The existing file and class layout is not a
constraint.** Preserve required behavior while changing the implementation boundaries.

1. **Name the exact promise and trace its critical dependency path.** Include parallel feeders,
   queues, dispatch, shared resources, and the consumer's definition of a useful result. A fast
   final stage cannot compensate for a missing upstream supply guarantee.
2. **Choose small, consumer-driven proof obligations.** For example: a structure request produces
   a usable plan or an explicit failure; only matching completed media receives playback credit.
   These "microclaims" are a way of organizing work, not additional Dagcert primitives.
   **Target one concrete claim about one named node, edge, or transition, with an obvious
   "we prove it by..." method and a few minutes of proof work.** If it expands into several
   independent facts or a whole-worker proof, split it again and reuse accepted task contracts.
3. **Refactor the real execution path into source-proved tasks.** Give each a clear input, closed
   outcomes, and explicit native-library boundaries. Production must call these implementations.
   Do not substitute an observer, a copied proof-only implementation, or an assumption about
   application-owned code. A helper or external call need not become another DAG node.
4. **Prove each task, then compose its resource, timing, and failure contracts.** Include the time
   and capacity spent on failed attempts and retries. Check dispatch and refill behavior as well
   as capacity. Use measurements to check explicit engineering premises, not to manufacture them
   from a passing run.

**Certify task contracts, not dependency internals.** Before proving a task, define its statically
typed input, closed success/error outcomes, consumer-required guarantees, resources, and timing
accounting. Bind established parsers, schema validators, HTTP clients, and model services through
explicit trusted external contracts. For example:

```text
parse_and_validate(text, schema) -> SchemaObject | Error
success: the object satisfies the supplied schema
error: no useful output; all elapsed time still counts
```

Prove the application's schema selection, call, outcome handling, and downstream use under that
contract. Do not make JSON grammar, recursive JSON types, dictionary reads, string operations,
or validation-library loops prerequisites for a task-level claim. Refactor production code to use
an established parser/schema validator instead of proving an unnecessary custom implementation.
Record what is assumed about the dependency separately from what is proved about the application.

**Stop rule:** if the next step is proving dependency internals or extending Dagcert/Maledictus to
represent them, stop that work and correct the task boundary first. A verifier refusal does not
authorize scope expansion. Verifier development is a separate task requiring explicit user scope;
first show the exact consumer-level obligation that remains after using suitable typed boundaries
and existing external contracts. Do not add limits or weaken the claim to bypass the issue.

Start with the smallest actual task and test its intended property and a deliberately false
variant. Complete microclaims in the agreed order. Browser, database, parser, or verifier work
requires its own relevance to the requested claim; being reachable in a call stack is insufficient.

See the [worked certification workflow](docs/CERTIFICATION_WORKFLOW.md): a structure builder with
explicit failures and retries, a parallel backend streaming DAG, and runnable repository examples
with their precise certification status.

For existing accepted component proofs, [carry native contracts and proof annotations
through the public issuer](dagcert/docs/native-proof-support.md). Keep each component's
native interfaces scoped to that component; certificate issuance and independent
verification rerun the actual proofs.

Dagcert is designed to catch a large class of failures involving:

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

> **Certify this app with https://github.com/nagolinc/dagcert. Derive every promise from the real
> worker/task/resource DAG and source-proved operations. Start with small consumer-driven claims;
> refactor actual production work into clean proved tasks, then compose them. Preserve required
> product behavior. For any LLM structured-output task, first run
> `dagcert --help structuredLLMOutput` and adapt its checked example.
> Define typed inputs and success/error outcomes first; stop proofs at explicit
> trusted dependency contracts. Do not turn task certification into parser or verifier development.
> Use measurements only as supporting run evidence, never as the promise itself,
> and do not add product restrictions merely to make the certificate pass.**

That is the intended interface. The agent can install Dagcert, read its installed help, initialize
the focused agent guide, inspect the complete examples, instrument the real runtime boundaries, and
return both a certificate and an honest account of anything it could not prove.

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, THE AGENT MUST USE DAGCERT'S SUPPLIED `/stats`
> VIEWER AND DISMISSIBLE RED VIOLATION BANNER LITERALLY. THEY ARE APPLICATION APIS, NOT EXAMPLE CODE
> TO COPY OR MODIFY.** Call `stats(app, certificate=..., evidence=...)` and `banner(app)`, then include exactly
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

Certification is guarantee-first. It is not permission to add arbitrary finite queues,
timeouts, rate limits, rejection, automatic retry, debounce delays, cancellation, or serialization
points merely to obtain a passing certificate. A truthful failure is better than a certificate
obtained by breaking the app.

> **THE OBSERVATION-ONLY ROUTE IS THE BAD PATH.** A successful retained run belongs in
> `dagcert analyze`; it says nothing about the next run and is not a certificate. Presenting a
> benchmark report as a behavioral guarantee will disappoint the user. Dagcert therefore refuses
> every `observed` certificate claim. Certificate promises must be `derived` or `chance` claims
> over the actual DAG, source-proved leaves, and explicit engineering premises.

## The core library and what it can certify

The formal application model contains five primitives:

- **workers** perform work and have declared concurrency;
- **tasks** bind real source callables whose compiler-checked input and closed outcome-union types
  form typed dependency edges;
- **resources** have capacity and state that tasks acquire, consume, or produce;
- **typed channels** connect a source-typed enqueue outcome to a source-typed dequeue payload
  field across a real asynchronous queue; and
- **timings** describe duration, arrival interval, waiting, or age, using measurements or explicit
  assumptions.

Those primitives are enough to prove conditional statements such as:

- every declared task has a feasible worker/resource path;
- the declared graph has no structural blocked state;
- task X receives enough work to avoid starvation after warm-up;
- available workers provide enough service capacity for the arrival rate;
- model X is never more than G generations out of date; and
- a handler or visible action completes within its declared deadline.

V16 issuance separates real `operation`, `external`, and `instrumentation` tasks and supports a
small structured workflow algebra: `leaf`, `sequence`, `parallel_all`, `finite_repeat`, the v11
leaf and v12 structured forms of `threshold_repeat`, the v8+ `async_handoff`, and the v9+
`external_handoff`.
Every v7+ leaf names the source outcome traversed and every sequence boundary must match real typed
dependency edges. A fork/join binds each branch output to a field of the downstream source input
record. A composition has no stopwatch of its own: Dagcert computes its bound from exact leaf
duration cases, using `max` for a parallel region only when worker and acquired-resource capacity
permit the declared overlap. Certificate claims are `derived` (a kernel deterministic formula)
or `chance` (a kernel probability bound over explicit engineering premises). Chance premises may
describe finite invocations, an external contract, or whole-window timing envelopes.
Retained observations are run evidence reported by `dagcert analyze`; they are not certificate
claims. Derived and chance claims cannot delegate proof to an arbitrary checker boolean.

A `threshold_repeat` is the restricted finite K-of-N operator. In v12 its body may be one real task
or a structured `sequence`, `parallel_all`, `finite_repeat`, `async_handoff`, or
`external_handoff`. One named terminal typed outcome is the qualifying exit, and that outcome alone
must produce exactly one unit of the named resource. Dagcert unions every leaf and transport
bad-event envelope in one attempt to obtain `q`, then uses
`P(miss) <= N*q/(N-K+1)`. This conservative Markov bound does not assume independent attempts.
Latency is a conservative all-N batch bound derived from each body's real workers, acquired
resources, and leaf timings; it is therefore also an upper bound on the Kth qualifying completion
when one occurs. The operator covers a predeclared finite attempt prefix. It does not prove that
inputs arrive, that an application controller actually dispatches that prefix, or that an unbounded
retry loop is live. See `dagcert help threshold-repeat`.

The same operator can prove a chance throughput envelope without claiming infinite failure-free
operation: `composition_required_successes` exposes the threshold's certified K, ordinary formula
division derives `K / T` from that value and the all-N duration bound, and the chance clause proves
the probability of reaching K. This expresses, for example, “with probability at least P,
production exceeds the playback consumption rate over this declared window” without adding a
domain-specific rate primitive.

An `async_handoff` does not pretend that a queue-poll request already contains an unknown producer
value. Its declared channel requires the producer's terminal outcome to equal the compiler-extracted
payload type and produce one queue-resource token. The successful dequeue outcome must consume one
token, and its named source input field must have that same extracted payload type. Dagcert then
unions the finite path's leaf budgets normally. It still does not infer FIFO ordering, infinite
liveness, or fairness.

An `external_handoff` is a narrow cross-language platform edge. It binds one source task/outcome
(and, for record outcomes, one compiler-extracted output field) to one destination task/input field,
plus the exact wire-field name. The kernel accepts only fixed representation-preserving mappings:
JSON `boolean`/`string` between JavaScript or TypeScript and Python `bool`/`str`, and URL-query
`string` to Python `str`. The handoff carries an explicit platform assumption, duration upper
bound, and engineering bad-event budget. Those terms are added to structured-composition latency
and union-bound calculations; they cannot be hidden inside an observer task. See
`dagcert help browser-fetch` for a runnable real `fetch` round trip.

V10 dependencies are all-of by default and can name an explicit `alternative_group` for several
real producers of the same input slot. Each group is one-of; distinct groups and ungrouped edges
remain conjunctive. Dagcert never guesses alternatives from matching types. External tasks also
separate their contextual task ID from a canonical `external_contract.boundary_id`, so the same
proved adapter can appear at real startup, refresh, or request call sites without changing its
source decorator identity. Evidence retains both identities. See
`dagcert help alternative-producers`.

### General timing proof language

Dagcert 0.23 exposes **first-order linear real arithmetic (SMT-LIB LRA)** as a
general proof language, not an enumeration of application-specific timing rules.
Every finite formula in that family is accepted for decision: exact rational
linear arithmetic, Boolean combinations, piecewise relations, and arbitrarily
nested real/Boolean quantifiers. Relational composition, substitution, conjunction,
disjunction and quantification remain inside the family. New application concepts
expressible there need formulas or reusable lemmas, not a new core operator.

Pinned Z3 quantifier elimination and arithmetic decision procedures establish
valid implications or refute them. Resource exhaustion/unknown never certifies.
This does not promise automatic invariant discovery, nonlinear mathematics, or
complete verification of arbitrary application source.

Source-mode `lra_theorem` claims bind actual compiler-extracted fields and
backend-proved relations, retain engineering hypotheses and their probability
events through lemma imports, and recheck every deduction. An assumed conclusion
with an irrelevant source fact is refused as a source-derived claim. Pure
mathematical certificates have separate commands and cannot replace an application
certificate. See [`dagcert help timing-logic`](dagcert/docs/linear-timing-logic.md)
and run `python -m examples.timing_logic --certify`.

V7+ tasks also distinguish resource effects at task start from effects on each typed completion
outcome. Kernel-owned state claims cover affine lifecycle invariants, finite-horizon
producer/consumer supply, a separate bounded dispatch wait, and generic `curve_bound` expressions.
The latter provide real-time calculus over arrival, available-service, departure, and inventory
envelopes. Addition, subtraction, min/max, time shifts, and min-plus convolution/deconvolution use
exact rational piecewise-affine curves, with no sampled time grid. They express buffer floors,
backlog ceilings, rolling throughput, and delay bounds without application-specific kernel types.

An all-time curve bound is supported when every premise explicitly covers all time; finite call
budgets or a successful session cannot establish it. Whole-window probabilistic envelopes use
`state_claim_success_probability_lower`, which first proves the conditional bound and then unions
the envelope and routing failure budgets. Worker capacity is not output: the derivation also needs
actual activations, service/dispatch bounds, typed outcomes, and every producer/consumer effect.
Source verification remains mandatory. See [`dagcert help timing-algebra`](dagcert/docs/timing-algebra.md)
for twenty application patterns and run `python -m examples.timing_algebra` for the two-producer
reserve example. These rules are not arbitrary temporal logic.

Variable-sized work uses quantity-valued `curve_bound` network programs:
worker service, interval work/quantity costs (including failures), shared
reservations, bounded batching and busy-period deficits. Source-bound
`relational_invariant` claims use real backend postconditions plus Z3 induction
for retained state, matching identities, capacity and duplicate accounting.
No caller-supplied proof boolean substitutes for source verification. See
[`dagcert help timing-systems`](dagcert/docs/timing-systems.md) and
`python -m examples.timing_systems --certify` for five source policies and an
infinite variable-streaming theorem. The example explicitly distinguishes
the proved policies from whole deployed applications and their external
timing/ownership assumptions. Pure source-policy tasks need no invented
stopwatch timing; any timing claim still requires its actual timing premises.

Actual completed quantity can feed another source-bound task through `transfer`
and can change units through a source-proved `quantity_map`. Convolutions prove
input/output conservation on every outcome; service capacity or discarded work
cannot masquerade as useful departures. These are convenient network-calculus
front ends, not the boundary of the general LRA language.

For Python, each v7+ task points to the production source file and symbol. Dagcert reads the real
one-input annotation and closed return union, rejects `Any` throughout those boundary variants,
runs strict mypy over the real implementation body itself, and requires an explicitly selected,
digest-pinned proof backend to prove the complete bound file has no undeclared exceptional exit.
Nagini/Viper remains the default. The independently distributed Maledictus executable is available
as an alternate backend for its advertised `dagcert-closed-typed-operations/v4` fragment. The
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
Proof-only stubs are parsed by one closed contract dialect rather than accepted as arbitrary Python.
Scalar and nominal-reference contracts remain restricted to their documented result relations.
Maledictus's heap dialect additionally permits a declared external function or method to return a
declared heap class, but only explicit `Result()` field permissions and identity relations become
available to the caller. It does not invent ownership, freshness, or context-manager identity.
For callable-valued frozen dataclass fields, an operation task may declare machine-readable
`callable_bindings`. Each binding identifies the real input field and either a source path/symbol
or an explicit external module/symbol/stub overlay. Dagcert derives the consumer operation and
input record from source rather than prose. Maledictus hash-binds every consumer, source provider,
and external stub, composes the provider's normal and exceptional outcomes, and rejects missing,
duplicate, unknown, or tampered edges.
Maledictus operation files may import application-owned helpers and frozen record types from other
Python modules. Dagcert recursively resolves the application-owned import closure from the exact
source manifest, adds every reachable module and package initializer as a proof-only source, and
does not turn those implementation files into contract tasks. The backend proves the providers and
consumer against one transitive closure and returns every source-import edge. Dagcert independently
reconstructs those imports and requires the importer, module, provider, provider hash, and imported
symbols to match; altered or omitted files or edges refuse issuance. The certificate separately
records task-bound proof roots and proof-only imported file hashes. An ignored application file
cannot be relabeled as external. See `dagcert help imported-helpers`.

An ordinary external-library call inside one worker invocation does not become another DAG task.
On a v12 contract, keep local work before the call, the call, and local work after it in one
`operation` task. Declare the adapter once in top-level `external_boundaries` and cite its ID in
that task's `external_calls`. Maledictus response v8 binds the exact consumer operation, real
source import, direct adapter call, literal boundary ID, provider overlay, and closed typed outcome
union. Create another task only when the application really schedules, queues, retries, or hands
off another unit of work. See `dagcert help nested-external-call`.

The same one-task rule applies to external heap objects. A checked external factory such as
`open(...) -> TextIO` or `post(...) -> Response`, subsequent method calls, and local application
logic stay inside the surrounding operation. Maledictus composes the factory and method contracts,
including a one-item `with factory(...) as value:` lifecycle. The stub must state every transferred
permission and, when `__enter__` returns the receiver, explicitly state `Ensures(Result() is self)`.

One operation may call several source-owned external adapters. Dagcert sends every declared
overlay in one proof request, and Maledictus composes every nonconflicting provider contract
reachable from that worker. A missing overlay, two different contracts for the same provider
module, an uncaught declared exception, or an undeclared external outcome refuses the proof. This
does not turn library calls into scheduler tasks; use `dagcert help multi-external-worker` for the
minimal environment/provider/typed-queue pattern.

The heap proof also preserves source-owned frozen records through closed generic providers and
shared typed state. A checked `Queue[T]` contract can be specialized as `Queue[PreparedJob]`; a
source module may expose `Queue[PreparedJob] | None` through one exact typed setter, and a production
adapter may read it and call `put_nowait` without packing the job, weakening it to `object`, or
splitting the library call into a fake task. Package-member imports bind the actual child module and
every participating source file is hash-sealed. The proof treats each state read as a fresh atomic
snapshot and grants no initialization, persistence, capacity, or liveness fact. See
`dagcert help async-channel`.

The v14 certificate seals strict-mypy output, the pinned verifier identity and proof scope, and
a manifest hash of the source-verification kernel and typing stubs. For Maledictus, response v8
also requires and retains the exact strict-mypy package, runtime executable, complete runtime
bundle, configuration, and contract-support hashes. Verification reruns the digest-pinned backend
and rejects any change in that recorded typechecker identity,
so verification also detects a changed type-enforcement kernel rather than trusting a version label.
Every dependency names an upstream outcome that must exactly match the downstream callable's source
input, and resource derivations use the minimum effect across every explicit outcome. Missing
backend/runtime, digest mismatch, unsupported syntax, verifier crash, translation failure, timeout,
or failed proof refuses issuance. Instrumentation is strict-mypy checked but cannot enter a derived
composition.

Select Maledictus only with an exact executable and SHA-256 pin; Dagcert does not discover, vendor,
or silently fall back between independently owned proof engines:

```powershell
dagcert lint dag_contract.json --requirements english_requirements.json `
  --proof-backend maledictus `
  --proof-backend-executable C:\proof-tools\maledictus.exe `
  --proof-backend-sha256 <64-hex-digest>
```

Pass the same three backend options to `issue` and `verify`. Verification recomputes the proof and
requires the complete v8 result—including its strict typechecker identity, callable-binding, and
embedded external-call evidence—to match the certificate.
Maledictus operation fragment v4 accepts the narrow source-owned Dagcert operation surface plus
explicit source or external-contract callable providers. Unsupported provider forms fail closed.
Source relations require the additional
`dagcert-closed-typed-operations+semantic-postconditions/v1` fragment: an ordinary typing/exception
proof or a generic heap proof is not a substitute. The sealed proof view adds outcome-guarded
native postconditions to the actual function, so `finally` and context-manager cleanup run before
the final returned value is checked. Read access to closed frozen input records does not require
an application `Requires` annotation and does not grant ownership of referenced mutable state.
An older backend lacking this joint fragment explicitly refuses relational verification.
On Windows, select
the packaged executable beside
its pinned `libz3.dll`, not a bare Cargo output missing its runtime.

Python `operation` tasks require strict mypy plus the selected proof backend. V7 also admits a
deliberately narrow JavaScript/TypeScript leaf only through the explicit Maledictus backend. The
contract's `verified_interface` is an assertion, not an authority: Maledictus asks pinned
TypeScript 5.9.3 for the real source symbol's parameter and return types, proves the accepted body
has no undeclared exceptional exit, and returns the compiler-derived interface for exact comparison.
The initial surface is synchronous with a compiler-derived vector of primitive parameters and one
primitive return. A DAG edge feeding one parameter names that parameter with `input_field`; no
wrapper or packed pseudo-input is required. Unsupported syntax or any mismatch refuses issuance.
Browser and platform behavior remain explicit external
assumptions; `tsc --strict` alone is never misrepresented as an exception-freedom proof.

Dagcert separately reports may-reachability and must-reachability. A success-only downstream branch
is structurally reachable but outcome-conditional; it is not mislabeled blocked and cannot be used
as an unconditional supply guarantee. Optional task error budgets classify a nonempty source-derived
subset of outcomes as good for one canonical duration stream. That subset may include every real
outcome; Dagcert does not require or invent a semantically bad branch. A
chance path requires each declared budget's good set to equal the exact typed outcome selected at
that step. A source-proved task with exactly that one outcome needs no budget and contributes zero;
it may still declare a conservative nonzero engineering budget without weakening the stronger
typed-totality result. Unbudgeted conditional paths remain invalid. Finite-path chance claims directly compare
the finite path's union-bound result with a literal probability; boolean fallback branches are
rejected. The kernel sums finite invocation budgets, so correlation and burstiness cannot make the
result falsely tighter.
Retained observations only check consistency with those engineering assumptions; they do not
statistically establish rare-event rates.

Temporal chance claims instead declare whole-window arrival, service/outcome, and routing
envelopes. A service envelope may restrict allowed outcomes only as an explicit joint premise
covering every invocation in that window; the complete source outcome union remains checked.
Finite-window and all-time premises must retain their actual scope.

The core also provides a small checker protocol. Applications can record case-bounded semantic
facts—such as database rows matching the visible DOM—without adding database, browser, queue, or UI
concepts to the core ontology. These results belong in run reports and supporting evidence; they
do not establish certificate promises by themselves.

### From a plain-English requirement to a formal certificate

The English requirements are the source of truth, not documentation added after the proof:

```text
english_requirements.json
        |
        | each claim declares derived/chance basis, assumptions, and references
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
   a stable ID, derived/chance basis, explicit assumptions, and exact references. Every claim has a
   kernel formula and cannot cite a checker as proof.
2. `dag_contract.json` is the formal translation using the five primitives.
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
retained event feed. Surface registration fails if the certificate self-digest, sealed evidence
digest, or sample source fingerprint does not match; evidence is not optional or substitutable. A
task with no retained sample is shown as neutral **not observed**, not failed or healthy. The
examples directory is only a standalone visual preview; its bundled three-task dataset must never
be served as application stats.

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

The repository ships current hardened example certificates. Historical audit artifacts remain
review material but are not proof for changed requirements.

### Structured worker-pipeline certificate

[`examples/certified_structured_pipeline`](examples/certified_structured_pipeline/README.md) is a
generic job pipeline demonstrating source-typed fork/join, task-start reservations, completion
effects, slot conservation, bounded finite supply, bounded dispatch, finite repetition, and
union-bound confidence. Its checked-in v11 certificate uses no aggregate observer task. Run
`python -m dagcert help composed-worker-pipeline` for the installed walkthrough.

### TypeScript verified-leaf certificate

[`examples/certified_typescript_leaf`](examples/certified_typescript_leaf/README.md) composes two
real TypeScript functions whose compiler-derived interfaces and accepted bodies are proved by the
digest-pinned Maledictus backend. The platform timing is explicitly assumed. Run
`python -m dagcert help external-verified-leaf` for the boundary rules.

### Certified vote and flow model

[`examples/certified_vote`](examples/certified_vote/README.md) is a deliberately narrow in-process
example showing how the core primitives express performance and conditional flow guarantees.

Its guarantee certificate establishes:

- strict-mypy-checked, Nagini-proved source-owned task boundaries; and
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

### Database-to-UI run-report example — not a certificate

[`examples/certified_database_ui`](examples/certified_database_ui/README.md) is retained as a
legacy SQLite/HTTP/JavaScript/Selenium measurement and semantic-audit example. Its directory name is
historical. **It is not a current Dagcert certificate example and `dagcert issue` rejects its
observation-only requirements.**

Its workflow checks:

- exact database-to-DOM membership and ordering on initial load;
- ascending and descending sorting;
- next/previous pagination;
- insertion through the browser, HTTP endpoint, SQLite commit, and final DOM;
- deletion through the same real boundaries;
- `<50ms` measured non-streaming HTTP work; and
- `<16ms` immediate browser feedback and local rendering for the measured workload.

Its checked-in historical artifact demonstrates the now-forbidden observation-only path. It may be
inspected as a run record, but current Dagcert deliberately refuses to issue or verify it as a
guarantee certificate. Do not copy this workflow when asked to certify an application.
See the complete [status record](examples/certified_database_ui/artifacts/STATUS.md),
[plain-English requirements](examples/certified_database_ui/english_requirements.json), and
[formal contract](examples/certified_database_ui/dag_contract.json).
Run `python -m dagcert help database-ui` for the run-report boundary and the explanation of what a
future source-proved browser guarantee would still need.

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
