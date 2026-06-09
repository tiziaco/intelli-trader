"""UNIV-02 engine proof over heterogeneous data spans (D-06 synthetic fixtures).

Behavior: construct a CSV-fed ``TradingSystem`` over tiny hand-pinned synthetic
multi-ticker CSVs — an EARLYUSD anchor present across the full window, a LATEUSD
that LISTS mid-run, and an ENDSEARLY ticker whose last bar precedes the window
end — drive a tiny long-only strategy that WOULD trade every ticker from day one,
and assert the engine survives the union window with no crash and no look-ahead.

This is the synthetic-fixture half of UNIV-02 (D-06): it proves the engine
handles a mid-run listing and differing end dates over the union ping grid (which
already ticks across the union — ``backtest_trading_system.py`` WR-07) and that
``current_bars``' sparse dict (no fill for an absent bar) holds end-to-end.

The full real-data ETH/SOL/AAVE E2E run is DEFERRED to Phase 9 (it needs the
Phase-4 harness; ROBUST-03 scopes it) — this test does NOT load the real CSVs.

Carries the ``integration`` marker automatically via the ``tests/integration/``
path (folder-derived auto-marking) — do NOT hand-add a marker. All stamps are
built tz-aware (Pitfall 2); CSVs use whole-day daily stamps anchored at 00:00 UTC
(the golden-bar grid) so (a) the load never touches the alias-sensitive resample
path (Pitfall 3) and (b) the daily ticks pass the UTC-midnight ``check_timeframe``
alignment seam so the strategy actually fires.
"""

from decimal import Decimal

import pandas as pd

from itrader.core.sizing import FixedQuantity, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import TradingSystem


KLINE_HEADER = (
    'Open time,Open,High,Low,Close,Volume,Close time,Quote asset volume,'
    'Number of trades,Taker buy base asset volume,Taker buy quote asset volume,Ignore\n'
)


def utc_midnight(day: str) -> pd.Timestamp:
    """The UTC-midnight bar stamp for ``day`` (matches the loaded frame index).

    The store loads ``<day> 00:00:00 UTC`` rows and tz-converts to TIMEZONE, so
    the engine carries a tz-aware stamp equal to ``00:00 UTC`` for that day. Build
    assertion stamps the same way so the comparison is tz-safe (Pitfall 2).
    """
    return pd.Timestamp(f"{day} 00:00:00", tz="UTC")


def write_kline_csv(path, days, base: float = 100.0):
    """Write a Binance-kline-shaped CSV anchored at 00:00 UTC (golden-bar grid).

    Mirrors ``tests/unit/price/test_bar_feed.py::write_kline_csv`` for the OHLCV
    shape (bar i: open=base+i, high=base+10+i, low=base-10+i, close=base+5+i,
    volume=1000+i) but stamps each bar at midnight UTC so a daily engine run's
    ``check_timeframe`` alignment seam fires (the seam aligns on the UTC grid).
    """
    rows = [KLINE_HEADER]
    for i, day in enumerate(days):
        open_time = f"{day} 00:00:00.000000 UTC"
        close_time = f"{day} 23:59:59.999000 UTC"
        rows.append(
            f"{open_time},"
            f"{base + i},{base + 10 + i},{base - 10 + i},{base + 5 + i},{1000 + i},"
            f"{close_time},1.0,1,1.0,1.0,0\n"
        )
    path.write_text(''.join(rows))
    return path


class BuyEachTickerOnce(Strategy):
    """Tiny purpose-built long-only strategy: BUY the first bar it ever sees for
    each ticker, then nothing more.

    It WOULD trade the late-lister from day one — but it can only act on a bar
    that the engine actually delivers. Because the feed's ``current_bars`` is a
    sparse dict (absent tickers dropped) and the strategy handler skips a
    ``None`` bar, the first signal for the late-lister cannot occur before its
    listing date. ``max_window=1`` so the pushed window is non-empty without
    needing real warm-up history.
    """

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(
            "BuyEachTickerOnce", timeframe, list(tickers),
            sizing_policy=FixedQuantity(qty=Decimal("1")),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
            max_positions=10,
        )
        self.max_window = 1
        self._bought: set[str] = set()

    def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
        # The handler only calls this when a bar for ``ticker`` exists at T
        # (sparse-dict guard), so the first call is the ticker's first delivered
        # bar — i.e. on/after its listing date, never before.
        if ticker in self._bought:
            return None
        self._bought.add(ticker)
        return self.buy(ticker)


# Synthetic spans (hand-pinned, D-06). Union window = Jan 1..Jan 20, 2020.
WINDOW_START = "2020-01-01"
WINDOW_END = "2020-12-31"

