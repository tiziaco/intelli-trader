# Phase 8: M5c — Cross-Validation & Final Oracle — RESEARCH (Agent Re-run)

**Researched:** 2026-06-08
**Domain:** External backtest-engine cross-validation (backtesting.py, backtrader, nautilus_trader) + golden-path Decimal cleanup
**Confidence:** HIGH on the two gating engines (verified by live install + run); MEDIUM on nautilus_trader (doc-confirmed API + version, not run end-to-end)
**Requirement:** M5-10

> **Purpose of this file.** This is a SEPARATE companion to `08-RESEARCH.md`. The existing
> research is solid on local facts (Decimal cleanup, force-match config, harness shape) but
> left the highest-value external claims flagged `[verify at impl-time]`. With connectivity
> restored I **empirically verified** them in throwaway venvs and against official docs/PyPI.
> Below, every item is tagged so the orchestrator can diff/merge: **[NEW — supersedes 08-RESEARCH
> uncertainty]**, **[CONFIRMS 08-RESEARCH]**, or **[CORRECTS 08-RESEARCH]**. Sections the
> existing file already covers well (D-06 line numbers, harness layout, re-freeze discipline,
> DoD table) are NOT repeated — only material deltas appear here.

---

## Headline deltas (read these first)

1. **backtrader compatibility is RESOLVED — no fork, no shim needed. [NEW — supersedes the
   "single biggest open question"]** Original `backtrader==1.9.78.123` (the last PyPI release)
   **imports AND runs a full backtest cleanly on this exact stack** — Python 3.13.1 + numpy 2.2.6
   + pandas 2.3.3 — even under `warnings.simplefilter("error")` (the strictest form of the repo's
   `filterwarnings=["error"]`). I built a throwaway venv with those pinned versions and ran a
   complete cerebro backtest (custom fractional sizer, `notify_order`, `notify_trade`, equity
   collection): it produced fills, closed trades, and a final equity != starting cash, with zero
   warnings/errors. **The 08-RESEARCH "high risk" item #2 and the fork/shim contingency are
   unnecessary.** Pin plain `backtrader = "1.9.78.123"`.
   - `backtrader` does NOT use numpy for its line buffers (it uses `array.array`), so the numpy-2
     alias removals (`np.bool`/`np.float`/`np.int`) never bite it. The widespread "backtrader is
     broken on numpy 2 / py3.13" folklore is about *compiled-extension* mismatch, not pure-Python
     backtrader. `[VERIFIED: local install + run]`

2. **nautilus_trader OFFICIALLY supports Python 3.13. [NEW — supersedes "verify at impl-time"]**
   PyPI `nautilus_trader==1.227.0` declares `requires_python = "<3.15,>=3.12"` and pins
   `numpy>=1.26.4`, `pandas<3.0.0,>=2.3.3` — **all compatible with this repo (numpy 2.2.6,
   pandas 2.3.3)**. It ships prebuilt wheels (Rust-backed, manylinux/macos), so install is a wheel
   download, not a from-source Rust compile, on macOS arm64/x86_64. Install weight is real (msgspec,
   pyarrow, uvloop, ~19 deps) but it is NOT a blocker. `[VERIFIED: PyPI metadata]`

3. **Both gating engines verified end-to-end under warnings-as-errors. [NEW]** I ran
   `backtesting==0.6.5` (`FractionalBacktest`) and `backtrader==1.9.78.123` to completion with
   `warnings.simplefilter("error")`, on numpy 2.2.6 / pandas 2.3.3 / py3.13.1. Both produced trade
   logs + equity curves with the exact column shapes the harness needs (below). `[VERIFIED: local
   install + run]`

4. **Live test count is 716, not 274. [CONFIRMS 08-RESEARCH; CORRECTS REQUIREMENTS/BRIEF]**
   `poetry run pytest --collect-only -q` → **"716 tests collected in 0.93s"**. REQUIREMENTS.md
   lines 43 & 183 and the REFACTOR-BRIEF still say "274". The D-13 DoD gate must assert the full
   live suite green (currently 716), never a hardcoded number. `[VERIFIED: local pytest]`

---

## User Constraints (from CONTEXT.md — verbatim anchors)

