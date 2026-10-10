# Timing algebra: streams, service, and inventory

This is the convenient network-calculus front end. For the general recognized
mathematical family, reusable lemmas, relational composition and quantifiers,
see `dagcert help timing-logic`. First-order LRA formulas do not need a new
kernel operator whenever a new application pattern appears.

For variable-sized output, shared workers, batches, retry accounting, keyed
progress, and persistent state, start with `dagcert help timing-systems` and
`python -m examples.timing_systems --certify`. The count-only example below is
an introduction, not an adequate model of those systems. A list of algebra
recipes is not a set of end-to-end application certificates.

Dagcert's timing language combines finite workflow composition with real-time calculus. A new
application supplies source-bound tasks, typed effects, arrival and service assumptions, and an
expression over them. It does not need a new bucket, video, cache, or queue-specific kernel rule.

Try the runnable example:

```powershell
python -m examples.timing_algebra
```

It loads three real Python operation signatures and proves that two producers maintain a
100-item reserve above 30 percent for all time, conditional on the declared envelopes. It prints
the exact lower bound, 46.8 items, and checks that the upper bound excludes overflow. This runner
evaluates the model, not the source-proof backend, and does not issue a certificate. The normal
`dagcert lint`, issuance, and verification gates still apply to source certification.

## What the curves mean

### Reusing actual variable-quantity departures

A derived completed-output curve can feed another real task. In a quantity
network, wrap it with `{"transfer": {"input": expression, "rule": "edge"}}`.
The `transfer` envelope names the downstream `task`, upstream measurement
`source`, `delay_ms`, and `bindings` for every producing upstream outcome.
Each binding selects a real typed `dependency` (with its `input_field`, or
`null` for the whole input), `channel` (`id`), or supported `external_handoff`
(`id`). It retains the common explicit assumption, horizon and failure budget.
It cannot invent a fresh arrival stream at an internal edge. Transport delay,
identity-preserving delivery and exactly-once useful transfer must hold under
that declared envelope.

For a change of measure, `{"quantity_map": {"input": expression, "rule": "map"}}`
selects a `quantity_map` envelope: `task`, upstream `source`, destination `unit`,
exact rational `factor`, and `outcome_quantities` for every outcome. The actual
source backend proves that each new output quantity equals the factor times
its old quantity. An outcome that contributes zero cannot silently become useful
work. The resulting quantity can itself be transferred and composed again.

Convolution additionally proves input/output quantity conservation against the
actual downstream operation on every outcome. A failed task that discards its
input is not a lossless server. Retained retry work needs explicit backlog and
failure accounting; it is not removed to make a service curve pass. Native
cross-language field-mapping restrictions still apply to external transports.

`tests/test_networks.py` includes two-, three-, five- and eight-stage chains,
real typed channels, unit conversion in the middle of a real three-stage source
certificate, and source-proof refusals for dropped input and false conversion.

### Arrival and service semantics

An arrival envelope bounds actual task activations, at the point where `start_resources` applies.
It does not count offered HTTP requests or queue entries before activation. A service envelope
bounds effective worker time credited to pending invocation work under its scheduling and resource
assumptions. These are different premises: an idle worker with capacity for
ten jobs per second does not produce ten jobs per second without arriving work.

The origin is an explicit epoch boundary: resource `initial` values are exact, and there are no
preexisting active invocations or undelivered handoffs. Put already-ready inventory in `initial`;
do not reset the clock in the middle of unmodeled work. A warm-up composition can establish this
boundary before the streaming claim begins.

For a task, write `A-` and `A+` for lower and upper cumulative arrival curves and `S` for its lower
service curve. The kernel derives:

```text
D- = A- convolve S       lower bound on completed invocations
D+ = A+                  conservative upper bound on completed invocations
```

The lower service curve comes from declared worker availability, allocated slots, and the task's
assumed duration and dispatch bounds. It charges dispatch per invocation and allows one
unfinished invocation per lane:

```text
S(t) = max(0, availability(t) / (duration_upper + dispatch_upper) - slots)
```

The service assumption includes the scheduler's work-conserving behavior and any competing load,
pauses, locks, or external blocking that affect that guarantee. The kernel checks slot allocation
against workers and acquired resource capacities. It cannot infer a scheduler guarantee merely
because the application has a thread pool.

Departures count completed invocations. By default resource production uses the minimum effect
over every typed outcome for a lower bound, and the maximum for an upper bound. A success producing
one item and a failure producing none have a guaranteed production of zero.

A service envelope may explicitly declare `outcomes: ["SuccessType"]`, or another nonempty subset
of the actual source union. That makes its premise stronger: every invocation in its horizon has
an allowed outcome, as well as the stated service availability. Its failure probability bounds a
violation of that entire joint premise. The kernel then uses effects over that subset, while the
source union and failure branches remain present. This is a declared whole-window assumption,
never inferred from a per-call failure budget or a passing run. Nonzero envelope probabilities
require a chance claim. Without an outcome subset, all typed outcomes still participate.

## Curve representation and operations

