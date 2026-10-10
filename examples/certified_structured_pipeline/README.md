# Certified structured worker pipeline

This is a generic Dagcert v7 example. It deliberately uses ordinary jobs rather than copying any
application architecture. It demonstrates:

- a source-typed fork/join with `parallel_all` and a real two-field join record;
- reservation at task start and outcome-specific completion effects;
- an affine slot-conservation proof;
- finite-horizon supply and a separate dispatch-wait proof;
- `finite_repeat`; and
- a conservative union-bound chance claim over the two parallel branches.

The measured operation timings remain evidence for the engineering error-budget checks. Separate
assumed service envelopes support the latency promise: prepare takes at most 10 ms, validation and
checksum each take at most 10 ms in parallel, and publication takes at most 20 ms. The kernel
derives `3 × (10 + max(10, 10) + 20) = 120 ms` for the three-job success path. The producer/consumer
service envelopes and dispatch bound are also explicit assumptions, so the latency and supply
results are conditional. A passing measurement is not promoted into a future timing guarantee.

To issue with the independently built Maledictus backend:

```powershell
python -m examples.certified_structured_pipeline.certify C:\proof-tools\maledictus.exe
```

The script computes and pins the exact executable digest, writes retained evidence, issues a v11
certificate, and independently verifies it with the same backend.
