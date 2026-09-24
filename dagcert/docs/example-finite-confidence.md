# Example: finite confidence

Chance composition uses engineering-envelope error budgets and the union bound. It does not infer
independence or correlations from samples.

```json
{
  "kind": "finite_repeat",
  "count": 10,
  "body": {
    "kind": "parallel_all",
    "children": [
      {
        "kind": "leaf",
        "task": "validate",
        "timing": "duration",
        "outcome_type": "Validated"
      },
      {
        "kind": "leaf",
        "task": "checksum",
        "timing": "duration",
        "outcome_type": "Checksummed"
      }
    ]
  }
}
```

With per-invocation bad-event budgets `0.01` and `0.02`, the ten-item failure upper bound is:

```text
10 × (0.01 + 0.02) = 0.30
```

`examples/certified_structured_pipeline` issues a chance claim over three generic jobs and retains
all branch observations used as consistency checks for its declared engineering envelopes.

The success lower bound is therefore `0.70`. Correlation cannot invalidate this conservative
bound. `finite_repeat` is the horizon: Dagcert has no operator for an infinite probabilistic
“always succeeds” claim.
