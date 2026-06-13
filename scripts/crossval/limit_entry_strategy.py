"""Crafted minimal deterministic LIMIT-entry strategy (D-07, Phase 5).

This is the strategy under cross-validation for the NEW owner-signed LIMIT-entry
golden (D-07). It is intentionally NOT ``SMA_MACD``: a declared-indicator MACD
strategy is too fiddly to replicate identically across three engines, so this
minimal date-keyed emitter isolates the genuinely-research-worthy mechanic — a
strategy authors a per-intent ``buy_limit`` (SIG-01/SIG-02), the limit RESTS and
fills on a LATER bar at the ``min(open, limit)`` price, and that entry fill
ANCHORS a percent SL/TP bracket (RECON-01 entry-fill -> bracket sequence).

The fill-price algebra agrees across iTrader / backtesting.py / backtrader BY
CONSTRUCTION: a BUY limit fills at ``min(open, limit)`` (limit-or-better) and a
bracket SL/TP is anchored at the entry fill. iTrader's ``MatchingEngine._evaluate``
(limit-or-better -> in-bar touch fills AT the limit; favorable gap fills at the
better open) == backtesting.py ``_process_orders`` (``min(open, limit)``) ==
backtrader ``buy_bracket(exectype=bt.Order.Limit)``.

Determinism (D-07 / T-05-17): the strategy is a pure date-keyed lookup — no wall
clock, no RNG, no per-call randomness — so a double run is byte-identical.

The scenario (a small pinned window of the REAL ``data/BTCUSD_1d_ohlcv_2018_2026``
golden CSV, chosen so every fill is hand-derivable) exercises BOTH required cases:

* **Resting limit, fills on a LATER bar (not immediate).** Decision 2018-09-02
  (close 7302.01): ``buy_limit`` at ``close * 0.98`` = 7155.9698. The two
  following bars (09-03, 09-04) do NOT touch (their lows stay above the trigger);
  09-05 dips (low 6682.0 <= 7155.9698) so the limit fills AT the trigger on
  2018-09-05 — three bars after the decision. That entry anchors a percent SL/TP
  bracket (``sl_pct``/``tp_pct`` below).

* **Marketable limit, fills at the bar OPEN (open vs limit pinned).** A second
  decision places a ``buy_limit`` whose trigger sits ABOVE the next bar's open, so
  ``open <= trigger`` -> the limit gaps through and fills at the (better) OPEN, not
  at the limit. This pins the open-vs-limit fill price across all three engines.

Money policy (CLAUDE.md): every price enters the Decimal domain via ``to_money``
(``buy_limit(price=...)`` calls ``to_money`` inside the factory) — never the
binary-float ``Decimal``-on-a-float path (use the string path instead).

SCRIPT-ONLY shared module: imported by the cross-val runners (``scripts/crossval/
cross_validate_limit`` path) AND by the e2e leaf (``tests/e2e/matching/entries/
limit_entry_crossval/scenario.py``). It imports ONLY ``itrader`` (no cross-val
engine), so re-using it under ``tests/`` is safe (D-10: only the backtesting.py /
backtrader RUNNERS are script-only, never this strategy).

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

from decimal import Decimal

from itrader.core.sizing import (
    FractionOfCash,
    SignalIntent,
    TradingDirection,
)
from itrader.strategy_handler.base import Strategy

# --- Crafted scenario parameters (single source of truth) -------------------
# Shared by the iTrader strategy AND the two cross-val engine runners so the
# offset / cadence / SL-TP / marketable-limit bar cannot drift between engines.

#: BUY-limit offset below the decision-bar close (D-07: e.g. close * 0.98).
LIMIT_OFFSET = Decimal("0.98")
#: Percent stop-loss / take-profit below/above the ENTRY FILL price.
SL_PCT = Decimal("0.95")  # stop-loss at fill * 0.95 (5% below)
TP_PCT = Decimal("1.15")  # take-profit at fill * 1.15 (15% above)
#: A multiplier ABOVE the decision-bar close for the MARKETABLE-limit case —
#: places the buy-limit above market so the next bar's open is below it and the
#: order gaps through, filling at the (better) OPEN.
MARKETABLE_MULT = Decimal("1.05")

#: Date-keyed script: each entry is a decision-bar date -> the kind of buy-limit.
#:   "resting"     -> buy_limit at close * LIMIT_OFFSET (rests, fills on a later bar)
#:   "marketable"  -> buy_limit at close * MARKETABLE_MULT (above market, fills at open)
#: Both anchor a percent SL/TP bracket from the entry fill. The two decisions are
#: spaced so the first round-trip closes (TP or SL) before the second opens
#: (single-position, LONG-only — no overlapping brackets to hand-trace).
SCRIPT: dict[str, str] = {
    "2018-09-02": "resting",
    "2018-09-13": "marketable",
}


class LimitEntryStrategy(Strategy):
    """Emit a crafted ``buy_limit`` keyed by the decision bar's DATE (D-07).

    A single-position LONG-only emitter: on a scripted decision-bar date it
    authors a ``buy_limit`` (resting BELOW market or MARKETABLE above market) with
    a percent SL/TP bracket anchored at the eventual entry fill. Every other tick
    returns ``None``. Pure date lookup -> deterministic / double-run identical.

    Parameters
    ----------
    timeframe : str
        Bar timeframe alias, e.g. ``"1d"``.
    tickers : list[str]
        The tickers the strategy trades (the scenario subscribes exactly one).
    """

    name = "limit_entry_crossval"
    # Wide window so the pushed window is never 0-width (date-keying does not gate
    # on width); warmup stays 0 so the handler short-circuit never skips a
    # scripted firing tick (mirrors ScriptedEmitter / SingleMarketBuy).
    max_window: int = 100

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        # FractionOfCash(Decimal("0.95")) is the golden sizing policy SMA_MACD
        # declares (string-path literal) — so the entry quantity is hand-derivable
        # (0.95 * available_cash / entry_price). LONG-only, single position.
        super().__init__(
            timeframe=timeframe,
            tickers=list(tickers),
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
            max_positions=1,
        )

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # evaluate() stashed the look-ahead-safe completed-bar window on
        # self.bars; this strategy registers no indicators so the repopulate loop
        # is a no-op. Key off the CURRENT (decision) bar's date in UTC — the same
        # fixed frame ScriptedEmitter uses (csv_store localizes to Europe/Paris;
        # tz_convert("UTC") keeps the date key boundary-safe and independent of the
        # Settings.timezone default).
        if self.bars.empty:
            return None
        decision_date = self.bars.index[-1].tz_convert("UTC").strftime("%Y-%m-%d")
        kind = SCRIPT.get(decision_date)
        if kind is None:
            return None
        close = Decimal(str(self.bars["close"].iloc[-1]))
        if kind == "resting":
            trigger = close * LIMIT_OFFSET
        else:  # marketable: place the buy-limit ABOVE market -> fills at open
            trigger = close * MARKETABLE_MULT
        # Percent SL/TP anchored at the limit trigger (the engine re-anchors the
        # bracket children at the actual entry FILL; the percent levels track the
        # fill). Money enters the Decimal domain via the buy_limit factory's
        # to_money — passing Decimal/str values here keeps it on the safe string
        # path (never the binary-float repr artifact).
        sl = trigger * SL_PCT
        tp = trigger * TP_PCT
        return self.buy_limit(ticker, price=trigger, sl=sl, tp=tp)
