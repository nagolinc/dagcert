from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from dagcert.synchronization import Mutex


def test_mutex_preserves_reference_and_releases_after_exception() -> None:
    state = [0]
    guard = Mutex(state)
    assert guard.get_locked() is state
    with pytest.raises(ValueError):
        with guard:
            state[0] = 1
            raise ValueError("task failed")
    with ThreadPoolExecutor(max_workers=1) as pool:
        def read() -> int:
            with guard:
                return guard.get_locked()[0]
        assert pool.submit(read).result(timeout=5) == 1


def test_mutex_excludes_another_worker_until_release() -> None:
    guard = Mutex([0])
    attempted, entered = Event(), Event()

    def work() -> None:
        attempted.set()
        with guard:
            entered.set()
            guard.get_locked()[0] += 1

    with ThreadPoolExecutor(max_workers=1) as pool:
        with guard:
            future = pool.submit(work)
            assert attempted.wait(timeout=5)
            assert not entered.is_set()
        future.result(timeout=5)
    assert entered.is_set()
    assert guard.get_locked() == [1]
