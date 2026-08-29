import json
from pathlib import Path
from typing import Any, Callable

import dagcert.surfaces as surfaces
from dagcert import ExternalBoundaryEvent, banner, stats


class FakeFlask:
    def __init__(self) -> None:
        self.extensions: dict[str, Any] = {}
        self.routes: dict[str, Callable[..., object]] = {}

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: Callable[..., object] | None = None,
        **options: object,
    ) -> None:
        assert endpoint
        assert view_func
        self.routes[rule] = view_func


def write_certificate(path: Path, task_count: int = 7) -> None:
    tasks = [
        {
            "id": f"pipeline.task-{index}",
            "worker": f"worker-{index % 3}",
            "depends_on": [] if index == 0 else [f"pipeline.task-{index - 1}"],
            "resources": {},
            "timings": {"completion": {"metric": "duration", "upper_ms": 50}},
        }
        for index in range(task_count)
    ]
    path.write_text(
        json.dumps(
            {
                "schema": "dagcert-certificate/v10",
                "source_fingerprint": "abc123",
                "analysis": {"passed": True, "conditional": False},
                "primitives": {
                    "workers": [
                        {"id": f"worker-{index}", "concurrency": 1}
                        for index in range(3)
                    ],
                    "tasks": tasks,
                    "resources": [],
                },
            }
        ),
        encoding="utf-8",
    )


def test_stats_binds_the_exact_certificate_instead_of_demo_data(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    write_certificate(certificate)
    app = FakeFlask()

    binding = stats(app, certificate=certificate)

    assert binding.routes == ("/stats", "/stats/", "/stats/<path:asset_name>")
    body, status, headers = app.routes["/stats"]()
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    prefix = "window.DAGCERT_BOUND_DATA="
    payload = str(body).split(prefix, 1)[1].split(";</script>", 1)[0]
    bound = json.loads(payload)
    assert len(bound["contract"]["tasks"]) == 7
    assert [task["id"] for task in bound["contract"]["tasks"]] == [
        f"pipeline.task-{index}" for index in range(7)
    ]
    assert bound["certificate"]["source_fingerprint"] == "abc123"
    assert "window.DAGCERT_BOUND_DATA || window.DAGCERT_SAMPLE" in str(
        app.routes["/stats/<path:asset_name>"]("app.js")[0]
    )


def test_banner_registers_script_and_feed_without_rewriting_html(monkeypatch: Any) -> None:
    app = FakeFlask()
    app.extensions["dagcert"] = {
        "task_workers": {"image.generate": "image-worker"}
    }
    event = ExternalBoundaryEvent(
        boundary_id="image.generate",
        elapsed_ms=92.0,
        outcome_type="ExternalTypeViolation",
        succeeded=False,
        recorded_at=1234.5,
        expected_type="GeneratedImage",
        observed_type="str",
        message="wrong image result type",
    )
    monkeypatch.setattr(surfaces, "runtime_violations", lambda: (event,))

    binding = banner(app)

    assert binding.routes == ("/dagcert/banner.js", "/dagcert/runtime-events")
    script, status, headers = app.routes["/dagcert/banner.js"]()
    assert status == 200
    assert headers["Content-Type"].startswith("application/javascript")
    assert "dagcert-violation-banner" in str(script)
    response, status, headers = app.routes["/dagcert/runtime-events"]()
    payload = json.loads(str(response))
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert payload["violation_count"] == 1
    assert payload["last_violation"]["task_id"] == "image.generate"
    assert payload["last_violation"]["worker_id"] == "image-worker"
    assert not hasattr(app, "after_request")