### Locked Decisions (the ones this re-run touches)
- **D-01** Force-match reference engines exactly: next-bar-open fills, `FractionOfCash(0.95)`,
  long-only, zero fees/slippage, $10k cash, SMA(50/100)/MACD(6/12/3), **filter-gates-BOTH-entry-
  AND-exit** quirk. Divergence must be near-zero; any gap is a real finding.
- **D-02** Trade-level primary (same count + entry/exit bar timing) + metric-level secondary.
- **D-03** Indicator-library divergence is the only legitimate trade-timing difference source.
- **D-05** Root-cause decides; iTrader correct unless proven a bug.
- **D-06/D-07/D-08** Golden-path Decimal cleanup lands FIRST → own named re-freeze.
- **D-10** Reference engines as pinned **dev-group** deps; reproducible `scripts/cross_validate.py`;
  committed report; NOT wired into `make test`/CI.
- **D-12** nautilus_trader = OPTIONAL NON-GATING third reference; must never stall the freeze.
- **D-13** Verify program-level definition of done.

### Claude's Discretion (relevant here)
- Exact pinned versions (resolved below). Whether engines run in one script or one module each
  (recommend one module per engine — confirmed by the compat-isolation finding). Engine-native vs
  injected `ta` indicators (recommend injected — see §3). Decimal retype boundaries (08-RESEARCH
  has the line-level map; one correction below).

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M5-10 | Cross-validate SMA_MACD on golden BTCUSD CSV vs backtesting.py + backtrader (gating); metrics reconciled; final numerical reference frozen | §1 (verified force-match APIs for both gating engines), §2 (verified nautilus optional path), §3 (trade-log extraction shapes), §5 (version pins). D-06 cleanup (§4) precedes per D-07. |

---

## §1 — Gating-engine force-match (VERIFIED)

Source of truth for the config = `scripts/run_backtest.py` + `SMA_MACD_strategy.py`: BTCUSD 1d,
2018-01-01→2026-06-03, cash $10k, fees 0, slippage 0, `FractionOfCash(Decimal("0.95"))`,
`allow_increase=False`, `LONG_ONLY`, SMA short=50/long=100, MACD FAST=6/SLOW=12/WIN=3, next-bar-open
fills, warm-up `len(bars) < max(long_window, 100)`. The quirk: in `generate_signal` the exit `elif`
is **nested inside** the `if short_sma.iloc[-1] >= long_sma.iloc[-1]:` filter, so the SMA filter
gates BOTH entry and exit (a held long is NOT exited on a MACD down-cross while the filter is False).
`[VERIFIED: source read]`

### backtesting.py — `0.6.5` (gating) `[VERIFIED: local install + run]`

- **Use `from backtesting.lib import FractionalBacktest`.** Verified constructor:
  `FractionalBacktest(data, Strategy, *, fractional_unit=1e-08, cash=..., commission=..., spread=...,
  margin=..., trade_on_close=..., exclusive_orders=..., finalize_trades=...)`. It scales prices ×
  `fractional_unit` and volume ÷ `fractional_unit` so whole-unit internal trading == fractional BTC.
  Default `fractional_unit=1e-08` (1 satoshi) is fine for BTC. `[CONFIRMS 08-RESEARCH; VERIFIED docs]`
- **Data shape requirement [NEW — important footgun]:** columns must be capitalized
  **`Open, High, Low, Close, Volume`** with a `DatetimeIndex`. The golden CSV is lowercase
  `open/high/low/close/volume` — the harness must rename before feeding backtesting.py. (My test
  failed with the lowercase names until renamed.) `[VERIFIED: local run]`
- **Force-match kwargs (verified to run):** `cash=10_000, commission=0.0, trade_on_close=False`
  (→ fill at next bar open), `exclusive_orders=True` (each new order closes the prior → single
  position == `allow_increase=False`), `finalize_trades=True` (see caveat). `spread=0.0`,
  `margin=1.0` for zero slippage / no leverage.
