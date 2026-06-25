"""Shared recent-bars cache capacity — one pure derive-once function (P5-D16/P5-D22).

This module is the pure derive-once-at-wiring sibling of
``universe/instruments.py::derive_instruments`` and ``universe/membership.py::
derive_membership`` for the **shared recent-bars feed**: given the set of
registered RAW-BAR consumers, derive the cache capacity = the maximum raw-history
depth any consumer requests.

Why capacity keys off RAW-BAR consumers, NOT indicator ``min_period``
--------------------------------------------------------------------
Under Model B (P5-D07) stateful indicators self-buffer — they hold their own
minimal bounded ring and do NOT read the shared cache. So the cache capacity is
NOT driven by indicator warmup/``min_period``; it is driven solely by consumers
that genuinely need RAW multi-bar history (a screener, a raw-history strategy).

Deferral (P5-D16/P5-D22)
------------------------
NO raw-bar consumer exists in this phase. With an empty consumer set the function
returns the **newest-bar-only** capacity (depth 1) — the deep capacity-derived
multi-bar buffer is DEFERRED to the first raw-bar consumer (screener /
raw-history strategy), tracked under
``.planning/todos/deep-shared-bar-history.md``. The INTERFACE ships now so that
consumer extends it with zero structural change.

Purity rule (mirrors ``instruments.py`` :3-8): a pure function producing derived
data at wiring time — no class holding state, no queue/feed/store import, no
parallel registry subsystem. The ladder (``max`` over declared depths) is the
``derive_instruments`` "compose, never reimplement, ladder per member" shape; the
``sorted(set(...))`` newest-first idiom is preserved for the deduped depth view.

Indentation: 4 SPACES (the ``price_handler/feed/`` package convention).
"""

from collections.abc import Iterable
from typing import Protocol

__all__ = ["RawBarConsumer", "NEWEST_BAR_ONLY", "derive", "derive_required_depths"]

#: The newest-bar-only capacity (P5-D16): depth 1 holds just the latest completed
#: bar per symbol. This is the floor capacity — the only one the (current) empty
#: consumer set yields, the deep multi-bar buffer being deferred.
NEWEST_BAR_ONLY = 1


class RawBarConsumer(Protocol):
    """The structural shape the capacity derivation reads off a raw-bar consumer.

    Mirrors ``membership.SupportsTickers``: a minimal structural ``Protocol`` for
    "a raw-bar consumer that declares a required history depth." A consumer that
    needs the last ``N`` raw bars of shared history declares ``N`` here; the
    capacity derivation ladders ``max`` over every registered consumer's declared
    depth.

    There are NO raw-bar consumers in this phase (indicators self-buffer under
    Model B, P5-D07), so this Protocol is the extension point the first
    screener / raw-history strategy implements with zero structural change.
    """

    @property
    def required_history_depth(self) -> int:
        """The number of raw shared bars this consumer needs visible (>= 1)."""
        ...


def derive_required_depths(consumers: Iterable[RawBarConsumer]) -> list[int]:
    """Return the registered consumers' declared depths, sorted/deduped.

    The ``sorted(set(...))`` derive-once idiom (mirrors ``derive_membership``):
    a pure, order-stable, deduplicated view of the distinct raw-history depths the
    registered consumers request. Empty for the (current) empty consumer set.

    Parameters
    ----------
    consumers : Iterable[RawBarConsumer]
        The registered raw-bar consumers; each contributes its
        ``required_history_depth``.

    Returns
    -------
    list[int]
        The distinct declared depths, ascending. Empty when no consumer is
        registered (the deferral case).

    Raises
    ------
    ValueError
        If any consumer declares ``required_history_depth < 1`` (WR-06). The
        contract is ``>= 1``; silently flooring an invalid depth via ``max``
        would mask a real consumer bug (undersized shared cache -> the consumer
        reads missing/stale bars with no error).
    """
    depths: set[int] = set()
    for consumer in consumers:
        d = consumer.required_history_depth
        # WR-06: reject a malformed declaration loudly (matching base.py IN-02),
        # never silently floor it to 1 in derive().
        if d < 1:
            raise ValueError(
                f"raw-bar consumer {consumer!r} declared "
                f"required_history_depth={d} (must be >= 1)")
        depths.add(d)
    return sorted(depths)


def derive(consumers: Iterable[RawBarConsumer] = ()) -> int:
    """Derive the shared recent-bars cache capacity at wiring time (P5-D16/P5-D22).

    Pure derive-once-at-wiring function (no class, no state, no queue/feed/store
    import) mirroring ``derive_membership``'s shape: composes over the registered
    RAW-BAR consumers and ladders (``max``) per consumer to the maximum raw-history
    depth requested. Capacity keys off raw-bar consumers — NOT indicator
    ``min_period`` — because indicators self-buffer under Model B (P5-D07).

    For an EMPTY consumer set (the current phase — no raw-bar consumer exists) the
    capacity is ``NEWEST_BAR_ONLY`` (depth 1): the deep capacity-derived multi-bar
    buffer is DEFERRED to the first raw-bar consumer (tracked to-do). The capacity
    never drops below the newest-bar floor.

    Parameters
    ----------
    consumers : Iterable[RawBarConsumer]
        The registered raw-bar consumers; each declares a
        ``required_history_depth``. Empty (the default) yields the deferred
        newest-bar-only capacity.

    Returns
    -------
    int
        The derived cache capacity: ``max(NEWEST_BAR_ONLY, max(declared depths))``
        — i.e. ``NEWEST_BAR_ONLY`` for the empty set, otherwise the deepest
        declared raw-history depth (never below the newest-bar floor).
    """
    depths = derive_required_depths(consumers)
    # Ladder per consumer (max over declared depths), never below the newest-bar
    # floor: the empty consumer set collapses to NEWEST_BAR_ONLY (the deferral).
    return max(NEWEST_BAR_ONLY, *depths) if depths else NEWEST_BAR_ONLY
