# Phase 8: M5c — Cross-Validation & Final Oracle — RESEARCH

**Researched:** 2026-06-08
**Requirement:** M5-10 (cross-validate vs `backtesting.py` + `backtrader`; metrics reconciled; final numerical reference frozen) + program definition-of-done.
**Method note:** The first two `gsd-phase-researcher` spawns died on transient socket errors (user connectivity) during the heavy web-research phase. This RESEARCH.md was authored by the orchestrator inline from (a) the full local source/golden/config facts read directly, and (b) bounded Context7 lookups against the official `backtesting.py` and `backtrader` docs. Reference-engine API claims below are doc-confirmed where marked **[doc-confirmed]**.

> **COMPANION FILE — read alongside this one:** After connectivity was restored, a fresh `gsd-phase-researcher` re-run produced **`08-RESEARCH-AGENT.md`**, which **empirically verified** the highest-uncertainty external claims by installing and running both gating engines on this exact stack. It supersedes this file on two points: (1) backtrader compatibility is **RESOLVED** (no fork needed — see Risk #2 below, now struck through), and (2) exact version pins are confirmed (`backtesting==0.6.5`, `backtrader==1.9.78.123`, `nautilus-trader==1.227.0`). It also adds concrete `nautilus_trader` `BacktestEngine` API guidance (MEDIUM confidence — non-gating per D-12). Where the two files differ, the AGENT companion's verified findings win.

---

## Summary (what the planner needs to know)

This phase is **validation, not refactoring**, with two sanctioned result-changing exceptions. The work decomposes into a clear, dependency-ordered sequence the CONTEXT already locks:

1. **D-07: Golden-path Decimal cleanup lands FIRST** (before any cross-validation), so float-rounding can never be misattributed to a reference engine. → `REFREEZE-M5C-DECIMAL` (D-08).
2. **Add pinned dev-deps + build `scripts/cross_validate.py`** (D-10) that force-matches `backtesting.py` + `backtrader` (+ optional `nautilus_trader`) to iTrader's exact semantics (D-01) and emits a committed reconciliation report (suggested `tests/golden/CROSS-VALIDATION.md`).
3. **Reconcile** at trade-level primary + metric-level secondary (D-02/D-04); root-cause every divergence (D-05). If a divergence traces to a genuine iTrader bug → fix it → its own named re-freeze.
4. **Freeze the final oracle** (D-11: the existing `tests/golden/*` set, post-cleanup-and-any-fix) and **verify the program definition-of-done** (D-13).

**The single biggest force-match landmine:** both gating engines, by default, round position size to **whole units**. BTC at ~$10k–$60k with $10k cash means a 95%-of-equity position is a *fractional* quantity (e.g. 0.25 BTC). If an engine floors to integer units it buys **0 BTC → zero trades**, and cross-validation silently produces a meaningless "0 vs 134" mismatch. The fix differs per engine (see §1) — this MUST be handled explicitly or the whole comparison is void.

**The single biggest near-zero-divergence lever (D-03):** feed all engines the **identical `ta`-computed SMA/MACD series** that iTrader uses, rather than each engine's native indicators. This collapses indicator-library divergence to zero, so any remaining trade-timing gap is purely engine order/fill/sizing semantics — exactly what D-01 wants isolated ("divergence should be near-zero, so any gap is a real finding").

---

## Current frozen reference (the reconciliation target)

From `tests/golden/summary.json` (frozen at Phase 7 re-freezes REFREEZE-M5B-DIRECTION + REFREEZE-M5B-INCREASE):

| Metric | Value |
|--------|-------|
| `trade_count` | **134** |
| `final_equity` / `final_cash` | **46189.87730727451** |
| `total_realised_pnl` | 36189.87730727451 |
| `starting_cash` | 10000.0 |
| `cagr` | 0.19910032815485068 |
| `max_drawdown` | -0.5382568231814071 |
| `profit_factor` | 1.291149869385797 |
| `sharpe` | 0.6583614133806533 |
| `sortino` | 1.0385040387966196 |
| `win_rate` | 0.3656716417910448 |
| window | 2018-01-01 → 2026-06-03, BTCUSD 1d |

These are the **D-04 headline metric set**. `trades.csv` (entry/exit dates + sides) is the **D-02 trade-level** target.

> **NOTE — DoD test count is stale.** CONTEXT/REFACTOR-BRIEF say "274 component tests." The live suite now collects **716 tests** (`poetry run pytest --collect-only -q` → "716 tests collected"). The planner's D-13 acceptance criterion must assert **the full live suite green**, not a hardcoded 274. Verify the real count at plan time and state it as "all collected tests pass (currently 716)".

---

## Force-match config: iTrader's exact rules (D-01)

Source of truth = `scripts/run_backtest.py` + `SMA_MACD_strategy.py`:

- **Data:** `data/BTCUSD_1d_ohlcv_2018_2026.csv`, window 2018-01-01 → 2026-06-03, BTCUSD 1d.
- **Capital:** start cash **$10,000**, **fees 0**, **slippage 0**.
- **Sizing:** `FractionOfCash(Decimal("0.95"))` — 95% of cash. `allow_increase=False` (no pyramiding) → a single long position at a time, entered from flat. `LONG_ONLY`.
- **Fills:** **next-bar-open** (Phase 6 convention) — a signal computed on the last completed bar `T` fills at bar `T+1`'s open.
- **Indicator params:** SMA short=50, long=100; MACD FAST=6, SLOW=12, WIN=3 (`ta.trend.SMAIndicator`, `ta.trend.MACD`, `macd_diff()` = the histogram).
- **THE QUIRK (must replicate exactly):** in `SMA_MACD_strategy.generate_signal`, the exit `elif` is **nested inside** the `if short_sma.iloc[-1] >= long_sma.iloc[-1]:` filter block. So the `SMA(50) >= SMA(100)` filter gates **BOTH** the MACD-up-cross entry **AND** the MACD-down-cross exit. When the filter is False, a held long is **NOT** exited on a MACD down-cross — it stays open until a later bar where the filter is True and a down-cross occurs. This is not standard crossover logic and must be coded verbatim into each reference engine's `next()`/`notify` logic.
  - Entry: `short_sma[-1] >= long_sma[-1]` AND `MACDhist[-1] >= 0` AND `MACDhist[-2] < 0` → buy.
  - Exit: `short_sma[-1] >= long_sma[-1]` AND `MACDhist[-1] <= 0` AND `MACDhist[-2] > 0` → close.
  - Minimum bars: `len(bars) < max(long_window, 100)` → no signal (warm-up).

### `backtesting.py` (gating) **[doc-confirmed]**

- **Use `FractionalBacktest`, not `Backtest`** — `from backtesting.lib import FractionalBacktest`. It is a drop-in that internally rescales prices to permit fractional BTC units. Plain `Backtest` floors to whole units → 0 BTC → 0 trades (the landmine). Set `fractional_unit` small enough for BTC (default 1 satoshi = `1/100e6`; `1/1e6` μBTC is plenty).
- Constructor kwargs that map iTrader's rules:
  - `cash=10_000`
  - `commission=0.0`, `spread=0.0`  → zero fees/slippage
  - `margin=1.0` → no leverage (full cash required)
  - `trade_on_close=False` → **fill at next bar open** (this is the default; matches D-01) ✓
  - `exclusive_orders=True` → each new order closes the previous; combined with only-buy-when-flat logic this enforces `allow_increase=False` single-position.
  - `finalize_trades=True` → so a still-open trade at the end is closed and counted (match iTrader's end-of-run handling — **confirm against how iTrader counts a final open position**; iTrader's 134 is closed trades, so check whether the run ends flat or with an open position. If iTrader leaves a final position open and excludes it from `trades.csv`, set `finalize_trades=False` to match).
- Strategy shape: register the **iTrader-`ta` SMA/MACD arrays** via `self.I(...)` (precomputed, see §2). Entry `self.buy(size=0.95)` (fraction of equity); exit `self.position.close()`. Implement the filter-gates-both quirk literally in `next()`.
- Trade log: `stats = bt.run()`; `stats['_trades']` is a DataFrame with `Size, EntryBar, ExitBar, EntryTime, ExitTime, EntryPrice, ExitPrice, PnL, ...`. Equity curve: `stats['_equity_curve']` DataFrame with an `Equity` column.
- **Do NOT trust `stats['Sharpe Ratio']` / `CAGR [%]` for reconciliation** — backtesting.py annualizes with its own convention (not necessarily PERIODS=365). Recompute metrics from `stats['_equity_curve']['Equity']` through iTrader's own `itrader/reporting/metrics.py` so the comparison is apples-to-apples (see §4).

### `backtrader` (gating) **[doc-confirmed]**

- **Fractional landmine again:** the built-in `bt.sizers.PercentSizer(percents=95)` casts size to **`int`** → 0 BTC → 0 trades. **Write a custom fractional sizer** that returns `0.95 * cash / price` as a **float** (backtrader accepts float sizes if the sizer returns a float; it only floors because PercentSizer chooses to). Subclass `bt.Sizer._getsizing`.
- Broker: `cerebro.broker.setcash(10000)`; `cerebro.broker.setcommission(commission=0.0)` → zero fees.
- **Fills:** backtrader's default is **next-bar-open** for a market order issued in `next()`. Keep `set_coc(False)` and `set_coo(False)` (defaults) — do **not** enable cheat-on-open/close. ✓ matches D-01.
- Strategy: feed the iTrader-`ta` SMA/MACD as **extra data lines** on a `bt.feeds.PandasData` subclass (precomputed columns), or compute the cross from those arrays inside the strategy. Implement filter-gates-both literally. Long-only: only `self.buy()` (custom-sized) when flat; `self.close()` to exit.
- Trade log: capture per-trade entry/exit in `notify_trade(self, trade)` (`trade.dtopen`, `trade.dtclose`, `trade.barlen`, `trade.pnl`) or via `bt.analyzers.TradeAnalyzer` (aggregate). For trade-level D-02 alignment you need per-trade open/close datetimes → collect them in `notify_trade` into a list. Equity curve via a custom observer or `bt.analyzers.TimeReturn` / track `self.broker.getvalue()` each `next()`.
- **COMPAT RISK [verify at impl-time]:** `backtrader` (PyPI `1.9.78.123`, effectively unmaintained) predates numpy 2.x and Python 3.13. The repo uses this stack (numpy 2.2.6, Python 3.13.1). Importing/running backtrader may hit removed numpy aliases (`np.bool`, `np.float`, `np.int`) or `collections`/`inspect` deprecations. Mitigations the planner should plan for: pin a version known to work, OR apply a small compat shim, OR use a maintained fork (`backtrader2` / `backtrader_next`). **Validate `import backtrader` runs end-to-end on this interpreter early — make it the first task after adding the dep, before building the whole harness.**

### `nautilus_trader` (optional, NON-gating — D-12) **[verify at impl-time]**

- Much heavier model: `BacktestEngine` + explicit `Venue`, `Instrument` (a `CurrencyPair`/crypto instrument), `BarSpecification`/`BarType`, account/fill config. Exact force-match of D-01 is harder (instruments/venues/fill model), which is **exactly why D-12 keeps it non-gating** — it must never stall the freeze.
- Recommendation: implement it **last**, in its **own module**, behind a flag/try-guard so install or config friction degrades gracefully (report "Nautilus: not reconciled — {reason}" rather than failing the run). Pin a recent version. Heavy Rust-backed install — confirm it installs on this machine before committing to it. If it force-matches cleanly, include it in the report as a third confirming reference; if not, document the config gap and move on.

---

## Trade-level reconciliation mechanics (D-02 / D-03)

**Recommendation — eliminate indicator divergence at the source (D-03):**
1. Compute SMA(50), SMA(100), and MACD-histogram(6,12,3) **once** with iTrader's exact `ta` calls on the full BTCUSD close series (replicating `SMA_MACD_strategy` — `ta.trend.SMAIndicator(...).sma_indicator()`, `ta.trend.MACD(...).macd_diff()`).
2. Feed those **identical** arrays into every engine (`self.I(...)` for backtesting.py; extra `PandasData` lines for backtrader; precomputed columns for nautilus). No engine computes its own SMA/MACD.
3. Result: every engine's *signal* logic is byte-identical to iTrader's; the only thing under test is fill/sizing/equity mechanics. Per D-01 this should drive divergence to near-zero, so any gap is a genuine finding (D-05), not "expected indicator difference."

> The CONTEXT (D-03) leaves "engine-native vs injected indicators" to the planner. The injected-`ta` path is strongly recommended: it is the only way to honor D-01's "near-zero divergence so any gap is a real finding" and D-02's trade-level-primary gate. Engine-native indicators would re-introduce the 5th–6th-decimal crossover differences D-03 warns about and make a clean trade-for-trade match unachievable.

**Comparable trade-log extraction (align to `tests/golden/trades.csv`):**
- iTrader side: already in `tests/golden/trades.csv` — entry_date, exit_date, side, plus avg_bought/avg_sold and realised_pnl + the D-17 slippage columns. Read this directly.
- backtesting.py: `stats['_trades']` → map `EntryTime`/`ExitTime` to bar dates, `Size>0` = LONG.
- backtrader: list assembled in `notify_trade` → `dtopen`/`dtclose`.
- Build one reconciliation table keyed by trade index: entry bar, exit bar, side, per engine. Flag any row where trade count differs or an entry/exit bar shifts. Per D-02, a `±1-bar` shift is tolerated ONLY if traced to a specific indicator-boundary rounding cause (which the injected-`ta` approach should eliminate entirely — if it persists, it is a finding).

**Pass criterion (D-02 + D-04):**
- Primary: same trade count (134) + matching entry/exit bar timing across engines.
- Secondary: headline metrics within ~1% (tighter if timing matches exactly; a documented, fully-attributed ±1-bar shift may diverge more but the excess must be entirely explained by the shifted trade's bar volatility).
- A compensating-errors structure must not pass — that is why trade-level is primary.

---

## D-06 Golden-path float→Decimal cleanup (lands FIRST, D-07)

**Exact targets (from `.planning/codebase/CONCERNS.md` "Float Leaks at Portfolio Property Boundary" + confirmed against source):**

`itrader/portfolio_handler/portfolio.py` — five properties currently `-> float`, each wrapping a Decimal source in `float(...)`:
- L223/230 `total_market_value` → `float(self.position_manager.get_total_market_value())` (source is Decimal)
- L233/240 `total_equity` → `self.total_market_value + float(self.cash)` (cash is already Decimal via `cash_manager.balance`)
- L243/245 `total_unrealised_pnl` → `float(self.position_manager.get_total_unrealized_pnl())`
- L248/250 `total_realised_pnl` → `float(self.position_manager.get_total_realized_pnl())`
- L253/257 `total_pnl` → `self.total_unrealised_pnl + self.total_realised_pnl`
- **Fix:** change return types to `Decimal`, drop the `float(...)` casts, keep aggregation in Decimal (`total_equity = total_market_value + self.cash`; `total_pnl = total_unrealised_pnl + total_realised_pnl`). The underlying `position_manager.get_total_*` already return Decimal, so this is removing coercions, not adding conversions.

`itrader/portfolio_handler/metrics/metrics_manager.py` — Decimal→float coercions (CONCERNS lines ~195,200,279,326,327,501,502):
- `_get_latest_metrics()` builds a dict with `float(latest_snapshot.total_equity)`, `float(...cash_balance)`, `float(...positions_value)`, `float(...unrealized_pnl)`, `float(...realized_pnl)`, `float(...total_pnl)`, `float(...portfolio_return)`.
- `_calculate_max_drawdown()` / `_calculate_performance_metrics()` build `equity_values = [float(s.total_equity) ...]` then do float ratio math.
- **Decision the planner must make (and record in the re-freeze note):** money fields (equity, cash, pnl) should stay Decimal end-to-end; but the **derived ratios** (drawdown %, returns, Sharpe/Sortino/CAGR) are inherently float statistics computed in numpy — those legitimately stay float. The cleanup is about **money on the result-bearing path**, not forcing Decimal into the statistical ratio math. Keep the float boundary *at the metric computation input* (e.g. `equity_series.astype(float)` feeding `compute_returns`), not at the Portfolio property.

`itrader/order_handler/order_validator.py` — `EnhancedOrderValidator` float comparisons (CONCERNS lines ~200,211,314,336,438,439,478): `float(order.price)` / `float(order.quantity)` cash-sufficiency checks ("float-domain until M4"). **Fix:** compare in native Decimal (`order.price`, `order.quantity`, portfolio cash/equity are Decimal). Only fix the comparisons that touch the **golden/result-bearing path** (D-06 scope) — i.e. ones that can change which orders pass validation on the SMA_MACD golden run. A validator change that flips an admit/reject decision *would* change results; one that is arithmetically inert would not.

**Serialization / representation change (drives the D-08 re-freeze):**
- `scripts/run_backtest.py::build_summary` reads `float(portfolio.total_equity)` and `float(portfolio.cash)`. Once the properties return Decimal, this becomes `float(Decimal(...))`. **Key question:** does `float(Decimal("46189.87730727451"))` reproduce the current `46189.87730727451`, or does Decimal precision shift the value? The whole point of D-06 is that Decimal arithmetic avoids the float rounding accumulated over thousands of bars — so the value **likely shifts** (CONTEXT D-08 anticipates this). If it shifts → `REFREEZE-M5C-DECIMAL` with an expected-diff note. If byte-exact inert → no re-freeze needed (D-08 allows this).
- `build_equity_curve` / `EQUITY_COLUMNS` produce the `total_equity` column for `equity.csv`. If the Portfolio property type changes, confirm the equity-curve frame dtype/serialization (the `FLOAT_FORMAT="%.10f"` pin) still produces stable bytes; decide whether the equity curve serializes from Decimal→str or Decimal→float.
- **`mypy --strict` / `filterwarnings=["error"]` traps:** changing return types from `float` to `Decimal` will surface every caller that does `float + Decimal` mixed arithmetic or passes the property where a float is expected → mypy errors + possible `TypeError`s. The planner should expect a **propagation sweep** of callers (reporting, validator, any consumer reading `total_equity`). Run `make typecheck` (= `poetry run mypy itrader`) after the retype and fix the fan-out. Confirm `--strict` is configured in `[tool.mypy]` of `pyproject.toml`.

**Sequencing (D-07):** Decimal cleanup → regenerate oracle (`make backtest`) → decide/execute `REFREEZE-M5C-DECIMAL` → ONLY THEN run cross-validation against the clean numbers.

---

## Cross-validation harness shape (D-10)

**Recommended structure:**
- `scripts/cross_validate.py` (new code → **4-space indent**, per CLAUDE.md "new scripts use spaces").
- One orchestrator script that imports one module per engine (e.g. `scripts/crossval/backtesting_py_run.py`, `scripts/crossval/backtrader_run.py`, `scripts/crossval/nautilus_run.py`) so each engine's force-match config is isolated and individually testable, and a missing/failing optional engine (nautilus) degrades gracefully. Keeps the script readable and the numpy-2/backtrader compat risk contained to one module.
- Inputs: reads `data/BTCUSD_1d_ohlcv_2018_2026.csv` and the frozen `tests/golden/{trades.csv,summary.json,equity.csv}` for the iTrader side. Precomputes the shared `ta` indicator arrays once and passes them to every engine.
- Each engine module returns `(trade_log_df, equity_curve_series)`; the orchestrator runs all three through iTrader's `itrader.reporting.metrics` to compute the headline set on identical formulas, builds the reconciliation table, and root-causes divergences.
- **Output (committed evidence):** `tests/golden/CROSS-VALIDATION.md` — a reconciliation table (per-engine trade count + headline metrics vs iTrader frozen) + a per-divergence root-cause section (D-05 dispositions: iTrader-bug-fixed / legitimate-reference-difference-documented). This is **evidence, not the oracle** (D-11).
- **NOT wired into `make test` / CI** (D-10) — the frozen `tests/golden/*` + the existing run-path integration test remain the permanent regression gate. Add the reference engines to the **poetry dev group** only.
- **`filterwarnings=["error"]` isolation:** the test suite sets `filterwarnings=["error", "ignore::UserWarning", ...]`. Importing backtesting.py (bokeh) / backtrader (numpy-2 deprecations) / nautilus could emit warnings. Because the harness is a **script, not a test**, it is outside pytest's filter — confirmed safe per D-10. Do **not** import these engines anywhere under `tests/` or in any module imported at test-collection time.

**Version pins (poetry dev group — pin exact for reproducibility, D-10) — VERIFIED in `08-RESEARCH-AGENT.md`:**
- `backtesting==0.6.5` — verified to install + run `FractionalBacktest` on this stack.
- `backtrader==1.9.78.123` — verified to import + run a full backtest on py3.13.1/numpy 2.2.6 under warnings-as-errors; **NO fork needed** (do not use `backtrader_next`/`backtrader2` — different import names / divergent API).
- `nautilus-trader==1.227.0` — optional/non-gating; PyPI metadata verified compatible (`requires_python <3.15,>=3.12`, numpy/pandas satisfied), prebuilt wheel; not run end-to-end (acceptable per D-12).

---

## Definition-of-Done verification (D-13)

Concrete checks the verification task must run (all must pass for the program-level DoD):

| DoD item | Command / check |
|----------|-----------------|
| SMA_MACD runs end-to-end, non-trivial trade log + equity curve | `make backtest` → `output/{trades.csv,equity.csv,summary.json}`; assert `trade_count` non-trivial (≈134) + equity curve has many points |
| `mypy --strict` clean | `make typecheck` (= `poetry run mypy itrader`); confirm `--strict` in `[tool.mypy]` |
| **No float money** | grep the golden path for residual `float(` on money members; assert `Portfolio.total_*` return `Decimal`; assert validator cash checks are Decimal. (Live-mode `TradingInterface` leaks are explicitly OUT — D-09/D-live.) |
| Single UUIDv7 scheme | confirm `idgen`/`uuid-utils` is the only ID source (no `uuid.uuid4`/`uuid1` in result path) |
| Deterministic | double-run byte-identical: `make backtest` twice → `diff` the two `output/` sets (or re-run vs `tests/golden/*` for the frozen run) |
| Full suite green under strictness | `make test` (`poetry run pytest tests/ -v`) — currently **716 tests** (verify live; do not hardcode 274) |
| Run-path integration test | the existing byte-exact integration test that diffs a fresh run against `tests/golden/*` — must pass against the FINAL frozen oracle |

---

## Re-freeze discipline (inherited law — Phase 6 D-21 / Phase 7 D-11)

Every result-changing event lands as a **named re-freeze note** with an expected-diff explanation + owner sign-off. Precedent files to mirror in `tests/golden/`: `REFREEZE-M5A.md`, `REFREEZE-M5B-DIRECTION.md`, `REFREEZE-M5B-INCREASE.md`, `REFREEZE-06-04.md`. Phase 8 may produce up to two such events:
1. `REFREEZE-M5C-DECIMAL` (D-08) — the Decimal cleanup (if the value shifts).
2. (Conditional) a `REFREEZE-M5C-<bugname>` if a cross-validation divergence traces to a real iTrader bug (D-05).
The **last frozen state is the final authoritative oracle** — the program definition of done.

---

## Validation Architecture

This phase is itself a validation milestone; its Nyquist-style validation coverage maps directly onto the success criteria.

**Critical behaviors to sample (and how each is observed):**
- **Money correctness (D-06):** every golden-path money member returns Decimal; the regenerated oracle is either byte-identical or re-frozen with an attributed diff. Observed via: type assertions on `Portfolio.total_*`, `make typecheck`, and a before/after `summary.json` diff.
- **Engine fidelity (D-01/D-02):** the SMA_MACD filter-gates-both quirk and next-bar-open fills are replicated; trade count + entry/exit timing match across engines on identical injected `ta` indicators. Observed via: the `CROSS-VALIDATION.md` reconciliation table.
- **Divergence accounting (D-05):** zero unexplained divergences; each is either fixed (iTrader bug → re-freeze) or documented (legitimate reference difference). Observed via: the per-divergence root-cause section.
- **Determinism (D-13):** double-run byte-identical. Observed via: diff of two `make backtest` runs.
- **Regression lock (D-10/D-11):** the frozen `tests/golden/*` + run-path integration test are the permanent gate; reference engines are dev-only and never in `make test`.

**Sampling adequacy:** the single golden strategy + single symbol (BTCUSD) is the intended scope (multi-strategy/multi-symbol deferred). Adequacy comes from *trade-level* granularity (134 trades, each entry/exit bar checked) rather than breadth — this is the correct Nyquist rate for a single deterministic reference run.

---

## Risks & landmines (ranked)

1. **Fractional units → 0 trades** (both gating engines). MUST use `FractionalBacktest` (backtesting.py) and a custom float sizer (backtrader). If unhandled, comparison is void. **[highest]**
2. ~~**backtrader × numpy 2.x / Python 3.13 import failure.**~~ **RESOLVED — see `08-RESEARCH-AGENT.md` headline #1.** The connectivity-restored re-run empirically installed and ran plain `backtrader==1.9.78.123` to completion on this exact stack (py3.13.1 / numpy 2.2.6 / pandas 2.3.3) under `warnings.simplefilter("error")`, clean — backtrader uses `array.array`, not numpy, for line buffers, so the numpy-2 alias removals never bite. No fork/shim needed; pin `1.9.78.123`. 08-04 keeps the import/run smoke gate as a confirmation, not a risk. **[was high → now low/resolved]**
3. **Misattributing indicator-library divergence as engine difference** (D-03). Mitigate by injecting identical `ta` series into all engines. **[high]**
4. **Decimal retype fan-out** breaking `mypy --strict` / mixed Decimal+float arithmetic across reporting/validator callers. Budget a propagation sweep. **[med]**
5. **Trusting engine-native annualized metrics** (different period/ddof conventions) instead of recomputing via iTrader's `metrics.py`. Always recompute apples-to-apples. **[med]**
6. **Final-open-trade counting mismatch** (`finalize_trades` in backtesting.py vs how iTrader's 134 counts a possibly-open final position). Confirm iTrader's end-of-run handling and match it. **[med]**
7. **nautilus install/config friction stalling the freeze** — keep non-gating, behind a guard, implemented last (D-12). **[low]**
8. **Importing reference engines into the test path** would break `filterwarnings=["error"]`. Keep them script-only (D-10). **[low]**

---

## Suggested plan decomposition (for the planner — not binding)

- **Wave 1 (must precede cross-validation, D-07):** Golden-path Decimal cleanup (Portfolio properties → MetricsManager coercions → validator checks → caller fan-out), regenerate oracle, `REFREEZE-M5C-DECIMAL` if shifted. → mypy + suite green.
- **Wave 2:** Add pinned dev-deps; validate each engine imports/runs on this interpreter (esp. backtrader). Build the shared `ta`-indicator precompute + the per-engine force-match modules (backtesting.py first, backtrader second, nautilus optional/last).
- **Wave 3:** `scripts/cross_validate.py` orchestrator → reconciliation table + `tests/golden/CROSS-VALIDATION.md`; root-cause each divergence (D-05); conditional bug-fix re-freeze.
- **Wave 4:** Freeze final oracle (D-11) + run the full D-13 definition-of-done gate.

Requirement **M5-10** is covered end-to-end by Waves 2–4; the D-13 DoD gate spans the whole phase.
