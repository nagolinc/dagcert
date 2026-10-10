# A compositional timing proof language

Dagcert's general arithmetic proof interface targets **first-order linear real
arithmetic (LRA)**: the recognized SMT-LIB mathematical family, not a list of
supported application patterns. The source-backed network calculus remains a
convenient front end. New application-specific constructions can instead be
expressed as LRA formulas without registering another kernel operator.

The contract is: given finite formulas in this family and consistent explicit
premises, every valid implication is expressible and has a decision procedure.
Dagcert delegates that decision to the pinned Z3 arithmetic solver and its
quantifier-elimination machinery. Validity is not determined by whether the
developers anticipated the application. Solver resource exhaustion, interruption,
or `unknown` does not produce a certificate and is not reported as a counterexample.

This is a mathematical-family guarantee, not a claim that every conceivable
program property is linear arithmetic or that Dagcert invents missing premises.

## The family, precisely

The language permits exact rational constants; real-valued variables; addition,
subtraction, multiplication by rational constants and division by nonzero
rational constants; comparisons; arbitrary Boolean connectives and Boolean
variables; finite piecewise expressions; and arbitrarily nested real/Boolean
`forall` and `exists` quantifiers.

Ordinary minimum, maximum, absolute value, clamps, finite races and order
statistics are definable with `ite` and comparisons. Relational composition is
existential quantification over the intermediate value. Substitution, conjunction,
disjunction, negation and further quantification remain in the family. A proved
relation is not restricted to being the final statement of a proof.

For example, two relations `F(x, y)` and `G(y, z)` compose as:

```text
exists y: F(x, y) and G(y, z)
```

Here `F` and `G` stand for actual formula bodies, or previously proved bodies
instantiated without capturing bound variables. They are not unconstrained
function symbols. Repeating composition needs no new Dagcert feature.

Time, byte counts, playable duration and work have meanings established by the
source-bound model. LRA's real scalars do not by themselves establish unit
conversions, physical stream identity, queue delivery or useful production.
Those connections remain part of the certificate's checked premises.

## What this covers

Finite rational piecewise-affine relations cover more than the continuous
single-input curves exposed by the convenient curve API. LRA formulas can express
discontinuities, multiple inputs and outputs, conditional availability, exact
rational conversion rates, relational handoffs, finite joins and races, and
quantified bounds over every nonnegative time.

Min-plus convolution can be stated by a quantified lower-bound condition and a
greatest-lower-bound condition. For continuous functions on a compact interval,
an attained minimum is available; general open or unbounded domains require the
actual infimum/supremum definition. The language does not require extrema to be
attained or silently replace an unbounded value with a large finite number.

Infinite-horizon claims use quantification, not an arbitrarily long simulation:

```text
forall t >= 0:
    initial_reserve + useful_production(t) - actual_consumption(t) >= reserve_floor
```

The named functions above must expand to LRA-definable relations or come from
properly established source/envelope facts. An arbitrary unknown function of
time is not automatically in pure LRA. Production while full or paused must not
be counted as useful retained output.

## Application meaning is not manufactured by arithmetic

A proof that the second of three numbers is below a deadline does not prove
that an actual coordinator commits by that deadline. An application claim needs
the source-proved readiness condition, distinct matching acknowledgements, actual
handoffs, and a bounded dispatch/service premise. Safety alone does not establish
progress. The example tests deliberately refuse to infer dispatch latency from
quorum readiness alone.

Each source-backed invocation has an explicit Boolean `$completed` binding.
Source postconditions are guarded by completion; an outcome-union selection is
exactly one only when completed and none when incomplete. Thus the type union
cannot manufacture termination. Multiple names for the same source field are
equated; changing a variable's name cannot create contradictory source premises.

The source adapter translates exact Python `int` and `bool` fields, including
finite nested projections through source-owned frozen field-only dataclasses,
and their linear integer/Boolean postconditions. For example,
`result.turn_id == input.narration.turn.id` follows the actual source annotations
and imported record identities; it does not collapse the records into strings or
replace them with an application-supplied schema. The original predicate
is submitted to the real source verifier, and its SMT version is constructed
mechanically from that same predicate. Callers cannot supply an unrelated
arithmetic formula and attach a source-proof label. The sealed projection schema
is a finite nominal graph: recursive record references are back edges, and a
finite requested path has no arbitrary depth cap. Extraction terminates on
repeated record identities and refuses unresolved cyclic import aliases.
Wildcard imports and conditionally rebound record, decorator, or primitive names
do not establish projection provenance. An extracted unresolved root remains
explicitly unresolved; it cannot fall back to an older flat field schema.

