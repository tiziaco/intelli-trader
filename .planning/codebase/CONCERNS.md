# Codebase Concerns

**Analysis Date:** 2026-06-27

> **Scope note.** iTrader is a brownfield backtest-correctness refactor. The
> backtest golden path (`SMA_MACD` over `data/BTCUSD_1d_ohlcv_2018_2026.csv`) is
> the trusted, regression-locked surface (oracle: **134 trades / final_equity
> `46189.87730727451`**). Most concerns below live in *deferred* subsystems (live
> trading, SQL stores, providers, screeners, `my_strategies`) that are
> intentionally out of the current trust boundary, NOT in the golden path. Two
> items (dual-layer order validator, tab/space indentation) are **documented-by-
> decision** and are explicitly NOT bugs — they are listed here only so future
> work does not "fix" them and break an invariant.

## Tech Debt

**PostgreSQL order storage is a pure stub:**
- Issue: `PostgreSQLOrderStorage` raises `NotImplementedError("...Phase 2")` from `__init__` and every method. The "Phase 2" it references is from a superseded plan and never landed. Live order persistence has no real backend — only `in_memory` is functional.
- Files: `itrader/order_handler/storage/postgresql_storage.py`
- Impact: Selecting the `postgresql` order-storage backend (the live-mode default per `OrderStorageFactory`) throws on construction. Live mode cannot persist orders.
- Fix approach: Implement against the same `OrderStorage` ABC the in-memory backend satisfies (`itrader/order_handler/storage/in_memory_storage.py` is the reference shape), backed by SQLAlchemy (already a dependency). Owned by the live-trading milestone.

**Deferred subsystems excluded from `mypy --strict`:**
- Issue: Eight module groups carry `ignore_errors = true` overrides — live trading (`live_trading_system`, `trading_interface`, `binance_stream`), SQL stores (`sql_store`, `postgresql_storage`), providers (`ccxt_provider`, `oanda_provider`, `exchange_base`), all of `screeners_handler.*`, and all of `my_strategies.*`. Third-party stubless libs are separately `ignore_missing_imports`.
- Files: `pyproject.toml` (`[[tool.mypy.overrides]]`, lines ~88–122)
- Impact: Type debt in these modules is suppressed, not resolved. The strict gate is green only because these are masked; new code added inside them gets no type checking.
- Fix approach: Each override is tagged with the milestone that owns its un-deferral (`D-live`, `D-sql`, `D-oanda`, `D-screener`, OUT/relocated). Strict-clean each module group when its milestone activates; do not add new modules to the override lists.

**Inherited legacy TODOs in deferred subsystems (mixed-language):**
- Issue: Scattered Italian-language TODOs flag known-incomplete logic — `# TODO: da modificare`, `# TODO: da testare`, `# TODO: da spostare in order_handler.compliance` (long-only filtering hardcoded in strategies instead of centralized in order admission), `# TODO: non prende window come argomento` (a screener bug), `TODO: to be tested` (custom indicators).
- Files: `itrader/price_handler/providers/oanda_provider.py` (lines 36, 74), `itrader/price_handler/providers/ccxt_provider.py:57`, `itrader/screeners_handler/screeners/volume_spyke.py:40`, `itrader/screeners_handler/screeners/base.py:29`, `itrader/strategy_handler/my_strategies/**` (multiple `da spostare in order_handler.compliance`), `itrader/strategy_handler/my_strategies/custom_indicators/ehlers_indicators.py:228`
- Impact: None on the golden path (all in deferred/relocated code). Signals that `compliance`/long-only logic is duplicated across strategies rather than owned by the order handler.
- Fix approach: When the screener/live milestones activate, centralize long-only/compliance into order admission and remove the per-strategy duplication.