- **Sizing nuance [NEW — must reconcile carefully].** `self.buy(size=0.95)` sizes as **fraction of
  available equity**, whereas iTrader's `FractionOfCash(0.95)` is **0.95 × cash**. When flat with
  no open position these coincide (cash == equity); with `exclusive_orders` + only-buy-when-flat
  they should stay aligned, but verify the entry quantity matches iTrader's on the first few trades.
  If it diverges, compute the size explicitly: `size = int((0.95*self.equity)/price)` is wrong (floors
  to 0 — the landmine); instead pass the fraction and let FractionalBacktest handle units, or pass an
  absolute fractional size. `[VERIFIED: live `_trades.Size` are fractional floats like 81.77, 106.36]`
- **Indicators:** register iTrader's `ta` arrays via `self.I(...)` (see §3) — do NOT use
  backtesting.py's built-in indicators.
- **Verified extraction:** `stats = bt.run()`. `stats['_trades']` is a DataFrame with columns
  (verified live): `Size, EntryBar, ExitBar, EntryPrice, ExitPrice, SL, TP, PnL, Commission,
  ReturnPct, EntryTime, ExitTime, Duration, Tag, ...`. `Size>0` ⇒ LONG. `stats['_equity_curve']`
  is a DataFrame with columns `Equity, DrawdownPct, DrawdownDuration` and one row per bar.
  `stats['# Trades']`, `stats['Equity Final [$]']` are scalars. `[VERIFIED: live]`
- **Do NOT trust `stats['Sharpe Ratio']`/`CAGR [%]`** for reconciliation — different annualization
  convention. Recompute from `stats['_equity_curve']['Equity']` through `itrader.reporting.metrics`
  (PERIODS=365, ddof=1). `[CONFIRMS 08-RESEARCH]`

### backtrader — `1.9.78.123` (gating) `[VERIFIED: local install + full run]`