Curves are continuous piecewise-affine functions on nonnegative time, with finitely many knots
and an affine tail. Values are exact rational numbers; strings such as `"1/100"` are convenient in
JSON. Time is milliseconds. Intersections and extrema are computed algebraically, without a
sampling grid. Integer task counts can use conservative continuous envelopes; the curve does not
assert that half an operation can execute.

For example, a periodic stream with a one-item phase allowance can declare:

```json
{
  "lower": {"points": [[0, 0], [100, 0]], "tail_slope": "1/100"},
  "upper": {"points": [[0, 1]], "tail_slope": "1/100"}
}
```

This bounds the count between `max(0, (t-100)/100)` and `1+t/100`. Arrival `window: "prefix"`
applies from the declared origin; `window: "interval"` applies to every interval of that length.
State which one the application can justify. A prefix bound alone does not bound every burst.

The `curve_bound.expression` language supports:

| Expression | Meaning |
|---|---|
| `{"arrivals_lower": "task"}`, `{"arrivals_upper": "task"}` | Bound admitted invocations of that task |
| `{"departures_lower": "task"}`, `{"departures_upper": "task"}` | Bound completed invocations derived from input and service |
| `{"service_lower": "task"}` | Available processing service, not actual production |
| `{"inventory_lower": "resource"}`, `{"inventory_upper": "resource"}` | Initial inventory plus every affecting task's typed start/completion effects |
| `{"constant": q}` | Constant rational curve |
| `{"add": [f, g, ...]}` | Pointwise sum |
| `{"subtract": [f, g]}` | Pointwise difference |
| `{"min": [f, g, ...]}`, `{"max": [f, g, ...]}` | Pointwise minimum or maximum |
| `{"scale": [f, q]}` | Multiply by rational `q` |
| `{"shift": [f, d]}` | `f(max(0, t-d))`; preserves the initial value before `d` |
| `{"advance": [f, d]}` | `f(t+d)`; the premise horizons must cover the advanced time |
| `{"convolve": [f, g]}` | Min-plus convolution: `inf` of `f(s)+g(t-s)` for `0 <= s <= t` |
| `{"deconvolve": [f, g]}` | Min-plus deconvolution: `sup` of `f(t+u)-g(u)` for `u >= 0` |

Deconvolution needs interval arrival envelopes and all-time premises because its supremum ranges
over unbounded time; an unbounded result is refused. Other expressions may use a finite horizon.
Choose compatible units before adding curves; multiplying items by item size or playback duration
uses `scale`.

A flow names one task, its input, and its service envelope. `{"arrival": "envelope-id"}` binds a
real ingress. An `output` binds the sole typed upstream edge and an explicit routing premise:

```json
{
  "output": {
    "task": "upstream-task",
    "delay_ms": 5,
    "assumption": "Every selected upstream result activates exactly one downstream invocation within 5 ms, without loss or duplication.",
    "horizon_ms": 60000,
    "failure_probability_upper": 0.001
  }
}
```

`{"merge": [link1, link2]}` contains those same routing objects for a declared alternative-producer
group. Arrival assumptions cannot bypass a task's typed dependencies. Type compatibility alone
does not establish dispatch or delivery; the routing premise supplies those facts and its
probability joins the chance calculation. A merge cannot count the same producer twice. A
fork/join needs the existing typed composition rules or a separately established matching
invariant; a curve minimum alone does not prove that two results belong to the same request.

## Declaring a bound

A state claim has `kind: "curve_bound"`, `envelopes`, `flows`, an `expression`, `operator` (`gte`
or `lte`), a rational `bound`, `start_ms`, `end_ms`, and `metadata`. `end_ms: null` asks for all time,
including the final affine rays; a finite end asks for every time in that closed interval.

Each envelope names its task, an English `assumption`, a `horizon_ms` (null means all time), and
`failure_probability_upper`. An arrival adds `window`, `lower`, and `upper`. A service adds
`availability` in worker-milliseconds, positive integer `slots`, and the names of assumed
`duration_timing` and `dispatch_timing` cases, and optionally the allowed source `outcomes` for its
joint event. Unused flows and envelopes are refused.

The two-producer example has this claim body, alongside its explicit envelopes and flows:

```json
{
  "expression": {"inventory_lower": "reserve"},
  "operator": "gte",
  "bound": 30,
  "start_ms": 0,
  "end_ms": null
}
```

Its English requirement uses the existing numeric formula:

```json
{"eq": [{"state_claim_proved": "state-claim:reserve-at-least-thirty-percent"}, 1]}
```

Inventory analysis includes every task affecting the resource. It also verifies that the upper
inventory envelope stays within capacity. It never silently clips an overflow: discarded early
production cannot later be counted as reserve. Model admitted production or explicit discards
when a real system drops work. Requests queued for later processing must be represented at the
correct admission/start boundary so reservation effects occur at their actual point.

## Probability applies to a whole envelope

