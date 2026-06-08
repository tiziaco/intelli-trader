# Codebase Concerns

**Analysis Date:** 2026-06-08

> **Context:** This framework just completed an 8-phase backtest-correctness refactor
> (all milestones M1–M5c done, 725 tests collected, `mypy --strict` clean across 151
> files). The historical pre-refactor catalog lives in
> `.planning/codebase/ARCHITECTURE-REVIEW.md` — **most of those 40 items were resolved
> across Phases 1–8**. This document records only concerns that are **still present in
> the current tree**. The dominant theme: the **backtest path is hardened and locked**,
> but the **live-trading and data-ingestion paths were explicitly out of refactor scope**
> and remain stubbed, untested, or fragile.

## Tech Debt

**PostgreSQL order storage is an unimplemented stub:**
- Issue: Every method raises `NotImplementedError("To be implemented in Phase 2")` /
  `"...will be implemented in Phase 2"`. The "Phase 2" referenced is a legacy plan, not
  the refactor's Phase 2. Live order persistence does not exist.
- Files: `itrader/order_handler/storage/postgresql_storage.py` (all 57 lines are stubs)
- Impact: `OrderStorageFactory.create('live', db_url)` produces an object that throws on
  first use. Live mode cannot persist or recover orders. Backtest (`in_memory`) is unaffected.
- Fix approach: Implement against the same `AbstractOrderStorage` contract the in-memory
  backend satisfies (`itrader/order_handler/storage/in_memory_storage.py`), reusing the
  SQLAlchemy 2.0 patterns already adopted in `itrader/price_handler/store/sql_store.py`.

**OANDA provider unfinished, carries untranslated TODOs:**
- Issue: `self.markets = self.exchange.load_markets() #TODO: da modificare` and
  `# TODO: da vedere se serve. In origine non c'era` — provider was partially migrated and
  never finished; comments are in Italian and non-actionable for future maintainers.
- Files: `itrader/price_handler/providers/oanda_provider.py:36`, `:74`
- Impact: OANDA data ingestion is not trustworthy; behavior at boundary conditions unverified.
- Fix approach: Finish the provider against the `AbstractDataProvider` seam used by
  `ccxt_provider.py`, translate/resolve the TODOs, add provider tests.

**`my_strategies/` carry a repeated stranded TODO ("move to order_handler.compliance"):**
- Issue: Five strategy files declare `long_only` / direction filtering inline with
  `# TODO: da spostare in order_handler.compliance` — an order-compliance concern that was
  never centralized. The logic is duplicated per strategy.
- Files: `itrader/strategy_handler/my_strategies/scalping/RSI_scalping_strategy.py:56`,
  `.../scalping/Stoch_RSI_Keltner_strategy.py:67`,
  `.../scalping/VWAP_BB_RSI_scalping_strategy.py:38,57`,
  `.../momentum/ATR_Hawkes_Momentum_strategy.py:129`
- Impact: Compliance rules (long-only, etc.) are scattered and inconsistently enforced; new
  strategies copy-paste the pattern. These strategies are outside the `SMA_MACD` reference path.
- Fix approach: Lift direction/compliance filtering into a single order-handler compliance
  layer (the existing `EnhancedOrderValidator` is the natural home).

**Stale screener/indicator TODOs:**
- Issue: `volume_spyke.py` notes `sma = volume.apply(overlap.sma, length=self.window) # TODO: non prende window come argomento` — a known-broken window argument; `screeners/base.py:29` `to_timedelta(frequency) #TODO: da testare`; `ehlers_indicators.py:228` `TODO: to be tested`.
- Files: `itrader/screeners_handler/screeners/volume_spyke.py:40`,
  `itrader/screeners_handler/screeners/base.py:29`,
  `itrader/strategy_handler/my_strategies/custom_indicators/ehlers_indicators.py:228`
- Impact: Screener/indicator correctness unverified; not on the backtest reference path.
- Fix approach: Add unit tests, fix the `volume_spyke` window-passing bug.

## Known Bugs

**SQL table-name injection in price store (live/offline path):**
- Symptoms: `delete_all_tables` builds DDL by string-formatting the symbol directly into the
  statement: `text(f'DROP TABLE IF EXISTS {"%s"};'%sym)`. `read_prices` passes the raw
  `symbol` straight into `pd.read_sql(symbol, ...)` as the table name.
