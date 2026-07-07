"""
Universe-domain enums for the iTrader system (D-02).

Home of the ``Readiness`` tri-state that a dynamic-universe entry moves
through as its warmup bars load: ``PENDING`` (added, no bars yet) ->
``READY`` (warmup satisfied, tradeable) or ``FAILED`` (backfill errored).
The per-symbol readiness gate (WR-02) keys strategy admission on this
member so a freshly-added ticker cannot trade before its history exists.

Unlike the event/side enums this carries NO ``_missing_`` string parser:
``Readiness`` never enters from an external string (it is set engine-side
only), so the plain three-member ``Enum`` (the ``Side`` shape) is enough.
"""

from enum import Enum


class Readiness(Enum):
    """Warmup readiness of a dynamic-universe entry (D-02).

    Members are explicit UPPERCASE strings, matching the house enum
    convention (``Side``/``ErrorSeverity``). No code relies on ``.value``
    being an int, so string values are safe and clearer.
    """
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"
