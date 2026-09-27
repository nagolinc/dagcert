# Finite threshold repetition

Use `threshold_repeat` for one finite K-of-N batch of a source-proved task. The expression names
literal `attempts` N, literal `required` K, the exact `qualifying_outcome`, and the resource that
only that outcome produces once.

Dagcert preserves every other typed outcome. Given per-attempt bad-event envelope `q`, it derives
`P(miss) <= min(1, N*q/(N-K+1))` without an independence assumption. It derives finite-batch time
from worker concurrency, acquired-resource capacity, and the leaf duration bound. It does not prove
that attempts arrive or describe an unbounded retry loop.

Run `dagcert help threshold-repeat` and inspect `examples/certified_threshold_repeat`.
