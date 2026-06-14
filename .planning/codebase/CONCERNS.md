# Codebase Concerns

**Analysis Date:** 2026-06-14

> **Scope note.** iTrader is a deliberate brownfield refactor whose *Definition of Done* is the
> **backtest path only** (`SMA_MACD` on the golden BTCUSD CSV). The vast majority of concerns below
> live on **deferred subsystems** (live trading, SQL persistence, CCXT/OANDA providers,
> `my_strategies/`, screeners) that are intentionally out of scope and gated behind `mypy`
> `ignore_errors` overrides. These are RECORDED, not silently suppressed — each carries an owning
> milestone. The backtest path itself is regression-locked by a byte-exact golden master
> (post-v1.3: **134 trades / `final_equity 53229.68512642488`**). Priorities reflect that the
> golden path is trustworthy and the debt is concentrated off it.

## Tech Debt

**Deferred order persistence (live):**
- Issue: `PostgreSQLOrderStorage` is a pure stub — every method raises `NotImplementedError("...Phase 2")`. Live order persistence does not exist.
- Files: `itrader/order_handler/storage/postgresql_storage.py` (all 57 lines)
- Impact: Live mode cannot persist or recover the order mirror; only `in_memory` storage works (backtest is fine).
- Fix approach: Implement the `OrderStorage` interface against SQLAlchemy when the persistence/live milestone (D-sql / D-live) is scheduled. Tracked as `FIX-LIST.md::FL-05` (deferred → v1.3+, still open).

**OANDA provider unfinished:**
- Issue: Provider carries untranslated Italian TODOs and uncertain init logic (`#TODO: da modificare`, `#TODO: da vedere se serve`).
- Files: `itrader/price_handler/providers/oanda_provider.py:36,74`
- Impact: OANDA ingestion is not trustworthy at boundary conditions; off the reference path.
- Fix approach: Finish + test when multi-asset / OANDA ingestion is scheduled. Tracked as `FIX-LIST.md::FL-07` (deferred).

**Stranded `long_only` compliance TODO duplicated across strategies:**
- Issue: The same `# TODO: da spostare in order_handler.compliance` note is copy-pasted per strategy; compliance logic belongs in the order handler, not each strategy.
- Files: `itrader/strategy_handler/my_strategies/momentum/ATR_Hawkes_Momentum_strategy.py:129`, `itrader/strategy_handler/my_strategies/scalping/RSI_scalping_strategy.py:56`, `itrader/strategy_handler/my_strategies/scalping/VWAP_BB_RSI_scalping_strategy.py:38,57`, `itrader/strategy_handler/my_strategies/scalping/Stoch_RSI_Keltner_strategy.py:67`
- Impact: Compliance rules are scattered and unenforced for non-reference strategies. `my_strategies/*` is flagged in `STATE.md` as user-relocated (OUT of scope).
- Fix approach: Centralize a compliance gate in `order_handler/admission/`. Tracked as `FIX-LIST.md::FL-08` (deferred → OUT / compliance milestone).

**Order state-change persistence undecided (live):**
- Issue: `# TODO: check if i have to store the state changes permanently in sql when in live trading`.
- Files: `itrader/order_handler/order.py:328`
- Impact: `state_changes` accumulate in-memory only; no durable audit trail in live mode.
- Fix approach: Decide + wire durable state-change persistence with the live/SQL milestone.

**Single-instrument money scale registry:**
- Issue: Only `BTCUSD` has a money-scale override; a general per-token registry is explicitly deferred because the golden dataset is BTCUSD-only.
- Files: `itrader/core/money.py:21-22,38-46` (`_INSTRUMENT_SCALES` / `_DEFAULT_SCALES`)
- Impact: Adding any non-BTCUSD instrument silently falls back to default scales (price/qty 8dp), which may mis-round real instruments (e.g. JPY pairs, equities).
- Fix approach: Build a per-instrument scale registry (config-driven) with the multi-asset milestone.

## Known Bugs

**SQL table-name injection (off backtest path):**
- Symptoms: `delete_all_tables` and `read_prices` string-interpolate / pass a raw `symbol` as the SQL table name — a malformed/hostile symbol is a SQL-injection vector.
- Files: `itrader/price_handler/store/sql_store.py:28` (`delete_all_tables`), `:60` (`read_prices`)
- Trigger: Any symbol value reaching the SQL price store that is attacker- or typo-controlled.
- Workaround: SQL store is `ignore_errors`-deferred (D-sql) and not on the run path; CSV store (`csv_store.py`) is used for backtest. Tracked as `FIX-LIST.md::FL-06` (deferred → v1.3+). See Security below.

