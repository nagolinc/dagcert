# Certification scope: prove tasks, stop at dependency contracts

- Before proof work, write the task's statically typed input, closed success/error outcomes,
  consumer-required guarantees, resources, and timing/failure accounting. Follow the user's
  microclaim order and finish the current claim before starting unrelated work.
- Use explicit trusted contracts for established parsers, schema validators, HTTP clients, and
  model services. `parse_and_validate(text, schema) -> SchemaObject | Error` is a boundary:
  success satisfies the supplied schema; failure produces no useful output and still costs time.
- Prove the application's selection of schema, invocation, outcome handling, and use of the
  returned object. Do not make dependency internals, JSON grammar, recursive JSON representations,
  dictionary/string operations, or validation-library loops prerequisites for a task-level claim.
  Refactor real application code to use a suitable existing library and typed boundary.
- At the first indication that proof work is descending into those internals, stop that descent
  and revise the boundary. Do not keep extending Dagcert/Maledictus for an unsuitable formulation.
  Verifier development requires explicit user scope and a concrete consumer-level obligation
  that remains after checking existing contracts and a simpler application boundary.
- Keep trusted assumptions explicit and bound to the real dependency/version. Do not silently
  assume application scheduling, joins, credit accounting, or other behavior being certified.
  A written contract is not an accepted proof; tests and observations are not certificates.
- Read `docs/CERTIFICATION_WORKFLOW.md` for the structure-builder example and stop procedure.

# Repository workspace hygiene

- Never create ad-hoc test, build, wheel, probe, virtualenv, or scratch directories at the
  repository top level.
- Use the operating system temporary directory for one-off work. The repository may have exactly
  one disposable-output directory at top level: `.cache/`, which is ignored.
- Put every repository-local pytest cache, mypy cache, test tree, build, wheel, probe, and scratch
  output below `.cache/`. Never create another disposable top-level directory.
- Pytest uses `.cache/pytest`; mypy uses `.cache/mypy`. The test configuration rejects any
  repository-local `cache_dir` or `--basetemp` outside `.cache/`.
- Build disposable wheels outside the repository or below `.cache/build`; remove them after use.
- Keep the top level limited to tracked project files, source directories, the active `.venv`, and
  explicitly user-owned sibling projects such as `Maledictus`.

## Completion and delivery

- A feature is not done until its commit has been successfully pushed to the configured remote,
  unless the user explicitly requested local-only work or explicitly asked not to push.
- Never report uncommitted or unpushed work as finished. State the exact commit and remote branch
  when handing off a completed feature.
