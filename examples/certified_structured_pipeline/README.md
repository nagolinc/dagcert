# Certified structured worker pipeline

This is a generic Dagcert v7 example. It deliberately uses ordinary jobs rather than copying any
application architecture. It demonstrates:

- a source-typed fork/join with `parallel_all` and a real two-field join record;
- reservation at task start and outcome-specific completion effects;
- an affine slot-conservation proof;
- finite-horizon supply and a separate dispatch-wait proof;
- `finite_repeat`; and
- a conservative union-bound chance claim over the two parallel branches.

The operation timings are measured. The producer/consumer service envelopes and dispatch bound are
explicit assumptions; the certificate therefore presents the supply result as conditional. The
example does not use a pipeline observer or an aggregate stopwatch.

To issue with the independently built Maledictus backend:

```powershell
python -m examples.certified_structured_pipeline.certify C:\proof-tools\maledictus.exe
```

The script computes and pins the exact executable digest, writes retained evidence, issues a v11
certificate, and independently verifies it with the same backend.