Each traversed record must be an actual frozen dataclass. Mutable records,
optional/union/container hops, external object fields, Python division and
numeric truthiness are explicitly outside this adapter;
they are not restrictions on the mathematical LRA language. Python integers are
relaxed to reals only in the conservative direction: proving the implication
for all reals also covers their integer values. A `float` is not silently treated
as an exact real, and a Boolean is not silently treated as an integer. Extracting
a path proves neither that it is non-null under an optional annotation nor that
the program satisfies the relation: the original whole-operation semantic proof
is still mandatory, including entry snapshots and final-exit behavior.

Similarly, a missing completion event has a presence flag. Its timestamp payload
has no meaning when absent. Assigning zero, a large timeout value or a finite
number called `infinity` must not turn absence into a completion.

Root premises are source facts or explicit platform/engineering envelopes. A
theorem's conclusion is recomputed by the kernel; a custom checker's Boolean
success result is not an arithmetic proof. Mathematics-only examples are labeled
as such and are not substitutes for source-bound application certificates.

For an application theorem, the checker also removes the source facts and asks
whether the environmental assumptions alone establish its conclusion. If they
do, the claim cannot be presented as a source-derived application guarantee.
This rejects an irrelevant source fact attached to an assumed conclusion.
Ordinary mathematical theorems remain valid in mathematical mode. This relevance
check does not prove that an engineering assumption describes reality; that
premise stays visible and must be justified by the application.

## Repetition and feedback

Induction uses supplied initialization and preservation obligations. When those
obligations are LRA formulas, they belong to the same decision family regardless
of the application. The language does not promise to synthesize the invariant,
prove that arbitrary application code implements the transition, or infer
fairness. Those are separate obligations.

Useful throughput cannot be deduced just from a bounded buffer invariant.
Progress additionally needs a service/dispatch condition and the connection from
the actual transitions to elapsed time and useful output.

## Probability and scope

An arithmetic derivation establishes a conditional implication. Its engineering
confidence comes from the declared failure events of the root envelopes, carried
through the proof with their identities and horizons. A union bound needs no
independence assumption. It does not justify replacing three retries at failure
probability `p` with `p**3`.

An envelope saying "this request misses its deadline with probability at most p"
is not the same event as "some deadline is missed over an infinite lifetime."
An infinite-horizon probability claim requires appropriately scoped whole-lifetime
premises or another explicit derivation. Shared assumptions must remain shared
through a branching proof; distinct invocation events must not be accidentally
deduplicated.

## Outside the named guarantee

The exact family excludes multiplication of two unknown real variables, division
by an unknown variable, arbitrary uninterpreted functions, arrays, transcendental
functions, and unbounded integer arithmetic. Such expressions are not quietly
approximated or certified by this interface. A conservative LRA envelope can be
used when explicitly justified. Python integers may be soundly relaxed to reals
for suitable obligations; IEEE floating-point execution is not exact real
arithmetic and needs its own verified bounds.

The LRA decision guarantee does not imply automatic invariant synthesis, complete
verification of arbitrary Python/JavaScript, or fixed verification runtime.
The supported family is broad but decidability is not a promise that all large
instances are cheap.

## Using the interface

`dagcert prove-math request.json --output theorem.json` and
`dagcert verify-math theorem.json` decide and replay a **mathematical** implication.
For example, `request.json` can contain:

```json
{
  "variables": {"reserve": "real"},
  "assumptions": ["(>= reserve 3)"],
  "conclusion": "(forall ((t Real)) (=> (>= t 0) (>= (- (+ reserve (ite (>= t 3) (- t 3) 0)) t) 0)))"
}
```

The commands seal exact inputs and solver/kernel identity and recompute the
decision on verification. They establish no application-source premise. The
usual `dagcert issue` / `verify` path remains mandatory for app certificates.

In a v7+ application's `state_claims`, use `kind: lra_theorem`, with:

