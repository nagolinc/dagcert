# Agent certification guide

"Certify this app using dagcert" authorizes an agent to describe and measure the application, run
tests and selected checkers, and create certificate artifacts. It does not authorize product
restrictions or unrelated redesign.

Unless the user explicitly asks not to include them, use Dagcert's supplied APIs literally:
`stats(app, certificate=..., evidence=...)` and `banner(app)`. They come from the normal Dagcert
package; there is no separate installer and they are not example code to copy or modify. Add exactly
`<script src="/dagcert/banner.js"></script>` to every user-facing shell. Never expose the bundled
three-task demo as application stats. Browser-test the exact certificate task set, violation display,
red task/worker health, dismissal, and reappearance for a new violation. Run
`python -m dagcert help app-surfaces` for the installed contract.

First write `english_requirements.json`. Every certificate requires it. Each complete
plain-English promise has a stable ID, explicit assumptions, and exact references to the formal
primitives and any application checker required to establish it. Issuance embeds the document;
verification rejects any later wording or mapping change.

The mandatory translation audit rejects any formal task or timing omitted from the English claims,
unknown references, missing required checkers, or an assumed timing without an explicit English
assumption. This is the always-on completeness audit. A user-requested independent Luna audit adds
the semantic judgment that the prose faithfully describes the exact source and evidence.

Inventory only workers, tasks, resources, and timings. Tasks can acquire transient capacity and
consume or produce resource units. Timings can describe duration, arrival interval, waiting, or age.
External facts such as user cadence are assumed timings and must appear in the conditional result.

This is sufficient to express work-supply/non-starvation, structural progress/no blocked tasks, and
bounded generation lag. Use an optional checker when the derivation is not built into the kernel;
do not add a new application primitive.

Preserve existing behavior, collect evidence against exact source, attach checker results only when
their claims matter, issue, then verify. Report a failure truthfully.

Use `<50ms` for recognizable non-streaming HTTP handling and `<16ms` for visible local UI feedback
unless the product explicitly specifies another requirement. Do not invent deadlines for slow or
asynchronous backend completion.

Page/control inventories, paid-service probes, and database-specific semantics are optional
application checkers, not primitives. An independent English-to-formal audit is a user-requested
tool that reads the exact mandatory requirements file; it is never the source of those claims and
never an automatic build/release gate.
