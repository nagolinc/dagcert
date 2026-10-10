# Five source policies and variable-size streaming

```powershell
python -m examples.timing_systems
python -m examples.timing_systems --certify
dagcert help timing-systems
```

`operations.py` contains actual A/V admission, dispatch, durable acknowledgement,
latest-wins publication and partial-window policies. `invariants.py` binds real
fields and all outcomes to source obligations. `streaming.py` supplies a small
segment-descriptor producer, consumer and refill controller. `models.py`
assembles inspectable contracts from compiler-extracted outcome types.

The streaming case has a 5000ms low-water mark, 15000ms capacity, 100ms refill
restart delay, and playback consumption at most 100+t media-ms per t-ms interval,
including the atomic callback crossing low water. Its dedicated
worker provides one worker-ms per elapsed ms while replenishment is backlogged:

```text
completed-output work, including unsuccessful attempts <= 0.8 * media-ms + 1400
unfinished work <= 3000 worker-ms
```

This permits alternating 2-second pieces taking 3 seconds and 5-second pieces
taking 2 seconds. The kernel derives maximum refill deficit 4600ms and reserve
floor **400ms** for every refill period over an unbounded horizon. Increasing
the outage allowance fails the claim despite unchanged asymptotic speed.
Source induction checks capacity; no overflow curve is silently clipped.

The example constructs descriptors, not video. Actual rendering, common-key
delivery, persistence, controller wakeup and effective service remain explicit
integration premises. Its certificate covers the toy source policies and
conditional timing theorem, not five deployed systems or unmodeled glue.

Generated artifacts go under `.cache/timing-systems`. Empty measurements are
intentional for conditional source/algebra claims; `--certify` still runs the
real source prover and independent verification. Model-only execution is
clearly labeled and is not certificate issuance.