The engineering-envelope model remains an explicit assumption, not an estimate obtained by
turning a few successful trials into a confidence interval. An envelope's `failure_probability_upper`
is the probability that it is violated anywhere in its stated horizon. It is not a per-call
failure rate. To claim the complete curve bound with probability at least `p`, use a chance claim:

```json
{
  "gte": [
    {"state_claim_success_probability_lower": "state-claim:reserve-at-least-thirty-percent"},
    0.994
  ]
}
```

For example, six whole-session envelopes each with violation probability at most `0.001` give
`1 - 6 × 0.001 = 0.994`, without an independence assumption. That formula first requires the
conditional curve proof to pass. It then unions the declared envelope and routing failure bounds, counting
each declared envelope ID once. It does not multiply probabilities, infer correlations, or turn
a finite-session premise into an all-time guarantee. The example itself declares zero envelope
failure budgets and states its assumptions explicitly; its derived claim is conditional on all of
them holding.

## Real application questions

The table uses `A`, `D`, and `S` for arrival, departure, and service bounds. These are reusable
expressions and model premises, not additional application-specific kernel operators. Where an
identity or scheduler fact is needed, it must come from the real source/system contract.

| Question | Construction in the existing algebra | Additional fact needed |
|---|---|---|
| Two pipes keep a bucket at least P percent full | Inventory lower bound `>= P × capacity` | Every inflow/outflow modeled; exclude overflow or account for discards |
| Video generation stays ahead of playback | Initial buffered seconds plus scaled producer departures minus playback consumption | Output duration per item and the actual playback consumption envelope |
| A burst of uploads never creates more than B pending jobs | Bound `A+ - D- <= B` for the worker flow | Arrival burst and available service envelopes |
| Every admitted request finishes within d ms | Bound `A+(t) - D-(t+d) <= 0`, using `advance` | FIFO or another source-proved correspondence from counts to individual requests |
| A cache stays within G updates of the writer | Writer departures upper minus refresh departures lower `<= G` | One refresh covers the corresponding updates; no silently dropped versions |
| A displayed value is no more than d ms old | Shift/advance the update and display curves and prove the count relation | Timestamps, latest-value selection, and a bound on source update freshness |
| A worker catches up after a one-off outage | Service availability flat during the outage, then increasing; bound backlog after recovery | An envelope that includes the outage and the actual recovery capacity |
| Periodic maintenance pauses do not drain the buffer | Conservative service availability with latency and reduced long-run rate | Scheduler-derived lower service over every backlogged interval |
| Interactive work leaves enough service for background work | Residual worker availability supplied to the background service envelope | Actual priority policy and a foreground demand upper envelope |
| Two independent audio/video branches are both ready | Existing `parallel_all` latency maximum; count-side minimum if matching is established | Matching IDs and real fork/join semantics, not merely two similarly sized streams |
| A batch has enough successful attempts before a deadline | Existing structured `threshold_repeat` with its duration and chance formula | Finite attempt scope and typed qualifying outcome; no implicit retry-to-pass |
| Autoscaling warm-up cannot exhaust the queue reserve | Piecewise availability before/after capacity is online; inventory lower bound | A bound on scale-up activation time and worker capacity actually available |
| A recovery worker clears a replication lag by time T | Bound production upper minus replay departures lower at and after T | Initial lag, ordered replay, and source write arrivals |
| Three tenants each get a minimum processing rate | Separate flows and service allocations, with shared capacity checks | A scheduler contract that reserves those shares under simultaneous demand |
| A renderer's double buffer never runs dry | Inventory lower `>= 1`, including frame reservation at start | Frame production, display cadence, and correct slot-release effects |
| A pipeline has a maximum gap between useful outputs | Compare shifted departure lower/upper counts across every window | Enough lower arrivals, service, and all-outcome useful production |
| Each rolling minute completes at least K jobs | Bound `D-(t+60000) - D+(t) >= K` | Premises cover every advanced window; completion counts have the intended meaning |
| A short spike is absorbed without permanent backlog growth | Arrival upper minus service/departure lower; inspect all-time affine tails | A burst envelope and sustainable admitted rate, not an average from one run |
| Cold-start work completes before steady playback begins | Sequence startup stages; shift the streaming origin by the composed warm-up bound | Actual warm-up admission rule and initial ready reserve |
| A deadline survives a bounded transport jitter | Include transport/dispatch delay in the source-bound path, then shift/compose curves | Explicit platform/transport bound and typed handoff identity |

Count curves do not prove fairness, FIFO, request identity, cancellation, or data freshness by
themselves. Those facts connect numerical envelopes to the intended behavior. Arbitrary nonlinear
curves, arbitrary temporal logic, and exact periodic staircase functions are not part of this
finite piecewise-affine representation; conservative envelopes often suffice. When a bound fails,
inspect the premises and the derived extremum instead of changing the claim to a successful run.

An external proof module can derive a scheduler envelope or construct one of these expressions.
The certificate still contains the normalized facts and expression, and Dagcert recomputes the
result. A plugin's `passed: true` is not a timing derivation. A genuinely new mathematical inference
may need a core rule; a new application noun should not.
