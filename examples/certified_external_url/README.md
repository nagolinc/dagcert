# Certified external URL adapter

This reference separates three things that must not be conflated:

- `boundary.py` is executable production code and calls the real `urllib.parse.urlsplit`.
- `boundary_contract.py` is a proof-only `ContractOnly` overlay with the exact same source types.
- `app.py` is ordinary application code proved by Nagini and consumes the real `ParsedUrl` edge.

At runtime, `external_boundary` validates the provider result and emits one retained evidence event
for success, exception, or wrong return type. The contract uses a zero bad-event engineering premise,
so either failure event makes issuance fail; it is never silently converted into success.

The latency claim composes two explicit 10 ms duration assumptions into a bound of at most 20 ms
on the typed success path. The separate measured `call` and `completion` cases retain runtime
evidence; they do not turn a passing sample into a promise about future calls. The `call` case
also supplies the external error-budget consistency check.
