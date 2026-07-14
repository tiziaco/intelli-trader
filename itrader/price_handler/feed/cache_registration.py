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
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "RawBarConsumer",
    "NEWEST_BAR_ONLY",
    "derive",
    "derive_required_depths",
    "StrategyWarmupConsumer",
    "derive_warmup_depth",
    "register_strategy_warmup",
]

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


# CACHE-CLASS: (a-infra) shared-bar-cache capacity (wiring-time) — see docs/CACHE-CLASSIFICATION.md
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


# -- Strategy warmup: a SEPARATE concern coexisting with the derive() ladder ----
#
# The symbols above (``derive`` / ``derive_required_depths``) are the RAW-HISTORY
# ladder: capacity keys off raw-bar consumers because indicators self-buffer under
# Model B (P5-D07). The symbols below are the STRATEGY-WARMUP concern (RUN-07/D-17):
# a raw-bar consumer sized to the max strategy warmup so the LIVE feed's ring warms
# the indicators. They are named distinctly (``derive_warmup_depth``, NOT ``derive``)
# so the two concerns are NOT conflated (RESEARCH Landmine 4).


class _SupportsWarmup(Protocol):
    """The minimal structural shape ``derive_warmup_depth`` reads off a strategy."""

    @property
    def warmup(self) -> int:
        """The number of bars this strategy needs before its indicators warm."""
        ...


class _SupportsRawBarConsumerRegistration(Protocol):
    """The minimal structural shape ``register_strategy_warmup`` needs off a feed.

    Only ``register_raw_bar_consumer`` is required — matching the loose-typing
    convention of this module (a consumer only needs to be appended; the feed's
    ``cache_capacity()`` re-derives from all registered consumers at call time).
    """

    def register_raw_bar_consumer(self, consumer: RawBarConsumer) -> None:
        ...


@dataclass(frozen=True)
class StrategyWarmupConsumer:
    """Raw-bar consumer that sizes ``LiveBarFeed.cache_capacity()`` to the warmup.

    A minimal frozen ``RawBarConsumer`` (declares ``required_history_depth``, so it
    structurally implements the ``RawBarConsumer`` Protocol above and coexists with
    the ``derive()`` ladder by construction) registered on the LIVE feed so the ring
    + warmup derive to the max strategy warmup (100 for SMA_MACD), not the
    newest-bar floor (1). Without it the indicators never warm and
    ``calculate_signals`` short-circuits to zero trades — the single most likely
    correctness failure of the live path (RESEARCH Pitfall 1).

    ONE global ring (a single scalar ``required_history_depth``): per-symbol ring
    sizing + the K-computation stay DEFERRED (D-17). CF-10 generalizes only the
    depth via ``derive_warmup_depth`` (below), not this consumer's shape.
    """

    required_history_depth: int


def derive_warmup_depth(strategies: Iterable[_SupportsWarmup]) -> int:
    """Derive the strategy-warmup ring depth — the NAMED, replaceable D-17 seam.

    Today returns the GLOBAL ``max((s.warmup for s in strategies), default=1)`` —
    the exact expression extracted from the old inline registration
    (``live_trading_system.py``). This is the CF-10 depth boundary: CF-10 later
    generalizes ONLY this function body — from the global ``max(warmup)`` to a
    per-concerned-strategy ``max(warmup for strategies concerned with symbol)``
    (the K-computation + per-symbol rings stay deferred) — WITHOUT re-touching the
    registration wiring below or ``SessionInitializer`` (which calls
    ``register_strategy_warmup``, never this function directly).

    Named distinctly from ``derive`` (RESEARCH Landmine 4): ``derive`` is the
    raw-history ladder (capacity keys off raw-bar consumers); this is the separate
    strategy-warmup concern coexisting in the same file.

    Parameters
    ----------
    strategies : Iterable[_SupportsWarmup]
        The registered strategies; each contributes its ``warmup``.

    Returns
    -------
    int
        The global maximum warmup depth, or ``1`` for an empty strategy set.
    """
    return max((s.warmup for s in strategies), default=1)


def register_strategy_warmup(
    feed: _SupportsRawBarConsumerRegistration,
    strategies: Iterable[_SupportsWarmup],
) -> None:
    """Register a warmup consumer sized to the strategies' warmup on ``feed``.

    The reusable registration entry point (D-17) — called by ``SessionInitializer``
    (06-04), replacing the inline registration in ``live_trading_system.py``.
    Computes the depth via the named ``derive_warmup_depth`` boundary, then
    registers a ``StrategyWarmupConsumer`` so ``feed.cache_capacity()`` re-derives
    the ring to the max strategy warmup at call time (``base.py`` reads
    ``derive(self._raw_bar_consumers)`` lazily, so registering IS what sizes it).

    Parameters
    ----------
    feed : _SupportsRawBarConsumerRegistration
        The feed to register on (needs only ``register_raw_bar_consumer``).
    strategies : Iterable[_SupportsWarmup]
        The strategies whose max ``warmup`` sizes the ring.
    """
    depth = derive_warmup_depth(strategies)
    feed.register_raw_bar_consumer(
        StrategyWarmupConsumer(required_history_depth=depth))
