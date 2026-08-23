"""Optional exact-projection checks for browser-rendered application data.

The core Dagcert ontology remains workers, tasks, resources, and timings. This
module is an application-owned checker helper: it compares an expected semantic
projection (often read from a database) with rows observed in a real browser.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import sqlite3

from dagcert import CheckContext, CheckFinding, CheckResult


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    """One semantic UI row, identified independently of its DOM position."""

    key: str
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ProjectionCase:
    """One named state transition or page whose projection must match."""

    name: str
    expected: Sequence[ProjectionRow]
    observed: Sequence[ProjectionRow]
    require_order: bool = False


def read_sql_projection(
    database_path: str | Path,
    *,
    query: str,
    key_column: str,
    field_columns: Sequence[str],
    parameters: Sequence[Any] = (),
) -> tuple[ProjectionRow, ...]:
    """Execute an app-owned read-only query that defines the expected UI rows.

    For a one-row-per-record UI, select the record's primary key. For a grouped
    UI, use GROUP BY in the query and select the semantic equivalence key plus
    any count/status annotation that must be visible.
    """

    uri = Path(database_path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        records = connection.execute(query, tuple(parameters)).fetchall()
    required = (key_column, *field_columns)
    rows: list[ProjectionRow] = []
    for index, record in enumerate(records):
        missing = [column for column in required if column not in record.keys()]
        if missing:
            raise ValueError(f"SQL projection row {index} is missing columns {missing}")
        rows.append(ProjectionRow(
            key=str(record[key_column]),
            fields={column: str(record[column]) for column in field_columns},
        ))
    return tuple(rows)


def observe_dom_projection(
    driver: Any,
    *,
    row_selector: str,
    key_attribute: str,
    field_selectors: Mapping[str, str],
) -> tuple[ProjectionRow, ...]:
    """Read semantic row keys and visible fields from the current Selenium page.

    The string ``"css selector"`` is accepted by Selenium's standard W3C API.
    Keeping Selenium imports out of this module lets the pure comparator remain
    usable without installing the optional browser dependency.
    """

    rows: list[ProjectionRow] = []
    for index, element in enumerate(driver.find_elements("css selector", row_selector)):
        key = element.get_attribute(key_attribute)
        if key is None or not str(key).strip():
            raise ValueError(
                f"DOM projection row {index} has no nonempty {key_attribute!r} attribute"
            )
        fields = {
            name: element.find_element("css selector", selector).text
            for name, selector in field_selectors.items()
        }
        rows.append(ProjectionRow(str(key), fields))
    return tuple(rows)


def check_exact_projection(
    context: CheckContext,
    *,
    expected: Iterable[ProjectionRow],
    observed: Iterable[ProjectionRow],
    primitive_refs: Sequence[str],
    checker: str = "example.exact-projection/v1",
    require_order: bool = False,
) -> CheckResult:
    """Require exactly one matching observed row for every expected key.

    Set ``require_order`` only when row order is part of the application's
    promise, such as a sorted or paginated result list.
    """

    expected_rows = tuple(expected)
    observed_rows = tuple(observed)
    findings: list[CheckFinding] = []
    expected_by_key = _unique_rows("expected", expected_rows, findings)
    observed_by_key = _unique_rows("observed", observed_rows, findings)

    for key in sorted(expected_by_key.keys() - observed_by_key.keys()):
        findings.append(CheckFinding(
            "missing-rendered-row", key, "expected semantic row was not present in the DOM",
        ))
    for key in sorted(observed_by_key.keys() - expected_by_key.keys()):
        findings.append(CheckFinding(
            "unexpected-rendered-row", key, "DOM contained a semantic row not in the projection",
        ))
    for key in sorted(expected_by_key.keys() & observed_by_key.keys()):
        expected_fields = dict(expected_by_key[key].fields)
        observed_fields = dict(observed_by_key[key].fields)
        if expected_fields != observed_fields:
            findings.append(CheckFinding(
                "rendered-field-mismatch",
                key,
                f"expected={expected_fields!r}, observed={observed_fields!r}",
            ))
    expected_order = [row.key for row in expected_rows]
    observed_order = [row.key for row in observed_rows]
    if require_order and expected_order != observed_order:
        findings.append(CheckFinding(
            "rendered-order-mismatch",
            "projection",
            f"expected key order={expected_order!r}, observed key order={observed_order!r}",
        ))

    return CheckResult(
        checker=checker,
        passed=not findings,
        source_fingerprint=context.source_fingerprint,
        contract_sha256=context.contract_sha256,
        evidence_sha256=context.evidence_sha256,
        requirements_sha256=context.requirements_sha256,
        primitive_refs=tuple(primitive_refs),
        findings=tuple(findings),
        facts={
            "claim": "observed DOM rows exactly equal the application-defined projection",
            "expected_count": len(expected_rows),
            "observed_count": len(observed_rows),
            "order_required": require_order,
            "expected_sha256": _projection_digest(expected_rows),
            "observed_sha256": _projection_digest(observed_rows),
            "expected_order_sha256": _order_digest(expected_rows),
            "observed_order_sha256": _order_digest(observed_rows),
        },
    )


def check_exact_projection_cases(
    context: CheckContext,
    *,
    cases: Sequence[ProjectionCase],
    primitive_refs: Sequence[str],
    checker: str,
) -> CheckResult:
    """Check multiple browser states as one certificate-bound application claim."""

    if not cases:
        raise ValueError("at least one projection case is required")
    names = [case.name.strip() for case in cases]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("projection case names must be nonempty and unique")
    findings: list[CheckFinding] = []
    facts: dict[str, Any] = {}
    for case in cases:
        result = check_exact_projection(
            context,
            expected=case.expected,
            observed=case.observed,
            primitive_refs=primitive_refs,
            checker=checker,
            require_order=case.require_order,
        )
        findings.extend(
            CheckFinding(item.code, f"{case.name}/{item.subject}", item.message)
            for item in result.findings
        )
        facts[case.name] = result.facts
    return CheckResult(
        checker=checker,
        passed=not findings,
        source_fingerprint=context.source_fingerprint,
        contract_sha256=context.contract_sha256,
        evidence_sha256=context.evidence_sha256,
        requirements_sha256=context.requirements_sha256,
        primitive_refs=tuple(primitive_refs),
        findings=tuple(findings),
        facts={"claim": "every named database-to-DOM projection case matches", "cases": facts},
    )


def check_rendered_actions(
    context: CheckContext,
    *,
    rendered_by_page: Mapping[str, Sequence[str]],
    expected_by_page: Mapping[str, Sequence[str]],
    primitive_refs: Sequence[str],
) -> CheckResult:
    """Retain the smaller repeated-control example for backwards compatibility."""

    findings: list[CheckFinding] = []
    for page, expected_actions in expected_by_page.items():
        rendered_counts = Counter(rendered_by_page.get(page, ()))
        expected_counts = Counter(expected_actions)
        if rendered_counts != expected_counts:
            missing = expected_counts - rendered_counts
            extra = rendered_counts - expected_counts
            findings.append(CheckFinding(
                "rendered-action-mismatch", page,
                f"missing={dict(sorted(missing.items()))}, extra={dict(sorted(extra.items()))}",
            ))
    unexpected_pages = sorted(set(rendered_by_page) - set(expected_by_page))
    for page in unexpected_pages:
        findings.append(CheckFinding(
            "unexpected-rendered-page", page,
            f"observed {len(rendered_by_page[page])} actions on an undeclared page",
        ))
    return CheckResult(
        checker="example.browser-actions/v1",
        passed=not findings,
        source_fingerprint=context.source_fingerprint,
        contract_sha256=context.contract_sha256,
        evidence_sha256=context.evidence_sha256,
        requirements_sha256=context.requirements_sha256,
        primitive_refs=tuple(primitive_refs),
        findings=tuple(findings),
        facts={
            "pages": sorted(rendered_by_page),
            "instances": sum(map(len, rendered_by_page.values())),
        },
    )


def _unique_rows(
    side: str,
    rows: Sequence[ProjectionRow],
    findings: list[CheckFinding],
) -> dict[str, ProjectionRow]:
    result: dict[str, ProjectionRow] = {}
    counts = Counter(row.key for row in rows)
    for key, count in sorted(counts.items()):
        if count != 1:
            findings.append(CheckFinding(
                f"duplicate-{side}-key",
                key,
                f"{side} projection contains {count} rows for one semantic key",
            ))
    for row in rows:
        result.setdefault(row.key, row)
    return result


def _projection_digest(rows: Sequence[ProjectionRow]) -> str:
    canonical = [
        {"key": row.key, "fields": dict(sorted(row.fields.items()))}
        for row in sorted(rows, key=lambda item: (item.key, sorted(item.fields.items())))
    ]
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _order_digest(rows: Sequence[ProjectionRow]) -> str:
    encoded = json.dumps([row.key for row in rows], ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
