# Codebase Concerns

**Analysis Date:** 2026-06-10

## Tech Debt

**PostgreSQL order storage is an unimplemented placeholder:**
- Issue: `PostgreSQLOrderStorage` raises `NotImplementedError` from `__init__` and from every method. Live order persistence does not exist; orders do not survive a restart in live mode.
- Files: `itrader/order_handler/storage/postgresql_storage.py` (all methods, lines 14-57), wired via `itrader/order_handler/storage/storage_factory.py`
- Impact: Live trading silently degrades to in-memory order storage (`itrader/trading_system/live_trading_system.py:120-135` catches the `NotImplementedError` and falls back to `OrderStorageFactory.create('backtest')`). The fallback only logs a `warning`; a caller assuming durable orders gets none.
- Fix approach: Implement the `OrderStorage` interface against SQLAlchemy/`psycopg2` (the engine deps already exist for the price DB). This is the "Phase 2 / D-sql / D-live" deferred work tagged throughout the file.

**"da modificare / da testare / da spostare" Italian TODOs in deferred subsystems:**
- Issue: Provider and strategy modules carry untranslated, unresolved TODOs marking code that was never finished or validated (e.g. screener window arg not honoured, compliance logic living in the wrong layer).
- Files: `itrader/price_handler/providers/oanda_provider.py:36,74`, `itrader/price_handler/providers/ccxt_provider.py:57`, `itrader/screeners_handler/screeners/volume_spyke.py:40` ("non prende window come argomento"), `itrader/screeners_handler/screeners/base.py:29`, and ~5 `my_strategies/*` files with `# TODO: da spostare in order_handler.compliance`
- Impact: These subsystems (providers, screeners, `my_strategies`) are explicitly out of the backtest-correctness scope and are NOT exercised by the run path or tests. Latent bugs only surface if they are reactivated.
- Fix approach: Treat as quarantined. Before reusing any of these, port the `# TODO: da spostare` compliance logic into the `order_handler` admission/validation layer where it belongs.

**`order_manager.py` is a 1279-line god-module:**
- Issue: Largest source file by far (~2x the next). Carries signal-to-order, lifecycle, modify/cancel, bracket declaration, fill reconciliation, and reservation release in one class.
- Files: `itrader/order_handler/order_manager.py`
- Impact: High change-risk surface; the most fragile area in the engine (see Fragile Areas). Hard to reason about transactional consistency across the mirror + reservation + bracket state.
- Fix approach: Extract bracket lifecycle and fill-reconciliation into collaborators (the matching engine already proves the pure-component split works). Do this only against the golden-master oracle so behaviour stays locked.

## Known Bugs

(none currently open)

## Security Considerations

**Live order-storage fallback hides a durability gap:**
- Risk: When `SYSTEM_DB_URL` is unset (or PostgreSQL storage is unimplemented), live mode silently runs on in-memory order storage. A restart loses all orders.
- Files: `itrader/trading_system/live_trading_system.py:121-135`
- Current mitigation: A `logger.warning` ("orders will NOT survive a restart") is emitted (WR-10 deliberately avoids shipping a default connection string with embedded credentials — good).
- Recommendations: Make live mode fail-fast (refuse to start) when durable storage is required but unavailable, rather than degrading to a fallback a caller may not notice.

**Secrets are well-handled at config edges, but credential plumbing is unfinished:**
- Risk: DB/exchange auth is intentionally NOT wired through the typed config (`D-live` deferred). Credentials are read ad-hoc via `os.getenv("SYSTEM_DB_URL")` and an `oanda.cfg` file consumed by `tpqoa`.
- Files: `itrader/trading_system/live_trading_system.py:34`, `itrader/config/settings.py` (notes `SecretStr` masking but DB/exchange auth "NOT wired here"), `itrader/price_handler/providers/oanda_provider.py`
- Current mitigation: `config/settings.py` uses `pydantic` `SecretStr` (masks `repr`/`str`/`model_dump`); `full_event_handler.py:152` notes error events never log secrets; `.env` is gitignored.
- Recommendations: When D-live resumes, route all credentials through the `Settings` `SecretStr` layer instead of raw `os.getenv` / loose `.cfg` files.

## Performance Bottlenecks

**No significant hot-path bottleneck detected on the backtest run path:**
- Problem: The bar feed was explicitly engineered to avoid per-tick resampling ("precompute once, `searchsorted` per tick — zero per-tick resample").
- Files: `itrader/price_handler/feed/bar_feed.py` (notes the `to_megaframe` column-misalignment bug from the legacy path was fixed during the split)
- Cause: N/A — the look-ahead-safe window slice is O(1)-ish per tick by design.
- Improvement path: None required for the reference single-symbol golden run. Re-profile only if multi-symbol universes or finer timeframes are introduced.

## Fragile Areas

**Fill reconciliation + reservation release in `OrderManager`:**
- Files: `itrader/order_handler/order_manager.py` (`on_fill`/reconcile path, lines ~240-275 and the `finally` reservation-release block)
- Why fragile: A reconciliation that fails after a terminal status is set can leave the order mirror and/or the cash reservation inconsistent. The code is deliberately fail-fast and re-raises (WR-04), but it depends on a subtle `should_release` flag and an idempotent release-in-`finally` to avoid a "stuck reservation corrupts buying power for the whole run" (T-05-17).
- Safe modification: Never change the terminal-status / `should_release` / `finally`-release interplay without running the golden-master oracle. Preserve idempotency of `release`.
- Test coverage: Exercised by `tests/e2e/` (cash, sltp, admission) and `tests/integration/`; the invariant is delicate enough that any change needs the numerical oracle re-check.

