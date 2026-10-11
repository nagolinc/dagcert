---
name: dagcert-certify-app
description: Certify an application with dagcert by deriving every promise from its real worker/task/resource DAG, source-proved operations, and explicit engineering premises. Retained observations are supporting run evidence, never certificate claims. Use when a user says "certify this app", "use dag-certificate", or "use dagcert".
---

# Certify an application with dagcert

This is the focused workflow. Run `python -m dagcert help` for packaged guides and examples, and
read [references/workflow.md](references/workflow.md) for current artifact formats and commands.

## First rule: typed tasks and explicit proof boundaries

**LLM call with structured output? Immediately run `python -m dagcert --help structuredLLMOutput`.**
That installed recipe contains the real `@external_boundary` API, a checked example, provider
contract, task wiring, and commands. Copy `examples/structured_llm_output/`, adapt the consumer's
schema and real provider call, and check it before expanding the proof. This is a routine pattern,
not permission to design a JSON parser or extend the verifier. A written sketch is insufficient:
run the actual example and distinguish typed adapter success from useful task success.

Before verification, define each task's statically typed input, closed success/error outcomes,
consumer-required guarantees, resources, and timing/failure accounting. Refactor the production
path into those tasks. Complete the microclaims in the user's agreed order.

**Certify task contracts, not dependency internals.** Bind established parsers, schema validators,
HTTP clients, and model services through explicit trusted external contracts. A schema parser's
contract is `parse_and_validate(text, schema) -> SchemaObject | Error`: success satisfies the
supplied schema and corresponds to that input; failure produces no useful output and costs time.
Prove the application's schema selection, call, success/error handling, and downstream use.
Do not prove JSON grammar, recursive JSON representations, dictionary reads, string stripping,
or validation-library loops as prerequisites for that task. Static types alone do not establish
schema validity: that semantic guarantee must be explicit in the trusted parser contract.

**Stop at the first descent into dependency internals.** If the proposed next step is another
container/string/parser proof or a verifier feature to support it, stop that work. Restate the
consumer-level obligation, check the external contract, and simplify/refactor the task boundary.
Use an established schema validator instead of proving an unnecessary custom validator. An
unsupported annotation or verifier refusal does not authorize scope expansion. Verifier
development is a separate task requiring explicit user scope and a retained demonstration that
the consumer-level obligation remains after checking suitable boundaries and existing contracts.
Do not add product limits, hide failures, or weaken the claim to obtain acceptance.