**Reverted "fusion" left a captured-but-unbuilt design:**
- Issue: Phase 8 plan 08-01 shipped a `_fused_valuation()` that was measured as a -15% W1 / -5% W2@50 regression and reverted (keep-only-measured, D-02). The *correct* single-pass per-bar valuation design is captured but not built.
- Files: `.planning/todos/pending/single-pass-portfolio-valuation.md`; touch points `itrader/portfolio_handler/position/position_manager.py` (`update_position_market_values`), `itrader/portfolio_handler/portfolio.py` (`get_total_market_value` / `get_total_unrealized_pnl`)
- Impact: Three per-bar iterations over open positions (1 write + 2 read) where 1 would suffice. Likely noise on W1 (few concurrent SMA_MACD positions); the W2 many-symbol axis is the real payoff.
- Fix approach: Compute market-value + unrealized-PnL accumulators inside the existing write pass; accessors become O(1) field reads. **Byte-exactness landmine:** accumulation order + quantization must match per-accessor summation exactly (seed `Decimal('0.00')`, preserve `+=` order, no mid-sum quantize) or the oracle drifts. Profile-first gate: confirm an attributable W2 CPU share before building.

## Documented-by-Decision (NOT bugs — do not "fix")

**Dual-layer order validator overlap (D-03a):**
- What: Order validation exists in two places — the domain `EnhancedOrderValidator` (`itrader/order_handler/order_validator.py`) and exchange-side admission (`itrader/execution_handler/exchanges/simulated.py`). They overlap by design (defense-in-depth).
- Why kept: The live `TradingInterface`/`OrderEvent` path bypasses the domain validator, so the exchange-side check is the only guard on that path. The dead `create_order` second path was removed in Phase 6 (W4-09); the live-path bypass alone justifies the remaining overlap. Decision tags `D-03a` are present in `admission_manager.py`, `bracket_manager.py`, `simulated.py`.
- Action: Do NOT remove the overlap. It is documented in `.planning/codebase/CONVENTIONS.md` and `CLAUDE.md`.

**Tab/space indentation split:**
- What: Handler/manager modules use **tabs**; `config/`, `core/`, `price_handler/feed/`, and `events_handler/events/` use **4 spaces**.
- Why a hazard: A normalization diff that mixes tabs and spaces in a tab file breaks the file. There is no autoformatter to catch it.
- Action: ALWAYS match the indentation of the file being edited. Never normalize. Documented in `CONVENTIONS.md` and the v1.1 cleanup standard (`.planning/codebase/CLEANUP-STANDARD.md`).

**Broad `except Exception` clauses (run-mode policy):**
- What: ~30 broad `except Exception` sites across handlers (`portfolio_handler.py`, `execution_handler.py`, `simulated.py`, `admission_manager.py`, `reconcile_manager.py`, `live_trading_system.py`, etc.).
- Why intentional: Backtest is fail-fast (`EventHandler._on_handler_error` re-raises, `itrader/events_handler/full_event_handler.py`); live is publish-and-continue (emit `ErrorEvent`, keep draining). Execution rejections surface as `FillEvent(REFUSED)` (e.g. `simulated.py:226` catch → `_emit_rejection`), not lost exceptions, so the order mirror reconciles. This is intentional, not an inconsistency.
- Action: Preserve the per-mode policy. The `except` breadth is the mechanism, not a smell.

## Fragile Areas

**Wall-clock `datetime.now(UTC)` embedded in otherwise-deterministic portfolio state:**
- Files: `itrader/portfolio_handler/portfolio.py` (lines 135, 598, 619, 657, 705), `itrader/portfolio_handler/portfolio_handler.py` (126–129, 174, 824, 846), `itrader/portfolio_handler/cash/cash_manager.py` (187, 248, 310), `itrader/reporting/cash_operations.py:19`
- Why fragile: Money/event timestamps are business-time end-to-end (an injected `BacktestClock`, `core/clock.py`), but several health-metric, state-transition, reservation-row, and snapshot-timestamp fields still stamp `datetime.now(UTC)`. In-code comments assert these are "admin path — not oracle-serialized" or "cannot fire during a green oracle run." Determinism holds only by the invariant that none of these wall-clock fields ever reaches a serialized/compared oracle field.
- Safe modification: Before surfacing any of these timestamps into a reported frame, equity snapshot, or serialized record, route it through the injected clock / business time. Do not assume "admin path" stays admin-only.
- Test coverage: Determinism double-run guards the aggregate oracle, but there is no targeted test asserting these specific fields never leak into a compared surface.

