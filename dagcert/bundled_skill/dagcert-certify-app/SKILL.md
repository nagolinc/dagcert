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
declares finite compositions over those primitives.

- `operation` tasks are real executable leaf boundaries and may have measured timings.
- `instrumentation` tasks may record aggregate observations but cannot participate in a derived
  composition.
- A composition names at least two connected operation tasks, exact duration cases, and finite
  execution counts. Dagcert computes its conservative bound from those leaves; it never accepts a
  direct aggregate stopwatch as the derivation.

Reconstruct the execution graph from source before writing the contract. Represent independently
scheduled stages, actual worker pools, queues, reservations, resource transfers, ordering rules,
success transitions, and failure-release transitions that affect a requested guarantee. Do not
collapse them into a pipeline observer or surround one catch-all measurement with meaningless task
names.

## Claim boundary

Classify every claim before collecting evidence:

- `observed` describes only retained executions. Its formula is `null`. Application checkers may
  support case-bounded semantic facts such as database-to-DOM correspondence.
- `derived` contains a formula in Dagcert's fixed kernel algebra. It cannot cite a checker as proof.
  The formula must use a declared multi-operation composition or bounds from at least two connected
  tasks plus relevant worker/resource state.

If the kernel cannot express or prove a requested system property, report it as unsupported. Never
replace non-starvation, bounded backlog, capacity, priority, sustained throughput, staleness, or
composed latency with a summary task whose measured output is the desired conclusion.

## Workflow

1. Run `dagcert init <app-root>` and replace every placeholder.
2. Inventory the user's requested guarantees. Classify each as observed or derived and write its
   exact scope and assumptions before evidence collection.
3. Trace source paths and build the smallest faithful worker/task/resource DAG. Do not mirror every
   function, but do not omit state or scheduling boundaries material to a claim.
4. Declare real workers, operation tasks, instrumentation, resources, and finite compositions.
5. Put external premises in `assumed` leaf timings. Do not infer worst-case gaps from averages or a
   few favorable samples.
6. Record every exact-source attempt, including failures. Exercise representative and adversarial
   cases. Never retry to replace a failed observation.
7. Run `dagcert lint`, application tests, and `dagcert analyze`. Resolve every coverage, binding,
   resource-effect, failed-attempt, and timing finding.
8. Encode derived claims as kernel formulas over the actual DAG. Do not use checker booleans or
   aggregate samples as proof premises.
9. Run `dagcert issue`, then `dagcert verify` with identical inputs and exclusions.
10. Report `CERTIFIED` only for the exact verified source and the exact observed/derived scope.
    Otherwise report `NOT CERTIFIED` and preserve the failures.

Never fabricate samples, types, capacities, transitions, formulas, checker results, or a passing
outcome. Certification does not imply general production readiness.

## Optional semantic audit

Run the independent audit only when requested. It uses the mandatory requirements file and creates
one sealed packet per claim. Each fresh audit worker must reconstruct the real execution graph from
source and compare it with the declared model. It must reject synthetic observer/summary timings,
missing queues or reservations, omitted failure transitions, average-rate substitutions for burst
bounds, and any proof that does not resemble the actual application DAG.

The review remains advisory: it can invalidate a claim, but its `passed` boolean cannot establish a
derived formula. Follow the per-claim handoff procedure in the workflow reference.
