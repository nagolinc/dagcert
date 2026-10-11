"""Exercise the real dependency and all task outcomes in the help recipe."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest

from dagcert.runtime import ExternalRaised, ExternalSuccess, ExternalTypeViolation, monitor_external_boundaries


@pytest.fixture
def recipe(monkeypatch):
    pytest.importorskip("pydantic_core")
    root = Path(__file__).parents[1] / "examples" / "structured_llm_output"
    modules = {}
    for name in ("boundary", "app"):
        spec = spec_from_file_location(name, root / f"{name}.py")
        module = module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules["app"], modules["boundary"]


@pytest.mark.parametrize("text,accepted", [
    ('{"title":"A","summary":"B","extra":{"keep":true}}', True),
    ('{"title":"A"}', False),
    ('{"title":42,"summary":"B"}', False),
    ('["A", "B"]', False),
    ('not json', False),
    ('', False),
])
def test_real_validator_classifies_output_and_times_each_attempt(recipe, text, accepted):
    app, _ = recipe
    events = []
    with monitor_external_boundaries(events.append):
        result = app.accept_model_response(app.ModelResponse(text))
    assert isinstance(result, app.PlanReady) == accepted
    if accepted:
        assert result.plan_json == text
    else:
        assert isinstance(result, app.PlanFailed)
    assert len(events) == 1
    assert events[0].elapsed_ms >= 0


@pytest.mark.parametrize("outcome", [
    ExternalSuccess(False),
    ExternalRaised("llm.plan.validate", "RuntimeError", "provider failed"),
    ExternalTypeViolation("llm.plan.validate", "bool", "str", "bad adapter"),
])
def test_non_success_never_becomes_a_plan(recipe, monkeypatch, outcome):
    app, _ = recipe
    monkeypatch.setattr(app, "validate_plan", lambda _text: outcome)
    result = app.accept_model_response(app.ModelResponse('{"title":"A","summary":"B"}'))
    assert isinstance(result, app.PlanFailed)


def test_provider_failure_is_an_explicit_failed_task(recipe, monkeypatch):
    app, boundary = recipe

    def unavailable(_schema):
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(boundary, "SchemaValidator", unavailable)
    assert isinstance(app.accept_model_response(app.ModelResponse("{}")), app.PlanFailed)
