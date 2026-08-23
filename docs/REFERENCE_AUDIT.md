# Reference example audit

The optional v3 audit requires separate claim reasoning, Rule 0 analysis, reviewed files,
strengths, weaknesses, improvements, test-fitting risks, evidence gaps, and invalidating findings.
Every claim is sealed into its own packet and assigned to a different fresh `gpt-5.6-luna`
subagent.

The four claims in `examples/certified_vote` pass that independent audit. They pass because their
English wording matches their evidence precisely:

- completion and responsiveness claims cover the exact in-process Python functions that were
  measured;
- the 16ms and 50ms results explicitly make no browser, network, or persistence promise;
- non-starvation and bounded-lag statements are explicitly conditional results about the declared
  worker/resource/timing model, not assertions about an unimplemented runtime scheduler;
- no queue limit, timeout, rate limit, retry, rejection, or reduced concurrency was added to make
  the example pass.

The auditors still report useful limitations. The workload is small and serial, resource effects
are declarations rather than runtime resource transitions, concurrency is modeled rather than
executed, and cadence/service envelopes are assumptions with no production samples. Those facts
limit the scope of the certificate but do not contradict its deliberately narrow promises.

The accepted detailed result is
`examples/certified_vote/artifacts/independent-audit-result.json`. It was generated directly from
the certificate's mandatory `english_requirements.json`, with no separate claims file. The audit remains a tool run only
on explicit user request; it is not an automatic build or release gate.
