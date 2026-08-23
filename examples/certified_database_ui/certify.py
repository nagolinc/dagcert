"""Collect real evidence and issue the certified database-to-UI example."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from threading import Thread
from time import perf_counter, time
from typing import Any
from urllib.request import Request, urlopen
import json

from dagcert import (
    CheckContext,
    EvidenceRecorder,
    TimingSample,
    analyze_contract,
    issue_certificate,
    load_contract,
    load_evidence,
    load_requirements,
    run_checker,
    sha256_file,
    source_fingerprint,
    verify_certificate,
)
from examples.optional_browser_checker import (
    ProjectionCase,
    check_exact_projection_cases,
    observe_dom_projection,
    read_sql_projection,
)
from examples.stats_viewer.screenshot import open_browser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from .app import create_server, initialize_database


PROJECTION_RESULTS = (
    "browse-projection.json",
    "insertion-projection.json",
    "deletion-projection.json",
)
EXPECTED_SORT_COLUMNS = {"title": "title", "category": "category", "created": "id"}


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    started = perf_counter()
    with urlopen(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    elapsed_ms = (perf_counter() - started) * 1000
    if not isinstance(result, dict):
        raise RuntimeError("HTTP endpoint returned a non-object JSON value")
    return result, elapsed_ms


def expected_projection(
    database: Path,
    *,
    page: int,
    page_size: int,
    sort: str,
    direction: str,
):
    column = EXPECTED_SORT_COLUMNS[sort]
    sql_direction = direction.upper()
    return read_sql_projection(
        database,
        query=f"""
            SELECT id AS row_key, title, category
            FROM items
            ORDER BY {column} {sql_direction}, id {sql_direction}
            LIMIT ? OFFSET ?
        """,
        key_column="row_key",
        field_columns=("title", "category"),
        parameters=(page_size, (page - 1) * page_size),
    )


def observed_projection(browser: Any):
    return observe_dom_projection(
        browser,
        row_selector="[data-item-row]",
        key_attribute="data-row-key",
        field_selectors={
            "title": "[data-field='title']",
            "category": "[data-field='category']",
        },
    )


def wait_for_next_load(browser: Any, previous_version: int) -> None:
    WebDriverWait(browser, 5).until(
        lambda current: int(current.find_element(By.TAG_NAME, "body").get_attribute("data-load-version") or 0)
        > previous_version
    )


def load_version(browser: Any) -> int:
    return int(browser.find_element(By.TAG_NAME, "body").get_attribute("data-load-version") or 0)


def capture_case(
    browser: Any,
    database: Path,
    name: str,
    *,
    page: int,
    sort: str,
    direction: str,
) -> ProjectionCase:
    return ProjectionCase(
        name=name,
        expected=expected_projection(
            database,
            page=page,
            page_size=3,
            sort=sort,
            direction=direction,
        ),
        observed=observed_projection(browser),
        require_order=True,
    )


def record_http_evidence(
    recorder: EvidenceRecorder,
    fingerprint: str,
    base_url: str,
) -> None:
    for index in range(12):
        direction = "asc" if index % 2 == 0 else "desc"
        sort = ("title", "category", "created")[index % 3]
        _, elapsed = request_json(
            base_url,
            f"/api/items?page={(index % 3) + 1}&page_size=3&sort={sort}&direction={direction}",
        )
        recorder.append(TimingSample(
            task_id="items.list",
            case="http",
            value_ms=elapsed,
            worker_id="http-server",
            source_fingerprint=fingerprint,
            recorded_at=time(),
            observed_worker_concurrency=1,
            observed_input_type="ItemPageQuery",
            observed_output_type="ItemPage",
            metadata={"boundary": "HTTP+SQLite+JSON", "sample": index},
        ))

    inserted_ids: list[int] = []
    for index in range(10):
        result, elapsed = request_json(
            base_url,
            "/api/items",
            method="POST",
            payload={"title": f"Timing item {index:02d}", "category": "timing"},
        )
        inserted_ids.append(int(result["id"]))
        recorder.append(TimingSample(
            task_id="items.insert",
            case="http",
            value_ms=elapsed,
            worker_id="http-server",
            source_fingerprint=fingerprint,
            recorded_at=time(),
            observed_worker_concurrency=1,
            observed_input_type="NewItem",
            observed_output_type="StoredItem",
            metadata={"boundary": "HTTP+SQLite commit+JSON", "sample": index},
        ))

    for index, identifier in enumerate(inserted_ids):
        result, elapsed = request_json(
            base_url,
            f"/api/items/{identifier}",
            method="DELETE",
        )
        if int(result["deleted"]) != identifier:
            raise RuntimeError("delete endpoint acknowledged the wrong item")
        recorder.append(TimingSample(
            task_id="items.delete",
            case="http",
            value_ms=elapsed,
            worker_id="http-server",
            source_fingerprint=fingerprint,
            recorded_at=time(),
            observed_worker_concurrency=1,
            observed_input_type="ItemId",
            observed_output_type="DeletionResult",
            metadata={"boundary": "HTTP+SQLite commit+JSON", "sample": index},
        ))


def exercise_browser(base_url: str, database: Path, screenshot: Path):
    browser = open_browser()
    browse_cases: list[ProjectionCase] = []
    insert_cases: list[ProjectionCase] = []
    delete_cases: list[ProjectionCase] = []
    try:
        browser.set_window_size(1280, 900)
        browser.get(base_url)
        wait_for_next_load(browser, 0)
        browse_cases.append(capture_case(
            browser, database, "initial-title-ascending", page=1, sort="title", direction="asc"
        ))

        version = load_version(browser)
        browser.find_element(By.ID, "sort-direction").click()
        wait_for_next_load(browser, version)
        browse_cases.append(capture_case(
            browser, database, "title-descending", page=1, sort="title", direction="desc"
        ))

        version = load_version(browser)
        browser.find_element(By.ID, "next-page").click()
        wait_for_next_load(browser, version)
        browse_cases.append(capture_case(
            browser, database, "next-page", page=2, sort="title", direction="desc"
        ))

        version = load_version(browser)
        browser.find_element(By.ID, "previous-page").click()
        wait_for_next_load(browser, version)
        browse_cases.append(capture_case(
            browser, database, "previous-page", page=1, sort="title", direction="desc"
        ))

        direction = "desc"
        for sort in ("category", "created"):
            version = load_version(browser)
            Select(browser.find_element(By.ID, "sort-field")).select_by_value(sort)
            wait_for_next_load(browser, version)
            browse_cases.append(capture_case(
                browser, database, f"{sort}-{direction}", page=1, sort=sort, direction=direction
            ))

            version = load_version(browser)
            browser.find_element(By.ID, "sort-direction").click()
            wait_for_next_load(browser, version)
            direction = "asc" if direction == "desc" else "desc"
            browse_cases.append(capture_case(
                browser, database, f"{sort}-{direction}", page=1, sort=sort, direction=direction
            ))

        version = load_version(browser)
        Select(browser.find_element(By.ID, "sort-field")).select_by_value("title")
        wait_for_next_load(browser, version)

        for index in range(5):
            title = f"Zulu browser {index:02d}"
            browser.find_element(By.ID, "title").send_keys(title)
            browser.find_element(By.ID, "category").send_keys("browser")
            version = load_version(browser)
            browser.find_element(By.CSS_SELECTOR, "#add-form button[type='submit']").click()
            wait_for_next_load(browser, version)
            inserted = capture_case(
                browser,
                database,
                f"insert-{index:02d}",
                page=1,
                sort="title",
                direction="desc",
            )
            insert_cases.append(inserted)
            inserted_id = next(
                row.key for row in inserted.observed if row.fields.get("title") == title
            )

            version = load_version(browser)
            browser.find_element(By.CSS_SELECTOR, f"[data-delete-id='{inserted_id}']").click()
            wait_for_next_load(browser, version)
            delete_cases.append(capture_case(
                browser,
                database,
                f"delete-{index:02d}",
                page=1,
                sort="title",
                direction="desc",
            ))

        screenshot.parent.mkdir(parents=True, exist_ok=True)
        height = max(
            900,
            int(browser.execute_script("return document.documentElement.scrollHeight")),
        )
        browser.set_window_size(1280, height)
        browser.execute_script("window.scrollTo(0, 0);")
        if not browser.save_screenshot(str(screenshot)):
            raise RuntimeError("Selenium did not save the database UI screenshot")
        events = browser.execute_script("return window.__dagcertEvents.slice();")
        if not isinstance(events, list):
            raise RuntimeError("browser timing events were unavailable")
        return tuple(browse_cases), tuple(insert_cases), tuple(delete_cases), tuple(events)
    finally:
        browser.quit()


def record_browser_evidence(
    recorder: EvidenceRecorder,
    fingerprint: str,
    events: tuple[dict[str, Any], ...],
) -> None:
    types = {
        "ui.feedback": ("UserAction", "VisibleStatus"),
        "ui.render": ("ItemPage", "RenderedItemRows"),
    }
    counts = {task: 0 for task in types}
    for event in events:
        task = str(event.get("task"))
        if task not in types:
            continue
        input_type, output_type = types[task]
        recorder.append(TimingSample(
            task_id=task,
            case=str(event["case"]),
            value_ms=float(event["value_ms"]),
            worker_id="browser",
            source_fingerprint=fingerprint,
            recorded_at=time(),
            observed_worker_concurrency=1,
            observed_input_type=input_type,
            observed_output_type=output_type,
            metadata={"boundary": "real browser DOM", **dict(event.get("metadata", {}))},
        ))
        counts[task] += 1
    deficient = {task: count for task, count in counts.items() if count < 10}
    if deficient:
        raise RuntimeError(f"insufficient browser timing samples: {deficient}")


def collect(root: Path) -> None:
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    database = artifacts / "runtime.sqlite3"
    evidence_path = artifacts / "timings.jsonl"
    evidence_path.unlink(missing_ok=True)
    initialize_database(database, reset=True)

    fingerprint = source_fingerprint(
        root, exclude=["dag_contract.json", "english_requirements.json"]
    )
    recorder = EvidenceRecorder(evidence_path)
    server = create_server(database)
    thread = Thread(target=server.serve_forever, name="certified-database-ui", daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        record_http_evidence(recorder, fingerprint, base_url)
        browse, insertions, deletions, events = exercise_browser(
            base_url,
            database,
            artifacts / "database-ui.png",
        )
        record_browser_evidence(recorder, fingerprint, events)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    contract_path = root / "dag_contract.json"
    requirements_path = root / "english_requirements.json"
    context = CheckContext(
        contract=load_contract(contract_path),
        timings=load_evidence(evidence_path),
        source_root=root,
        source_fingerprint=fingerprint,
        contract_sha256=sha256_file(contract_path),
        evidence_sha256=sha256_file(evidence_path),
        requirements=load_requirements(requirements_path),
        requirements_sha256=sha256_file(requirements_path),
    )
    checks = (
        (
            artifacts / PROJECTION_RESULTS[0],
            browse,
            ("task:items.list", "task:ui.render", "timing:items.list/http", "timing:ui.render/visible"),
            "example.database-ui.browse-projection/v1",
        ),
        (
            artifacts / PROJECTION_RESULTS[1],
            insertions,
            ("task:items.insert", "task:items.list", "task:ui.feedback", "task:ui.render"),
            "example.database-ui.insertion-projection/v1",
        ),
        (
            artifacts / PROJECTION_RESULTS[2],
            deletions,
            ("task:items.delete", "task:items.list", "task:ui.feedback", "task:ui.render"),
            "example.database-ui.deletion-projection/v1",
        ),
    )
    for output, cases, refs, checker in checks:
        result = run_checker(
            lambda current, cases=cases, refs=refs, checker=checker: check_exact_projection_cases(
                current,
                cases=cases,
                primitive_refs=refs,
                checker=checker,
            ),
            context,
            output,
        )
        if not result.passed:
            raise RuntimeError(f"projection checker failed: {checker}")
    analysis = analyze_contract(context.contract, context.timings, source_fingerprint=fingerprint)
    if not analysis.passed:
        raise RuntimeError("primitive analysis failed: " + "; ".join(
            f"{finding.code}: {finding.message}" for finding in analysis.findings
        ))
    print(f"collected real HTTP/browser evidence for source {fingerprint}")


def issue(root: Path, audit_result: Path | None) -> None:
    artifacts = root / "artifacts"
    contract = root / "dag_contract.json"
    requirements = root / "english_requirements.json"
    evidence = artifacts / "timings.jsonl"
    projection_paths = [artifacts / name for name in PROJECTION_RESULTS]
    checks = list(projection_paths)
    if audit_result is not None:
        if not audit_result.is_file():
            raise RuntimeError(f"requested audit result does not exist: {audit_result}")
        checks.append(audit_result)
    certificate = artifacts / "certificate.json"
    document = issue_certificate(
        contract,
        evidence,
        certificate,
        source_root=root,
        requirements_path=requirements,
        check_result_paths=checks,
    )
    verification = verify_certificate(
        certificate,
        contract_path=contract,
        evidence_path=evidence,
        requirements_path=requirements,
        source_root=root,
        check_result_paths=checks,
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    label = "audited certificate" if audit_result is not None else "certificate"
    print(f"issued and verified {label} {document['certificate_sha256']}")


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Certify the real database-to-UI reference application")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    issue_command = commands.add_parser("issue")
    issue_command.add_argument("--audit-result")
    args = parser.parse_args(argv)
    root = Path(__file__).parent.resolve()
    if args.command == "collect":
        collect(root)
    else:
        audit_result = Path(args.audit_result) if args.audit_result else None
        if audit_result is not None and not audit_result.is_absolute():
            audit_result = root / audit_result
        issue(root, audit_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
