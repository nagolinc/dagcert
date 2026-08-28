---
name: dagcert-certify-app
description: Certify an application with dagcert by modeling its real worker/task/resource DAG, separating observed claims from kernel-derived formulas, collecting exact-source evidence, and optionally auditing application-specific observations. Use when a user says "certify this app", "use dag-certificate", or "use dagcert".
---

# Certify an application with dagcert

This is the focused workflow. Run `python -m dagcert help` for packaged guides and examples, and
read [references/workflow.md](references/workflow.md) for current artifact formats and commands.

## Rule 0: improve the experience; never certify a regression

Certification observes and reports. It is not permission to redesign the application. Do not add
queues, limits, timeouts, retries, debounce, serialization, rejection, reduced concurrency,
resource caps, fake fast paths, or altered behavior merely to pass. Report a truthful failure.

## Model the actual execution DAG

Dagcert's primitives remain workers, tasks, resources, and timings. A hardened contract also
declares finite source-outcome paths over those primitives.

- `operation` tasks are real executable leaf boundaries and may have measured timings.
- In a v6 contract, an operation binds a real source file and symbol. Dagcert extracts its one-input
  type and closed return union and runs strict mypy itself. It then requires the digest-pinned
  Nagini/Viper container to prove the complete bound Python file has no undeclared exceptional
  exit. Contract JSON cannot declare or override task types.
- Dagcert verifies the provenance of `operation` and `dataclass`; local lookalike decorators and
  source-tree modules shadowing `dagcert` or `dataclasses` fail. The marker preserves the exact
  callable type; it does not catch exceptions or widen the outcome union.
- A v10 certificate seals strict-mypy output, the pinned Nagini image digest and proof scope, and the
  exact type-enforcement core-file manifest—not only a claimed Dagcert version or compiler result.
- `instrumentation` tasks may record aggregate observations but cannot participate in a derived
  composition.
- A v6 composition names the source outcome at every step, and adjacent steps must be a real typed
  dependency edge. Dagcert computes its conservative bound from those leaves; it never accepts a
  direct aggregate stopwatch as the derivation.

Reconstruct the execution graph from source before writing the contract. Represent independently
scheduled stages, actual worker pools, queues, reservations, resource transfers, ordering rules,
success transitions, and failure-release transitions that affect a requested guarantee. Do not
collapse them into a pipeline observer or surround one catch-all measurement with meaningless task
names.

Write the production operation boundary in its strongly typed form before modeling it. For Python,
use an explicit input class, explicit named outcome classes, an inline closed return union, and
`@dagcert.runtime.operation`. Every v6 dependency names an upstream outcome type and must feed a downstream
callable that accepts that exact source type. Model effects for every explicit source outcome.
Expected failures must be return variants; an unexpected exception invalidates the proof. Keep
parsing, normalization, lookup, reservation, and other claim-relevant argument preparation inside
the verified boundary. Never create a typed certification wrapper that production bypasses.
Do not use operation-level Nagini `Requires` or executable-module `Assume`/`ContractOnly`; Dagcert
must prove executable behavior for the complete declared input type without trusted axioms.

For a real third-party or standard-library boundary that Nagini cannot translate, declare a v6
`external` task. Put the executable adapter in its own module, mark it with
`@dagcert.runtime.external_boundary(TASK_ID)`, and put the Nagini `ContractOnly` specification in a
different source-owned stub named by `external_contract.stub_path`. The stub is a proof overlay, not
production code. Its input and success dataclass shapes must exactly match the adapter. Declare the
real provider module/symbols and the precise engineering assumption. Run production calls under
`monitor_external_boundaries(ExternalEvidenceMonitor(...))`; exceptions and wrong return types are
typed violation outcomes and retained evidence, never success. Use a zero bad-event upper bound for
a p=1 premise; any observed violation then refuses issuance.
The stub body is intentionally limited to `Ensures(Result() is not None)`; arbitrary postconditions
could make the proof vacuous and are rejected. Put richer value validation in executable code.

