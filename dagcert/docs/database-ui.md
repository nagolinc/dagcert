# Certifying that database entries appear correctly in the UI

This common Dagcert claim does not require a database, browser, row, or projection primitive. The
certificate combines the four core primitives with an application-owned exact-projection checker:

```text
database/application state -> render task -> browser-visible rows
                                      |              |
                                 timing evidence     Selenium observation
                                      |              |
                                      +-- exact-projection check result -- certificate
```

"The core analyzer cannot derive this claim" does not mean "Dagcert cannot certify this claim."
A passing application checker selected during issuance is a required, digest-bound part of the
certificate and must be supplied again during verification.

## Complete installed reference application

Dagcert ships `examples.certified_database_ui`, a real SQLite-backed HTTP and browser application,
not a pseudocode fragment. Its checked-in exact-source certificate and per-claim independent audit
cover:

- initial database-to-DOM membership and ordering;
- ascending and descending sorting;
- next and previous pagination;
- insertion through the browser, HTTP endpoint, and SQLite commit;
- deletion through the browser, HTTP endpoint, and SQLite commit;
- the standard 50 ms non-streaming HTTP and 16 ms local UI deadlines for its measured sequential
  reference workload.

Read `examples.certified_database_ui/english_requirements.json` first. It is the mandatory,
human-readable source of all three promises, assumptions, primitive references, and required
projection checkers. The certificate embeds that exact document, and the optional audit consumes
it directly; there is no separate audit-claims file.

Inspect `examples.certified_database_ui.README.md` and run:

```text
python -m examples.certified_database_ui.app --reset
python -m examples.certified_database_ui.certify collect
python -m examples.certified_database_ui.certify issue
```

The checked-in certificate includes the accepted per-claim audit result. The audit remains
optional and runs only when the user asks for it; it is not a build or release gate. The README
contains the exact subscription-backed `gpt-5.6-luna` handoff sequence. Collecting new evidence
invalidates the checked-in audit, so including a new audit requires fresh workers.

## 1. Model the work with the four primitives

Declare the real task that obtains and renders the data. For example, `results.render` may be
performed by the browser worker, depend on `results.fetch`, consume a `results-snapshot` resource,
and produce a `RenderedResults` output. Give it a duration or age timing that expresses the real
requirement. Do not add a queue, timeout, retry, or rate limit to make certification pass.

The exact-projection check proves semantic content. Timing evidence separately proves when that
content appears. If the claim is "the correct rows appear within 200 ms," both must pass. Selenium
waiting limits belong only to the test harness and should come from that declared requirement; they
must not alter application behavior.

## 2. Define the expected projection explicitly

Use a read-only SQL query that describes what the page promises to show. Select a stable semantic
key and every visible field covered by the claim.

One UI row per database entry:

```sql
SELECT id AS row_key, title, status
FROM jobs
WHERE archived = 0
ORDER BY id
```

One UI row per equivalence class, with multiplicity as an annotation:

```sql
SELECT obligation_id AS row_key, MIN(label) AS label, COUNT(*) AS helper_count
FROM candidates
GROUP BY obligation_id
ORDER BY obligation_id
```

The query is application code and should be reviewed like any other statement of product
semantics. Do not weaken it to match a buggy UI. If the UI intentionally filters, paginates, or
uses permissions, encode those same declared inputs in the query and exercise every relevant case.

## 3. Give rendered rows stable semantic identities

Prefer nonvisual `data-*` attributes so the checker does not depend on row order or CSS layout:

```html
<tr data-result-row data-row-key="job-123">
  <td data-field="title">Compile report</td>
  <td data-field="status">Running</td>
</tr>
```

Adding test-only semantic attributes is optional and does not change the user experience. Existing
accessible roles, labels, and selectors are also valid when they identify rows unambiguously.

## 4. Compare the database projection with the real DOM

The reusable helper is `examples.optional_browser_checker`. The complete reference app above uses
it directly. The app-building agent remains
responsible for starting the real application, preparing representative database state, logging in
when necessary, navigating Selenium to the page, and triggering the real user action.

```python
from dagcert import run_checker
from examples.optional_browser_checker import (
    check_exact_projection,
    observe_dom_projection,
    read_sql_projection,
)

expected = read_sql_projection(
    app_database,
    query="""
        SELECT id AS row_key, title, status
        FROM jobs
        WHERE archived = 0
        ORDER BY id
    """,
    key_column="row_key",
    field_columns=("title", "status"),
)

driver.get(results_url)
observed = observe_dom_projection(
    driver,
    row_selector="[data-result-row]",
    key_attribute="data-row-key",
    field_selectors={
        "title": "[data-field='title']",
        "status": "[data-field='status']",
    },
)

run_checker(
    lambda current: check_exact_projection(
        current,
        expected=expected,
        observed=observed,
        primitive_refs=(
            "task:results.fetch",
            "task:results.render",
            "timing:results.render/visible",
        ),
        checker="myapp.results-page-exact-projection/v1",
    ),
    context,
    "artifacts/results-page-projection.json",
)
```

The helper fails on missing rows, unexpected rows, duplicate semantic keys, or mismatched visible
fields. It records counts and canonical projection digests in the check result. Ordering is ignored
by default because row identity, not DOM position, defines correspondence. Set `require_order=True`
when ordering or pagination is part of the promise; the helper then compares and records the exact
semantic-key sequence as the complete reference app does.

## 5. Make the result part of the certificate

Attach the same result during issuance and verification:

```text
dagcert issue ... --check-result artifacts/results-page-projection.json
dagcert verify ... --check-result artifacts/results-page-projection.json
```

The certificate is valid only while the check result passes and its source fingerprint, contract
digest, evidence digest, and primitive references match. Report the narrow claim that was tested;
one page/case does not imply that every database row appears on every page or for every user.

## Required cases

At minimum, exercise empty, single-row, multiple-row, duplicate/equivalence-class, filtered, and
special-character data. Add pagination, authorization, live-update, loading, and error cases when
the application has those behaviors. These are test cases, not new Dagcert primitives.
