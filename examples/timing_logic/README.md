# A general timing language, not another scenario opcode

```powershell
dagcert help timing-logic
python -m examples.timing_logic
python -m examples.timing_logic --certify
```

The first run proves ten mathematical constructions using ordinary SMT-LIB
first-order linear real arithmetic: composition and re-composition, min-plus
convolution, missing-event-aware quorum readiness, all-time reserve, jumps,
unattained extrema, unboundedness, and buffer-invariant obligations. No custom
quorum, streaming or extremum opcode is registered in Dagcert.

These standalone mathematical artifacts are **not application certificates**.
Their premises do not assert that any production system implements the relations.

`--certify` additionally proves the real `operations.py` release policy through
the source backend, issues its application certificate, and independently verifies
it. Two distinct replicas must acknowledge the requested version; an absent third
is allowed, while duplicate identities and wrong versions do not count. A general
`lra_theorem` composes the source-proved readiness and timestamp relations with an
explicit whole-window dispatch/application envelope. It derives release by
`deadline + dispatch_allowance`, with engineering success lower bound `0.999`.

The platform premise includes actual snapshot integrity, dispatch, execution and
atomic application; arithmetic does not manufacture these guarantees. This is a
certificate of a toy policy and its conditional timing theorem, not a complete
distributed storage system. All artifacts default to `.cache/timing-logic`.

Independent negative tests remove dispatch, reuse a duplicate acknowledgement,
and supply an arithmetically useful but false source relation. Those must fail.
