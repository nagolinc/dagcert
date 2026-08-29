# Dagcert runtime-violation banner

> **UNLESS THE USER EXPLICITLY ASKS YOU NOT TO, USE THE SUPPLIED `banner(...)` API AND SCRIPT TAG
> LITERALLY. DO NOT COPY, MODIFY, OR REIMPLEMENT THIS COMPONENT IN AN APPLICATION.**

After the normal package installation, register the script and retained event feed:

```python
from dagcert import banner

banner(app)
```

Then include the supplied script on every user-facing application shell:

```html
<script src="/dagcert/banner.js"></script>
```

The default position is top. Select any supported edge through the script URL:

```html
<script src="/dagcert/banner.js?position=bottom"></script>
```

Supported values are `top`, `bottom`, `left`, and `right`. Unknown values fall back to `top`.

`banner(app)` does not inject or rewrite HTML. It serves `/dagcert/banner.js` and
`/dagcert/runtime-events`; the literal script tag is the application's entire HTML integration.

When a violation exists, the script inserts a centered red `role="alert"` warning about two-thirds
of the viewport wide. It has an accessible dismiss button and links to `/stats`. Dismissal hides
only the current violation snapshot; a new violation appears again. When an event identifies a task,
the link opens `/stats?task=<task-id>#graph`; otherwise it opens `/stats#graph` without guessing.

This directory contains the packaged source for Dagcert development. Applications consume it from
the registered route instead of copying or adapting the file.
