# Finite threshold repetition

Use `threshold_repeat` when a finite batch is successful after at least `K` of `N` invocations
produce one named typed outcome and one corresponding resource unit:

```json
{
  "kind": "threshold_repeat",
  "attempts": 10,
  "required": 7,
  "task": "item.prepare",
  "timing": "completion",
  "qualifying_outcome": "PreparedItem",
  "resource": "prepared-items"
}
```

Dagcert checks that `PreparedItem` is in the operation's source-extracted outcome union, that it
produces exactly one `prepared-items` unit, and that no other outcome produces that unit. Failures
stay visible as the other typed outcomes; they are not discarded or rewritten as successes.

For a declared per-attempt bad-event envelope `q`, Dagcert bounds the probability of missing the
threshold without assuming independence:

```text
failures needed = N - K + 1
P(threshold missed) <= min(1, N*q / failures needed)
```

This is Markov's inequality applied to the number of bad outcomes. It is deliberately conservative
when attempts are independent, but it remains valid when failures are correlated or bursty. The
retained evidence only checks that observations do not contradict the declared engineering
envelope; it does not infer `q`.

The duration is a conservative finite-batch bound:

```text
ceil(N / effective concurrency) * per-attempt upper bound
```

Effective concurrency is the task worker's declared concurrency, capped by any acquired-resource
capacity. The operator bounds already-dispatched finite attempts. It does not prove that inputs
arrive, model an unbounded retry loop, or replace queue/liveness state claims.

Runnable source: `examples/certified_threshold_repeat`.