- Files: `itrader/price_handler/store/sql_store.py:35` (delete), `:60` area (`read_prices`)
- Trigger: Any symbol value sourced from external/exchange input flows unsanitized into SQL.
  Also fragile: the `{"%s"}%sym` construction is convoluted and breaks if a symbol contains
  quotes/spaces.
- Workaround: Symbols are currently exchange-controlled, limiting exposure — but there is no
  enforced allowlist. This path is out of the backtest correctness scope (review item #26 was
  only partially addressed).

**Stale `pytest.skip` masks a now-passing test:**
- Symptoms: `tests/unit/core/test_enums.py:32` still skips with
  `pytest.skip("pending M2-07: FillStatus enum not added yet")`, but `FillStatus` was added in
  Phase 3 (`itrader/core/enums/execution.py:59`). The guarded assertions never run.
- Files: `tests/unit/core/test_enums.py:25-40`
- Trigger: Always — the `importorskip`/`getattr` fallback short-circuits silently.
- Workaround: None needed; remove the stale skip so the FillStatus case-insensitive parse
  assertions actually execute.

## Security Considerations

**SQL identifier interpolation (see Known Bugs above):**
- Risk: Table-name injection / DDL injection through unsanitized symbol strings.
- Files: `itrader/price_handler/store/sql_store.py`
- Current mitigation: Symbols originate from exchange APIs (not direct user input).
- Recommendations: Validate symbols against `[A-Za-z0-9_]` allowlist before use as a table
  name; use SQLAlchemy `quoted_name`/reflection instead of f-string DDL.

**Secrets handling:**
- Risk: Low. `.env` at repo root is loaded by the `Makefile`; `oanda.cfg` holds OANDA
  credentials. Both are environment/file based.
- Files: `.env` (gitignored), `oanda.cfg` (if present)
- Current mitigation: `settings/` and `.env` are gitignored; Pydantic `Settings` fail-loud
  on missing secrets (Phase 3 M2-06). No hardcoded secrets found in source.
- Recommendations: Ensure `oanda.cfg` is also gitignored; document required env vars.

## Performance Bottlenecks

No active hot-path bottlenecks in the backtest path — review items #4 (resampling per tick)
and #5 (RNG seeding, flat order index) were addressed in Phase 6 (precomputed frames, Bar
struct). Remaining considerations are confined to the unoptimized data-ingestion path:

**Data download has no rate-limit/backoff handling:**
- Problem: CCXT/OANDA providers issue requests in loops with no retry, timeout, or
  rate-limit backoff (`grep` for `retry|timeout|backoff|sleep` in
  `itrader/price_handler/providers/` returns nothing).
- Files: `itrader/price_handler/providers/ccxt_provider.py`,
  `itrader/price_handler/providers/oanda_provider.py`
- Cause: Synchronous fetch loops; on transient failure they bail (single `except Exception`
  at `ccxt_provider.py:35`) rather than retrying.
- Improvement path: Wrap fetches in bounded retry-with-backoff; honor CCXT `rateLimit`.
  (Review item #25 — only partially addressed; the Provider/Store/Feed split landed in
  Phase 6 but robustness did not.)

## Fragile Areas

**Live trading system + TradingInterface (zero test coverage):**
- Files: `itrader/trading_system/live_trading_system.py` (483 lines),
  `itrader/trading_system/trading_interface.py` (220 lines)
- Why fragile: The threaded live path has no tests (no `tests/**/*live*` or
  `*interface*` files exist). It catches `Exception` broadly at six sites
  (`live_trading_system.py:187,224,281,320,436`) and carries an open-ended
  `# TODO: Add more specific event type handling...` at `:197`. Start/stop/status
  lifecycle, the background processing thread, and `TradingInterface` order creation are
  unverified.
- Safe modification: Touch only when adding live-mode tests first. The backtest path
  (`backtest_trading_system.py`) is the locked, oracle-validated sibling — mirror its
  wiring, do not invent new control flow.
- Test coverage: None. This is the largest untested critical surface.

