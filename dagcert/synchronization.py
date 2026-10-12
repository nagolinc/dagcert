"""A real mutex with a stable reference to the object whose state it protects.

The proof contract transfers the protected invariant on entry and exit. The
runtime delegates exclusion to threading.Lock; it does not execute proof stubs.
Getting the reference alone does not acquire the mutex.
"""
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar("T")


class Mutex(Generic[T]):
    def __init__(self, value: T) -> None:
        self._value = value
        self._lock = Lock()

    def get_locked(self) -> T:
        return self._value

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        self.release()