Keep dependency assumptions explicit, version-bound, and distinct from proved application
behavior. Do not relabel scheduling, joins, useful-output accounting, or other application logic
being certified as external. A contract declaration is not a completed proof; report actual
backend acceptance, measurements, and composition separately. See the
[worked boundary and stop procedure](references/workflow.md#typed-task-boundaries-and-the-stop-rule).

## Required application surfaces: use the supplied APIs literally

**UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THESE LITERALLY. THEY ARE SUPPLIED APPLICATION
APIS, NOT EXAMPLE CODE TO COPY, MODIFY, OR REIMPLEMENT.**

- After the normal `pip install dagcert`, call `stats(app, certificate=..., evidence=...)` and
  `banner(app)`; there is no separate installer.
- Pass the issued certificate's sealed evidence file. `stats(...)` refuses a missing file, an
  evidence digest mismatch, a certificate digest mismatch, or a sample from another source
  fingerprint. Never pass a nonexistent or substitute file to reduce the page payload.
- Include exactly `<script src="/dagcert/banner.js"></script>` on every user-facing shell.
- Verify `/stats` contains one node for every task in the bound certificate. Never serve the
  bundled three-task `sample-data.js` demo as application data.

`banner(app)` serves the script and event feed; it does not inject HTML. Test in the real browser
that `/stats` loads the real certificate and sealed evidence, a task without a retained sample is
neutral rather than failed, a forced violation produces the red warning and red task/worker state,
the dismiss button hides that warning, and a later violation makes it reappear.
Omit a surface only after an explicit user opt-out, and report that opt-out in the handoff. Read the
**Required application surfaces** section of the workflow reference before integrating them.

## Rule 0: improve the experience; never certify a regression

Certification proves explicit guarantees. It is not permission to redesign the application. Do not add
queues, limits, timeouts, retries, debounce, serialization, rejection, reduced concurrency,
resource caps, fake fast paths, or altered behavior merely to pass. Report a truthful failure.

**THE OBSERVATION-ONLY ROUTE IS THE BAD PATH.** A successful run belongs in `dagcert analyze`; it
says nothing about the next run and is not a certificate. Presenting it as a guarantee will
disappoint the user. Dagcert refuses `observed` certificate claims. Every certificate promise must
be a `derived` or `chance` kernel formula over the actual DAG. Measurements may challenge or
support explicit premises, but they never become the promised behavior by themselves.

## Model the actual execution DAG

Dagcert's primitives remain workers, tasks, resources, and timings. A hardened contract also
declares finite source-outcome paths over those primitives.

- `operation` tasks are real executable leaf boundaries and may have measured timings.
- In a v7 contract, an operation binds a real source file and symbol. Dagcert extracts its one-input
  type and closed return union and runs strict mypy itself. It then requires an explicitly selected,
  digest-pinned proof backend to prove the complete bound Python file has no undeclared exceptional
  exit. Nagini/Viper is the default; Maledictus is an alternate only for its advertised narrow
  Dagcert operation fragment. Contract JSON cannot declare or override task types.
- Dagcert verifies the provenance of `operation` and `dataclass`; local lookalike decorators and
  source-tree modules shadowing `dagcert` or `dataclasses` fail. The marker preserves the exact
  callable type; it does not catch exceptions or widen the outcome union.
- Keep shared frozen record types in their natural source-owned modules. Maledictus proves
  cross-file operation-record imports as explicit source edges, and Dagcert checks those edges
  against the exact bound files and hashes. Do not duplicate or flatten records to make operation
  files artificially self-contained.
- A v16 certificate seals strict-mypy output, the selected proof-engine identity and proof scope, and the
  exact type-enforcement core-file manifest—not only a claimed Dagcert version or compiler result.
- `instrumentation` tasks may record aggregate observations but cannot participate in a derived
  composition.
- A v12 composition is built only from `leaf`, `sequence`, `parallel_all`, `finite_repeat`,
  `threshold_repeat`, `async_handoff`, and `external_handoff`. Use `async_handoff` for a real queue between independently scheduled workers;
  declare its typed channel instead of feeding the unknown producer value into the dequeue request.
  Sequence boundaries are real typed dependency edges. A parallel join binds every branch output
  to a field of the real downstream input record, and hidden cross-branch dependencies fail.
  Dagcert computes its conservative bound from those leaves; it never accepts a direct aggregate
  stopwatch as the derivation.
- Use `threshold_repeat` only for a predeclared finite K-of-N prefix. Put the complete
  source-proved attempt path in its structured body, including every task and transport envelope;
  do not threshold only its last classifier. Name one terminal qualifying outcome and the resource
  unit produced only by that outcome. Its engineering-envelope probability uses a correlation-free
  Markov bound; it does not prove arrivals, controller dispatch, or unbounded retries. See
  `dagcert help threshold-repeat`.
- Use `external_handoff` only for a real cross-language platform transport between source-proved
  endpoints. Bind the exact wire field and compiler-extracted endpoint types, state the platform
  assumption, and include its latency and engineering failure budget. See
  `dagcert help browser-fetch`; never invent a same-language browser adapter.
- Dependencies are all-of unless real alternative producers for the same input slot share an
  explicit `alternative_group`. Never list mutually exclusive call sites as ungrouped dependencies,
  and never infer one-of behavior merely because types match. See
  `dagcert help alternative-producers`.
- V7 lifecycle effects distinguish task start from typed completion outcomes. Use kernel state
  claims for affine conservation, finite-horizon supply, and bounded dispatch; do not substitute a
  custom checker boolean for those proofs.
- Use generic `curve_bound` state claims for streams, inventory floors, backlog, and delay/rate
  bounds. Read `dagcert help timing-algebra` before constructing them. Bind actual task activations,
  assumed duration/dispatch costs, effective worker availability, explicit routing, and every
  typed resource effect. The kernel composes exact rational curves; new application nouns do not
  require new kernel types. All-time bounds require explicitly all-time premises. A finite run or
  finite invocation budget cannot establish a forever claim, but all-time claims are not generally
  forbidden. Source verification remains mandatory.
- For variable-sized output or retained state, read `dagcert help timing-systems`.
  Bind useful quantity to real outcome fields and prove source accounting relations.
  Include failed/retried/discarded work in interval cost envelopes. Use source-bound
  induction for capacity, identity, deduplication and latest-wins state; do not treat
  normal return types as proof of these semantics. Separate actual departures from
  available service, and analyze finite-buffer refill periods including restart
  delay. A fast average, min of unmatched stream totals, scheduler weights, or a
  successful model-only example does not establish the application guarantee.
- For a timing relation not covered by those convenience operators, read
  `dagcert help timing-logic`. The general family is first-order linear real
  arithmetic, including quantifiers and finite piecewise relations. Build reusable
  mathematical lemmas and source-mode `lra_theorem` claims; do not request another
  application-specific kernel opcode for a relation already expressible there.
  Bind actual fields and source postconditions, preserve completion guards and
  dispatch premises, and retain all imported assumptions and scoped failure events.
  A mathematics-only artifact is not an application certificate. The source adapter
  and invariant discovery are separate from the completeness of the math language.

Reconstruct the execution graph from source before writing the contract. Represent independently
scheduled stages, actual worker pools, queues, reservations, resource transfers, ordering rules,
success transitions, and failure-release transitions that affect a requested guarantee. Do not
collapse them into a pipeline observer or surround one catch-all measurement with meaningless task
names.

A function call is not automatically a DAG task. When one worker invocation performs local work,
calls external code, then continues local work, keep it as one operation task. On v12, declare the
monitored adapter in top-level `external_boundaries` and cite its ID from that task's
`external_calls`; use the pinned Maledictus backend to seal the real import/call edge and exhaustive
typed outcomes. Create separate tasks only for real scheduling, queue, retry, or handoff boundaries.
Heap-returning provider calls stay in that same operation too: use a checked Maledictus heap
contract for the factory and methods, state every `Result()` permission explicitly, and state
`Ensures(Result() is self)` when a context manager's `__enter__` returns its receiver. Never split
factory, method, or `with` lifecycle steps into artificial DAG tasks.
If the worker calls several external adapters, declare every boundary in `external_calls` and prove
the complete worker with all reachable provider overlays in one Maledictus request. Do not settle
for isolated adapter proofs. Missing overlay coverage, conflicting contracts for the same provider
module, or any uncaught declared exception must refuse issuance. See
`dagcert help multi-external-worker`.
For shared external containers, retain the real generic payload. A source-owned
`Queue[Job] | None` state cell with one exact typed setter and a checked `Queue[T]` provider
contract may be consumed directly by the adapter; never replace `Job` with `object`, packed text,
or an observer task. Treat every state read as a fresh optional snapshot and model its `None`
outcome. Initialization, persistence, capacity, and liveness remain separate proof obligations.
See `dagcert help nested-external-call` and `dagcert help async-channel`.

Write the production operation boundary in its strongly typed form before modeling it. For Python,
use an explicit input class, explicit named outcome classes, an inline closed return union, and
`@dagcert.runtime.operation`. Every v7+ dependency names an upstream outcome type and must feed a downstream
callable that accepts that exact source type. Model effects for every explicit source outcome.
Expected failures must be return variants; an unexpected exception invalidates the proof. Keep
claim-relevant argument preparation and dependency invocations inside the verified task. Parsing
through an external parser/schema contract does not require proving that library's internals.
Never create a typed certification wrapper that production bypasses.
Do not use operation-level Nagini `Requires` or executable-module `Assume`/`ContractOnly`; Dagcert
must prove executable behavior for the complete declared input type under the sealed external
contracts, without adding assumptions in place of application-owned behavior.

Use `--proof-backend maledictus` only with both `--proof-backend-executable` and
`--proof-backend-sha256`, and pass the same selection to lint, issue, and verify. Never switch
backends after a refusal. Maledictus operation fragment v4 requires
`dagcert-closed-typed-operations/v4`. Its response
v8 must
include the exact strict-mypy package, runtime executable and bundle, configuration, and support
hashes. Dagcert retains that identity in the certificate and requires an exact match on verification.
For passed-at-construction callable fields, declare task-local `callable_bindings`; each binding
must identify the field and a real source path/symbol or an explicit external-contract overlay.
Never replace this machine-readable provenance with prose or a checker assertion.

Keep application-owned helper imports inside the logical task that calls them. Dagcert recursively
adds their reachable Python modules as hash-bound proof-only sources; they are not `contract.tasks`.
Review `source_verification.proof_source_closure` and require every relevant helper and package
initializer to appear there. Never inflate ordinary imported functions into DAG nodes, omit them as
unproved glue, or copy them into a catch-all operation. See `dagcert help imported-helpers`.

For a real third-party or standard-library boundary that is itself scheduled work, declare a v10
`external` task. Put the executable adapter in its own module, mark it with
`@dagcert.runtime.external_boundary(CANONICAL_BOUNDARY_ID)`, and put the Nagini `ContractOnly` specification in a
different source-owned stub named by `external_contract.stub_path`. The stub is a proof overlay, not
production code. Its input and success dataclass shapes must exactly match the adapter. Declare the
real provider module/symbols and the precise engineering assumption. Run production calls under
`monitor_external_boundaries(ExternalEvidenceMonitor(...))`; exceptions and wrong return types are
typed violation outcomes and retained evidence, never success. Use a zero bad-event upper bound for
a p=1 premise; any observed violation then refuses issuance.
When several contextual tasks call the same adapter, give them the same
`external_contract.boundary_id`, require otherwise identical source bindings, and retain the call
site by executing it inside `ExternalEvidenceMonitor.task_context(task_id)`.
This standalone external-task stub body is intentionally limited to
`Ensures(Result() is not None)`; arbitrary postconditions there are rejected. This restriction is
not an instruction to implement or prove a JSON validator. For richer validation, invoke an
established schema library through its supported provider contract inside the executable
operation and handle its outcomes. State a representation gap if that contract cannot be bound;
apply the stop rule instead of launching parser or verifier development.
If the call is internal to one logical operation instead, do not manufacture an external task:
use `external_boundaries` plus the operation's `external_calls` as described above.

JavaScript or TypeScript operations require the explicit digest-pinned Maledictus backend and a v8
`verified_interface`. The declaration is only an assertion: Maledictus must return the exact
compiler-derived signature and prove the accepted source body has no undeclared exceptional exit.
The current leaf surface is synchronous with a compiler-derived vector of primitive parameters and
one primitive return. Preserve the real source parameters; never add a packing wrapper merely to
fit the certificate. A DAG edge feeding one parameter must name it with `input_field`.
Browser and host-platform behavior remains an explicit external assumption; `tsc --strict` alone
is not a proof.

## Claim boundary

Classify every requested behavior before collecting evidence. Retained-execution facts are run
report material and must not appear as certificate claims.

- `derived` contains a formula in Dagcert's fixed kernel algebra. It cannot cite a checker as proof.
  The formula uses a declared composition, kernel state proof, guaranteed typed resource effects,
  or bounds from connected tasks with relevant worker/resource state.
- `chance` contains a finite-composition formula, an external-contract probability premise, or
  `state_claim_success_probability_lower` for a conditional `curve_bound` proof. Temporal envelopes
  budget violations anywhere in their stated window; they are not per-call probabilities. Explicit
  service `outcomes` restrict the actual source union only as part of a joint whole-window premise.
  Without that premise every outcome contributes to resource bounds. A finite composition step
  with a declared task-local engineering error budget selects a
  source-typed good outcome and cites that budget as an explicit assumption. A source-proved task
  whose complete outcome union is exactly the selected outcome contributes structural zero when its
  budget is null. It may instead declare a conservative nonzero budget without weakening its typed
  totality guarantee. The budget's complete good set must equal the exact selected outcome. Do not
  invent failure outcomes: an optional budget may classify every real outcome as good. Use one direct success-lower/failure-upper comparison with a
  literal probability; never add a boolean fallback branch. Retained observations test consistency
  only; never describe them as statistically establishing the leaf probability.

Keep may- and must-reachability distinct. A downstream success branch may be structurally reachable
without being guaranteed across failure outcomes. Do not call it blocked, and do not use it as
unconditional supply. Chance formulas use the union bound only; do not multiply success rates or
assume independence.

If the kernel cannot express or prove a requested system property, report it as unsupported. Never
replace non-starvation, bounded backlog, capacity, priority, sustained throughput, staleness, or
composed latency with a summary task whose measured output is the desired conclusion.

## Workflow

1. Run `dagcert init <app-root>` and replace every placeholder. Unless explicitly declined, install
   the literal `/stats` viewer and dismissible violation banner before application certification.
2. Inventory the user's requested guarantees. Classify each as derived or chance and write its
   exact scope and assumptions before evidence collection. Put observations in the evidence/run
   report, never in the certificate promise set.
3. Trace source paths and build the smallest faithful worker/task/resource DAG. Define typed task
   inputs, success/error outcomes, and trusted dependency contracts before proving internals.
   Do not mirror every function or omit state/scheduling boundaries material to a claim.
4. Declare real workers, operation tasks, instrumentation, resources, structured finite
   compositions, and any required lifecycle or temporal curve state claims.
   Bind each task to the source symbol actually called by its production worker; do not write
   `input_type` or `output_type` labels in the contract.
5. Put timing premises in `assumed` leaf timings. Model external-library behavior with a declared
   `external_contract`, proof-only stub, typed runtime boundary, and canonical evidence stream. Do
   not infer worst-case gaps or probabilities from a few favorable samples.
6. Record every exact-source attempt, including failures. Exercise representative and adversarial
   cases. Never retry to replace a failed observation.
7. Run `dagcert lint`, application tests, and `dagcert analyze`. Resolve coverage, binding,
   strict-mypy, proof, resource-effect, failed-attempt, and timing findings within the agreed
   claim. A finding involving dependency internals triggers the stop rule, not an open-ended
   mandate to expand the verifier.
8. Encode derived claims as kernel formulas over the actual DAG. Do not use checker booleans or
   aggregate samples as proof premises.
9. Run `dagcert issue`, then `dagcert verify` with identical inputs and exclusions.
10. Report `CERTIFIED` only for the exact verified source and the exact derived/chance scope.
    Otherwise report `NOT CERTIFIED` and preserve the failures.

Never fabricate samples, capacities, transitions, formulas, checker results, or a passing
outcome. Certification does not imply general production readiness.

## Optional semantic audit

Run the independent audit only when requested. It uses the mandatory requirements file and creates
one sealed packet per claim. Each fresh audit worker must reconstruct the real execution graph from
source and compare it with the declared model. It must reject synthetic observer/summary timings,
missing queues or reservations, omitted failure transitions, average-rate substitutions for burst
bounds, mutually exclusive callers modeled as simultaneous dependencies, real joins weakened into
alternatives, contextual external evidence attributed to the wrong call site, and any proof that
does not resemble the actual application DAG.
For temporal proofs, also check that service capacity is not substituted for actual production,
all consumers and possible overflows are accounted for, routing has a real dispatch/delivery
premise, shared worker/resource slots are not overcommitted, and finite assumptions have not been
promoted to all-time promises. A conditional all-time envelope proof is valid in scope; an observed
finite run is not its proof.

The review remains advisory: it can invalidate a claim, but its `passed` boolean cannot establish a
derived formula. Follow the per-claim handoff procedure in the workflow reference.
