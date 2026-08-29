# Repository workspace hygiene

- Never create ad-hoc test, build, wheel, probe, virtualenv, or scratch directories at the
  repository top level.
- Use the operating system temporary directory for one-off work. Put persistent tool caches below
  `.cache/`, which is ignored.
- Let pytest use its configured `.cache/pytest` cache and its default system-temp base directory.
  Do not pass a repository-root `--basetemp` path.
- Build disposable wheels outside the repository or below `.cache/build`; remove them after use.
- Keep the top level limited to tracked project files, source directories, the active `.venv`, and
  explicitly user-owned sibling projects such as `Maledictus`.

## Completion and delivery

- A feature is not done until its commit has been successfully pushed to the configured remote,
  unless the user explicitly requested local-only work or explicitly asked not to push.
- Never report uncommitted or unpushed work as finished. State the exact commit and remote branch
  when handing off a completed feature.