**Strategy filter / compliance logic duplicated across strategies:**
- Files: multiple `itrader/strategy_handler/my_strategies/**` (long-only flags, `da spostare in order_handler.compliance` TODOs)
- Why fragile: Trade-admission concerns (long-only) are reimplemented per strategy instead of centralized in order admission. Each new strategy re-derives the rule and can get it subtly wrong.
- Safe modification: Centralize in `order_handler` admission when the screener/strategy milestone activates; strategies should emit signals and let admission enforce compliance.

## Security Considerations

**Exchange/DB credentials in `.env` (present, gitignored):**
- Risk: Live exchange API keys and DB URLs live in `.env` at repo root, loaded by `Makefile` (`include .env`, `.EXPORT_ALL_VARIABLES`).
- Files: `.env` (present locally, listed in `.gitignore`, NOT committed — verified clean in `git ls-files`)
- Current mitigation: `.env` is gitignored; `pydantic-settings` reads `ITRADER_`-prefixed vars. No secrets found committed to the repo.
- Recommendations: Keep `.env` out of version control. Never read or echo its contents in tooling. Rotate any key that ever appears in a log.

**`oanda.cfg` referenced but not gitignored:**
- Risk: The OANDA provider (`itrader/price_handler/providers/oanda_provider.py`, via `tpqoa`) expects an `oanda.cfg` credentials file at repo root. `.gitignore` lists `.env` but NOT `oanda.cfg`.
- Files: `.gitignore` (covers `.env` only), `itrader/price_handler/providers/oanda_provider.py`
- Current mitigation: `oanda.cfg` does not currently exist in the working tree (deferred provider), so nothing is exposed today.
- Recommendations: Add `oanda.cfg` (and `*.cfg` credential patterns) to `.gitignore` *before* the live/OANDA milestone creates the file, to prevent an accidental credential commit.

## Performance Bottlenecks

**Per-bar portfolio valuation: 3 iterations where 1 suffices:**
- Problem: See the deferred single-pass valuation item above. `update_position_market_values` (write) + `get_total_market_value` + `get_total_unrealized_pnl` (two reads) each iterate open positions per bar.
- Files: `itrader/portfolio_handler/position/position_manager.py`, `itrader/portfolio_handler/portfolio.py`
- Cause: Accessors recompute instead of reading a per-tick snapshot.
- Improvement path: O(1) accessors fed by accumulation inside the existing write pass; gated on a measured W2 win (the W1 hotspot was already collapsed in Phase 3).

**W1 benchmark is thermally sensitive (measurement hazard, not a code defect):**
- Problem: The v1.5 W1 wall-clock benchmark drifts with machine thermal state; a throttled box understates wins.
- Files: benchmark probe / `.planning` perf artifacts (v1.5 shipped 2026-06-26)
- Cause: Wall-clock micro-benchmark sensitivity, compounded by a since-fixed quadratic probe bug (baseline re-frozen 153.7s → 28.3s on 2026-06-25).
- Improvement path: Attribute future wins via same-machine A/B + Scalene CPU-share, not against a frozen baseline on a hot machine. Defer any re-freeze to a cool box.

## Test Coverage Gaps

**Trading-system entry points have no direct unit tests:**
- What's not tested: Composition roots and the run loop — covered only transitively by the integration oracle.
- Files: `itrader/trading_system/backtest_trading_system.py`, `itrader/trading_system/backtest_runner.py`, `itrader/trading_system/compose.py`, `itrader/trading_system/system_spec.py`, `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`
- Risk: Wiring regressions (a mis-ordered route, a dropped injection) surface only as an oracle drift, with no narrow failing test to localize them. Live composition (`live_trading_system`, `trading_interface`) is wholly untested AND mypy-deferred.
- Priority: Medium (backtest path is oracle-guarded); High for the live path when it activates.

