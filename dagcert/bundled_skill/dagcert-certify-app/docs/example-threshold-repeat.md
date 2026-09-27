# Finite threshold repetition

Use `threshold_repeat` for a predeclared finite K-of-N prefix whose attempt is a real structured
task body. The body may use `sequence`, `parallel_all`, `finite_repeat`, `async_handoff`, and
`external_handoff`; nested thresholds are forbidden. Name one terminal typed outcome as the
`qualifying_exit`. That outcome alone must produce exactly one unit of the counted resource.

Dagcert unions every selected leaf and transport bad-event envelope in one attempt to obtain `q`,
then computes `P(miss) <= min(1, N*q/(N-K+1))`. This Markov envelope does not assume independent
attempts. Its latency result is a conservative all-N batch bound over the real workers, resources,
transports, and leaf timings, and therefore safely bounds the Kth qualifying completion when one
occurs.

The operator does not prove input arrival, production-controller dispatch, infinite retry
liveness, or queue liveness. Keep those premises explicit. Do not isolate only the final classifier
when earlier attempt stages have failure envelopes; put the complete attempt path in the body.

Run `dagcert help threshold-repeat` and inspect `examples/certified_threshold_repeat`.
