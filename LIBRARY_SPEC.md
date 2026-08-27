# Dagcert library specification

## 1. Purpose

Dagcert creates a tamper-evident, source-bound report about an application's workers, tasks,
resources, and timings. Those are its only application-model primitives.

The library is not a scheduler, runtime, queue, HTTP framework, browser harness, retry manager,
rate limiter, or deployment gate. Certification observes and reports by default. It must not add a
queue limit, timeout, rejection, cancellation, retry, debounce, serialization point, or other
behavioral regression merely to make a claim pass.

## 2. Contract schema

New issuance uses `dagcert-contract/v4`. The loader retains v2/v3 support for verification of
existing certificates. JSON is built in; YAML is available with PyYAML.

### Worker

- `id`: unique nonempty string.
- `concurrency`: positive integer describing actual simultaneous task capacity.
- `metadata`: optional opaque object.
- `role`: `operation` for real executable work or `instrumentation` for observers/aggregate probes.

### Resource

- `id`: unique nonempty string.
- `capacity`: positive finite amount.
- `initial`: nonnegative initial amount, no greater than capacity; default 0.
- `unit`: nonempty application-defined unit; default `slots`.
- `metadata`: optional opaque object.

A resource can represent transient capacity (CPU/GPU slots, connections, locks), flowing work
(prompts, messages), or a bounded quantity (generations of model lag). Dagcert does not register
resource kinds.

### Task

- `id`: unique nonempty string.
- `worker`: declared worker ID.
- `implementation`: language, source-root-relative path, and symbol for the real operation callable.
- `depends_on`: typed edges naming an upstream task and one exact upstream outcome type; the graph
  must be acyclic and the outcome must equal the downstream source input type.
- `outcomes`: the complete source return union, with a ResourceEffect mapping for every variant.
- `timings`: nonempty timing-case mapping containing at least one `duration` metric.
- `metadata`: optional opaque object.

A ResourceEffect contains nonnegative amounts:

- `acquire`: transient capacity held while the task executes;
- `consume`: units removed when an instance starts;
- `produce`: units added when an instance completes.

At least one effect must be positive. No individual acquisition, consumption, or production may
exceed resource capacity. A completed producer therefore makes work available to a downstream
consumer without adding a queue or framework primitive.

The contract is not authoritative for task types. For Python, Dagcert parses the bound source
callable, requires exactly one explicit source-defined input class and an inline finite union of
explicit source-defined outcome classes, rejects `Any` throughout that boundary, runs strict mypy
over the real implementation body itself, and seals both
the extraction and compiler result. Python operations use `@dagcert.runtime.operation`; its runtime guard
adds `dagcert.runtime.UnhandledException` to every outcome union. The contract must cover that
kernel-owned variant and cannot add, omit, or rename a source outcome.
The kernel-owned exception variant cannot be assigned resource effects. Code that recovers or
releases capacity must catch the failure and return an explicit source-defined recovery outcome.
The v4 Python provider currently rejects async callables because a synchronous decorator cannot
type exceptions and cancellation raised while awaiting them.

Decorator names are provenance-checked. `operation` must resolve from `dagcert` or
`dagcert.runtime`, and `dataclass` must resolve from the standard-library `dataclasses` module;
local rebindings and source-tree modules that shadow either trusted module are rejected. At runtime,
the operation guard recursively validates the actual input and returned dataclass fields against
the resolved source annotations. A malformed value becomes `UnhandledException`, so an `Any` value
originating in an external dependency cannot silently cross a certified task edge.

Resource effects remain formal transitions, but any unconditional derived amount is the minimum
effect across the complete source outcome union. Thus a success outcome producing one queue item
and a failure/exception outcome producing none has guaranteed production zero.

### Composition

A v4 composition is a finite, typed outcome path over at least two `operation` tasks. Each step
names an exact task duration case, source outcome, and positive integer execution count; adjacent
steps must match an actual typed dependency edge. Instrumentation tasks are
forbidden. Compositions have no directly measured timing: the kernel conservatively sums their
certified leaf upper bounds. This prevents a monolithic pipeline stopwatch from substituting for a
derivation over the actual task graph.

### Timing

A timing is a named temporal constraint on a task:

- `metric`: `duration`, `interval`, `wait`, or `age`;
- `lower_ms`: optional nonnegative exclusive lower bound;
- `upper_ms`: optional positive exclusive upper bound;
- `evidence`: `measured` or `assumed`, default `measured`;
- `minimum_samples`: positive for measured timings (default 10), zero for assumptions;
- `policy`: `max` or `percentile` for upper-bound selection;
- `percentile`: required for percentile policy, strictly between 0 and 100;
- `safety_factor`: at least 1, default 1.30.

At least one bound is required. For measured values, the certified lower value is the observed
minimum divided by the safety factor. The certified upper value is the selected maximum or
nearest-rank percentile multiplied by the safety factor. Certified values must remain strictly
inside declared bounds.

