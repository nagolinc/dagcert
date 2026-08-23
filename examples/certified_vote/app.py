"""Small in-process vote calculation application with no Dagcert dependency."""


def preview_vote_total(current: int, delta: int) -> int:
    """Return the proposed total without mutating authoritative state."""
    return _add(current, delta)


def commit_vote_total(current: int, delta: int) -> int:
    """Return the authoritative total for this pure in-process application."""
    return _add(current, delta)


def advance_summary_generation(generation: int) -> int:
    """Advance the application's summary-generation counter once."""
    if not isinstance(generation, int):
        raise TypeError("generation must be an integer")
    return generation + 1


def render_vote_snapshot(total: int) -> str:
    """Render the application's complete text snapshot for a vote total."""
    if not isinstance(total, int):
        raise TypeError("total must be an integer")
    return f"votes:{total}"


def _add(current: int, delta: int) -> int:
    if not isinstance(current, int) or not isinstance(delta, int):
        raise TypeError("current and delta must be integers")
    return current + delta
