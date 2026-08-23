---
name: dagcert-certify-app
description: Certify an application with dagcert by declaring workers, tasks, resources, and timings; collecting source-bound timing evidence; and optionally attaching application-specific checker results. Use when a user says "certify this app", "use dag-certificate", or "use dagcert".
---

# Certify an application with dagcert

This skill is the focused getting-started guide, not the library reference. After installation,
run `python -m dagcert help` to discover the authoritative packaged guides and reusable examples.

## Rule 0: improve the experience; never certify a regression

Certification observes and reports. It is not permission to redesign the application.

Do not introduce queues, queue limits, rate limits, timeouts, cancellation, retries, debounce,
serialization, rejection, worker-count changes, resource caps, or altered product behavior merely
to obtain a passing result. A truthful failure is preferable to a certificate obtained by making
the application worse. If a change is independently desirable, explain it and obtain the same
approval it would require without certification.

## The complete model

Dagcert's domain model has exactly four kinds of things:

- **workers** execute tasks and declare concurrency;
- **tasks** declare dependencies, types, their worker, and resource acquisition/consumption/production;
- **resources** declare capacities, initial amounts, and application-defined units;
- **timings** bound task duration, arrival interval, waiting, or age using measurements or explicit assumptions.

Do not invent Dagcert concepts for endpoints, pages, controls, queues, databases, retries, user
actions, or frameworks. Represent work as tasks and relevant constraints as resources/timings.
Put application-specific structure in an optional checker owned by the application.

**Core cannot derive does not mean Dagcert cannot certify.** When a promise depends on semantic
application facts—such as database entries appearing as the correct UI rows—observe those facts in
an application-owned checker and attach its passing result to issuance and verification. A selected
checker result is a required, exact-source-bound part of the certificate, not informal supporting
documentation.

## Workflow

1. Run `dagcert init <app-root>`. It creates `dag_contract.json` and the mandatory
   `english_requirements.json`; replace every `replace_me` value in both.
2. Write every promised behavior as a complete plain-English claim with a stable ID, explicit
   assumptions, and references to the exact primitives and required application checkers. This
   file is the source of truth for certificate meaning, not optional audit material.
3. Map real work to the smallest useful task DAG. Do not mirror every function or DOM node.
4. Declare actual workers and resources. Use task resource effects to represent transient
   acquisition and the production/consumption of downstream work. Do not add a queue or cap to the
   application; describe existing flow.
5. Declare timing cases for real requirements. For recognizable non-streaming HTTP handling and
   visible local UI feedback, use the standard `<50ms` and `<16ms` limits respectively unless the
   product already specifies another limit. These are ordinary task timings, not special endpoint
   or UI primitives.
6. Record successful, exact-source timing samples. Exercise representative and adversarial cases.
   A sample names its task, timing case, worker, source fingerprint, timing value, and optionally
   observed concurrency/resource use.
7. Run `dagcert lint`, the application's tests, and `dagcert analyze`, always supplying the
   requirements path where the command requires it. Lint's mandatory translation audit must show
   that every formal task and timing appears in the English claims, references resolve, and assumed
   timings have explicit English assumptions.
8. Derive important claims from the primitives. Work supply comes from producer resource effects
   and interval timings; service capacity comes from duration timings and worker concurrency;
   generation lag is a flowing resource; structural progress comes from the task/resource graph.
   Represent external behavior as an `assumed` timing so the resulting claim is conditional. Use a
   checker for a derivation the kernel does not implement; it still cites only the four primitives
   and emits `dagcert-check-result/v2` bound to exact source, contract, evidence, and requirements.
9. Run `dagcert issue`, then `dagcert verify` with the same contract, English requirements,
   evidence, source root, exclusions, and optional checker result files.
10. Report `CERTIFIED` only for the exact verified source and only for the claims actually encoded
   by the contract and selected checkers. Otherwise report `NOT CERTIFIED` and the findings.

Never fabricate samples, types, capacities, coverage, checker results, or a passing outcome.
Never claim that certification eliminates every possible defect. It demonstrates only the stated,
measured, source-bound claims.

## Optional work

- Multi-page browser inventories, repeated controls, and database-to-UI correspondence belong in
  an application checker. For database-backed rows, use the optional exact-projection helper and
  run `python -m dagcert help database-ui` for the installed source-of-truth guide. Define expected
  rows with an application-owned read-only query, observe the real DOM with Selenium, compare stable
  semantic keys and promised visible fields, then attach the result to issuance and verification.
- Optimistic Mithril updates and buffered deltas are an application pattern; see the optional
  helper example. Choose debounce and retry semantics from product needs, not certification.
- The optional flow checker demonstrates non-starvation, structural progress, and bounded
  generation lag using only workers, tasks, resources, and timings.
- The optional stats viewer is presentation only. When modifying it, keep source unminified and use
  Selenium to capture and inspect desktop and mobile screenshots.
- Run an independent semantic audit only when the user requests it. It reads the exact mandatory
  `english_requirements.json`; there is no separate audit-claims file that can drift. The optional
  audit example generates a separate sealed directory, packet, prompt, schema, and response path
  for every claim.
  The human-authored worker instructions live in `examples/independent_audit_prompt.txt`; do not
  bury or duplicate system prompts in Python or JavaScript source. Every packet includes the exact
  source contents so the worker can review the implementation, not only hashes and formal data.
  For each claim, launch a different fresh built-in `spawn_agent` worker with
  `model="gpt-5.6-luna"`, `fork_turns="none"`, a unique task name, and only that claim's complete
  prompt. Never give multiple claims to one worker. Save each final JSON to its designated response
  path, then run the example's accept command to validate every digest and aggregate the results.
  Built-in `spawn_agent` uses the active ChatGPT/Codex subscription session; do not substitute an
  API-key call or claim separate API execution occurred.
  Reject terse entailment-only answers. Each worker must apply Rule 0, identify concrete strengths,
  weaknesses, evidence gaps, certificate-fitting risks, and prioritized improvements, and distinguish
  “this claim is entailed” from “this application is production-ready.”
  This is a user-requested tool for the active app-building agent, never a build/release gate. Use
  an external Codex CLI runner only when the current host has no subagent facility.

Read [references/workflow.md](references/workflow.md) for artifact formats and exact commands.
