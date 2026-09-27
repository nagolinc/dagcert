# Certified finite threshold

This minimal example proves a finite “at least K of N” claim over one real typed operation.
The `PreparedItem` outcome produces exactly one `prepared-items` unit; the retained
`PreparationRejected` outcome produces none. Both remain part of the source-extracted union.

The probability premise is an engineering envelope, not a statistical inference. With ten
attempts, seven required successes, and per-attempt bad-event probability at most 0.1, a miss
requires at least four bad outcomes. Markov's inequality therefore gives:

`P(miss) <= (10 * 0.1) / 4 = 0.25`

No independence or failure-rate correlation model is assumed. The time bound is separately
derived as three five-millisecond waves on four workers. This composition says nothing about
an unbounded retry loop or about attempts that were never dispatched.
