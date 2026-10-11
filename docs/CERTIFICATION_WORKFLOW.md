# From a product promise to proved production tasks

Dagcert's purpose is to make the application work. The preferred route is to clarify the promise,
refactor the real work into tractable tasks, prove those tasks, and compose their contracts. It is
not to preserve a tangled implementation at any cost, nor to replace a proof with a successful run.

This guide contains worked **design examples**, not a certificate for a deployed streaming app.
The runnable repository examples linked below state their own narrower claims and assumptions.

## Mandatory boundary rule: certify tasks, not dependency internals

Before running a verifier, write down each task's statically typed request, closed success/error
outcomes, consumer-required guarantees, resources, and timing/failure accounting. Identify which
guarantees the application establishes and which come from explicit trusted dependency contracts.
Types describe the interface; semantic guarantees such as schema validity belong in the contract.

Established parsers, schema validators, HTTP clients, and model services are external boundaries.
Their implementation details are not prerequisites for a task-level certificate. Keep the actual
dependency invocation and outcome handling in the application proof; stop at the sealed contract.
In particular, do not turn a structure-builder claim into proofs of JSON grammar, recursive JSON
types, dictionary lookup, whitespace stripping, or validation-library loops. Refactor a custom
validator to use an established schema validator when that supplies the required behavior.

**Stop procedure, triggered by the first proposed dependency-internals proof or verifier extension:**

1. Stop that line of work. State the current microclaim and the exact fact its consumer needs.
2. Check whether an existing parser/validator/provider contract supplies that fact. Bind the real
   dependency, relevant version/configuration, guarantees, and error outcomes explicitly.
3. Refactor the production task to call that boundary and handle its typed outcomes. Preserve
   failed work, retries, occupied resources, elapsed time, and required output data.
4. Verify that small task and resume the agreed claim order. If the chosen backend cannot bind
   the needed contract, retain the minimal diagnostic and report that precise limitation.
   Do not substitute an hours-long sequence of container/JSON proofs or verifier changes.

Verifier development is separate work requiring explicit user scope. Before proposing it, show
the consumer-level obligation that remains after checking a suitable typed boundary and existing
contracts. A backend refusal alone does not establish a need for a new verifier feature. Do not
add arbitrary limits or silently weaken the claim. Do not make another task, browser workflow,
database proof, or generic parser a prerequisite merely because it is reachable in source.

This rule does not permit hiding application scheduling, joins, accounting, or the very behavior
being certified behind assumptions. Trusted dependency behavior must stay visible in the result.
Written contracts, accepted source proofs, measurements, and composed certificates are distinct
milestones; report which actually finished, not the number of helper obligations attempted.

## 1. Work backward from the consumer

Write the exact target claim and its scope before collecting evidence. For playback, distinguish
"a playable segment is ready" from "an image request completed" and "a 30-minute run did not
buffer" from a conditional future supply guarantee. State the horizon and any engineering failure
envelopes explicitly.

Trace every dependency needed to satisfy that consumer, including parallel producers. Record the
workers, concurrency, queues, shared hardware, required input availability, output units, and actual
dispatch/refill policy. A task's service capacity is not a promise that it receives or dispatches
work. A producer that sometimes fails does not produce a useful unit on every invocation.

Then choose small proof obligations that compose into the target. Each should say what an actual
piece of production code establishes for its consumer. "Microclaim" means this working unit of
reasoning; it is not a new schema field or core proof type.

## 2. Worked task: request a usable structure

Suppose a story worker needs a plan with a title, summary, the requested number of steps, and the
fields consumed by the next stage. Its logical task is:

```text
prepared planning request
    -> external model call in JSON mode
    -> external parser/schema validator: Plan | ParseError
    -> PlanReady | PlanFailed
```

The task's success means **usable by the declared consumer**, not merely valid JSON, an HTTP 200,
or a value of Python type `dict`. Do not add unrelated schema restrictions or discard additional
JSON fields that the application must preserve. JSON mode is an external interface setting; it
does not prove the application's required fields, cardinality, or semantics.

### The small contract and implementation to write first

Use a real parser/schema validator with this **explicit trusted contract**:

```text
parse_and_validate(response_text, plan_schema) -> Plan | ParseError

Plan: the returned object is the decoded response and satisfies plan_schema.
ParseError: no usable plan is returned.
```

