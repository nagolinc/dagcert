import json
from threading import Event
from time import monotonic

import pytest

from dagcert.promise_events import clear_promise_violations, promise_violations
from dagcert.promises import Promise, PromiseMonitor
from dagcert.runtime import external_boundary, clear_runtime_violations
from dagcert.surfaces import banner
from test_surfaces import FakeFlask


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear_runtime_violations()
    yield
    clear_runtime_violations()


def test_default_logging_persists_and_banner_exposes_exact_failed_promise(tmp_path):
    monitor = PromiseMonitor([Promise('startup.prepared', 'admit', 'prepared', '>=', 4)])
    assert not monitor.observe('admit', {'prepared': 1}, context={'story_id': 's', 'epoch_id': 'e'})
    row = json.loads((tmp_path / '.dagcert/violations.jsonl').read_text())
    assert row['promise_id'] == 'startup.prepared'
    assert row['expected']['bound'] == 4 and row['observed'] == 1
    assert row['story_id'] == 's' and row['epoch_id'] == 'e'
    app = FakeFlask()
    banner(app)
    data = json.loads(app.routes['/dagcert/runtime-events']()[0])
    assert data['violations'] == [row]
    clear_promise_violations()
    assert (tmp_path / '.dagcert/violations.jsonl').exists()


def test_windows_are_separate_for_each_story_and_count_failures(tmp_path):
    monitor = PromiseMonitor([Promise('narration.three', 'narration', 'elapsed_ms', '<=', 218, 3)])
    for story, value in [('a', 79), ('b', 40), ('a', 76), ('b', 40)]:
        assert monitor.observe('narration', {'elapsed_ms': value}, context={'story_id': story})
    assert not monitor.observe('narration', {'elapsed_ms': 84}, context={'story_id': 'a'})
    assert promise_violations()[0]['observed'] == 239


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), True, '12'])
def test_missing_or_invalid_observation_is_a_violation(value):
    monitor = PromiseMonitor([Promise('p', 'event', 'value', '>=', 1)])
    assert not monitor.observe('event', {'value': value})
    assert len(promise_violations()) == 1


def test_hung_work_is_logged_before_completion_and_completion_does_not_duplicate():
    monitor = PromiseMonitor([Promise('slow', 'work', 'elapsed_ms', '<=', 15)])
    deadline = monitor.start('work', context={'turn_id': 4}, invocation_id='a')
    until = monotonic() + 2
    while not promise_violations() and monotonic() < until:
        Event().wait(.01)
    assert len(promise_violations()) == 1
    assert promise_violations()[0]['in_progress'] is True
    deadline.finish()
    assert len(promise_violations()) == 1


def test_success_cancels_live_deadline():
    monitor = PromiseMonitor([Promise('slow', 'work', 'elapsed_ms', '<=', 1000)])
    monitor.start('work', context={}, invocation_id='a').finish()
    assert not promise_violations()


def test_external_failure_is_persistent_without_any_monitor_setup(tmp_path):
    @external_boundary('provider')
    def failing() -> str:
        raise RuntimeError('unavailable')
    failing()
    assert json.loads((tmp_path / '.dagcert/violations.jsonl').read_text())['promise_id'] == 'provider'


def test_persistence_failure_propagates(tmp_path):
    path = tmp_path / 'file'
    path.write_text('not a directory')
    monitor = PromiseMonitor([Promise('p', 'e', 'v', '>=', 1)], directory=path)
    with pytest.raises(OSError):
        monitor.observe('e', {'v': 0})