**Screener window-arg bug + untested timing path:**
- Symptoms: `volume_spyke` SMA "non prende window come argomento" (window arg not applied); `screeners/base.py` `to_timedelta(frequency)` marked untested.
- Files: `itrader/screeners_handler/screeners/volume_spyke.py:40`, `itrader/screeners_handler/screeners/base.py:29`
- Trigger: Running the (deferred) screener subsystem.
- Workaround: Screeners are a deferred subsystem (`screeners_handler.*` under `mypy ignore_errors`); not exercised on the backtest path. Tracked as `FIX-LIST.md::FL-09` (deferred → screener milestone).

## Security Considerations

**SQL injection via symbol → table name:**
- Risk: See "Known Bugs" above — raw symbol used as a table identifier in DDL/DML.
- Files: `itrader/price_handler/store/sql_store.py:28,60`
- Current mitigation: Module is deferred and not on the run path; backtest uses CSV. No production exposure today.
- Recommendations: Validate/whitelist symbols and use a fixed schema with parameterized columns (never identifier interpolation) before any live SQL use.

**Secrets in `.env` and `oanda.cfg`:**
- Risk: DB URLs and exchange API credentials live in `.env` (loaded by `Makefile` via `include .env`) and an `oanda.cfg` referenced by the OANDA provider.
- Files: `.env` (repo root), `oanda.cfg` (referenced by `itrader/price_handler/providers/oanda_provider.py`)
- Current mitigation: `.env`/settings are gitignored in production; `pydantic-settings` reads `ITRADER_`-prefixed vars (`itrader/config/settings.py`).
- Recommendations: Confirm `.env` and `oanda.cfg` are never committed; move live secrets to a secret manager before live deployment.

**Broad `RuntimeError` re-raise masks provider error class (low risk):**
- Risk: CCXT provider catches `except Exception` and re-raises as a generic `RuntimeError`, losing the original error type/context for callers.
- Files: `itrader/price_handler/providers/ccxt_provider.py:35`
- Current mitigation: Specific `ccxt.NetworkError`/`ccxt.ExchangeError` are caught first; the broad arm is the fallthrough. Off the backtest path.
- Recommendations: Preserve the original exception via `raise ... from e` and a typed `DataError` when the provider is hardened.

## Performance Bottlenecks

**No retry / timeout / rate-limit backoff in data download providers:**
- Problem: Transient network/exchange failures bail rather than retry; long downloads can fail near the end and restart from scratch.
- Files: `itrader/price_handler/providers/ccxt_provider.py`, `itrader/price_handler/providers/oanda_provider.py`
- Cause: Single-shot request loops with no backoff/resume.
- Improvement path: Add bounded exponential backoff + per-symbol checkpointing during the (deferred) live/ingestion milestone. Tracked as `FIX-LIST.md::FL-10` (deferred → live).

> Note: The backtest run path itself is performance-conscious by design — `BacktestBarFeed`
> precomputes resampled frames once and uses `searchsorted` per tick (zero per-tick resample,
> per ARCHITECTURE.md). No backtest-path performance concern was identified.

## Fragile Areas

**Fill-reconciliation / reservation-release path (FRAGILE-zone):**
- Files: `itrader/order_handler/reconcile/reconcile_manager.py` (354 lines), `itrader/order_handler/order_manager.py`
- Why fragile: This is the load-bearing terminal-state reconciliation (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED) plus the idempotent reservation-release invariant. `STATE.md` explicitly flags it as the FRAGILE zone and co-phases all edits so `reconcile/` is touched once per re-baseline. A `should_release` arming mistake either double-releases or strands a reservation.
- Safe modification: Touch only under a single owner-gated re-baseline with cross-validation; preserve the `else: raise NotImplementedError` terminal-status fallthrough (`reconcile_manager.py:255`) that fails loud BEFORE `should_release` is armed rather than silently mis-reconciling as REFUSED.
- Test coverage: Covered by the integration oracle + e2e suite, but the path is intolerant of partial edits.

**Broad `except Exception` in domain handlers (by design, awareness-only):**
- Files: `itrader/portfolio_handler/portfolio_handler.py` (7 sites: `:166,206,348,375,484,495`), `itrader/execution_handler/exchanges/simulated.py:169,352`, `itrader/order_handler/{admission,lifecycle,brackets,reconcile}/*`, `itrader/trading_system/live_trading_system.py` (5 sites)
- Why fragile: Broad catches can mask programming errors. **This is intentional** per CLAUDE.md — the event loop must not stall, and all sites log with context. Note the run-mode policy split: backtest is fail-fast (`EventHandler._on_handler_error` re-raises), live is publish-and-continue.
- Safe modification: When already editing one of these handlers, narrow the catch to the specific domain exception. Do NOT do a blanket sweep — the broad-except policy is documented and not-to-be-relitigated (`CONVENTIONS.md`). Tracked as `FIX-LIST.md::FL-12` (awareness-only).

