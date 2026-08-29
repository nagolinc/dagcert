# Dagcert runtime-violation banner

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THIS FILE LITERALLY. IT IS A SHIPPED
> APPLICATION SURFACE, NOT EXAMPLE CODE TO MODIFY.**

Copy `dagcert-violation-banner.js` unchanged into the application's static assets and include it on
every user-facing application shell:

```html
<script src="/dagcert-violation-banner.js"></script>
```

The script polls `GET /dagcert/runtime-events` once per second. That endpoint must return a JSON
object with `violation_count` and `last_violation`; `last_violation` is either null or an object with
a human-readable `message`, `detail`, or `error`. The banner also accepts an `events` array whose
violations have `violation: true` or `passed: false`.

When a violation exists, the script inserts a full-width red `role="alert"` above the application,
states that certified guarantees do not hold, links to `/stats`, and provides an accessible ×
button. Dismissal hides only the current violation snapshot; a new violation appears again.
When the event identifies a task through `task_id`, `task`, `node_id`, or a `task:` primitive
reference, the link opens `/stats?task=<task-id>#graph`; the literal viewer scrolls to and highlights
that failing DAG node. Events without a task link to `/stats#graph` without inventing a mapping.

The only integration-specific work is exposing the runtime-event endpoint and serving the unchanged
file. Do not restyle, inline, rename, rewrite, or substitute the component unless the user explicitly
asks for a different banner.