**Binance live streamer buffer ownership:**
- Files: `itrader/price_handler/providers/binance_stream.py:176`
- Why fragile: `self.completed_bars.append(...)` accumulates without an obvious bound;
  a code comment notes buffer-rebuild responsibility lives elsewhere ("D-live's"), which is
  not implemented. Unbounded growth risk in long-running live sessions (review item #25's
  "unbounded live memory" — unaddressed).
- Safe modification: Add a `maxlen`/eviction policy and a test before relying on it in live mode.

**Broad `except Exception` in domain logic:**
- Files: `itrader/order_handler/order_manager.py` (8 sites incl. `:246,435,491,711,1080,1171,1245`),
  `itrader/portfolio_handler/portfolio_handler.py` (7 sites),
  `itrader/execution_handler/exchanges/simulated.py:155,316`
- Why fragile: These are intentional (the event loop must not stall — documented in CLAUDE.md
  architecture notes) and all log with context, so this is acceptable by design. The risk is
  that a logic bug can be swallowed and surface only as a missing fill/order. Flagged for
  awareness, not action.
- Safe modification: When editing these handlers, prefer narrowing to specific domain
  exceptions (`itrader/core/exceptions/`) where the failure mode is known.

## Scaling Limits

**Live order persistence absent:**
- Current capacity: Backtest uses in-memory order storage (unbounded by design, single run).
- Limit: Live mode has no working persistence backend (PostgreSQL stub), so it cannot recover
  state across restarts or scale beyond a single in-memory process.
- Scaling path: Implement `PostgreSQLOrderStorage` (see Tech Debt).

## Dependencies at Risk

No dependencies flagged as deprecated or abandoned. `pandas-ta 0.4.71b0` is a **beta**
(`b0`) release pinned in `pyproject.toml`; it underpins strategy filters and SLTP models
(`itrader/strategy_handler/sltp_models/`, `.../my_strategies/filters/`). Beta pin is a
mild supply-chain/stability risk but is isolated to the non-reference strategy code.

## Missing Critical Features

**Live mode is not production-ready:**
- Problem: PostgreSQL order storage unimplemented; live system untested; data providers lack
  resilience. The refactor scope was explicitly **backtest correctness only**.
- Blocks: Any live/paper trading deployment.

## Test Coverage Gaps

**Live trading path — completely untested:**
- What's not tested: `LiveTradingSystem` lifecycle/threading, `TradingInterface` order
  creation/validation, live-mode event processing.
- Files: `itrader/trading_system/live_trading_system.py`,
  `itrader/trading_system/trading_interface.py`
- Risk: Live regressions ship silently; the entire live surface could break unnoticed.
- Priority: High (if live mode is ever pursued).

**Data providers / streaming — untested:**
- What's not tested: No tests for CCXT, OANDA, or Binance-stream providers
  (`find tests/ -iname "*ccxt*|*oanda*|*stream*|*binance*"` → empty).
- Files: `itrader/price_handler/providers/ccxt_provider.py`,
  `.../oanda_provider.py`, `.../binance_stream.py`
- Risk: Ingestion bugs (pagination dupes, timezone handling, rate limits) escape detection.
- Priority: Medium (offline ingestion path, not the golden-CSV backtest path).

**`my_strategies/` strategies — untested:**
- What's not tested: 15 modules under `itrader/strategy_handler/my_strategies/` (scalping,
  momentum, mean-reversion, custom indicators). Only the reference `SMA_MACD_strategy.py`
  and the base `Strategy` contract are covered (`tests/unit/strategy/test_strategy.py`).
- Files: `itrader/strategy_handler/my_strategies/**`
- Risk: These strategies' signals, sizing, and the stranded `long_only` compliance logic are
  unverified; they are not on the locked reference path.
- Priority: Low (out of the `SMA_MACD` backtest-correctness mandate).

**Skipped golden/inertness tests pending frozen oracle:**
- What's not tested when skipped: `tests/integration/test_backtest_oracle.py:107` and
  `tests/integration/test_reservation_inertness.py:65` `pytest.skip` when `tests/golden/`
  is not frozen.
- Risk: Low — the oracle was frozen at Phase 8 close, so these run in the locked tree; the
  skip is a defensive guard, not a permanent gap.
- Priority: Low (verify the golden fixtures remain committed).

---

*Concerns audit: 2026-06-08*
