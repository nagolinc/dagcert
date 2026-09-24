# Example: composed worker pipeline

This capstone uses generic jobs and adds no new proof mechanism:

```text
accept
  -> reserve slot
  -> prepare
  -> parallel_all(validate, checksum)
  -> ready
  -> deliver
  -> release slot
```

Use the focused examples together:

1. `fork-join` binds the branch outputs to fields of the real delivery input record.
2. `reservation-lifecycle` proves conservation across starts, successes, and failures.
3. `bounded-buffer` proves finite-horizon supply and a separate scheduler wait bound.
4. `finite-confidence` composes typed bad-event budgets without independence assumptions.
5. `external-verified-leaf` binds any non-Python application stage to a registered verifier and
   leaves platform behavior as an explicit assumption.

The capstone must not add an aggregate observer task or a measured pipeline stopwatch. End-to-end
latency comes from the structured expression, confidence from its typed leaves, and queue behavior
from the lifecycle state claims. A custom checker may provide supplementary observations, but it
cannot prove any of those derived claims.

Run `python -m examples.certified_structured_pipeline.certify PATH_TO_MALEDICTUS` from the Dagcert
repository to regenerate and independently verify the generic v11 certificate.
