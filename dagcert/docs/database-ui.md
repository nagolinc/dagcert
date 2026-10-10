# Database-to-UI run-report workflow — not a certificate

The historical workflow records that database entries appeared correctly in retained browser runs.
That is useful semantic run evidence, but it is not a Dagcert guarantee and current Dagcert refuses
to issue its observation-only requirements.

**The observation-only route is the bad path.** A passing projection checker says nothing about
the next request or browser session. Presenting this run report as a certificate will disappoint
the user. A real guarantee requires source-proved application operations, typed external HTTP/JSON
handoffs, explicit platform premises, and a `derived` or `chance` kernel formula over that DAG.

The historical run report combines application primitives with an exact-projection checker:

```text
database/application state -> render task -> browser-visible rows
                                      |              |
                                 timing evidence     Selenium observation
                                      |              |
                                      +-- exact-projection result -- run report
```

An application checker may retain semantic evidence or invalidate a premise. Its boolean result
cannot establish a certificate promise. If the kernel cannot derive the requested property, report
`NOT CERTIFIED`; do not substitute the checker result or a successful browser run.

## Complete installed reference application

Dagcert retains `examples.certified_database_ui`, a real SQLite-backed HTTP and browser application,
as a historical run-report example. Its old directory name and artifact are not a current
certificate. Its retained evidence covers:

- initial database-to-DOM membership and ordering;
- ascending and descending sorting;
- next and previous pagination;
- insertion through the browser, HTTP endpoint, and SQLite commit;
- deletion through the browser, HTTP endpoint, and SQLite commit;
- the standard 50 ms non-streaming HTTP and 16 ms local UI deadlines for its measured sequential
  reference workload.

Read `examples.certified_database_ui/english_requirements.json` only as a historical example of the
now-refused `basis: observed` shape. Do not copy it into a certificate.

Inspect `examples.certified_database_ui.README.md` and run:

```text
python -m examples.certified_database_ui.app --reset
python -m examples.certified_database_ui.certify collect
```

The checked-in historical artifact is deliberately invalid under current Dagcert. Collection and
projection comparison remain useful run-report tools.

## 1. Model the work with the five primitives

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

## 5. Keep the result as supporting evidence

The projection result describes only the retained cases. It may accompany a run report or challenge
an explicit platform premise in a separately derived certificate. It cannot itself satisfy a
certificate claim. Report the narrow observation that was tested; one page/case does not imply
that every database row appears on every page or for every user.

## Required cases

At minimum, exercise empty, single-row, multiple-row, duplicate/equivalence-class, filtered, and
special-character data. Add pagination, authorization, live-update, loading, and error cases when
the application has those behaviors. These are test cases, not new Dagcert primitives.