The supplied schema states the requested step count and the nonblank fields the consumer needs.
Bind that schema and the parser's real implementation/version. Preserve additional metadata if
the consumer requires it. Do not replace the success guarantee with merely `dict`, `object`,
`Any`, or HTTP 200, and do not assume the model always produces a valid response.

The operation should have this size and shape. This is typed design pseudocode, not a new Dagcert
API or an issued certificate; the named external outcomes must be bound to the actual adapters:

```python
@dataclass(frozen=True)
class PlanRequest:
    prompt: str
    schema: PlanSchema

@dataclass(frozen=True)
class PlanReady:
    plan: Plan

@dataclass(frozen=True)
class PlanFailed:
    error: str

@operation
def build_plan(request: PlanRequest) -> PlanReady | PlanFailed:
    response: ModelText | ModelError = request_json(request.prompt)
    if isinstance(response, ModelError):
        return PlanFailed(response.message)
    parsed: Plan | ParseError = parse_and_validate(response.text, request.schema)
    if isinstance(parsed, ParseError):
        return PlanFailed(parsed.message)
    return PlanReady(parsed)
```

If the library reports errors by raising exceptions, the adapter/task catches the declared
exceptions into the same failure outcome. The trusted contract must include those exits.
The application proof checks the right schema was supplied, only the validated result becomes
`PlanReady`, and all failure outcomes are handled. The provider and parser contracts supply their
internal behavior. Resource and timing composition charges the entire invocation, including
unsuccessful attempts. Existing retries remain accounted for in the task or its actual controller.

**Wrong next step:** build recursive JSON types in Maledictus, prove dictionary/string semantics,
or add verifier machinery for nested validation loops. **Correct next step:** use the typed
parser/schema contract, prove this small outcome-handling task, and complete the next agreed
microclaim. If the contract cannot be represented, apply the stop procedure above; an unresolved
binding is not permission to start verifier development.

### Refactor the implementation, not just the diagram

Move the existing request, parsing, validation, and relevant retry logic into a clear production
task module. Give it explicit input and outcome types and make the live caller use that function.
Keep its domain records and simple helpers easy to verify. Retain the existing product behavior;
do not invent timeouts, retry counts, fallback modes, or limits to simplify the proof.

For example, if conversation preparation precedes the request and database persistence follows
the accepted plan, the planning task can begin with prepared inputs and end with `PlanReady` or
`PlanFailed`. Certifying that scope does not require proving the database transaction. If the target
instead promises a committed arc, persistence belongs on that larger target's dependency path.

The refactor changes the production call graph, for example:

```text
Before: one controller method prepares context, calls the model, parses, validates,
        retries, persists state, and starts downstream work.

After:  orchestration prepares PlanRequest
        -> build_plan(PlanRequest) returns PlanReady | PlanFailed
        -> orchestration persists an accepted plan or records failure
        -> downstream task consumes the accepted result
```

The request, validation, and retry implementation moves into `build_plan`; its caller
stops carrying a second copy. This can remain a synchronous function on the existing story
worker. Small proof boundaries do not require extra workers, queues, or scheduling overhead.

Choose interfaces from real data boundaries. Retaining the provider's actual response text can
preserve arbitrary additional fields, but a `PlanReady` carrying text must only be constructed
after the claimed validation of that exact text. Its consumer must receive the corresponding
value. Packing internal records into strings solely to bypass the type checker establishes neither
relationship. A frozen record also does not make referenced mutable data immutable or grant its
ownership.

### Separate external assumptions from owned behavior

The real HTTP client, model service, and parser/schema validator use explicit, sealed external
contracts. These specify normal results, consumer-required semantic guarantees, relevant
permissions, and possible exceptional exits. The owned schema selection, invocation, response
handling, retry controller, and outcome classification remain application code to prove.
Calling an established schema validator replaces the need to prove a custom validation algorithm;
it does not require proving the library's implementation. Merely renaming application scheduling
or output-credit logic "external" would hide the requested claim and is not allowed.

A library call inside one invocation normally stays inside the same task. Use another DAG task
when the application has a real scheduling, queue, retry, or handoff boundary, not merely because
the next statement calls a library. The
[nested external-call example](../examples/certified_nested_external_call/README.md) demonstrates
this source shape. **Its historical observational requirements are deliberately refused by
current issuance; it is not a certificate template.**

For this fallible task, use a source-bound `operation` and declare its provider calls as embedded
external boundaries. Declare expected provider exceptions and handle them into explicit outcomes.
Do not choose a standalone `external` task with a nonzero failure budget: the current
`ContractOnly` external-task route requires a probability-one premise. Ordinary fallibility
belongs in the executable operation's outcome model.

