# Certified finite threshold

This minimal example proves a finite “at least K of N” claim over a real two-stage typed attempt.
Sampling and preparation each retain their explicit rejected outcome. The `PreparedItem` terminal
outcome produces exactly one `prepared-items` unit; no other body outcome produces that unit.

The probability premise is an engineering envelope, not a statistical inference. With ten
attempts, seven required successes, and two stage envelopes of 0.05, the complete-attempt envelope
is at most 0.1 by the union bound. A miss
requires at least four bad outcomes. Markov's inequality therefore gives:

`P(miss) <= (10 * 0.1) / 4 = 0.25`

No independence or failure-rate correlation model is assumed. The time bound is separately
derived as five two-millisecond sampling waves followed by three five-millisecond preparation
waves. The finite prefix may stop after the seventh success; bounding completion of all ten is a
safe conditional bound on the seventh successful completion. The composition does not claim an
infinite retry guarantee.
