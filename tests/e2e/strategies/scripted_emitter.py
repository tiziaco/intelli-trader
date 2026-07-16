"""Generic date-keyed scripted-emitter strategy (Phase 6, D-01/D-03/D-04).

``ScriptedEmitter`` is the ONE generic, hand-verifiable strategy fixture every
Phase 6-9 matching scenario reuses (D-01) — it generalizes the Phase 4
``SingleMarketBuy`` canary from bar-COUNT keying to bar-DATE keying (D-04) and
parametrizes the action so a single mechanism covers every fill-shape (BUY/SELL,
SL/TP brackets, partial exits) without ~10x near-duplicate strategy classes.

Why date-keying (D-04)
----------------------
The canary fired on ``len(bars) == N``, which couples the firing tick to
``max_window`` and the warmup guard (its docstring had to explain the gotcha).
This emitter instead reads the CURRENT (decision) bar's date — ``bars.index[-1]``
``strftime("%Y-%m-%d")`` — and looks it up in a ``{date: action}`` script. The
VERIFY note then cross-checks trivially against ``bars.csv`` dates, and the firing
no longer depends on the window width. ``max_window`` stays wide (100) only so the
pushed window is never 0-width (an empty window yields no decision bar); warmup
stays 0 so the handler short-circuit never skips a scripted firing tick.

Why ``order_type`` is per INSTANCE (D-03, Pitfall 3)
---------------------------------------------------
A LIMIT/STOP **entry** scenario (MATCH-02/03) selects its entry type by
constructing the emitter with ``order_type=OrderType.LIMIT``/``STOP`` — a
per-INSTANCE fixture knob (NOT scripted per bar). MARKET is the default.

As of Phase 5 (D-01) the per-bar ``SignalIntent`` carries its OWN ``order_type``
+ ``entry_price`` (the per-instance ``Strategy.order_type`` class attr was
retired). This fixture preserves its prior behavior by routing each scripted
intent through the matching typed factory: a LIMIT/STOP emitter rests the entry
at the DECISION-bar close (``self.latest_bar(ticker).close``, P5-D13a) —
value-identical to the legacy ``SignalEvent.price = to_money(decision_bar.close)``
fan-out — so
every existing golden stays byte-exact. Bracket SL/TP **children** get their
STOP/LIMIT types from the bracket assembler regardless of the entry type, so a
MARKET-entry bracket still works.

Script entry shape (Claude's discretion, D-06)::

    {"YYYY-MM-DD": {"side": "BUY" | "SELL",
                    "sl": Decimal | None,
                    "tp": Decimal | None,
                    "exit_fraction": Decimal}}   # exit_fraction optional, default 1

``sl``/``tp`` are explicit Decimal bracket levels (D-15 — used verbatim, the
``sltp_policy`` percent path is Phase 7). ``exit_fraction`` defaults to 1 (full
exit). Indentation: 4 spaces (matches ``tests/conftest.py``).
"""

from decimal import Decimal

from itrader.core.enums.order import OrderType
from itrader.core.sizing import (
    FractionOfCash,
    SignalIntent,
    SizingPolicy,
    SLTPPolicy,
    TradingDirection,
)
from itrader.strategy_handler.base import Strategy


