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