**Event dispatch core has no direct test:**
- What's not tested: `EventHandler.process_events` / `_dispatch` / `_on_handler_error` (the data-driven `_routes` table and the fail-fast vs publish-and-continue seam).
- Files: `itrader/events_handler/full_event_handler.py`
- Risk: The `NotImplementedError`-on-unrouted-type guard and the per-mode error policy are load-bearing but unverified by a unit test.
- Priority: Medium.

**Reporting builders are near-untested:**
- What's not tested: Frame/order builders have no dedicated tests; only a plots smoke test and a metrics test exist (`tests/unit/reporting/test_metrics.py`, `test_plots_smoke.py`, `test_cash_operations.py`).
- Files: `itrader/reporting/frames.py`, `itrader/reporting/orders.py`, `itrader/reporting/plots.py`
- Risk: Reported trade-log/equity-curve artifacts (the project's core deliverable) can drift in shape without a failing test.
- Priority: Medium.

**Deferred subsystems are untested by design:**
- What's not tested: Providers (`ccxt_provider`, `oanda_provider`, `binance_stream`, `exchange_base`), screeners (`screeners_handler` + all screeners), SQL stores (`sql_store`).
- Files: `itrader/price_handler/providers/*`, `itrader/screeners_handler/*`, `itrader/price_handler/store/sql_store.py`
- Risk: Acceptable while deferred; these will need test scaffolding before their owning milestone can trust them.
- Priority: Low now, High at activation.

## Scaling Limits

**Backtest is a single-threaded synchronous for-loop:**
- Current capacity: Comfortable for SMA_MACD on a single symbol over the golden daily dataset; the run is one `for` loop over a `TimeGenerator` grid with in-memory storage and no locking (D-19 single-writer contract).
- Limit: The symbol axis (W2 — many concurrent markets) is the scaling pressure, not bar count. Per-bar work that is O(open positions)/O(symbols) (valuation, screening) compounds as symbols grow.
- Scaling path: Collapse per-bar valuation to O(1) accessors (deferred todo); keep the single-writer contract (no premature parallelism — it would forfeit determinism guarantees).

## Dependencies at Risk

**`pandas-ta` pinned to a beta:**
- Risk: `pandas-ta 0.4.71b0` is a pinned beta release used in strategy filters / SLTP models and custom indicators.
- Impact: Pre-release API instability; upstream churn could break strategy indicators on upgrade.
- Migration plan: Keep pinned; treat any bump as a behavior-affecting change requiring an oracle re-run. The `ta` library (`ta ^0.11.0`) covers some overlapping indicators if migration is needed.

**Cross-validation oracles are external gating dependencies:**
- Risk: `backtesting.py 0.6.5` and `backtrader 1.9.78.123` are *gating* cross-validation oracles (`tests/golden/CROSS-VALIDATION.md`); `nautilus-trader 1.227.0` is non-gating.
- Impact: An incompatible upgrade to either gating lib could block the validation gate independent of iTrader correctness.
- Migration plan: Pin exactly (already pinned); upgrade only deliberately with a cross-validation re-baseline.

**`psycopg2-binary` carried for an unimplemented backend:**
- Risk: `psycopg2-binary ^2.9.12` and SQLAlchemy are dependencies for PostgreSQL price/order storage, but `PostgreSQLOrderStorage` is an unimplemented stub.
- Impact: Dependency surface (and `-binary` packaging caveats) carried for code that does not yet run.
- Migration plan: Retain — it is needed by the SQL price store on the live path and will back the order store when implemented.

## Missing Critical Features

**Live order persistence:**
- Problem: No working `OrderStorage` backend for live mode (`postgresql_storage` is all `NotImplementedError`).
- Blocks: Durable live trading — orders cannot survive a process restart in live mode.

---

*Concerns audit: 2026-06-27*
