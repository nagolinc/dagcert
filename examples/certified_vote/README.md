# Certified in-process vote example

Run `py -m examples.certified_vote.certify` from the repository root. It measures the exact
source-typed functions in `app.py`, issues a certificate, and verifies it.

The example deliberately claims only what it implements:

- **responsiveness:** `preview_vote_total` is measured below 16ms and `commit_vote_total` below
  50ms for the exact in-process workload;
- **computational liveness:** every declared Python task implementation has successful completion
  evidence;
- **no structural blocked state:** the declared acyclic task/resource graph passes structural
  progress under its printed assumptions;
- **source-owned types:** Dagcert extracts every input and outcome union from the real callable and
  runs strict mypy plus digest-pinned Nagini exception-freedom verification; the contract cannot
  state substitute type labels; and
- **typed edges:** `PreviewTotal` is the real input to commit, and `CommittedTotal` is the real input
  to both downstream functions.
- **finite error budget:** one preview followed by one commit has a kernel-derived success budget
  of at least 98%, conditional on explicit 1% engineering bad-event budgets for each leaf. The
  kernel uses the union bound and does not infer independence from the ten retained observations.

The success-only downstream tasks are may-reachable but not must-reachable because preview and
commit have explicit rejection outcomes. This is not a browser, HTTP, database, external-model, or Comfy example, and neither its contract nor
its English claims imply those boundaries. The former non-starvation and bounded-lag claims are not
carried forward: the explicit rejection outcomes produce no downstream work, so their old
unconditional supply premise is false. No queue limit, timeout, rate limit, retry, or runtime
restriction is added to make the certificate pass.

`english_requirements.json` is the mandatory plain-English source of truth embedded in every
certificate. On explicit request, the optional audit reads that exact file: run its `prepare`
command, give each generated claim prompt to a different fresh
`gpt-5.6-luna` subagent with no conversation fork, save each response, and run `accept`. Claims are
never bundled into one worker. See `../../docs/REFERENCE_AUDIT.md` for the latest audit result.