class ScriptedEmitter(Strategy):
    """Emit a scripted ``SignalIntent`` keyed by the current bar's DATE (D-01/D-04).

    Parameters
    ----------
    timeframe : str
        Bar timeframe alias, e.g. ``"1d"``.
    tickers : list[str]
        The tickers the strategy trades.
    script : dict[str, dict]
        ``{"YYYY-MM-DD": {"side", "sl", "tp", "exit_fraction"}}`` — on a decision-bar
        date hit the configured BUY/SELL is emitted; a miss returns ``None``.
    order_type : OrderType
        The per-instance ENTRY order type (D-03, Pitfall 3) — ``MARKET`` (default),
        ``LIMIT`` or ``STOP``. NOT scripted per bar.
    direction : TradingDirection
        Admission direction guard (default ``LONG_ONLY``); widen for SELL-entry
        scenarios.
    sizing_policy : SizingPolicy
        Defaults to ``FractionOfCash(Decimal("0.95"))`` — the same golden sizing
        policy SMA_MACD declares, so entry quantity is hand-derivable.
    """

    name = "scripted_emitter"
    # Wide window so the pushed window is never 0-width (a 0-width window has no
    # decision bar). Under date-keying the width does NOT gate firing; warmup 0
    # keeps the handler short-circuit from skipping a scripted firing tick.
    max_window: int = 100

    def __init__(self, timeframe: str, tickers: list[str], *,
                 script: dict[str, dict],
                 order_type: OrderType = OrderType.MARKET,
                 direction: TradingDirection = TradingDirection.LONG_ONLY,
                 sizing_policy: SizingPolicy | None = None,
                 sltp_policy: "SLTPPolicy | None" = None,
                 allow_increase: bool = False,
                 max_positions: int = 1) -> None:
        # D-01 (Phase 5): order_type is a per-INSTANCE fixture knob — this is HOW
        # MATCH-02/03 select a LIMIT/STOP entry. The per-bar script only picks
        # action + sl/tp/exit_fraction. The retired Strategy.order_type class
        # attr is NO LONGER a base **kwargs param, so stash it on the fixture and
        # pick the matching typed factory in generate_signal (below).
        if sizing_policy is None:
            sizing_policy = FractionOfCash(Decimal("0.95"))
        # D-05 (Plan 02-03): every param threads straight through the base
        # **kwargs surface (no pydantic config layer) — kwarg→setattr→SignalEvent.
        # sltp_policy default None is correct (no engine-side SLTP policy);
        # allow_increase=False / max_positions=1 preserve every existing leaf's
        # behavior. Per-INSTANCE (not per-bar). FractionOfCash(Decimal("0.95"))
        # is the string-path literal (Pitfall 4 — byte-exact).
        super().__init__(
            timeframe=timeframe,
            tickers=list(tickers),
            sizing_policy=sizing_policy,
            direction=direction,
            allow_increase=allow_increase,
            max_positions=max_positions,
            sltp_policy=sltp_policy,
        )
        self.script = script
        self.order_type = order_type

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # P5-D13a: the per-tick self.bars master-frame slice is GONE — the handler
        # drives update(ticker,bar) and the strategy reads the LATEST (decision) bar
        # via self.latest_bar(ticker). A None means no bar seen yet (the old
        # self.bars.empty skip). The decision bar IS the latest pushed bar.
        bar = self.latest_bar(ticker)
        if bar is None:
            return None
        # D-04: key off the CURRENT (decision) bar's date, not len(bars).
        # WR-03: anchor the date key to a FIXED frame (UTC), independent of the
        # project TIMEZONE default, consistent with _make_on_tick in conftest.py.
        # csv_store localizes the bar time to TIMEZONE (Europe/Paris); converting
        # back to UTC here keeps the emitter's date key and the operator hook's key
        # in the same frame so scripted firings and operator actions agree on a
        # boundary-safe date independent of the config default. bar.time is the SAME
        # tz-aware Timestamp the old self.bars.index[-1] carried (byte-identical key).
        decision_date = bar.time.tz_convert("UTC").strftime("%Y-%m-%d")
        action = self.script.get(decision_date)
        if action is None:
            return None
        exit_fraction = action.get("exit_fraction", Decimal("1"))
        is_buy = action["side"] == "BUY"
        sl = action.get("sl")
        tp = action.get("tp")
        # D-01 (Phase 5): pick the typed factory matching the per-instance
        # order_type. MARKET keeps plain buy()/sell() (entry_price None, fills at
        # close). LIMIT/STOP rest the entry at the DECISION-bar close — the same
        # close the legacy fan-out used for SignalEvent.price = to_money(close),
        # so every golden stays byte-exact (Pitfall 1 canary).
        if self.order_type is OrderType.MARKET:
            if is_buy:
                return self.buy(ticker, sl=sl, tp=tp, exit_fraction=exit_fraction)
            return self.sell(ticker, sl=sl, tp=tp, exit_fraction=exit_fraction)
        # P5-D13a: the LIMIT/STOP entry rests at the DECISION-bar close — read it
        # from the latest pushed bar (bar.close, a Decimal), the SAME value the old
        # self.bars["close"].iloc[-1] carried (byte-identical resting price).
        entry = bar.close
        if self.order_type is OrderType.LIMIT:
            if is_buy:
                return self.buy_limit(ticker, price=entry, sl=sl, tp=tp,
                                      exit_fraction=exit_fraction)
            return self.sell_limit(ticker, price=entry, sl=sl, tp=tp,
                                   exit_fraction=exit_fraction)
        if is_buy:
            return self.buy_stop(ticker, price=entry, sl=sl, tp=tp,
                                 exit_fraction=exit_fraction)
        return self.sell_stop(ticker, price=entry, sl=sl, tp=tp,
                              exit_fraction=exit_fraction)