An assumed timing makes the certificate conditional. This handles external sources honestly:
`user.interaction/cadence` may assume an interval below 500ms, and every derived statement lists
that premise instead of pretending it was measured.

Standard application profiles remain ordinary duration timings:

- non-streaming HTTP handling: upper bound 50ms;
- visible local UI feedback: upper bound 16ms.

## 3. Mandatory plain-English requirements

Every certificate has an `english_requirements.json` document with schema
`dagcert-english-requirements/v2`. This is mandatory certificate input, not optional audit input or
supporting documentation. It contains at least one claim. Each claim has:

- a stable unique `id`;
- a complete plain-English `statement` describing the scoped behavior promised to the user;
- `primitive_refs` naming the workers, tasks, resources, and timings that support it;
- `checker_refs` naming any application checkers required to establish it;
- explicit `assumptions`, including workload or environment limits.
- `basis`: `observed` or `derived`;
- `formula`: null for observed claims and a fixed-algebra kernel formula for derived claims.

Every reference must resolve. Every checker named by a claim must be supplied, pass, and bind to
the exact source, contract, evidence, and requirements document. Additional checker results may be
attached as supplementary evidence; the optional independent semantic audit is one such result.
Derived claims cannot name checkers as proof. Their formulas must use a declared composition or a
connected multi-task worker/resource surface that Dagcert evaluates itself.

The requirements document does not enlarge the four-primitive ontology. It is the certificate's
mandatory human-readable promise and traceability map. Issuance embeds its complete normalized
contents and byte digest. Verification requires the exact file and rejects changed wording,
assumptions, or references, even if the formal contract is unchanged.

Issuance and verification also recompute `dagcert-translation-audit/v1`. Passing is mandatory. The
audit requires every formal task and every formal timing guarantee to appear in at least one
English claim, every primitive reference to resolve, every claim-required checker to be selected,
and every referenced assumed timing to have an explicit English assumption. The complete audit is
embedded in the certificate. Additional selected checkers are labeled supplementary rather than
silently treated as English promises.

This deterministic audit proves coverage and traceability, not natural-language entailment. On
explicit user request, the independent Luna workflow performs the semantic audit of each exact
English claim against source, contract, evidence, analysis, assumptions, and application checks.
It consumes the same mandatory requirements file and cannot substitute different prose.

### Kernel claim algebra

The claim algebra is deliberately closed and small. Numeric expressions support finite literals,
certified timing upper/lower bounds, worker concurrency, resource capacity/initial state,
minimum all-outcome task production/consumption, composition upper bounds, addition,
multiplication, division, and maximum. Boolean expressions
support comparison, conjunction, disjunction, negation, and implication. Unknown operators fail.

A derived formula must use either `composition_upper_ms` or timing bounds from at least two tasks
that form one dependency/resource-connected DAG surface plus worker/resource state. A one-task
aggregate stopwatch therefore cannot become a derived claim. Temporal reachable-state operators
are intentionally not accepted until Dagcert has a model checker for them; such claims remain
unsupported rather than being delegated to a checker boolean.

## 4. What the four primitives can express

The primitives intentionally have flow semantics:

- work-producing tasks add units to resources;
- downstream tasks consume those units;
- interval timings bound supply cadence;
- duration timings bound worker consumption rates;
- worker concurrency scales service capacity;
- resource initial amount and capacity describe warm-up supply and bounded state.

Consequently analyzers can derive statements such as:

- `image.render` has enough supplied work to avoid starvation after warm-up;
- every declared task has a feasible worker/resource path and no structural blocked state;
- `model.update` remains at most G generation units behind its producer.

These are results over the four primitives, not additional `proof`, `queue`, `blocked_state`, or
`staleness` primitives. Domain-specific helpers may construct formula syntax, but their boolean
results are not trusted proof. The kernel evaluates the normalized fixed-algebra formula.

## 5. Evidence

Timing evidence is JSON Lines. Each record contains:

- `task_id`, timing `case`, and `worker_id`;
- nonnegative generic `value_ms`;
- exact `source_fingerprint`;
- numeric `recorded_at` and the actual runtime `outcome_type`;
- optional observed worker concurrency;
- observed acquired, consumed, and produced resource amounts for declared task effects;
- optional resource levels and opaque metadata.

`value_ms` may measure duration, interval, wait, or age according to its declared timing. V4 records
with the correct task, case, worker, source, and source-declared outcome count. Invalid records still
produce findings. Assumed timings require no fabricated samples and are copied into the analysis as
conditions.

Identifiers and outcome names are validated as nonempty strings; booleans and numeric strings
are not silently coerced into timing/resource numbers. Observed
concurrency a positive integer, and every numeric value finite and nonnegative.

Evidence cannot state or override source input/output types. For every duration sample, the runtime
outcome must be in the extracted source union and its outcome-specific effects must match. Legacy
type labels, undeclared outcomes, retained `UnhandledException`, undeclared/missing effects, and
resource levels above capacity fail.