### Account for retries and failures at the same boundary

Choose one invocation unit and keep it consistent across source, evidence, and the model:

| Contract item | Meaning for one complete planning invocation |
| --- | --- |
| `PlanReady` | One usable plan is produced, after the required checks. |
| `PlanFailed` | Zero usable plans are produced; failure is retained and handled. |
| Occupied time | Includes provider attempts, retry waits, parsing, validation, and repair work inside this invocation. |
| Resources | Includes capacity used on successful and unsuccessful attempts; release happens on every relevant exit. |
| Engineering failure budget `p` | Explicit upper premise for the invocation's bad outcome, not an estimate inferred from three successes. |

If retries occur inside the task, their time is already part of that invocation. Do not count each
retry as another successful plan or infer a failure probability of `p` raised to the retry count
without the additional premises that calculation requires. If attempts are separately scheduled,
model their actual boundaries and controller instead. Nested retries and retry delays cannot
disappear from either model.

For a concrete accounting example, suppose an invocation spends six seconds on a rejected
response, two seconds waiting to retry, and seven seconds obtaining an accepted response.
It produces **one plan in fifteen seconds**. If a second invocation fails after ten seconds,
the two invocations together produced one plan in twenty-five seconds. Reporting only the
seven-second successful response would overstate useful throughput. These illustrative
observations do not establish a future latency or failure bound.

Dagcert's existing task `error_budget` uses `basis: engineering_assumption`, one duration
`evidence_case`, `good_outcomes: [PlanReady]`, and a declared
`bad_event_probability_upper`. A one-leaf composition can express a conditional success lower
bound of `1 - p`; its duration bound comes from a separate explicit service premise. Retain all
outcomes when checking the timing and failure envelopes. An unexpected exception escaping the
declared operation is not a legitimate error-budget branch.

The [vote example](../examples/certified_vote/README.md) contains an issued finite chance-path
example with actual typed rejected outcomes. Its
[contract](../examples/certified_vote/dag_contract.json) and
[requirements](../examples/certified_vote/english_requirements.json) show the budget and
`composition_success_probability_lower` formula. The
[structured threshold example](../examples/certified_threshold_repeat/README.md) shows a finite
K-of-N attempt composition; it does not prove an unbounded retry loop live.

### Verify the small claim before composing it

Exercise the complete actual task early, including the native calls it makes.
An admitted contract declaration or a conditional helper proof does not establish
that the invocation works or that its real caller supplies the helper's premises.
Report declaration admission, semantic proof, and whole-task composition separately.

Check the actual task's type/exception closure and its consumer-relevant semantic relation. Then
test meaningful negative cases: missing required fields, wrong step count, ignored validation,
provider failure, and failure during cleanup. Exercise the real schema library for malformed-input
checks; prove the task's outcome handling under its external contract. Do not turn these tests into
an obligation to prove every library rejection algorithm. A frontend refusal or solver `unknown`
is not a semantic counterexample. Record which result occurred. A concrete execution satisfying all
preconditions and violating the postcondition is also a counterexample, but must not be reported
as an SMT refutation.

Keep three statuses distinct: source proof complete under named premises; measurements consistent
with the service/failure premises; composed application certificate issued and independently
verified. Finishing the first does not imply the third. The structure-builder design here remains
illustrative until its actual task, dependencies, and claim are bound and verified.

## 3. Worked composition: a backend streaming service

For the backend streaming claim, trace both preparation branches into the actual render join:

```text
structure -> story text --+-> visual plan ------+
                         |                    +-> matching render request
                         +-> narration/audio -+       -> video + finalization
                                                      -> committed playable supply
```

Trace the actual multiplicities: one structure may feed several story turns, and one turn may
produce several clips. Do not charge one structure per frame or silently assume an infinite supply
of planned turns. The drawing is a design example, not a requirement to change an app's topology.

Useful small obligations include:

- **Planning and production:** each stage returns its declared useful result or failure; failed
  attempts still occupy workers and shared devices.
- **Dispatch:** when required inputs and capacity are available, eligible work starts within the
  declared delay. Refill maintains the required lookahead.
- **Join and accounting:** only matching, published, usable media advances the ordered prefix.
  Duplicates and incomplete branches receive no credit. Quantity is established playable duration,
  not intended scene duration copied from metadata.