- **No fork needed (headline #1).** Pin `backtrader = "1.9.78.123"`. Imports + runs cleanly on
  numpy 2.2.6 / pandas 2.3.3 / py3.13.1 under warnings-as-errors. `[CORRECTS 08-RESEARCH risk #2 /
  "biggest open question"]`
- **Fractional sizing — verified pattern.** `PercentSizer` casts to int → 0 BTC. Write a custom
  `bt.Sizer` returning a **float**:
  ```python
  class FracOfCashSizer(bt.Sizer):
      params = (("frac", 0.95),)
      def _getsizing(self, comminfo, cash, data, isbuy):
          if isbuy:
              return (cash * self.p.frac) / data.close[0]   # float -> fractional BTC
          return self.broker.getposition(data).size          # close full position
  ```
  Verified: this takes a real fractional position (sizes ~79–172 in my oscillating test) and the
  final value moves off 10_000. NOTE: backtrader sizer's `cash` argument is **available cash**
  (== equity when flat with `allow_increase=False`), matching `FractionOfCash`. `[VERIFIED: live]`
- **Broker:** `cerebro.broker.setcash(10000.0)`; `cerebro.broker.setcommission(commission=0.0)`.
- **Fills = next-bar-open by default.** Verified `cerebro.broker.p.coc == False` (no cheat-on-close)
  and the default `coo == False` (no cheat-on-open). A market order issued in `next()` fills at the
  next bar's open — matches D-01. Do NOT enable `set_coc`/`set_coo`. `[VERIFIED: live]`
- **Data feed:** `bt.feeds.PandasData(dataname=df)` accepts the lowercase `open/high/low/close/volume`
  + DatetimeIndex directly (no rename needed, unlike backtesting.py). Inject `ta` arrays as extra
  data lines (subclass `PandasData` with extra `lines`/`params`) — see §3. `[VERIFIED: live with the
  standard OHLCV feed]`
- **Verified trade-level extraction:** collect in `notify_trade(self, trade)` when `trade.isclosed`:
  `(bt.num2date(trade.dtopen), bt.num2date(trade.dtclose), trade.pnl)`. For fills/sides use
  `notify_order` on `order.status == order.Completed`: `order.isbuy()`, `bt.num2date(order.executed.dt)`,
  `order.executed.price`, `order.executed.size`. Equity curve: append `self.broker.getvalue()` each
  `next()`. All verified to produce per-trade open/close dates + a full equity series. `[VERIFIED: live —
  produced 4 trades with correct entry/exit dates + PnL on test data]`
- **Long-only / single position:** only `self.buy()` (custom-sized) when `not self.position`;
  `self.close()` to exit. Encode the filter-gates-both quirk literally in `next()`.

---

## §2 — nautilus_trader (OPTIONAL, NON-GATING — D-12) — actionable guidance

**Version pin: `nautilus-trader = "1.227.0"`** (latest; `requires_python <3.15,>=3.12`,
`numpy>=1.26.4`, `pandas<3.0.0,>=2.3.3` — all satisfied). Install is a prebuilt Rust-backed wheel;
heavy but not from-source. `[VERIFIED: PyPI metadata]` — I did NOT run nautilus end-to-end (the wheel
+ ~19 transitive deps is a large install I avoided in a throwaway venv), so the API specifics below
are **`[CITED: nautilustrader.io docs + official examples]`**, confidence MEDIUM. This is acceptable
under D-12 (non-gating); the recommendation is to implement it last, guarded.

### Low-level BacktestEngine workflow (the right API for force-matching)

Use the **low-level API** (`BacktestEngine` directly), not the high-level `BacktestNode` — it gives
the explicit venue/account/instrument control D-01 needs.

```python
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.identifiers import Venue, TraderId
from nautilus_trader.model.enums import OmsType, AccountType, BookType
from nautilus_trader.model.objects import Money
from nautilus_trader.model.currencies import USD  # or define USDT/USD as needed

engine = BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId("BACKTESTER-001")))
engine.add_venue(
    venue=Venue("SIM"),
    oms_type=OmsType.NETTING,          # single net position -> matches allow_increase=False
    account_type=AccountType.CASH,     # cash account, no leverage
    base_currency=USD,
    starting_balances=[Money(10_000, USD)],
    book_type=BookType.L1_MBP,         # REQUIRED for bar-based execution (see fill note)
)
```
`[CITED: backtest_low_level docs]`

### Instrument with ZERO fees

Construct a `CurrencyPair` for BTC/USD with `maker_fee=Decimal("0")` and `taker_fee=Decimal("0")`
(zero fees per D-01). `TestInstrumentProvider` has convenience builders (e.g. `btcusdt_binance()`)
but those carry non-zero default fees — for an exact zero-fee force-match, build the `CurrencyPair`
manually with the fee fields set to `Decimal("0")`, plus `price_precision`/`size_precision`/
`price_increment`/`size_increment` chosen fine enough for fractional BTC (size_precision ≥ 6).
`[CITED: instruments docs + crypto example]` — **exact CurrencyPair constructor signature is the one
genuinely uncertain piece; verify the kwarg names at impl-time against the installed version's
`help(CurrencyPair)`.**

### Bar data + next-bar-open fill timing `[NEW — key nautilus mechanic]`

- Feed OHLCV via `BarDataWrangler` → `engine.add_data(bars)`. Define a `BarType`/`BarSpecification`
  for 1-DAY bars (`BarAggregation.DAY`, `PriceType.LAST`), `AggregationSource.EXTERNAL` (internally-
  aggregated bars are **skipped for execution**).
- **Critical timing rule (from official docs):** `ts_init` of each bar must represent the bar's
  **close** time. If the golden CSV timestamps bars at the **open**, set
  `BarDataWrangler(..., ts_init_delta=<bar_duration_ns>)` (for 1d = `86_400_000_000_000`) so
  `ts_init = ts_event + duration`. **Inspect the golden CSV timestamp convention before wiring this**
  — getting it wrong shifts every fill by one bar and would manifest as a fake "1-bar divergence"
  (exactly the misattribution D-03/D-05 warn about). `[CITED: backtesting concepts docs]`
- **Bar execution requires `book_type=L1_MBP`** on the venue (L2/L3 ignore bars for execution).
  With L1 + bars, a market order submitted on bar T fills against the next available bar price —
  approximating next-bar-open. This is the closest nautilus gets to D-01's fill convention; document
  any residual timing difference rather than fighting it (D-12 non-gating).

### Post-run extraction `[CITED: docs — verified method names]`

- `engine.trader.generate_order_fills_report()` → per-fill DataFrame (sides, prices, timestamps) →
  pair into per-trade entry/exit for the D-02 reconciliation.
- `engine.trader.generate_positions_report()` → closed-position records (entry/exit/realized PnL).
- `engine.trader.generate_account_report(Venue("SIM"))` → account balance time series → equity curve.

### Implementation posture (honoring D-12)

Implement nautilus **last**, in its **own module** (`scripts/crossval/nautilus_run.py`), behind a
`try/except ImportError` + a config flag. If install or force-match config friction appears, the
orchestrator/report records "Nautilus: not reconciled — {reason}" and the freeze proceeds on the two
gating engines. **It must never stall the DoD freeze.** `[CONFIRMS 08-RESEARCH + D-12]`

**Genuinely uncertain (verify at impl-time, MEDIUM confidence):** exact `CurrencyPair` constructor
kwargs; whether L1+bars fills at the bar's open vs close vs next-bar-open precisely; the cash-account
sizing API for submitting a fractional-quantity market order. These are non-gating per D-12.

---

## §3 — Trade-level reconciliation & indicator injection (D-02/D-03)

**Recommendation (strong): inject iTrader's exact `ta` series into every engine.** Compute SMA(50),
SMA(100), and MACD-histogram(6,12,3) ONCE on the full BTCUSD close series using the identical `ta`
calls from `SMA_MACD_strategy` — `ta.trend.SMAIndicator(close, 50, True).sma_indicator()`,
`ta.trend.SMAIndicator(close, 100, True).sma_indicator()`,
`ta.trend.MACD(close, window_fast=6, window_slow=12, window_sign=3, fillna=False).macd_diff()` —
then feed those arrays into each engine instead of engine-native indicators:
- backtesting.py: `self.sma50 = self.I(lambda: precomputed_sma50_array, ...)` (register precomputed).
- backtrader: extra lines on a `PandasData` subclass (add `sma50/sma100/macdhist` columns to the df).
- nautilus: precomputed columns referenced inside the strategy's `on_bar`.

This collapses indicator-library divergence to **zero**, so any remaining trade-timing gap is purely
fill/sizing/equity mechanics — exactly what D-01 wants isolated ("near-zero divergence so any gap is
a real finding"). Engine-native indicators would re-introduce the 5th–6th-decimal crossover
differences D-03 describes and make the D-02 trade-for-trade gate unachievable. `[CONFIRMS 08-RESEARCH —
this re-run agrees and reinforces]`

**Quirk encoding (all engines, in `next()`/`on_bar`):**
- Entry: `sma50[-1] >= sma100[-1]` AND `macdhist[-1] >= 0` AND `macdhist[-2] < 0` → buy (when flat).
- Exit: `sma50[-1] >= sma100[-1]` AND `macdhist[-1] <= 0` AND `macdhist[-2] > 0` → close.
- The exit is gated by the SAME SMA filter — a held long is NOT closed on a down-cross when the
  filter is False. Encode the exit branch as nested inside the filter, exactly as the source does.

**iTrader side of the reconciliation:** read `tests/golden/trades.csv` directly (entry_date,
exit_date, side, realised_pnl). It currently holds **134 trades**; `tests/golden/equity.csv` holds
**3076 equity points**; `final_equity = 46189.87730727451`. `[VERIFIED: local read]`

**Final-open-trade caveat [CONFIRMS 08-RESEARCH risk #6].** iTrader's 134 are **closed** positions
(`portfolio.closed_positions`). If the run ends with an open position, the engines' `finalize_trades`
behavior must match iTrader's exclusion of it. Check whether the golden run ends flat; set
backtesting.py `finalize_trades=False` if iTrader leaves a final position open and excludes it.
The last golden trade exits 2019-... onward — confirm the final bar state before pinning this kwarg.

---

## §4 — D-06 Decimal cleanup: one correction + confirmations

**[CONFIRMS 08-RESEARCH]** The float-leak targets and line numbers in 08-RESEARCH match the source
and CONCERNS.md exactly. Verified `Portfolio` properties currently return `float` via `float(...)`
wrappers over Decimal sources:
- `total_market_value` (L223) → `float(self.position_manager.get_total_market_value())`
- `total_equity` (L233) → `self.total_market_value + float(self.cash)`
- `total_unrealised_pnl` (L243), `total_realised_pnl` (L248), `total_pnl` (L253).
The underlying `position_manager.get_total_*` already return Decimal and `self.cash` is Decimal, so
the fix is **removing coercions**, not adding conversions. `[VERIFIED: source read portfolio.py
215-260]`

**[CORRECTS a stale line ref]** CONCERNS.md cites `portfolio.py:223,230,240,245,250`. In the current
tree the property bodies are at L223 (`total_market_value`), L233/240 (`total_equity`), L245
(`total_unrealised_pnl`), L250 (`total_realised_pnl`), L257 (`total_pnl`). The set is correct; the
exact line offsets drifted slightly — the planner should grep `-> float` in `portfolio.py` rather
than trust fixed line numbers.

**[CONFIRMS] mypy strict is real and scoped.** `pyproject.toml [tool.mypy] strict = true`,
`python_version = "3.13"`, `files = ["itrader"]`. `trading_interface`/`live_trading_system` are in the
`ignore_errors` override list (D-live deferral) — so the D-09 deferral is already encoded in mypy
config; the Decimal retype must keep the **in-scope** modules strict-clean. `ta.*` is in
`ignore_missing_imports`. Changing `Portfolio.total_*` from `float`→`Decimal` will surface mixed
`float + Decimal` arithmetic across `MetricsManager`/reporting/validator callers under `--strict` —
budget a propagation sweep, then `make typecheck` (= `poetry run mypy itrader`). `[VERIFIED: pyproject]`

**Derived-ratio boundary (the key design call, confirmed):** keep money fields Decimal end-to-end,
but the statistical ratios (drawdown %, returns, Sharpe/Sortino/CAGR) are numpy float computations —
keep the float boundary at the metric *input* (e.g. `equity["total_equity"].astype(float)` feeding
`compute_returns`, exactly as `scripts/run_backtest.py::build_metrics_block` already does), NOT at the
Portfolio property. `build_summary` does `float(portfolio.total_equity)` / `float(portfolio.cash)`;
after the retype these become `float(Decimal(...))`. Whether the serialized value shifts from
`46189.87730727451` decides whether `REFREEZE-M5C-DECIMAL` is needed (D-08 anticipates a shift).
`[VERIFIED: run_backtest.py read]`

---

## §5 — Version pins (poetry dev group)

| Package | Pin | requires_python | Verified compat | Notes |
|---------|-----|-----------------|-----------------|-------|
| `backtesting` | `0.6.5` (latest) | `>=3.9` | numpy 2.2.6 / pd 2.3.3 / py3.13.1 ✓ (ran) | `FractionalBacktest` is the API used. `[VERIFIED]` |
| `backtrader` | `1.9.78.123` (last PyPI) | (none declared) | numpy 2.2.6 / pd 2.3.3 / py3.13.1 ✓ (ran, warnings-as-errors clean) | **No fork needed.** `[VERIFIED]` |
| `nautilus-trader` | `1.227.0` (latest) | `<3.15,>=3.12` | metadata-compatible (not run) | optional/non-gating; prebuilt wheel. `[VERIFIED: PyPI metadata]` |

Forks (NOT recommended unless original ever fails): `backtrader_next==2.3.7` (`>=3.11`) — faster but
**different import name** `import backtrader_next as bt` (NOT a drop-in for `import backtrader`) and a
divergent API surface; `backtrader2==1.9.76.123` (older mirror). The original works, so prefer it for
fidelity. `[VERIFIED: PyPI metadata + README fetch]`

**Add to `[tool.poetry.group.dev.dependencies]` only** (D-10). The dev group currently holds pytest*,
ipython, ipykernel, mypy. `[VERIFIED: pyproject read]`

---

## §6 — filterwarnings isolation (verified safe)

`pyproject.toml [tool.pytest.ini_options].filterwarnings = ["error", "ignore::UserWarning",
"ignore::DeprecationWarning"]`. The cross-validation harness is a **script, not a test**, so it is
outside pytest's filter (D-10). I additionally verified that **even under the strictest
`warnings.simplefilter("error")`**, importing and running both gating engines emits no warning that
would trip the gate — so even if a future task accidentally imports them at test-collection time, the
gating engines themselves are clean (the risk would only be transitive deps like bokeh). Keep them out
of `tests/` regardless, per D-10. `[VERIFIED: ran both under simplefilter("error")]`

---

## §7 — DoD verification (D-13) — confirmations

| DoD item | Command | Status |
|----------|---------|--------|
| SMA_MACD end-to-end | `make backtest` → `output/{trades,equity,summary}.json/csv` | `make backtest` = `poetry run python scripts/run_backtest.py` `[VERIFIED Makefile]` |
| mypy --strict clean | `make typecheck` = `poetry run mypy itrader` | strict=true confirmed `[VERIFIED]` |
| No float money | grep golden path; assert `Portfolio.total_*` → Decimal | targets in §4 |
| Single UUIDv7 | `idgen`/`uuid-utils` only on result path | per brief |
| Deterministic | double-run byte-identical `output/` diff | per D-13 |
| **Full suite green** | `make test` = `poetry run pytest tests/ -v` — **716 tests** (NOT 274) | `[VERIFIED: 716 collected]` |
| Run-path integration test | existing byte-exact diff vs `tests/golden/*` | per D-10 |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | nautilus `CurrencyPair` accepts `maker_fee=Decimal("0")`/`taker_fee=Decimal("0")` and the manual constructor kwargs are as cited | §2 | nautilus zero-fee config differs; non-gating so low risk (degrade gracefully) |
| A2 | nautilus L1_MBP + external bars fills approximate next-bar-open | §2 | nautilus fill timing off by a bar; non-gating, document the diff |
| A3 | backtesting.py `self.buy(size=0.95)` (fraction of equity) stays aligned with iTrader's `0.95×cash` under exclusive_orders + buy-when-flat | §1 | entry quantities diverge → metric drift; mitigated by verifying first-trade size against golden |
| A4 | Golden run's final trade is closed (or its open-position handling is known) so `finalize_trades` can be matched | §3 | off-by-one trade count (134 vs 135); check final bar state before pinning |

**All other claims in this file are `[VERIFIED]` (local install/run or PyPI/source read) or
`[CITED]` against official nautilus docs.**

## Open Questions

1. **Does `float(Decimal(final_equity))` reproduce `46189.87730727451` after the D-06 cleanup?**
   - Known: properties become Decimal; `build_summary` re-casts to float for JSON.
   - Unclear: whether accumulated Decimal precision shifts the headline value.
   - Recommendation: regenerate the oracle right after the cleanup, diff `summary.json`; if shifted →
     `REFREEZE-M5C-DECIMAL` with expected-diff note (D-08 already plans for this).

2. **nautilus exact instrument/fill API** (A1/A2) — non-gating; resolve at impl-time via
   `help(CurrencyPair)` on the installed 1.227.0 and the official crypto bar examples.

## Sources

### Primary (HIGH confidence — local verification)
- Live install + full backtest run of `backtesting==0.6.5` and `backtrader==1.9.78.123` on
  numpy 2.2.6 / pandas 2.3.3 / Python 3.13.1, under `warnings.simplefilter("error")`.
- `poetry run pytest --collect-only -q` → 716 tests.
- PyPI JSON metadata for backtesting/backtrader/nautilus_trader/backtrader_next/backtrader2.
- Source reads: `scripts/run_backtest.py`, `itrader/strategy_handler/SMA_MACD_strategy.py`,
  `itrader/portfolio_handler/portfolio.py`, `pyproject.toml`, `.planning/codebase/CONCERNS.md`,
  `tests/golden/{summary.json,trades.csv,equity.csv}`.

### Secondary (MEDIUM confidence — official docs)
- backtesting.py `FractionalBacktest` docs — https://kernc.github.io/backtesting.py/doc/backtesting/lib.html
- nautilus_trader low-level backtest / instruments / backtesting concepts docs —
  https://nautilustrader.io/docs/latest/getting_started/backtest_low_level/ ,
  https://nautilustrader.io/docs/latest/concepts/instruments/ ,
  https://nautilustrader.io/docs/latest/concepts/backtesting/
- backtrader_next README — https://github.com/smalinin/backtrader_next

## Metadata
- **Confidence breakdown:** gating engines HIGH (ran them); nautilus MEDIUM (doc + metadata, not run);
  Decimal cleanup HIGH (source-confirmed); pins HIGH (PyPI + run).
- **Research date:** 2026-06-08
- **Valid until:** ~30 days (engine versions stable; nautilus moves fastest — re-pin if >1 minor behind).
