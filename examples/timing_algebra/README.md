# Two producers maintain a reserve

Run the conditional model proof:

```powershell
python -m examples.timing_algebra
```

Two independent workers each produce one item per invocation. A third worker reserves one item
at admission. The reserve starts with 50 items and has capacity 100. Source-bound operations have
one declared outcome each. No aggregate observer supplies the result.

The example assumes periodic-rate arrival envelopes: each producer has rate `1/100` items/ms,
the consumer has rate `1/50` items/ms, and each count has a one-item burst/phase allowance. Each
worker has a dedicated slot, a 9 ms duration bound, and a 1 ms dispatch bound. The service curve
allows one unfinished operation, so producer completion lower bounds are
`max(0, (t - 110)/100)`.

The kernel derives, for every nonnegative time:

```text
inventory lower = 50 + 2 × max(0, (t - 110)/100) - (1 + t/50)
                >= 46.8 items >= 30 percent of capacity

inventory upper = 50 + 2 × (1 + t/100) - max(0, (t - 50)/50)
                <= 53 items <= capacity
```

The overflow check matters: clipping an overflowing bucket and then counting the discarded
production as future reserve would give an invalid lower bound. This example's admitted flow
never needs that clipping.

These are explicit engineering assumptions over all time. A finite production trace cannot
establish them. Use a finite `end_ms` and matching envelope `horizon_ms` when the intended promise
only covers one session. The runner loads the real operation signatures, audits the English claim,
and evaluates the conditional model; it does not run a source-proof backend or issue a certificate.

For the usual source verification gate, run:

```powershell
dagcert lint examples/timing_algebra/dag_contract.json --requirements examples/timing_algebra/english_requirements.json
```

That requires the configured proof backend. Successful model analysis alone is not a source
certificate. See `dagcert help timing-algebra` for the curve language and other application patterns.

To issue and independently verify the source-bound conditional certificate:

```powershell
dagcert issue --contract examples/timing_algebra/dag_contract.json --requirements examples/timing_algebra/english_requirements.json --evidence examples/timing_algebra/artifacts/timings.jsonl --source-root examples/timing_algebra --output examples/timing_algebra/artifacts/certificate.json
dagcert verify examples/timing_algebra/artifacts/certificate.json --contract examples/timing_algebra/dag_contract.json --requirements examples/timing_algebra/english_requirements.json --evidence examples/timing_algebra/artifacts/timings.jsonl --source-root examples/timing_algebra
```

The supplied evidence file is deliberately empty: every timing here is explicitly assumed, not
measured. Issuance must still run strict mypy and the selected source-proof backend. The certificate
proves the typed leaves and conditional model; it does not establish the environmental envelopes
from observations or promise that an arbitrary scheduler satisfies them.