- `mode`: `source` for an app claim; `mathematical` for a reusable logical lemma.
- `variables`: each name maps to `{sort, unit, binding}`. A binding is either
  `null` for a mathematical parameter or `{task, invocation, outcome, field}`.
  Fields are actual `input.name`, `result.name`, `$completed`, or `$selected`.
- `premises`: named source predicates, engineering envelopes or theorem imports.
  Source predicates use `{id, kind: source, task, invocation, outcome, predicate}`;
  `predicate` is the source-backend relation, e.g. `result.value == input.value + 1`.
  An envelope uses `{id, kind: envelope, formula, assumption, event, horizon_ms,
  failure_probability_upper, primitive_refs}`; its `formula` is an SMT-LIB term.
  A theorem import uses `{id, kind: theorem, claim, substitutions}` with a
  capture-free substitution for every declared child variable. Math-only roots
  can use `{id, kind: fact, formula}` and are never silently promoted to app facts.
- `lemmas`: any finite DAG of `{id, uses, conclusion}` implications. `uses` names
  premise or local-lemma IDs. Every used lemma is recomputed, not accepted as a proof flag.
- `uses` and `conclusion`: the inputs and SMT-LIB term for the final implication.
- `horizon_ms`: the whole scope (`null` means all time); `metadata`: a JSON object.

The executable source example is the complete reference shape. Imports keep
source projections, completion guards, hypotheses and failure events intact.
Source variables cannot be rebound to a different task or field; invocations can
be consistently re-instantiated. Unit labels are checked when binding aliases and
importing source projections; they are not an inference engine that invents
dimensionally valid arithmetic. Physical conversions need source-proved relations.

English claims use `state_claim_proved` for a conditional deterministic theorem,
or `state_claim_success_probability_lower` in a `chance` claim for nonzero envelope
budgets. Source proof is still run at lint, issuance and verification. A mathematical
lemma by itself cannot be used as the English application's guarantee.

## Executable closure examples

`examples/timing_logic/math_examples.py` supplies formulas, not application-specific
kernel instructions. `tests/test_timing_logic_math.py` checks:

- Associativity of relational pipeline composition and reusing its result.
- Exact min-plus convolution via quantified inequalities and witnesses.
- The second of three acknowledgements, including absent acknowledgements.
- An all-time reserve bound and a deliberately insufficient service envelope.
- A discontinuous release quota.
- A finite supremum that is not attained and a set with no finite upper bound.
- Supplied initialization and preservation obligations for variable-sized buffers.

Counterexamples cover missing dispatch bounds, counting absent acknowledgements,
shortened service latency, unsupported reserve floors and unguarded buffer writes.
These are closure tests. Source-backed issuance and independent verification are
additional acceptance checks, not replaced by these mathematical examples.

## Source-backed timed release example

`examples/timing_logic/operations.py` contains an executable acknowledgement
release policy. It requires two present acknowledgements with distinct replica
identities, the requested version, and arrival timestamps no later than its
current transition timestamp. It does not wait for a missing third replica and
does not count a duplicate acknowledgement twice.

`examples/timing_logic/model.py` binds its real input and result fields, proves
the readiness rule and returned timestamp against the source, then derives the
deadline using ordinary LRA. The platform envelope covers the snapshot's
integrity, common clock, and bounded dispatch/execution/atomic application. It
contains no assumed release-result fields. Under that whole-window envelope,
any valid pair arriving by `D` results in a release transition timestamp at most
`D + dispatch_allowance`.

The default model gives the entire 60,000 ms envelope a failure budget of
`1/1000`, so the derived chance lower bound is `999/1000`; these are configurable
example inputs, not statistically inferred rates. The source certificate is for
this toy policy and conditional timing implication, not an entire storage
cluster. Its tests issue and independently verify a real certificate, refuse a
missing dispatch bound, and refuse a false source-readiness postcondition.

## Mathematical and solver references

The [SMT-LIB LRA declaration](https://smt-lib.org/logics-all.shtml#LRA) specifies
the rational linear real language and its quantified extension.
The [Z3 quantifier-elimination documentation](https://microsoft.github.io/z3guide/docs/strategies/summary/#tactic-qe)
describes the solver's native elimination support for linear arithmetic.