EARLY_DAYS = [f"2020-01-{d:02d}" for d in range(1, 21)]    # Jan 1..20 (full anchor)
LATE_DAYS = [f"2020-01-{d:02d}" for d in range(10, 21)]    # Jan 10..20 (lists mid-run)
ENDSEARLY_DAYS = [f"2020-01-{d:02d}" for d in range(1, 6)]  # Jan 1..5 (ends early)

LATE_LISTING_DATE = utc_midnight("2020-01-10")
ENDSEARLY_LAST_DATE = utc_midnight("2020-01-05")


def test_engine_survives_heterogeneous_spans_with_no_look_ahead(tmp_path):
    """UNIV-02: union-window run over a mid-run lister + a differing-end-date
    ticker completes without raising and produces no look-ahead fill."""
    early = write_kline_csv(tmp_path / "early.csv", EARLY_DAYS, base=100.0)
    late = write_kline_csv(tmp_path / "late.csv", LATE_DAYS, base=200.0)
    ends = write_kline_csv(tmp_path / "ends.csv", ENDSEARLY_DAYS, base=300.0)

    system = TradingSystem(
        exchange="csv",
        csv_paths={"EARLYUSD": early, "LATEUSD": late, "ENDSEARLYUSD": ends},
        start_date=WINDOW_START,
        end_date=WINDOW_END,
    )

    # Register the synthetic tickers with the simulated exchange's supported set.
    # The default preset only admits the golden BTCUSD (execution_handler.py:109);
    # the same instance-set mutation lets validate_symbol admit our fixtures.
    # Test-only wiring — the Phase-9 E2E harness will own a richer symbol setup.
    simulated = system.execution_handler.exchanges["simulated"]
    simulated._supported_symbols = set(simulated._supported_symbols) | {
        "EARLYUSD", "LATEUSD", "ENDSEARLYUSD",
    }
    # WR-02: fail loudly at setup if the private attribute drifts (e.g. the
    # supported-symbol set moves behind a config object). Without this, a
    # rename would silently reject our orders, leaving positions empty so the
    # downstream look-ahead asserts vacuously pass while `assert late_positions`
    # fails with a misleading message far from the real cause.
    assert {"EARLYUSD", "LATEUSD", "ENDSEARLYUSD"} <= simulated._supported_symbols

    strategy = BuyEachTickerOnce(
        timeframe="1d",
        tickers=["EARLYUSD", "LATEUSD", "ENDSEARLYUSD"],
    )
    system.strategies_handler.add_strategy(strategy)

    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1,
        name="spans_pf",
        exchange="csv",
        cash=1_000_000,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # (a) NO CRASH: the union ping grid ticks across [Jan 1, Jan 20] (the union of
    # all three spans) and the run completes over the mid-run listing and the
    # differing end date without raising.
    system.run(print_summary=False)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    # All positions (open + closed) seen during the run.
    all_positions = list(portfolio.positions.values()) + list(portfolio.closed_positions)

    def positions_for(ticker: str):
        return [p for p in all_positions if p.ticker == ticker]

    # Sanity anchor: the always-present ticker traded (proves the engine ran and
    # the strategy actually fired over the daily grid).
    assert positions_for("EARLYUSD"), "expected the always-present anchor to trade"

    # (b) NO LOOK-AHEAD for the mid-run lister: it has >=1 position, and every
    # position's entry is at or after its listing date — zero before.
    late_positions = positions_for("LATEUSD")
    assert late_positions, (
        "expected >=1 LATEUSD position at/after its listing date "
        "(strategy buys it from day one once a bar is delivered)"
    )
    for position in late_positions:
        assert position.entry_date >= LATE_LISTING_DATE, (
            f"LATEUSD position entry {position.entry_date} is before its listing "
            f"date {LATE_LISTING_DATE} — look-ahead leak"
        )
    # The earliest LATEUSD entry is strictly >= the listing date (the acceptance lock).
    earliest_late_entry = min(p.entry_date for p in late_positions)
    assert earliest_late_entry >= LATE_LISTING_DATE

    # (c) DIFFERING END DATE: ENDSEARLYUSD's last bar is Jan 5; after that the
    # engine keeps ticking (to Jan 20) with no further bar/fill for it — any
    # position it has was entered on/before its last bar, never after.
    ends_positions = positions_for("ENDSEARLYUSD")
    for position in ends_positions:
        assert position.entry_date <= ENDSEARLY_LAST_DATE, (
            f"ENDSEARLYUSD position entry {position.entry_date} is after its last "
            f"bar {ENDSEARLY_LAST_DATE} — an absent bar produced a fill"
        )
