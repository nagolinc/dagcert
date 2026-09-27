"""Application-bound Dagcert status and runtime-warning surfaces."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Protocol, cast

from .certificate import canonical_json, sha256_file
from .evidence import load_evidence
from .runtime import runtime_violations


class SurfaceError(ValueError):
    """A Dagcert application surface could not be bound safely."""


class _FlaskLike(Protocol):
    extensions: dict[str, Any]

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: Callable[..., object] | None = None,
        **options: object,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SurfaceBinding:
    """Routes registered by one Dagcert application surface."""

    routes: tuple[str, ...]


def _app(application: object) -> _FlaskLike:
    if not hasattr(application, "add_url_rule"):
        raise SurfaceError("Dagcert application surfaces currently require a Flask application")
    if not hasattr(application, "extensions"):
        raise SurfaceError("Flask application has no extensions registry")
    return cast(_FlaskLike, application)


def _route(value: str) -> str:
    if not isinstance(value, str) or not value.strip("/"):
        raise SurfaceError("surface route must be a non-root URL path")
    return "/" + value.strip("/")


def _asset(name: str) -> str:
    return files("examples").joinpath("stats_viewer", name).read_text(encoding="utf-8")


def _banner_asset() -> str:
    return files("examples").joinpath(
        "violation_banner", "dagcert-violation-banner.js"
    ).read_text(encoding="utf-8")


def _sha256_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise SurfaceError(f"certificate {name} must be a SHA-256 digest")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise SurfaceError(f"certificate {name} must be a SHA-256 digest") from exc
    if len(decoded) != 32:
        raise SurfaceError(f"certificate {name} must be a SHA-256 digest")
    return value


def _certificate_document(path: str | Path) -> tuple[Path, dict[str, Any]]:
    certificate_path = Path(path).resolve()
    try:
        raw = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurfaceError(f"cannot read Dagcert certificate {certificate_path}: {exc}") from exc
    if not isinstance(raw, dict) or not str(raw.get("schema", "")).startswith(
        "dagcert-certificate/"
    ):
        raise SurfaceError("stats requires a Dagcert certificate document")
    primitives = raw.get("primitives")
    if not isinstance(primitives, dict):
        raise SurfaceError("certificate has no sealed primitives")
    for name in ("workers", "tasks", "resources"):
        if not isinstance(primitives.get(name), list):
            raise SurfaceError(f"certificate primitives.{name} must be an array")
    claimed_digest = raw.get("certificate_sha256")
    unsigned = dict(raw)
    unsigned.pop("certificate_sha256", None)
    actual_digest = sha256(canonical_json(unsigned)).hexdigest()
    if not isinstance(claimed_digest, str) or claimed_digest != actual_digest:
        raise SurfaceError("stats certificate digest does not match its sealed contents")
    for name in ("evidence_sha256", "source_fingerprint"):
        _sha256_digest(raw.get(name), name)
    return certificate_path, raw


def _bound_data(
    certificate_path: Path,
    certificate: dict[str, Any],
    evidence_path: str | Path | None,
) -> dict[str, Any]:
    primitives = cast(dict[str, Any], certificate["primitives"])
    selected_evidence = Path(evidence_path).resolve() if evidence_path is not None else (
        certificate_path.parent / "timings.jsonl"
    )
    if not selected_evidence.is_file():
        supplied = "explicitly supplied" if evidence_path is not None else "default"
        raise SurfaceError(
            f"stats {supplied} evidence file does not exist: {selected_evidence}"
        )
    try:
        actual_evidence_sha256 = sha256_file(selected_evidence)
        samples = load_evidence(selected_evidence)
    except (OSError, ValueError) as exc:
        raise SurfaceError(
            f"cannot read certificate-bound evidence {selected_evidence}: {exc}"
        ) from exc
    sealed_evidence_sha256 = cast(str, certificate["evidence_sha256"])
    if actual_evidence_sha256 != sealed_evidence_sha256:
        raise SurfaceError(
            "stats evidence digest does not match certificate.evidence_sha256: "
            f"expected {sealed_evidence_sha256}, got {actual_evidence_sha256}"
        )
    source_fingerprint = cast(str, certificate["source_fingerprint"])
    mismatched_samples = sorted({
        sample.source_fingerprint
        for sample in samples
        if sample.source_fingerprint != source_fingerprint
    })
    if mismatched_samples:
        raise SurfaceError(
            "stats evidence contains samples from a different source fingerprint: "
            f"certificate={source_fingerprint}, evidence={mismatched_samples}"
        )
    evidence = [sample.to_mapping() for sample in samples]
    return {
        "contract": {
            "schema": "dagcert-contract/bound-certificate",
            "workers": primitives["workers"],
            "tasks": primitives["tasks"],
            "resources": primitives["resources"],
        },
        "evidence": evidence,
        "evidence_binding": {
            "sha256": actual_evidence_sha256,
            "source_fingerprint": source_fingerprint,
            "sample_count": len(evidence),
            "sealed": True,
        },
        "certificate": certificate,
        "runtime_events": {"violation_count": 0, "violations": [], "last_violation": None},
    }


def _dagcert_extension(application: _FlaskLike) -> dict[str, Any]:
    extension = application.extensions.setdefault("dagcert", {})
    if not isinstance(extension, dict):
        raise SurfaceError("Flask app.extensions['dagcert'] is not an object")
    return cast(dict[str, Any], extension)


def stats(
    application: object,
    *,
    certificate: str | Path,
    evidence: str | Path | None = None,
    route: str = "/stats",
) -> SurfaceBinding:
    """Register a certificate-bound Dagcert dashboard on a Flask application."""
    app = _app(application)
    base = _route(route)
    certificate_path, document = _certificate_document(certificate)
    bound = _bound_data(certificate_path, document, evidence)
    contract = cast(dict[str, Any], bound["contract"])
    tasks = cast(list[dict[str, Any]], contract["tasks"])
    task_workers = {
        str(task["id"]): str(task["worker"])
        for task in tasks
        if "id" in task and "worker" in task
    }
    boundary_tasks: dict[str, list[tuple[str, str]]] = {}
    for task in tasks:
        external = task.get("external_contract")
        if not isinstance(external, dict):
            continue
        boundary_id = external.get("boundary_id") or task.get("id")
        if isinstance(boundary_id, str):
            boundary_tasks.setdefault(boundary_id, []).append(
                (str(task["id"]), str(task["worker"]))
            )
    extension = _dagcert_extension(app)
    extension["task_workers"] = task_workers
    extension["external_boundary_tasks"] = boundary_tasks
    extension["certificate_path"] = str(certificate_path)
    extension["evidence_sha256"] = cast(
        dict[str, Any], bound["evidence_binding"]
    )["sha256"]

    index = _asset("index.html")
    index = index.replace("<head>", f'<head>\n    <base href="{base}/" />', 1)
    payload = json.dumps(bound, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    index = index.replace(
        '<script src="sample-data.js"></script>',
        f"<script>window.DAGCERT_BOUND_DATA={payload};</script>\n"
        '<script src="sample-data.js"></script>',
        1,
    )
    assets = {
        "app.js": (_asset("app.js"), "application/javascript; charset=utf-8"),
        "sample-data.js": (_asset("sample-data.js"), "application/javascript; charset=utf-8"),
        "style.css": (_asset("style.css"), "text/css; charset=utf-8"),
    }

    def index_view() -> tuple[str, int, dict[str, str]]:
        return index, 200, {"Content-Type": "text/html; charset=utf-8"}

    def asset_view(asset_name: str) -> tuple[str, int, dict[str, str]]:
        selected = assets.get(asset_name)
        if selected is None:
            return "Not found", 404, {"Content-Type": "text/plain; charset=utf-8"}
        body, content_type = selected
        return body, 200, {"Content-Type": content_type}

    token = str(id(application))
    app.add_url_rule(base, f"dagcert_stats_index_{token}", index_view)
    app.add_url_rule(base + "/", f"dagcert_stats_slash_{token}", index_view)
    app.add_url_rule(base + "/<path:asset_name>", f"dagcert_stats_asset_{token}", asset_view)
    return SurfaceBinding((base, base + "/", base + "/<path:asset_name>"))


def banner(
    application: object,
    *,
    script_route: str = "/dagcert/banner.js",
    events_route: str = "/dagcert/runtime-events",
    extra_events: Callable[[], Iterable[Mapping[str, object]]] | None = None,
) -> SurfaceBinding:
    """Register Dagcert's banner script and retained violation feed."""
    app = _app(application)
    script_path = _route(script_route)
    events_path = _route(events_route)
    extension = _dagcert_extension(app)
    extension["banner_script_route"] = script_path

    def script_view() -> tuple[str, int, dict[str, str]]:
        return _banner_asset(), 200, {
            "Content-Type": "application/javascript; charset=utf-8"
        }

    def events_view() -> tuple[str, int, dict[str, str]]:
        rows: list[dict[str, object]] = []
        task_workers = cast(dict[str, str], _dagcert_extension(app).get("task_workers", {}))
        boundary_tasks = cast(
            dict[str, list[tuple[str, str]]],
            _dagcert_extension(app).get("external_boundary_tasks", {}),
        )
        for event in runtime_violations():
            row = cast(dict[str, object], asdict(event))
            row.update({"violation": True, "passed": False, "active": True})
            if event.boundary_id in task_workers:
                row["task_id"] = event.boundary_id
                row["worker_id"] = task_workers[event.boundary_id]
            elif len(boundary_tasks.get(event.boundary_id, [])) == 1:
                row["task_id"], row["worker_id"] = boundary_tasks[event.boundary_id][0]
            rows.append(row)
        if extra_events is not None:
            rows.extend(dict(event) for event in extra_events())
        payload = {
            "violation_count": len(rows),
            "violations": rows,
            "last_violation": rows[-1] if rows else None,
        }
        return json.dumps(payload, ensure_ascii=False), 200, {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        }

    token = str(id(application))
    app.add_url_rule(script_path, f"dagcert_banner_script_{token}", script_view)
    app.add_url_rule(events_path, f"dagcert_banner_events_{token}", events_view)
    return SurfaceBinding((script_path, events_path))
