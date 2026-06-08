"""Optional NON-GATING Nautilus Trader force-match reference module (08-06, D-12).

The THIRD cross-validation reference engine. Nautilus is the closest
architectural mirror to iTrader (event-driven, real order/fill lifecycle,
realistic matching engine), so where it runs it can catch event-semantics bugs
the vectorized backtesting.py / hybrid backtrader cannot. But it is explicitly
NON-GATING (D-12): the two gating engines (backtesting.py + backtrader, 08-05)
fully cover the D-04 cross-validation. Nautilus is evidence-only and must NEVER
be able to stall the definition-of-done freeze (08-07 reconcile / 08-09 freeze).

DEGRADE-SAFE CONTRACT (the D-12 non-gating guarantee):
  * `run_nautilus(...)` wraps ALL Nautilus work (import + config + run) in a
    single top-level try/except and NEVER raises. On ANY failure (missing
    install, config error, API-shape mismatch) it returns a degraded
    `CrossvalResult(reconciled=False, reason="Nautilus: not reconciled — ...")`.
  * The guarded `import nautilus_trader` happens INSIDE the function body (NOT at
    module scope) so this module ALWAYS imports even when nautilus-trader is
    absent.

OWNER-DIRECTED DEVIATION (supersedes 08-04 D-12 drop): the project owner
directed installing `nautilus-trader==1.227.0` by narrowing the repo's python
constraint from `^3.13` (→ `>=3.13,<4.0`, which has no `<3.15` ceiling and so
failed nautilus's `requires_python <3.15,>=3.12`) to `>=3.13,<3.14` — now a
subset of `[3.12,3.15)`, so the 08-04 version-solve rejection disappears. This
module therefore now completes the REAL low-level `BacktestEngine` force-match
(below) instead of the prior clean-degrade scaffold. The degrade path remains
intact as the D-12 safety net (any config/API/runtime failure still degrades
rather than raising), so the freeze stays protected — but on this interpreter
the engine reconciles a real result.

UNIFORM ORCHESTRATOR CONTRACT (consumed by 08-07 exactly like the gating engines):
  * `run(prices=None, indicators=None) -> (trade_log_df, equity_series)` calls
    `run_nautilus`; if it reconciles, returns the (trade_log, equity_curve);
    otherwise RAISES `RuntimeError(reason)` — that raise IS the degrade signal
    08-07 catches in its uniform per-engine try-guard. `run_nautilus` itself
    never raises; only this thin wrapper does.

SCRIPT-ONLY (D-10): never import this module (or nautilus_trader) under `tests/`
or in `itrader/` — keep it on the script path only so the repo's
`filterwarnings=["error"]` test contract stays intact.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from scripts.crossval.indicators import (
    MIN_BARS,
    compute_indicators,
    load_golden_with_indicators,
)

CASH = 10_000.0
FRACTION = 0.95

# Nautilus next-bar-open fills: bar T closes and becomes available for execution
# at its CLOSE timestamp, the matching engine then fills market orders at the
# NEXT bar's open. The golden CSV stamps each bar at its OPEN (midnight UTC), so
# we shift ts_init forward one full day (86_400 s in ns) to the bar close —
# getting this wrong fakes a 1-bar divergence (08-RESEARCH-AGENT.md §2).
_TS_INIT_DELTA_NS = 86_400_000_000_000


@dataclass
class CrossvalResult:
    """Small result container the 08-07 orchestrator reads (keep names stable).

    `reconciled` is True only when the engine ran end-to-end. When False,
    `reason` carries the human-readable degrade cause (always prefixed
    "Nautilus: not reconciled — ...") and the trade_log / equity_curve are None.
    """

    engine: str
    reconciled: bool
    reason: str | None
    trade_log: "pd.DataFrame | None"
    equity_curve: "pd.Series | None"


def _load_golden_ohlcv() -> pd.DataFrame:
    """Load the windowed golden bar+indicator frame for the standalone/fallback path.

    Reuses `scripts.crossval.indicators.load_golden_with_indicators` so the
    window (2018-01-01 → 2026-06-03) and the Binance-CSV normalization stay in
    lockstep with the gating engines and the oracle generator — no drift.
    """
    return load_golden_with_indicators()


def _indicators(ohlcv, short_sma, long_sma, macd_hist) -> pd.DataFrame:
    """Resolve the injected SMA/MACD arrays, computing inline via `ta` if absent.

    When all three series are supplied (the 08-07 orchestrator path) they are
    used as-is so every engine consumes the IDENTICAL arrays (D-03). When any is
    None (standalone path) they are computed via iTrader's exact `ta` calls
    through `compute_indicators` — the module is self-sufficient and does NOT
    hard-import 08-05's shared helper beyond the engine-agnostic precompute.
    """
    if short_sma is not None and long_sma is not None and macd_hist is not None:
        return pd.DataFrame(
            {
                "sma_short": pd.Series(short_sma).to_numpy(),
                "sma_long": pd.Series(long_sma).to_numpy(),
                "macd_hist": pd.Series(macd_hist).to_numpy(),
            },
            index=pd.DatetimeIndex(ohlcv.index),
        )
    # Compute inline from the close series via iTrader's exact ta calls.
    return compute_indicators(ohlcv["close"])


def _build_zero_fee_btcusd():
    """Construct a zero-fee BTCUSD `CurrencyPair` for the D-01 force-match.

    Mirrors `TestInstrumentProvider.btcusdt_binance()` but with USD as the quote
    currency (to match the $10k USD cash) and `maker_fee=taker_fee=Decimal("0")`
    (D-01 zero fees). `size_precision=6` gives fractional-BTC 95%-of-equity
    sizing; `price_precision=2` and a $10M `max_price` cover BTC's range over the
    2018→2026 window. `min_notional=None` so no trade is rejected for being small.
    """
    from nautilus_trader.model.currencies import BTC, USD
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.model.objects import Money, Price, Quantity

    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol("BTCUSD"), venue=Venue("SIM")),
        raw_symbol=Symbol("BTCUSD"),
        base_currency=BTC,
        quote_currency=USD,
        price_precision=2,
        size_precision=6,
        price_increment=Price(1e-02, precision=2),
        size_increment=Quantity(1e-06, precision=6),
        lot_size=None,
        max_quantity=Quantity(9000, precision=6),
        min_quantity=Quantity(1e-06, precision=6),
        max_notional=None,
        min_notional=None,
        max_price=Price(10_000_000, precision=2),
        min_price=Price(0.01, precision=2),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
    )


def _make_strategy_class():
    """Build the SMA_MACD force-match Strategy class against the installed API.

    Defined inside the guard (imports nautilus only when the package is present)
    so module import never depends on nautilus_trader. The strategy consumes the
    INJECTED `ta` arrays (NOT Nautilus-native indicators, D-03) via a
    timestamp-keyed lookup, replicating the filter-gates-both-entry-AND-exit
    quirk verbatim, sizing 95% of free balance, long-only, single-position.
    """
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.trading.strategy import Strategy

    class SMAMACDNautilus(Strategy):
        def __init__(self, config=None):
            super().__init__(config)
            self.instrument = None
            self.venue = None
            self.bar_type = None
            # Injected indicator lookup keyed by bar OPEN timestamp (ns).
            self.sma_short_by_ts: dict[int, float] = {}
            self.sma_long_by_ts: dict[int, float] = {}
            self.macd_hist_by_ts: dict[int, float] = {}
            self._prev_macd: float | None = None
            self._bar_count = 0
            self.trades_log: list[dict] = []
            self.equity_dates: list[pd.Timestamp] = []
            self.equity_values: list[float] = []
            # Open-trade tracker for per-trade pnl assembly.
            self._open_entry_ts = None
            self._open_entry_price = None
            self._open_qty = None

        def configure(self, instrument, bar_type, indicators):
            self.instrument = instrument
            self.venue = instrument.id.venue
            self.bar_type = bar_type
            ts = indicators.index.view("int64")
            for i, key in enumerate(ts):
                self.sma_short_by_ts[int(key)] = float(indicators["sma_short"].iloc[i])
                self.sma_long_by_ts[int(key)] = float(indicators["sma_long"].iloc[i])
                self.macd_hist_by_ts[int(key)] = float(indicators["macd_hist"].iloc[i])

        def on_start(self):
            self.subscribe_bars(self.bar_type)

        def _free_usd(self) -> float:
            from nautilus_trader.model.currencies import USD

            account = self.portfolio.account(self.venue)
            if account is None:
                return 0.0
            free = account.balance_free(USD)
            return 0.0 if free is None else float(free.as_double())

        def on_bar(self, bar):
            ts_open = bar.ts_event  # bar open timestamp (ns)
            bar_dt = pd.Timestamp(ts_open, tz="UTC")
            # Per-bar equity = free USD + mark-to-market value of any open BTC
            # position at this bar's close (robust across account-config nuances;
            # the zero-fee CASH account holds USD free + BTC position).
            free = self._free_usd()
            pos_value = 0.0
            if self._open_qty is not None:
                pos_value = float(self._open_qty) * float(bar.close.as_double())
            self.equity_dates.append(bar_dt)
            self.equity_values.append(free + pos_value)

            self._bar_count += 1
            macd = self.macd_hist_by_ts.get(int(ts_open))
            sma_s = self.sma_short_by_ts.get(int(ts_open))
            sma_l = self.sma_long_by_ts.get(int(ts_open))

            prev_macd = self._prev_macd
            # Advance the prev-macd window AFTER reading it (needs [-2] vs [-1]).
            self._prev_macd = macd

            # Warm-up gate: mirror the strategy's len(bars) < max_window guard.
            if self._bar_count < MIN_BARS:
                return
            if macd is None or sma_s is None or sma_l is None or prev_macd is None:
                return

            in_position = self._open_qty is not None
            # THE QUIRK — SMA filter gates BOTH entry and exit; exit is the
            # nested elif inside the filter block. Filter False → held long is
            # NOT closed on a MACD down-cross.
            if sma_s >= sma_l:  # Filter
                if (macd >= 0) and (prev_macd < 0):  # Buy trigger
                    if not in_position:
                        self._submit_entry(bar)
                elif (macd <= 0) and (prev_macd > 0):  # Sell trigger
                    if in_position:
                        self._submit_exit()

        def _submit_entry(self, bar):
            free = self._free_usd()
            price = float(bar.close.as_double())
            if price <= 0 or free <= 0:
                return
            raw_qty = FRACTION * free / price
            qty = self.instrument.make_qty(raw_qty)
            if float(qty) <= 0:
                return
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.BUY,
                quantity=qty,
            )
            self.submit_order(order)

        def _submit_exit(self):
            if self._open_qty is None:
                return
            qty = self.instrument.make_qty(self._open_qty)
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.SELL,
                quantity=qty,
            )
            self.submit_order(order)

        def on_position_opened(self, event):
            self._open_entry_ts = pd.Timestamp(event.ts_opened, tz="UTC")
            self._open_entry_price = float(event.avg_px_open)
            self._open_qty = float(event.quantity)

        def on_position_closed(self, event):
            self.trades_log.append(
                {
                    "entry_date": pd.Timestamp(event.ts_opened, tz="UTC"),
                    "exit_date": pd.Timestamp(event.ts_closed, tz="UTC"),
                    "side": "LONG",
                    "realised_pnl": float(event.realized_pnl)
                    if event.realized_pnl is not None
                    else 0.0,
                }
            )
            self._open_entry_ts = None
            self._open_entry_price = None
            self._open_qty = None

    return SMAMACDNautilus


def run_nautilus(
    ohlcv: "pd.DataFrame | None" = None,
    short_sma: "pd.Series | None" = None,
    long_sma: "pd.Series | None" = None,
    macd_hist: "pd.Series | None" = None,
) -> CrossvalResult:
    """Degrade-safe Nautilus force-match — NEVER raises (D-12 non-gating).

    Wraps ALL Nautilus work in a single top-level try-guard. The guarded
    `import nautilus_trader` lives INSIDE the body so this module imports even
    when the package is absent. On ANY exception returns a degraded
    CrossvalResult with `reconciled=False` and a "Nautilus: not reconciled — ..."
    reason; it never re-raises.
    """
    try:
        # --- Resolve the golden frame + injected indicator arrays -----------
        if ohlcv is None:
            ohlcv = _load_golden_ohlcv()
        indicators = _indicators(ohlcv, short_sma, long_sma, macd_hist)

        # --- Guarded Nautilus imports (INSIDE the body, never module scope) -
        # Owner-directed deviation (supersedes 08-04 D-12): nautilus-trader is
        # now installed (python narrowed to >=3.13,<3.14). The low-level
        # BacktestEngine force-match below runs the real reconciled result; any
        # failure still degrades via the outer except (D-12 safety net intact).
        from nautilus_trader.backtest.engine import (  # noqa: F401
            BacktestEngine,
            BacktestEngineConfig,
        )
        from nautilus_trader.config import LoggingConfig
        from nautilus_trader.model.currencies import USD
        from nautilus_trader.model.data import BarType
        from nautilus_trader.model.enums import (
            AccountType,
            BookType,
            OmsType,
        )
        from nautilus_trader.model.identifiers import Venue
        from nautilus_trader.model.objects import Money
        from nautilus_trader.persistence.wranglers import BarDataWrangler

        venue = Venue("SIM")
        instrument = _build_zero_fee_btcusd()

        # Bar type: 1-DAY LAST EXTERNAL on the SIM BTCUSD instrument.
        bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")

        # --- Wrangle the golden OHLCV into Nautilus Bars --------------------
        # The wrangler wants lowercase open/high/low/close/volume on a
        # DatetimeIndex. ts_init is shifted forward one full day to the bar
        # CLOSE so the bar becomes executable at close and market orders fill at
        # the NEXT bar's open (D-01 next-bar-open fills).
        feed = pd.DataFrame(
            {
                "open": ohlcv["open"].to_numpy(),
                "high": ohlcv["high"].to_numpy(),
                "low": ohlcv["low"].to_numpy(),
                "close": ohlcv["close"].to_numpy(),
                "volume": ohlcv["volume"].to_numpy(),
            },
            index=pd.DatetimeIndex(ohlcv.index),
        )
        wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)
        bars = wrangler.process(feed, ts_init_delta=_TS_INIT_DELTA_NS)

        # --- Build the engine (zero fees via zero-fee instrument; no slippage)
        engine = BacktestEngine(
            config=BacktestEngineConfig(
                trader_id="CROSSVAL-001",
                logging=LoggingConfig(bypass_logging=True),
            )
        )
        # No base_currency → a MULTI-currency CASH account that can hold both
        # USD (quote) and BTC (the bought base asset). A single-currency CASH
        # account (base_currency=USD) rejects a BTC/USD spot pair.
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(CASH, USD)],
            book_type=BookType.L1_MBP,  # required for bar-based execution
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)

        # --- Strategy consuming the INJECTED ta arrays (D-03) ---------------
        strategy_cls = _make_strategy_class()
        strategy = strategy_cls()
        # Align indicators to the bar OPEN timestamps used by the strategy's
        # lookup. ohlcv.index is the bar OPEN; indicators share that index.
        strategy.configure(instrument, bar_type, indicators)
        engine.add_strategy(strategy)

        engine.run()

        # --- Extract the reconciled result ----------------------------------
        trade_log = pd.DataFrame(
            strategy.trades_log,
            columns=["entry_date", "exit_date", "side", "realised_pnl"],
        )
        equity_curve = pd.Series(
            strategy.equity_values,
            index=pd.DatetimeIndex(strategy.equity_dates),
            name="equity",
        )
        engine.dispose()

        return CrossvalResult(
            engine="nautilus",
            reconciled=True,
            reason=None,
            trade_log=trade_log,
            equity_curve=equity_curve,
        )

    except Exception as exc:  # noqa: BLE001 — D-12: degrade on ANY failure
        return CrossvalResult(
            engine="nautilus",
            reconciled=False,
            reason=f"Nautilus: not reconciled — {exc}",
            trade_log=None,
            equity_curve=None,
        )


def run(prices=None, indicators=None):
    """Uniform orchestrator entry — same shape as the gating engines (08-05).

    Maps `prices`/`indicators` into `run_nautilus`'s params and, if it
    reconciles, returns `(trade_log_df, equity_series)`. If degraded, RAISES
    `RuntimeError(reason)` so 08-07's uniform per-engine try-guard records the
    "Nautilus: not reconciled — {reason}" status (D-12). `run_nautilus` itself
    never raises — only this thin wrapper does, to feed the orchestrator's
    try-guard the same shape across all three engines.
    """
    if indicators is not None:
        short = indicators["sma_short"]
        long = indicators["sma_long"]
        hist = indicators["macd_hist"]
    else:
        short = long = hist = None

    result = run_nautilus(
        ohlcv=prices,
        short_sma=short,
        long_sma=long,
        macd_hist=hist,
    )
    if result.reconciled:
        return result.trade_log, result.equity_curve
    raise RuntimeError(result.reason)


if __name__ == "__main__":
    # Standalone observability of the degrade path (no orchestrator needed):
    # load the golden frame, run, and print reconciled/reason (+ a one-line
    # trade-count summary if reconciled).
    res = run_nautilus(None)
    print("nautilus:", "reconciled" if res.reconciled else "degraded")
    if res.reconciled:
        trade_count = 0 if res.trade_log is None else len(res.trade_log)
        final_equity = (
            None
            if res.equity_curve is None or len(res.equity_curve) == 0
            else float(res.equity_curve.iloc[-1])
        )
        print("  trades:", trade_count, "| final_equity:", final_equity)
    else:
        print(" ", res.reason)