Evidence collection remains application-owned. Unit/integration tests, benchmarks, browser
automation, production traces, and hardware probes differ too much for one collector to be honest
for every application.

## 6. Core analysis and structural progress

Issuance requires:

1. unique, valid primitive references and an acyclic task graph;
2. positive worker capacity and feasible resource effects;
3. a duration timing for every task;
4. enough exact-source successful evidence for every measured timing and no retained failed attempt;
5. every safety-adjusted timing range inside its declared bounds;
6. every explicitly selected optional checker to pass and bind exactly.

Analysis reports a derived structural-progress claim: every declared task has a feasible
worker/resource path and finite completion evidence. The claim states its semantics: declared
resource effects match runtime behavior, reachable producer task types may recur, acquisition is
atomic, and scheduling is fair. A task is structurally blocked when its task dependencies cannot
be reached or it consumes a resource with neither enough initial supply for a first execution nor
a reachable producer. This catches unseeded resource cycles and consumers with no supply. It does
not pretend to prove throughput, queue policy, or all runtime waits; those require timings and,
where appropriate, an optional checker. Assumed timings make the result conditional and are printed
verbatim.

This is a claim about the declared DAG. Undeclared waits or work cannot be proven away; the model
must first represent them as tasks, resources, or timings.

## 7. Extensible checkers

Some observed application semantics do not belong in the kernel. `CheckContext` supplies the
parsed four-primitive contract, timing observations, source root/fingerprint, and contract/evidence
digests. A Python `Checker` emits `CheckResult`; any language may emit equivalent JSON.

`dagcert-check-result/v2` contains:

- a unique checker identity and boolean result;
- exact source, contract, evidence, and English-requirements bindings;
- references limited to `worker:ID`, `task:ID`, `resource:ID`, and `timing:TASK/CASE`;
- structured findings and optional application-owned facts.

Dagcert does not register checker categories or interpret their facts. A route inventory, DOM test,
or independent semantic audit can evolve without growing the application ontology. Because those
facts are untrusted by the kernel, a checker can support an observed claim but cannot establish a
derived formula. Attaching a result is explicit through repeated `--check-result` options.

The optional semantic-audit workflow reads the mandatory requirements document directly, creates
one sealed packet per English claim, and requires a
fresh context-free Luna worker for each packet. Responses cannot be reused across claims because
each response carries its packet digest. The active agent validates all individual responses before
aggregating them into one checker result. Auditing occurs only on explicit user request.

## 8. Source identity and certificate

Dagcert hashes every included source file, canonicalizes the sorted path-to-digest manifest, and
SHA-256 hashes it. It ignores common generated directories and `.dagcertignore` patterns;
`--exclude` adds explicit patterns. Contract, English requirements, evidence, certificate, and
selected checker artifacts inside the source root are automatically excluded to avoid
self-reference.

`dagcert-certificate/v7` records source identity, exclusions, contract/evidence/requirements
digests, source signature extraction and strict compiler result, the exact Dagcert source/runtime
type-enforcement kernel descriptor and source-file manifest hash, the complete normalized English
requirements, the mandatory translation audit, serialized
primitives and compositions, deterministic primitive and claim analysis, selected checker results
and hashes, issue time, and its own
canonical digest. Verification recomputes all of them and fails closed on any mismatch.
It separately compares the stored serialized primitives and exclusion list with the current
contract and invocation, so recomputing the outer digest cannot hide fabricated display data.

This is an integrity-bound evidence report, not a signer identity. Sign the certificate artifact
with an existing release-signing system when cryptographic authorship is required.

## 9. API, CLI, and optional viewer

The public API exports the four primitive dataclasses, evidence recording/loading, analysis,
generic checker protocol, source hashing, issuance, and verification. The CLI exposes only:

- `init`, `install-skill`;
- `lint`, `fingerprint`, `analyze`, `check-result`;
- `issue`, `verify`.

There is no required runtime or `/stats` route. `examples/stats_viewer` is a polished optional static
artifact viewer. It shows the task DAG, resource flow, timing distributions, normalized recent
trends, guarantees, and assumptions. Its desktop and mobile Selenium screenshots are committed with
the example. Presentation code cannot affect whether a certificate passes.

## 10. Agent workflow and non-regression rule

An agent can act on "certify this app using dagcert." It first writes the exact promises and
assumptions in `english_requirements.json`, then maps actual work to the smallest useful
task/resource flow, records real timings, applies the 50ms/16ms standard profiles where applicable,
runs tests and selected checkers, issues, and verifies.

It must not invent requirements, samples, capacities, assumptions, or passing results. It must not
introduce finite queues, timeouts, rate limits, retries, debounce, cancellation, serialization, or
rejection merely for certification. If the unchanged product cannot support a claim, the correct
result is `NOT CERTIFIED` with evidence.
