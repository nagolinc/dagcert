# Finite threshold repetition

Use `threshold_repeat` when a finite attempt prefix is successful after at least `K` of `N`
structured attempts reach one named terminal typed outcome and produce one corresponding resource
unit:

```json
{
  "kind": "threshold_repeat",
  "attempts": 10,
  "required": 7,
  "body": {
    "kind": "sequence",
    "children": [
      {
        "kind": "leaf",
        "task": "item.sample",
        "timing": "completion",
        "outcome_type": "SampledItem"
      },
      {
        "kind": "leaf",
        "task": "item.prepare",
        "timing": "completion",
        "outcome_type": "PreparedItem"
      }
    ]
  },
  "qualifying_exit": {
    "task": "item.prepare",
    "outcome_type": "PreparedItem",
    "resource": "prepared-items"
  }
}
```

The body uses the ordinary closed composition algebra: `leaf`, `sequence`, `parallel_all`,
`finite_repeat`, `async_handoff`, and `external_handoff`. Nested thresholds are rejected. Dagcert
checks that the qualifying exit occurs exactly once among the body's terminal exits, that its
outcome is in the source-extracted return union, that it produces exactly one named resource unit,
and that no other body outcome produces that resource. Failures stay visible as their real typed
outcomes.

Dagcert unions every selected task and transport bad-event envelope in one attempt to obtain `q`.
It then bounds the chance of missing the threshold without assuming independence:

```text
failures needed = N - K + 1
P(threshold missed) <= min(1, N*q / failures needed)
```

This is Markov's inequality applied to the number of bad attempts. It is conservative when attempts
are independent, but remains valid when failures are correlated or bursty. Retained evidence only
checks that observations do not contradict the declared engineering envelopes; it does not infer
`q`.

Duration is a conservative all-N batch bound derived from the body's actual workers, acquired
resources, transports, and leaf upper bounds. Sequence stages use batch barriers. Parallel branches
overlap only when their worker sets and acquired resources are disjoint. Completing all N attempts
is no earlier than reaching the Kth qualifying exit, so the same value is a safe conditional bound
on the Kth success.

The same threshold can prove a finite-window production-rate guarantee. A chance formula may
conjoin exactly two bounds for the same threshold composition: the probability of reaching K and
the derived lower production rate `K / all-N-upper-duration`:

```json
{
  "and": [
    {
      "gte": [
        {"composition_success_probability_lower": "composition:prepare-seven-of-ten"},
        0.75
      ]
    },
    {
      "gt": [
        {
          "divide": [
            {
              "composition_required_successes":
                "composition:prepare-seven-of-ten"
            },
            {
              "divide": [
                {"composition_upper_ms": "composition:prepare-seven-of-ten"},
                1000
              ]
            }
          ]
        },
        250
      ]
    }
  ]
}
```

This means: under the declared engineering envelopes, at least seven qualifying outputs arrive
within the composition's 25 ms upper bound with probability at least 0.75, so the finite-window
production rate is greater than 250 outputs/second. The rate is not an average measured from a
successful run. It is recomputed from K and the DAG-derived duration bound.

This operator proves a predeclared finite attempt prefix. It does not prove that inputs arrive, that
the production controller dispatches the prefix, that an unbounded retry loop is live, or that a
particular N makes a larger end-to-end chance claim positive. Those premises and remaining failure
envelopes stay explicit.

The v11 single-leaf syntax remains accepted for old contracts. New contracts should use v12 and the
structured form whenever one attempt crosses more than one real task.

Runnable source: `examples/certified_threshold_repeat`.
