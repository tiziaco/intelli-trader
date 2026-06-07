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
"""

from collections.abc import Iterable, Sequence
from typing import Protocol


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
    included) plus the screener half of the legacy
    ``DynamicUniverse.universe`` property: strategy tickers ∪ screener
    tickers, deduplicated.

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
        The deduplicated membership. Order is unspecified (set-derived,
        exactly like the legacy code) — consumers must not rely on it.
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
    return list(set(tickers))
