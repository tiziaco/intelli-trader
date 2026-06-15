"""Symbol -> ``Instrument`` resolution — the pure derive-once map (INST-02, D-03/D-07/D-09/D-10).

This module is the single home for symbol -> ``Instrument`` resolution. The
universe already owns the symbol set (``derive_membership``, D-20/D-21), so it is
the natural — and ONLY — home for per-symbol ``Instrument`` resolution (D-03): no
parallel ``InstrumentRegistry`` subsystem. ``derive_instruments`` mirrors
``derive_membership``'s purity exactly — no class, no state, no queue/feed/store
import — it is a pure function producing derived data at wiring time.

The precision ladder (D-09), applied per member symbol:

- **price_precision** = declared -> inferred(guarded, string-read, 8dp cap) -> default
- **quantity_precision** = declared -> default (NOT inferable — D-10)
- **min_order_size** = declared -> ``None`` (D-01a, NOT inferable; ``None`` falls
  through to the venue ``ExchangeLimits`` fallback at the exchange)
- **margin params** (``maintenance_margin_rate`` / ``max_leverage``) = declared ->
  default (inert this phase, consumed in Phase 2/4)
- **settles_funding** = declared -> ``False`` (inert, Phase B deferred)

**Byte-exact guard (D-10, Pitfall 1 — INST-02):** BTCUSD declares 8dp price +
8dp quantity in ``_DECLARED`` and leaves ``min_order_size`` UNDECLARED, exactly
reproducing the deleted ``_INSTRUMENT_SCALES["BTCUSD"]`` entry. Inference is
NEVER invoked on BTCUSD (declared wins) — it would infer ~2dp off the BTCUSD
price column and drift the SMA_MACD oracle. INST-02 inference is covered by a
SYNTHETIC non-oracle symbol fixture only.

**Inference reads the raw CSV STRING (Pitfall 1):** the in-memory frame is
float64 (``csv_store.py:178`` ``.astype(float)``), under which a decimal count is
lost. ``_infer_price_scale`` counts decimal places off the raw price string and
caps at 8 (crypto max), entering the resulting scale via the D-04 string path
(``Decimal("1e-<n>")``).
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from itrader.core.instrument import Instrument
from itrader.universe.membership import SupportsTickers, derive_membership

__all__ = ["derive_instruments"]

# Inference cap (INST-02): crypto venues quote at most 8 decimal places. A raw
# cell with more decimals (float-repr noise, exotic feeds) is clamped to 8dp.
_MAX_PRICE_DP = 8

# D-09 no-data fallbacks. The default price scale mirrors
# ``core.money._DEFAULT_SCALES["price"]`` (2dp); the default quantity scale
# mirrors ``_DEFAULT_SCALES["quantity"]`` (8dp, NOT inferable — D-10).
_DEFAULT_PRICE_SCALE = Decimal("0.01")
_DEFAULT_QUANTITY_SCALE = Decimal("0.00000001")

# Inert margin defaults (INST-03; consumed Phase 2 leverage / Phase 4
# liquidation). Conservative Phase-1 placeholders — present + Decimal-typed so
# every constructed Instrument is strict-clean, unused this phase.
_DEFAULT_MAINTENANCE_MARGIN_RATE = Decimal("0.005")
_DEFAULT_MAX_LEVERAGE = Decimal("1")


class _Declared:
    """A declared per-symbol metadata record (the in-code Phase-1 config home).

    Fields default to ``None`` so an omitted field falls through to the ladder's
    inferred/default rung. ``min_order_size`` omitted (``None``) is the D-01a
    undeclared-fallback signal.
    """

    __slots__ = (
        "price_precision",
        "quantity_precision",
        "min_order_size",
        "maintenance_margin_rate",
        "max_leverage",
        "settles_funding",
    )

    def __init__(
        self,
        *,
        price_precision: Decimal | None = None,
        quantity_precision: Decimal | None = None,
        min_order_size: Decimal | None = None,
        maintenance_margin_rate: Decimal | None = None,
        max_leverage: Decimal | None = None,
        settles_funding: bool | None = None,
    ) -> None:
        self.price_precision = price_precision
        self.quantity_precision = quantity_precision
        self.min_order_size = min_order_size
        self.maintenance_margin_rate = maintenance_margin_rate
        self.max_leverage = max_leverage
        self.settles_funding = settles_funding


# The Phase-1 declared table (OQ1 — small in-code config home, D-03). BTCUSD
# reproduces the deleted ``_INSTRUMENT_SCALES["BTCUSD"]`` 8dp scales EXACTLY and
# leaves ``min_order_size`` UNDECLARED (D-01a) so the exchange falls through to
# ExchangeLimits(0.001) — the oracle-protecting fallback. Inference never runs
# on BTCUSD because it is declared (D-10).
_DECLARED: dict[str, _Declared] = {
    "BTCUSD": _Declared(
        price_precision=Decimal("0.00000001"),
        quantity_precision=Decimal("0.00000001"),
        # min_order_size intentionally OMITTED (D-01a) -> None -> venue fallback.
    ),
}


def _infer_price_scale(raw_cells: Sequence[str]) -> Decimal | None:
    """Infer the price scale from raw CSV price strings (INST-02, Pitfall 1).

    Counts the decimal places after the dot in each RAW string cell (never off
    a float64 frame — float coercion loses the count) and returns the scale for
    the MAX count observed, capped at 8dp (crypto max). Returns ``None`` when no
    usable cell is present so the caller falls through to the default rung.

    Parameters
    ----------
    raw_cells : Sequence[str]
        Raw price-column cells read as strings (pre-float-cast).

    Returns
    -------
    Decimal | None
        ``Decimal("1e-<n>")`` for the inferred decimal count ``n`` (0 < n <= 8),
        or ``None`` when nothing is inferable.
    """
    max_dp = 0
    seen = False
    for cell in raw_cells:
        text = str(cell).strip()
        if "." not in text:
            continue
        seen = True
        decimals = len(text.split(".", 1)[1])
        if decimals > max_dp:
            max_dp = decimals
    if not seen:
        return None
    capped = min(max_dp, _MAX_PRICE_DP)
    if capped <= 0:
        return None
    # D-04 string path — Decimal("1e-<n>") normalized to the explicit scale.
    return Decimal(f"1e-{capped}")


def derive_instruments(
    strategies: Iterable[SupportsTickers],
    screener_tickers: Iterable[str] = (),
    *,
    price_data: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Instrument]:
    """Resolve every member symbol to an ``Instrument`` via the D-09 ladder.

    Pure derive-once-at-wiring sibling of ``derive_membership`` (D-07): no class,
    no state, no queue/feed/store import. Membership is COMPOSED from
    ``derive_membership`` over the same inputs — never reimplemented here.

    For each member symbol the precision ladder (D-09) resolves:
    ``price_precision`` = declared -> inferred(string-read, 8dp cap) -> default
    (2dp); ``quantity_precision`` = declared -> default (8dp, NOT inferable, D-10);
    ``min_order_size`` = declared -> ``None`` (D-01a, NOT inferable); margin
    params = declared -> default; ``settles_funding`` = declared -> ``False``.

    BTCUSD is declared (8dp price + 8dp quantity, min_order_size undeclared) so
    it ALWAYS takes the declared rung — inference is never consulted for it
    (D-10), keeping the oracle byte-exact.

    Parameters
    ----------
    strategies : Iterable[SupportsTickers]
        The registered strategies; each contributes its ``tickers`` (tuple-pair
        legs flattened by ``derive_membership``).
    screener_tickers : Iterable[str]
        The screener universe — empty when no screeners are wired.
    price_data : Mapping[str, Sequence[str]], optional
        Symbol -> raw price-column cells (read as STRINGS pre-float-cast,
        Pitfall 1) used ONLY for price-precision inference on UNDECLARED symbols.
        Absent/empty entries fall through to the default price scale.

    Returns
    -------
    dict[str, Instrument]
        Symbol -> resolved ``Instrument`` for every member symbol.
    """
    price_data = price_data or {}
    members = derive_membership(strategies, screener_tickers)

    instruments: dict[str, Instrument] = {}
    for symbol in members:
        declared = _DECLARED.get(symbol)

        # price_precision: declared -> inferred(guarded) -> default (D-09).
        if declared is not None and declared.price_precision is not None:
            price_scale = declared.price_precision  # declared wins (D-10)
        else:
            inferred = _infer_price_scale(price_data.get(symbol, ()))
            price_scale = inferred if inferred is not None else _DEFAULT_PRICE_SCALE

        # quantity_precision: declared -> default (NOT inferable — D-10).
        if declared is not None and declared.quantity_precision is not None:
            quantity_scale = declared.quantity_precision
        else:
            quantity_scale = _DEFAULT_QUANTITY_SCALE

        # min_order_size: declared -> None (D-01a — NOT inferable).
        min_order_size = declared.min_order_size if declared is not None else None

        # margin params: declared -> default (inert this phase).
        if declared is not None and declared.maintenance_margin_rate is not None:
            maintenance_margin_rate = declared.maintenance_margin_rate
        else:
            maintenance_margin_rate = _DEFAULT_MAINTENANCE_MARGIN_RATE
        if declared is not None and declared.max_leverage is not None:
            max_leverage = declared.max_leverage
        else:
            max_leverage = _DEFAULT_MAX_LEVERAGE
        if declared is not None and declared.settles_funding is not None:
            settles_funding = declared.settles_funding
        else:
            settles_funding = False

        instruments[symbol] = Instrument(
            symbol=symbol,
            price_precision=price_scale,
            quantity_precision=quantity_scale,
            min_order_size=min_order_size,
            maintenance_margin_rate=maintenance_margin_rate,
            max_leverage=max_leverage,
            settles_funding=settles_funding,
        )

    return instruments
