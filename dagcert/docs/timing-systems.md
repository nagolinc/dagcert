# Variable quantities, shared workers, and persistent state

```powershell
python -m examples.timing_systems
python -m examples.timing_systems --certify
```

The second command runs strict mypy, the pinned semantic verifier, source
postconditions, and Z3 induction; issues a certificate; then independently
verifies it. Docker must be running for default Nagini. Outputs are under
`.cache/timing-systems`. The first command explicitly does **not** claim source
certification. These are reusable toy policies, not certificates of five
deployed applications.

## Proof language

`curve_bound` also accepts a `network` program. Algebra expressions are not
extra application tasks. Leaves name physical worker-time envelopes, ingress
quantities, source-bound useful quantities, workload relations, and
scheduler/ordering premises. Exact rational curve operations compose them.

Available service, completed work, and useful output are distinct. Capacity
cannot be added to a buffer as already-produced data. Bound direction,
physical server provenance, and units travel through expressions. Reserving
the same worker twice, omitting a failure outcome, treating ordinary residual
service as strict, or using finite envelopes for infinite claims is refused.

Generic arithmetic proves numerical functionals, not additional physical
streams. Adding a completed-output bound to itself is a bound on twice that
quantity, not twice the production; taking the minimum of unrelated outputs
does not prove a keyed join. Such expressions lose physical stream identity
and cannot be reused where actual ingress or completions are required. The
diagnostic reports that distinction; source relations and explicit premises
must justify any application interpretation such as playable reserve.

An interval workload relation has the form:

```text
work charged to completed outputs + failed/retried/discarded work
    <= a * useful quantity + excess work
unfinished work <= M
```

Effective worker service W gives usable service `max(0, (W-excess-M)/a)`.
The premise covers **every relevant backlogged interval**, not just startup
or a measured average. Slow chunks can be offset by fast chunks; failed work
cannot disappear from costs and duplicate acknowledgements are not new bytes.

For finite buffers, `service_deficit` compares consumption with usable service
during each refill busy period, including bounded restart delay. The source
controller, state invariant and scope are explicit. Never accumulate
hypothetical production while a full buffer paused or discarded output.

## Five application shapes exercised

| Shape | Source policy | Timing mechanism and counterexample |
|---|---|---|
| Variable A/V streaming | Only the next matching key adds playable duration; preserve capacity; refill below low water | Variable work/quantity service and all-time refill deficit. Faster average with a long enough gap fails. |
| Shared interactive/background worker | No dispatch during nonpreemptible work; priority selection; partial-batch timer | Reservations with bounded lag, residual work service, per-unit cost plus per-release overhead. Weights alone do not prove fairness. |
| File synchronization | Only the next unique durable acknowledgement advances progress; duplicates/failures retain it | Useful-byte cost includes retry work; withheld-progress bounds cover ordering. High attempt rate with zero useful output proves no supply. |
| Search/map UI | Stale results cannot replace the current generation; input changes request cancellation | Stable-input deadline composes debounce, queue wait, execution and handoff bounds. Endless edits need not produce a stable result; cancellation does not instantly reclaim capacity. |
| Telemetry windows | Unique matching readings accumulate; timer flush retains simultaneous input | Variable quantities and partial-release demand. Dividing by maximum batch size undercounts timer singletons. Processing-time windows do not silently become event-time/watermark proofs. |

The source certificate includes all five policy safety obligations and the
variable-streaming timing theorem. Shared-worker, batching and ordering
arithmetic additionally has executable positive/adversarial tests. This is
not a complete end-to-end deadline certificate for all five systems. An
embedding app must bind its real ingress, queues, scheduler, clocks,
persistence, external contracts and state ownership.

## Source semantics and induction

`relational_invariant` specifies initialization, an invariant and every
outcome's before/after relation. Variables bind to actual source fields and
the complete compiler-extracted outcome union. A source relation is a
predicate over entry `input` and final `result`, not a checker-provided pass
boolean. A deterministic proof view is checked by the real backend; original
and proof-view hashes are sealed. Lint, issuance and standalone verification
enforce the same gate.

Z3 proves initialization and preservation under arbitrary repetition. False
initialization, counterexamples, and solver `unknown` refuse certification.
Initialization and exclusive mutation scope remain explicit premises:
selecting functions does not prove no other code changes state. Invariants
alone do not prove fairness or liveness.
Simultaneously declared initial states must also be jointly satisfiable.
Claims sharing the same task/input field cannot rename it to assume conflicting
initial values; different task instances are not aliased merely by field name.

Induction supports linear numeric arithmetic and Boolean logic; source state
bindings currently use Python integers. IEEE floats are not silently exact
reals. Integer sequence/version fields express identity. Arbitrary heap/set
properties require suitable source-verifier postconditions, not fake types.

The current source-relation binding targets an operation with one typed request
parameter. Nagini native postconditions handle cleanup for single-outcome
operations. Multi-outcome relations containing `with`, `finally`, or yields
are currently refused: checking a value before cleanup cannot establish its
final value. This is a source-proof adapter limitation, not an assumption that
cleanup is harmless or a restriction on ordinary Dagcert task signatures.

## Confidence is still an engineering envelope

Each envelope declares a horizon and probability that the **whole envelope**
fails. The union bound needs no independence assumption. Per-request failure
probability is not an all-time chance of no failure. No millions-of-trials
requirement was added; an observed average is not a universal premise.

Use `basis: chance` with `state_claim_success_probability_lower` for nonzero
envelope probabilities. `basis: derived` proves the conditional implication.
Measurements can challenge assumptions but do not replace source/algebra proof.

The shipped streaming example uses four whole-horizon engineering budgets of
`1/10000`: playback demand, effective renderer service, variable-work accounting,
and refill-controller scheduling. Its actual chance formula requires
`state_claim_success_probability_lower >= 0.9996`. If all four envelopes hold,
the source-bound timing proof retains at least 400ms in every refill period,
including variable-length pieces whose individual production time can exceed
their playback duration. The union bound therefore gives:

```text
P(any modeled interruption over the entire unbounded lifetime) <= 0.0004
```

Each budget applies to failure of the **whole envelope anywhere in that
lifetime**, not to a request or a time slice. These deliberately explicit
engineering assumptions are not statistically established by this example,
and they do not estimate an actual platform's infinite-lifetime reliability.
Independence is neither assumed nor required. A finite-horizon premise cannot
support the all-time claim; a per-request failure rate cannot be substituted.
The deterministic initialization and exclusive-state-ownership premises remain
necessary in addition to the four probabilistic envelopes.
