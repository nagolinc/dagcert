from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

class SurfaceError(ValueError): ...

class SurfaceBinding:
    routes: tuple[str, ...]

def stats(
    application: object,
    *,
    certificate: str | Path,
    evidence: str | Path | None = ...,
    route: str = ...,
) -> SurfaceBinding: ...

def banner(
    application: object,
    *,
    script_route: str = ...,
    events_route: str = ...,
    extra_events: Callable[[], Iterable[Mapping[str, object]]] | None = ...,
) -> SurfaceBinding: ...