Do not claim a JavaScript or TypeScript task is a proved operation. This release has no approved
exception/totality verifier for those languages; `tsc --strict` is not a substitute. Represent such
boundaries only as observational instrumentation, and never use them in a derived composition.

## Claim boundary

Classify every claim before collecting evidence:

- `observed` describes only retained executions. Its formula is `null`. Application checkers may
  support case-bounded semantic facts such as database-to-DOM correspondence.
- `derived` contains a formula in Dagcert's fixed kernel algebra. It cannot cite a checker as proof.
  The formula must use a declared multi-operation composition or bounds from at least two connected
  tasks plus relevant worker/resource state.
- `chance` contains either a finite-composition engineering-envelope formula or one external-contract
  probability premise. Every composition step must use a task-local
  engineering error budget, select a source-typed good outcome, and cite that budget as an explicit
  assumption. The budget's complete good set must equal the exact selected outcome. Do not invent
  failure outcomes: a total task can use `error_budget: null`, and an optional budget may classify
  every real outcome as good. Use one direct success-lower/failure-upper comparison with a
  literal probability; never add a boolean fallback branch. Retained observations test consistency
  only; never describe them as statistically establishing the leaf probability.

Keep may- and must-reachability distinct. A downstream success branch may be structurally reachable
without being guaranteed across failure outcomes. Do not call it blocked, and do not use it as
unconditional supply. Chance formulas use the union bound only; do not multiply success rates or
assume independence.

If the kernel cannot express or prove a requested system property, report it as unsupported. Never
replace non-starvation, bounded backlog, capacity, priority, sustained throughput, staleness, or
composed latency with a summary task whose measured output is the desired conclusion.

## Workflow

1. Run `dagcert init <app-root>` and replace every placeholder.
2. Inventory the user's requested guarantees. Classify each as observed, derived, or chance and write its
   exact scope and assumptions before evidence collection.
3. Trace source paths and build the smallest faithful worker/task/resource DAG. Do not mirror every
   function, but do not omit state or scheduling boundaries material to a claim.
4. Declare real workers, operation tasks, instrumentation, resources, and finite compositions.
   Bind each task to the source symbol actually called by its production worker; do not write
   `input_type` or `output_type` labels in the contract.
5. Put timing premises in `assumed` leaf timings. Model external-library behavior with a declared
   `external_contract`, proof-only stub, typed runtime boundary, and canonical evidence stream. Do
   not infer worst-case gaps or probabilities from a few favorable samples.
6. Record every exact-source attempt, including failures. Exercise representative and adversarial
   cases. Never retry to replace a failed observation.
7. Run `dagcert lint`, application tests, and `dagcert analyze`. Resolve every coverage, binding,
   strict-mypy, Nagini translation/proof, resource-effect, failed-attempt, and timing finding.
8. Encode derived claims as kernel formulas over the actual DAG. Do not use checker booleans or
   aggregate samples as proof premises.
9. Run `dagcert issue`, then `dagcert verify` with identical inputs and exclusions.
10. Report `CERTIFIED` only for the exact verified source and the exact observed/derived/chance scope.
    Otherwise report `NOT CERTIFIED` and preserve the failures.

Never fabricate samples, capacities, transitions, formulas, checker results, or a passing
outcome. Certification does not imply general production readiness.

## Optional semantic audit

Run the independent audit only when requested. It uses the mandatory requirements file and creates
one sealed packet per claim. Each fresh audit worker must reconstruct the real execution graph from
source and compare it with the declared model. It must reject synthetic observer/summary timings,
missing queues or reservations, omitted failure transitions, average-rate substitutions for burst
bounds, and any proof that does not resemble the actual application DAG.

The review remains advisory: it can invalidate a claim, but its `passed` boolean cannot establish a
derived formula. Follow the per-claim handoff procedure in the workflow reference.
