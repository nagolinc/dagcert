from pathlib import Path


def test_stats_viewer_assets_are_readable_source():
    root = Path(__file__).parents[1] / "examples" / "stats_viewer"
    minimum_lines = {"app.js": 150, "style.css": 250, "sample-data.js": 40}
    for name, minimum in minimum_lines.items():
        lines = (root / name).read_text(encoding="utf-8").splitlines()
        assert len(lines) >= minimum, f"{name} looks minified"
        assert max(map(len, lines)) < 600, f"{name} contains a minified-style line"
    script = (root / "app.js").read_text(encoding="utf-8")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "ok: check.passed === true" in script
    assert "certificate: null" in script
    assert 'timing.metric === "interval"' in script
    assert 'new URLSearchParams(window.location.search).get("task")' in script
    assert 'class="dag-node${t.id === targetedTask ? " is-target" : ""}"' in script
    assert "target.scrollIntoView" in script
    assert 'typeof dependency === "string" ? dependency : dependency?.task' in script
    assert "Throughput &amp; staleness" in html


def test_optional_mithril_helper_is_readable_source():
    path = Path(__file__).parents[1] / "examples" / "optional_mithril_buffered_delta.js"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 80
    assert max(map(len, lines)) < 120


def test_violation_banner_is_a_literal_accessible_component():
    path = (
        Path(__file__).parents[1]
        / "examples" / "violation_banner" / "dagcert-violation-banner.js"
    )
    script = path.read_text(encoding="utf-8")
    lines = script.splitlines()
    assert len(lines) >= 120
    assert max(map(len, lines)) < 120
    assert 'banner.setAttribute("role", "alert")' in script
    assert 'dismiss.textContent = "×"' in script
    assert "dismissedToken === visibleToken" in script
    assert 'url.searchParams.set("task", taskId)' in script
    assert 'url.hash = "graph"' in script
    assert '"View failing task in /stats"' in script
    assert '"View graph in /stats"' in script
    assert '"/dagcert/runtime-events"' in script