- **Failure disposition:** errors release reservations or retain work according to the actual
  policy. A terminal error that stops refill must appear in the supply/failure model.
- **Reserve:** warmup and refill thresholds cover the permitted production deficit, including
  dispatch pauses, slow stretches, failed attempts, and consumption during wakeup.

Prove these on clean production boundaries, then compose. Video and audio can overlap only to the
extent their workers and shared-resource allocations permit it. A parallel `max` is not justified
if both branches need the same exclusive device. Bounded queues need actual admission and release
rules; they are not evidence of sustainable throughput.

For every time in the certified interval, the target is:

```text
initial buffer + cumulative committed playable duration >= cumulative consumption
```

One way to establish that condition over a refill window of length `W` is:

```text
H >= sup over 0 <= u <= W of (consumption_upper(u) - useful_production_lower(u)) + margin
```

Derive `useful_production_lower` from stage activations, service, routing, outcomes, quantities, and
shared-resource budgets. Do not assume a monolithic "the pipeline runs realtime" stopwatch.
Average generation faster than average playback does not bound the largest deficit. Variable-size
outputs and occasional generation slower than their playable duration are compatible with a
guarantee when the declared cumulative work/output and deficit envelopes establish it.

An infinite-horizon result needs premises covering that horizon. Finite per-call failure budgets
or a successful half-hour run cannot be silently promoted to a small probability of interruption
over an unlimited lifetime. The engineering-envelope approach does not require a correlation
model, but it does require retaining the scope and strength of the premises used.

Start with these runnable, explicitly scoped examples:

The structured worker pipeline below gives a small numerical composition to work through.
Its explicit service premises are 10 ms for preparation, 10 ms for each of two parallel
branches, and 20 ms for publication. With the declared resources permitting overlap:

```text
one item:              10 + max(10, 10) + 20 = 40 ms
three sequential items: 3 * 40 = 120 ms
```

If those branches instead need the same exclusive resource, that parallel bound is unavailable;
serializing their two 10 ms stages gives 50 ms per item. The task proofs and resource model
determine which composition is justified. This numerical example proves a conditional batch
latency; the streaming application additionally needs its playable-output and reserve claims.

| Example | What to learn and what it does not certify |
| --- | --- |
| [Structured worker pipeline](../examples/certified_structured_pipeline/README.md) | Issuance workflow for typed fork/join, reservations, resource-aware overlap, finite supply, dispatch, and chance composition; not infinite playback. |
| [Asynchronous channel](../examples/certified_async_channel/README.md) | Real queue handoff and typed payload/resource binding; not inferred FIFO, fairness, or infinite liveness. |
| [Variable-size streaming policies](../examples/timing_systems/README.md) | `--certify` proves toy policies and a conditional infinite refill/reserve theorem, including slow pieces and failed work; it constructs descriptors, not real video. |
| [General timing logic](../examples/timing_logic/README.md) | Linear arithmetic composition and a source-bound release policy; mathematical artifacts alone are not app certificates. |

Their READMEs contain exact commands. Installed walkthroughs are available through `dagcert help
composed-worker-pipeline`, `dagcert help async-channel`, `dagcert help timing-systems`, and
`dagcert help timing-logic`. A browser proof is a separate extension only if the target requires it;
then the [real browser-fetch example](../examples/certified_browser_fetch/README.md) demonstrates
application-owned source plus explicit platform handoffs.

## 4. Finish the claim, not an unrelated verification project

When source proof is difficult, first ask whether a production refactor exposes a smaller,
coherent task and an interface its consumer actually needs. Preserve behavior and unclaimed data.
Do not force the verifier to absorb the application's incidental object graph, package layout,
or every feature of a large orchestration class. Conversely, moving an essential step outside the
claimed boundary does not prove it: either include it or state the narrower claim explicitly.

Escalate a verifier limitation only with the exact production shape or a faithful minimal
reproducer, expected property, source/toolchain hashes, and actual diagnostic. Unsupported syntax,
permission failure, a false property, and solver exhaustion are different findings.

Use new formulas or source-bound lemmas in the existing proof language before proposing a new
core operator. See the [general timing language](../dagcert/docs/linear-timing-logic.md). A timing
algebra's expressiveness does not imply that every Python implementation is already supported by
the selected source backend.

Finally, collect exact-source evidence for the chosen task boundaries, issue the composed claim,
and independently verify it. Explain remaining assumptions and gaps. Observation-only reports
belong in `dagcert analyze`, never in place of the promised certificate.