**Broad `except Exception` at handler/event boundaries:**
- Files: `itrader/portfolio_handler/portfolio_handler.py` (8 sites), `itrader/order_handler/order_manager.py` (~9 sites), `itrader/execution_handler/execution_handler.py:74,90`, `itrader/trading_system/live_trading_system.py` (7 sites), `itrader/events_handler/full_event_handler.py:126`
- Why fragile: Catch-and-log without re-raise is intentional in *live* mode (publish-and-continue) and in `ExecutionHandler.on_order`/`on_market_data` (prevent queue stalls), but the same pattern can mask real defects. Backtest paths must re-raise (fail-fast); a copy-paste of a live `except` into a backtest path would silently corrupt results.
- Safe modification: Verify the error policy for the file's run mode before editing — backtest = fail-fast (`_on_handler_error` re-raises), live = publish-and-continue.
- Test coverage: Error-policy behaviour is covered for the event handler; per-handler swallow paths are less directly tested.

**Indentation split (tabs vs 4 spaces) is a latent diff hazard:**
- Files: handler/manager modules under `itrader/order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/` use **tabs**; `config/`, `core/`, `price_handler/feed/`, and `events_handler/events/` use **4 spaces**.
- Why fragile: A mixed-indentation edit in a tab file breaks the file (Python). Autoformatters are intentionally absent, so the guard is manual discipline only.
- Safe modification: Always match the indentation of the file being edited; never normalize.

## Scaling Limits

**Single shared `global_queue`, single-threaded backtest loop:**
- Current capacity: Designed for one reference symbol (`SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv`), single-threaded synchronous for-loop.
- Limit: All event throughput is serialized through one `queue.Queue` drained by one `EventHandler`. Large universes / high-frequency timeframes would serialize everything.
- Scaling path: Out of current scope (correctness-first refactor). Live mode already runs the drain on a background daemon thread; horizontal scaling would require partitioning the queue per symbol/portfolio.

## Dependencies at Risk

**Beta / pinned-pre-release TA libraries:**
- Risk: `pandas-ta 0.4.71b0` is a pinned beta; `nautilus-trader` is a non-gating reconciliation oracle.
- Impact: Beta TA functions back strategy filters and SLTP models; an upstream API change could silently alter indicator output. Only matters for `my_strategies/` and screeners (deferred), not the gating backtest path.
- Migration plan: Keep the exact pin. If reactivating affected strategies, validate indicator output against a known reference before trusting numbers.

**Stubless third-party libs deferred from `mypy --strict`:**
- Risk: `ta`, `pandas_ta`, `ccxt`, `pandas`, `scipy`, `sklearn`, `statsmodels`, `plotly`, `yaml`, `tqdm`, `pytz` are `ignore_missing_imports = true` (`pyproject.toml` mypy overrides).
- Impact: Type errors at these boundaries are invisible to the gate. New code touching these APIs is unprotected by static typing.
- Migration plan: Acceptable for now (no stubs available). Wrap third-party calls in typed adapters where they cross into strict-typed core code.

## Missing Critical Features

**Live execution path is broadly deferred (D-live):**
- Problem: `live_trading_system.py` and `trading_interface.py` are excluded from `mypy --strict` (`ignore_errors = true`); live statistics reporting was deleted with the legacy reporting subsystem and now only logs a warning (`live_trading_system.py:512-515`); Binance streaming is quarantined (`binance_stream.py` — "NOT imported on any run path").
- Blocks: Any real live trading. The framework's `Definition of Done` is backtest-correctness only; live is explicitly out of scope for this milestone.

**Screener / universe screening is a deferred subsystem:**
- Problem: `screeners_handler/*` is excluded from strict typing and has unresolved TODOs; only `universe/membership.py` has direct unit coverage (`tests/unit/universe/test_membership.py`).
- Blocks: Dynamic market screening on the TIME route. Not needed for the single-symbol reference run.

## Test Coverage Gaps

**Deferred subsystems have little-to-no test coverage:**
- What's not tested: live trading system, trading interface, screeners, providers (CCXT/OANDA/Binance), SQL stores, `my_strategies/*`.
- Files: `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`, `itrader/screeners_handler/`, `itrader/price_handler/providers/`, `itrader/price_handler/store/sql_store.py`, `itrader/strategy_handler/my_strategies/`
- Risk: Reactivating any of these without first adding tests would ship unverified code. Confirmed gaps: no `tests/**/*screen*`, no `tests/**/*live*`, no `tests/**/*interface*` files exist.
- Priority: Low while deferred; High before any of these re-enters the run path.

**The gating coverage is the golden-master, not line coverage:**
- What's not tested: There is no enforced line-coverage threshold; the real safety net is the numerical/behavioral oracle (`tests/golden/` — `summary.json`, `trades.csv`, `equity.csv`, `CROSS-VALIDATION.md`, multiple `REFREEZE-*.md`).
- Files: `tests/golden/`, plus `tests/unit/`, `tests/integration/`, `tests/e2e/` (~113 `test_*.py` files)
- Risk: Code outside the SMA_MACD backtest path can regress without tripping the oracle.
- Priority: Medium — acceptable given the milestone's correctness-of-one-path mandate, but be explicit that "green oracle" ≠ "fully covered codebase".

---

*Concerns audit: 2026-06-10*
