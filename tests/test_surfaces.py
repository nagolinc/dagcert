import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import dagcert.surfaces as surfaces
import pytest
from dagcert import (
    EvidenceRecorder,
    ExternalBoundaryEvent,
    SurfaceError,
    TimingSample,
    banner,
    sha256_file,
    stats,
)
from dagcert.certificate import canonical_json


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


def write_certificate(
    path: Path,
    task_count: int = 7,
    *,
    sample_source_fingerprint: str | None = None,
) -> Path:
    source_fingerprint = "a" * 64
    evidence = path.with_name("timings.jsonl")
    evidence.write_text("", encoding="utf-8")
    if sample_source_fingerprint is not None:
        EvidenceRecorder(evidence).append(
            TimingSample(
                task_id="pipeline.task-0",
                case="completion",
                value_ms=10,
                worker_id="worker-0",
                source_fingerprint=sample_source_fingerprint,
            )
        )
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
    document = {
        "schema": "dagcert-certificate/v10",
        "source_fingerprint": source_fingerprint,
        "evidence_sha256": sha256_file(evidence),
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
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    path.write_bytes(canonical_json(document) + b"\n")
    return evidence


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
    assert bound["certificate"]["source_fingerprint"] == "a" * 64
    assert bound["evidence"] == []
    assert bound["evidence_binding"] == {
        "sha256": sha256_file(tmp_path / "timings.jsonl"),
        "source_fingerprint": "a" * 64,
        "sample_count": 0,
        "sealed": True,
    }
    assert "window.DAGCERT_BOUND_DATA || window.DAGCERT_SAMPLE" in str(
        app.routes["/stats/<path:asset_name>"]("app.js")[0]
    )


def test_stats_rejects_a_missing_explicit_evidence_file(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    write_certificate(certificate)

    with pytest.raises(SurfaceError, match="explicitly supplied evidence file does not exist"):
        stats(
            FakeFlask(),
            certificate=certificate,
            evidence=tmp_path / "missing.jsonl",
        )


def test_stats_rejects_a_missing_default_evidence_file(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    evidence = write_certificate(certificate)
    evidence.unlink()

    with pytest.raises(SurfaceError, match="default evidence file does not exist"):
        stats(FakeFlask(), certificate=certificate)


def test_stats_rejects_evidence_not_sealed_by_the_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    evidence = write_certificate(certificate)
    evidence.write_text("\n", encoding="utf-8")

    with pytest.raises(SurfaceError, match="evidence digest does not match"):
        stats(FakeFlask(), certificate=certificate)


def test_stats_rejects_evidence_from_different_source(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    write_certificate(certificate, sample_source_fingerprint="b" * 64)

    with pytest.raises(SurfaceError, match="different source fingerprint"):
        stats(FakeFlask(), certificate=certificate)


def test_stats_rejects_a_tampered_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    write_certificate(certificate)
    document = json.loads(certificate.read_text(encoding="utf-8"))
    document["analysis"]["passed"] = False
    certificate.write_bytes(canonical_json(document) + b"\n")

    with pytest.raises(SurfaceError, match="certificate digest does not match"):
        stats(FakeFlask(), certificate=certificate)


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
