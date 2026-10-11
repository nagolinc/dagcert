# Agent certification guide

"Certify this app using dagcert" authorizes an agent to describe and measure the application, run
tests and selected checkers, refactor actual production work into clean proved tasks, and create
certificate artifacts. Preserve required behavior; the existing file/class layout is not fixed.
This does not authorize product restrictions or unrelated redesign.

Start with the [worked certification workflow](CERTIFICATION_WORKFLOW.md): state the consumer's
exact promise, trace its critical path and parallel feeders/resources, select small proof
obligations, prove the real task implementations, then compose their timing and failure contracts.
Do not begin by wrapping the whole app in a stopwatch or forcing a tangled implementation into a
single proof. Measurements support engineering premises; observation-only claims are not
certificates.

Unless the user explicitly asks not to include them, use Dagcert's supplied APIs literally:
`stats(app, certificate=..., evidence=...)` and `banner(app)`. They come from the normal Dagcert
package; there is no separate installer and they are not example code to copy or modify. Add exactly
`<script src="/dagcert/banner.js"></script>` to every user-facing shell. Never expose the bundled
three-task demo as application stats. Browser-test the exact certificate task set, violation display,
red task/worker health, dismissal, and reappearance for a new violation. Run
`python -m dagcert help app-surfaces` for the installed contract.

First write `english_requirements.json`. Every certificate requires it. Each complete
plain-English promise has a stable ID, a derived/chance basis, explicit assumptions, and exact
references to its formal derivation. Application checkers provide supporting run evidence, not a
substitute proof. Issuance embeds the document;
verification rejects any later wording or mapping change.

The mandatory translation audit rejects any formal task or timing omitted from the English claims,
unknown references, missing required checkers, or an assumed timing without an explicit English
assumption. This is the always-on completeness audit. A user-requested independent Luna audit adds
the semantic judgment that the prose faithfully describes the exact source and evidence.

Inventory workers, tasks, resources, typed channels, and timings. Tasks can acquire transient
capacity and consume or produce resource units. Timings can describe duration, arrival interval,
waiting, or age. Failed attempts and retry waits still consume time and capacity.
External facts such as user cadence are assumed timings and must appear in the conditional result.

Compose guarantees in the kernel's supported workflow, state, and timing proof languages. Reusable
proof builders may generate formulas or source-bound lemmas; an optional checker boolean cannot
replace a derivation. Check dispatch and useful-output supply, not just average service capacity.

Production must call the implementations being proved. Keep native/library contracts explicit;
do not relabel owned request, validation, or retry code as external. Verify each small claim before
expanding the model, collect evidence against exact source, attach relevant supporting checker
results, issue, then independently verify. Report a failure truthfully.

Use `<50ms` for recognizable non-streaming HTTP handling and `<16ms` for visible local UI feedback
unless the product explicitly specifies another requirement. Do not invent deadlines for slow or
asynchronous backend completion.

Page/control inventories, paid-service probes, and database-specific semantics are optional
application checkers, not primitives. An independent English-to-formal audit is a user-requested
tool that reads the exact mandatory requirements file; it is never the source of those claims and
never an automatic build/release gate.
