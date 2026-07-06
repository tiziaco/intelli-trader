"""Universe membership — THE universe, as one pure documented function (M5-08, D-20).

This stub IS the universe: a **static symbol set derived once at wiring
time** as the union of every strategy's traded tickers (tuple-pair
flattening included — the pairs-trading shape) and the screener set,
deduplicated. There is no "dynamic" machinery here because the engine has
none: membership never changes mid-run today. The multi-strategy union IS
the membership union (D-21) — adding strategies extends membership with
zero structural change.

Growth target (D-20): when per-tick membership arrives, it grows HERE in
the shape of the LEAN ``UniverseSelectionModel`` — a selection model the
engine polls for adds/removes — driven by the D-screener rebalance loop
(screeners propose, membership disposes). That milestone touches ONLY this
module.

Purity rule: membership is derived data, never event plumbing. BarEvent
production lives in the feed (``itrader.price_handler.feed.bar_feed`` —
the data-engine shape); the future rebalance milestone touches only
membership, never event plumbing.

The per-tick **availability** query — ``is_active`` / ``active_membership``
(UNIV-01) — was added ALONGSIDE ``derive_membership`` (D-03): a separate,
composable span-model primitive answering "what is live at T?" (vs. the
static "what do we track?" the union seam answers).
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable


class SupportsTickers(Protocol):
    """The strategy shape membership reads: a ``tickers`` declaration.

    Single tickers are ``str``; pairs strategies declare ``tuple`` entries
    whose legs are flattened into membership.
    """

    @property
    def tickers(self) -> Sequence[str | tuple[str, ...]]: ...


def derive_membership(
    strategies: Iterable[SupportsTickers],
    screener_tickers: Iterable[str] = (),
) -> list[str]:
    """Derive the tradable symbol membership at wiring time (M5-08, D-20).

    The union logic relocated verbatim from
    ``StrategiesHandler.get_strategies_universe`` (tuple-pair flattening
    included) plus the screener half of the legacy universe union
    property: strategy tickers ∪ screener tickers, deduplicated.

    Parameters
    ----------
    strategies : Iterable[SupportsTickers]
        The registered strategies; each contributes its ``tickers``. A
        ``tuple`` entry (pairs trading) contributes every leg.
    screener_tickers : Iterable[str]
        The screener universe (``ScreenersHandler.get_screeners_universe``)
        — empty when no screeners are wired.

    Returns
    -------
    list[str]
        The deduplicated membership, sorted (WR-05). Sorting at the membership
        boundary makes multi-symbol runs reproducible (``list(set(...))`` order
        varies with ``PYTHONHASHSEED``); a single-symbol universe is its own
        sort, so the byte-exact single-symbol oracle is unaffected. Consumers
        still should treat order as a derived property of this seam, not relied
        on cross-version.
    """
    tickers: list[str] = []
    for strategy in strategies:
        for entry in strategy.tickers:
            # Check if the strategy is trading pairs (tuple-pair flattening).
            if isinstance(entry, tuple):
                tickers.extend(entry)
            else:
                tickers.append(entry)
    tickers.extend(screener_tickers)
    return sorted(set(tickers))


# A span is a half-inclusive-both-ends [first_bar, last_bar] availability
# window (D-01): the ticker's full listed lifespan, internal gap days included.
Span = tuple[datetime, datetime]


def is_active(spans: dict[str, Span], ticker: str, asof: datetime) -> bool:
    """True iff ``ticker`` is live at ``asof`` under the span model (UNIV-01, D-01).

    Pure availability query, added alongside ``derive_membership`` (D-03):
    no class, no state, no queue, no feed/store import — exactly the
    ``derive_membership`` shape, over an injected span-map instead of the
    ``SupportsTickers`` Protocol. It is the per-tick "what is live at T?"
    primitive the feed (Plan 02) and the future v1.3 screener consume.

    Parameters
    ----------
    spans : dict[str, Span]
        Each ticker's ``(first_bar, last_bar)`` availability window, derived
        solely from its loaded data extent (no screening/ranking).
    ticker : str
        The ticker to test.
    asof : datetime
        The time T to test membership at. Must share tz-ness with the span
        bounds (both naive or both tz-aware). A tz-naive/tz-aware mismatch
        is rejected at the boundary with a ``ValueError`` (WR-01) rather
        than allowed to surface as a raw ``TypeError`` deep inside the
        comparison — this primitive is an explicit reusable seam (the
        future v1.3 screener consumes it), so misuse must fail with an
        intelligible message.

    Returns
    -------
    bool
        ``True`` iff ``first_bar <= asof <= last_bar`` (D-01 — inclusive
        BOTH ends, so a mid-life gap day inside the span is still active).
        A ticker absent from ``spans`` returns ``False`` (sparse contract:
        a ticker the store never loaded is simply not a member — mirrors the
        sparse-universe "absent, never None" guard).

    Raises
    ------
    ValueError
        If ``asof`` and the span bounds disagree on tz-ness (one naive, one
        tz-aware). The golden feed path is safe by construction (spans are
        seeded tz-aware from ``frame.index`` and ``asof`` is a tz-aware
        ``pd.Timestamp``); this guard turns a future injection bug into a
        legible failure instead of a raw comparison ``TypeError``.
    """
    span = spans.get(ticker)
    if span is None:
        return False
    first, last = span
    if (first.tzinfo is None) != (asof.tzinfo is None):
        raise ValueError(
            f"is_active tz mismatch for {ticker}: span tz-aware="
            f"{first.tzinfo is not None}, asof tz-aware={asof.tzinfo is not None}"
        )
    return first <= asof <= last


def active_membership(spans: dict[str, Span], asof: datetime) -> set[str]:
    """The set of tickers live at ``asof``, derived solely from spans (UNIV-01, D-01).

    Pure availability — NO screening/ranking. Composes with the static
    ``derive_membership`` selection seam (D-03): the future v1.3 screener
    does ``screen(active_membership(spans, T), ranking)`` ("screeners
    propose, membership disposes").

    Parameters
    ----------
    spans : dict[str, Span]
        Each ticker's ``(first_bar, last_bar)`` availability window.
    asof : datetime
        The time T to query the live set at.

    Returns
    -------
    set[str]
        The tickers live at ``asof``. Returns a ``set`` (NOT a ``list`` like
        ``derive_membership``): the divergence is intentional — availability
        is honestly unordered, and ``set`` composes directly into
        ``screen(active_membership(T), ranking)``. Like ``derive_membership``,
        callers must not rely on order.
    """
    return {t for t in spans if is_active(spans, t, asof)}


# ---------------------------------------------------------------------------
# Lean UniverseSelectionModel — the D-20 growth target (UNIV-01, poll seam)
# ---------------------------------------------------------------------------
#
# This is the D-20 growth target realised: a LEAN "what SHOULD the universe be?"
# selection seam the engine polls for mid-run adds/removes. It grows HERE (the
# module's own growth-target docstring) alongside ``derive_membership`` /
# ``active_membership`` — same purity contract: it holds NO queue and NO feed,
# answering a pure ``select(asof) -> set[str]`` (the poll handler that owns the
# queue + feed + cadence lives elsewhere; selection proposes, the engine
# disposes). The returned ``set`` composes directly into the poll's D-06
# ``validate_symbol`` filter, mirroring ``active_membership``'s set contract.
#
# It is DELIBERATELY NOT the deferred v2 ranked production screener — no ranking,
# no rebalance loop, no scoring. Just the lean poll seam the milestone ships.


@runtime_checkable
class UniverseSelectionModel(Protocol):
    """The lean selection seam: "what SHOULD the universe be at ``asof``?" (UNIV-01).

    A pure/derived Protocol — implementations hold NO queue and NO feed (those
    live on the poll handler host). ``select`` returns a ``set[str]`` (unordered,
    like ``active_membership``) so it composes directly into the poll handler's
    D-06 ``validate_symbol`` filter before ``Universe.apply``.

    This is the D-20 growth target, NOT the deferred v2 ranked production
    screener (no ranking/scoring/rebalance).
    """

    def select(self, asof: datetime) -> set[str]:
        """Return the desired membership set at ``asof``."""
        ...


class StaticUniverseSelectionModel:
    """A lean, operator-driven ``UniverseSelectionModel`` over a fixed symbol set.

    Pure and queue/feed-free by construction: the ctor takes ONLY symbols, so
    there is no seam for a connector/queue/feed. ``select`` ignores ``asof`` and
    returns a COPY of the held set (a defensive copy — callers must not corrupt
    internal state). ``set_symbols`` is the operator/test lever that drives a
    mid-run add/remove (the poll then resolves the delta via ``Universe.apply``).
    """

    def __init__(self, symbols: Iterable[str]) -> None:
        """Hold the desired symbol set (deduplicated into a ``set``).

        Parameters
        ----------
        symbols : Iterable[str]
            The initial desired membership. Deduplicated; order is irrelevant
            (selection is honestly unordered, mirroring ``active_membership``).
        """
        self._symbols: set[str] = set(symbols)

    def select(self, asof: datetime) -> set[str]:
        """Return a COPY of the desired set (``asof``-independent for the static model).

        The ``asof`` parameter satisfies the ``UniverseSelectionModel`` contract
        (a span-model or ranked screener would consult it); the static model is
        time-invariant, so it is accepted and ignored.
        """
        return set(self._symbols)

    def set_symbols(self, symbols: Iterable[str]) -> None:
        """Re-drive the desired set (the mid-run add/remove operator/test lever)."""
        self._symbols = set(symbols)


@runtime_checkable
class SupportsStrategiesUniverse(Protocol):
    """The live strategy-universe source the strategy-derived model reads (D-12).

    Structurally satisfied by ``StrategiesHandler`` — its
    ``get_strategies_universe()`` returns the union of every registered strategy's
    ``tickers`` (the live membership union, recomputed each call). An operator
    ticker edit (Plan 04 mutating a strategy's ``.tickers``) is reflected on the
    NEXT read, so re-reading the source each ``select`` is how the edit propagates.
    """

    def get_strategies_universe(self) -> list[str]: ...


class StrategyDerivedSelectionModel:
    """A ``UniverseSelectionModel`` reading the LIVE strategy set each ``select`` (D-12).

    The operator-seam selection source (OP-SEAM): instead of holding a frozen
    snapshot like ``StaticUniverseSelectionModel``, it re-reads the injected
    ``StrategiesHandler`` (``get_strategies_universe``) on EVERY ``select`` call, so
    an operator ticker edit (Plan 04 mutating a strategy's ``.tickers``, then
    emitting a ``UniversePollEvent``) propagates to membership on the very next
    poll — no stale snapshot, no re-wiring.

    Oracle-safety: this model is LIVE-ONLY (the poll route it feeds is never wired
    on the backtest path — backtest never polls), and the SMA_MACD oracle's tickers
    are construction-fixed, so re-reading them each ``select`` yields the same set.
    The backtest byte-exact path is untouched by construction.

    Pure/queue-free (mirroring ``StaticUniverseSelectionModel``): it holds ONLY the
    source reference, no queue and no feed. ``select`` returns a fresh ``set`` each
    call (unordered, like ``active_membership``) that composes directly into the
    poll handler's D-06 ``validate_symbol`` filter before ``Universe.apply``.
    """

    def __init__(self, source: SupportsStrategiesUniverse) -> None:
        """Hold the live strategy-universe source (the ``StrategiesHandler``).

        Parameters
        ----------
        source : SupportsStrategiesUniverse
            The live strategy set source — its ``get_strategies_universe()`` is
            re-read on every ``select`` so ticker edits propagate (D-12).
        """
        self._source = source

    def select(self, asof: datetime) -> set[str]:
        """Return the CURRENT strategy universe as a ``set`` (read-live each call, D-12).

        Re-reads ``source.get_strategies_universe()`` on every call — NO held
        snapshot — so an operator ticker edit between two ``select`` calls changes
        the result. The ``asof`` parameter satisfies the ``UniverseSelectionModel``
        contract (a span-model or ranked screener would consult it); the
        strategy-derived model is time-invariant with respect to ``asof`` (it tracks
        strategy edits, not calendar time), so it is accepted and ignored.
        """
        return set(self._source.get_strategies_universe())