**Binance live streamer unbounded buffer:**
- Files: `itrader/price_handler/providers/binance_stream.py:43,175-176` (`completed_bars`)
- Why fragile: `completed_bars` is a plain list appended per completed bar with no size bound — unbounded memory growth in long-running live sessions.
- Safe modification: Replace with a bounded `collections.deque(maxlen=...)` or drain-and-clear when the streamer is hardened. Tracked as `FIX-LIST.md::FL-11` (deferred → live).

## Scaling Limits

**Single-symbol golden dataset / BTCUSD-only assumptions:**
- Current capacity: Backtest is validated and money-scale-tuned for BTCUSD only.
- Limit: Multi-asset / multi-currency portfolios are not exercised; money scales, universe membership, and screeners are single-asset-shaped today.
- Scaling path: Per-instrument money-scale registry (`core/money.py`), multi-asset universe + screener validation — scheduled for the N+2 margin/shorts/multi-asset milestone (Backlog 999.4).

**In-memory order + portfolio state (live):**
- Current capacity: Order mirror and portfolio state are in-memory; durable persistence is a stub.
- Limit: A live process crash loses all order/portfolio state; no recovery.
- Scaling path: Implement `PostgreSQLOrderStorage` + order state-change persistence with the live/SQL milestone.

## Dependencies at Risk

**`pandas-ta 0.4.71b0` (beta pin):**
- Risk: A beta-version dependency pinned exactly; underpins strategy filters / SLTP models.
- Impact: Supply-chain/stability risk; a yanked or breaking beta could break non-reference strategy code.
- Migration plan: Isolated to non-reference strategy code (not the `SMA_MACD` golden path). Re-evaluate / pin to a stable release when strategies are productionized. Tracked as `FIX-LIST.md::FL-14` (deferred → isolated).

**Third-party libs without type stubs:**
- Risk: `ta`, `pandas_ta`, `ccxt`, `pandas`, `scipy`, `plotly`, `sklearn`, `statsmodels`, `pytz`, `tqdm`, `yaml` are `ignore_missing_imports` in mypy.
- Impact: No type safety at these call boundaries; runtime type errors are not caught by `mypy --strict`.
- Migration plan: Acceptable trade-off (documented in `pyproject.toml:111-120`); add local stubs only if a boundary becomes a recurring bug source.

**`psycopg2-binary` for production:**
- Risk: `psycopg2-binary` is documented by upstream as unsuitable for production (binary wheel).
- Impact: Potential runtime issues under production load when SQL/live is enabled.
- Migration plan: Switch to `psycopg2` (source build) or `psycopg[binary]`/`psycopg` v3 when the persistence milestone lands.

## Missing Critical Features

**Live order persistence + recovery:**
- Problem: `PostgreSQLOrderStorage` is a stub; no durable order/portfolio state in live mode.
- Blocks: Crash-safe live trading and post-restart reconciliation.

**Offline ingestion pipeline:**
- Problem: `itrader/price_handler/ingestion.py` is a stub that raises loudly ("offline ingestion pipeline — deferred to the persistence milestone (D-sql)").
- Blocks: Provider → store data pipeline for refreshing/extending the price database.

**Centralized strategy compliance gate:**
- Problem: `long_only`/compliance checks are scattered as per-strategy TODOs (see Tech Debt).
- Blocks: Uniform admission/compliance enforcement across strategies.

## Test Coverage Gaps

**Live trading system + trading interface have zero test coverage:**
- What's not tested: The entire live path — threaded event processing, start/stop/status lifecycle, order creation/validation via the external-API bridge.
- Files: `itrader/trading_system/live_trading_system.py` (550 lines), `itrader/trading_system/trading_interface.py`
- Risk: The largest untested critical surface; live regressions are invisible. (No `tests/*live*` or `*trading_interface*` files exist.)
- Priority: Medium for now (off the backtest DoD path); High before any live deployment. Tracked as `FIX-LIST.md::FL-13` (deferred → live).

**Deferred subsystems untested:**
- What's not tested: CCXT/OANDA/Binance providers, SQL price store, screeners, `my_strategies/*`.
- Files: `itrader/price_handler/providers/*`, `itrader/price_handler/store/sql_store.py`, `itrader/screeners_handler/*`, `itrader/strategy_handler/my_strategies/*`
- Risk: Boundary bugs (provider retries, SQL injection, screener window arg) surface only when these are activated.
- Priority: Low until the owning milestone activates each subsystem.

**Custom indicator untested:**
- What's not tested: `ehlers_indicators` — module note literally says "TODO: to be tested."
- Files: `itrader/strategy_handler/my_strategies/custom_indicators/ehlers_indicators.py:228`
- Risk: Incorrect indicator output for non-reference strategies.
- Priority: Low (off reference path).

---

*Concerns audit: 2026-06-14*
