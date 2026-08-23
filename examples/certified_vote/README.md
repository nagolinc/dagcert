# Certified in-process vote example

Run `py -m examples.certified_vote.certify` from the repository root. It measures the exact
functions in `app.py`, derives conditional flow-model guarantees, issues a certificate, and
verifies it.

The example deliberately claims only what it implements:

- **responsiveness:** `preview_vote_total` is measured below 16ms and `commit_vote_total` below
  50ms for the exact in-process workload;
- **computational liveness:** every declared Python task implementation has successful completion
  evidence;
- **no structural blocked state:** the declared acyclic task/resource graph passes structural
  progress under its printed assumptions;
- **non-starvation:** the declared worker/resource/timing model has sufficient snapshot work after
  warm-up under its explicit cadence and service-envelope assumptions;
- **bounded lag:** the same conditional model has enough summary service capacity to stay within
  its declared three-generation lag capacity.

This is not a browser, HTTP, database, external-model, or Comfy example, and neither its contract nor
its English claims imply those boundaries. The cadence and service envelopes are explicit modeling
assumptions, not measured production facts. No queue limit, timeout, rate limit, retry, rejection,
or runtime restriction is added to make the certificate pass.

`english_requirements.json` is the mandatory plain-English source of truth embedded in every
certificate. On explicit request, the optional audit reads that exact file: run its `prepare`
command, give each generated claim prompt to a different fresh
`gpt-5.6-luna` subagent with no conversation fork, save each response, and run `accept`. Claims are
never bundled into one worker. See `../../docs/REFERENCE_AUDIT.md` for the latest audit result.
