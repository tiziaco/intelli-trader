# Codebase Concerns

**Analysis Date:** 2026-07-21

> Refreshed after v1.8 Phases 8–10.1 (error handling, runtime config, strategies registry,
> strategy-handler refactor). This is an incremental verification pass against the 2026-07-07
> baseline (v1.7 milestone close) — every prior item was re-checked against current code and is
> marked **STILL OPEN**, **RESOLVED**, or **CHANGED** below. 2606 tests collected (up from 1988 at
> the last refresh). The backtest oracle remains regression-locked (SMA_MACD spot golden
> `134 / 46189.87730727451`).

## Resolved Since 2026-07-07

**AUD-3 — ERROR-route aggregate circuit breaker: RESOLVED.**
- Previously: no aggregate tripwire on `_publish_and_continue`, flagged HIGH real safety gap.
- Now: a full `ErrorPolicy` / CF-1 tripwire landed in v1.8 Phase 8 — `itrader/events_handler/error_policy.py`. It classifies every failing event into a `FailureClass` via a declarative route map (`_ROUTE_CLASS`: `FILL`→`SETTLEMENT`, `ORDER`→`ORDER_IO`, `SIGNAL`→`ADMISSION`, else `LOOP_BACKSTOP`), tracks a per-class hit-deque against threshold/window policy (`_POLICY_FIELDS`), and trips the existing idempotent `halt(reason)` with a typed `HaltReason` on breach. `LiveTradingSystem` exposes a CF-1 tripwire snapshot on `get_status()` (`itrader/trading_system/live_trading_system.py:930`).
- Confirms the spec drafted in the old audit (`v17_audit_results.md` §3b) was built essentially as designed (SETTLEMENT/ORDER_IO/ADMISSION/LOOP_BACKSTOP classes, FILL_TRANSLATION reuses SETTLEMENT_FAILURE per D-16).

**WR-04 — off-vocabulary halt reason `'baseline-residual'`: RESOLVED (code); todo file stale.**
- Previously: `self.halt('baseline-residual')` was a free string not enumerated anywhere.
- Now: `itrader/core/enums/system.py` defines a typed `HaltReason(Enum)` (`:72`) with `BASELINE_RESIDUAL = "baseline-residual"`, `CONNECTOR_FATAL`, `RECONCILIATION_UNRESOLVED`, `DURABLE_HALT`, `DRIFT`, plus one member per `FailureClass` for the CF-1 tripwire (D-16). The call site now reads `self._halt(HaltReason.BASELINE_RESIDUAL.value)` in `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:215`, and `CONNECTOR_FATAL.value` is used the same way in `itrader/trading_system/live_trading_system.py:414`. The docstring on `HaltReason` explicitly frames this as "P1 defines the enum; migrating the remaining `halt()` call sites and its `reason: str` signature is P8's job (D-11)."
- Gap: `.planning/todos/pending/off-vocabulary-halt-reason-baseline-residual-wr04.md` still carries `status: scheduled` and is not marked done — a bookkeeping staleness, not a code gap. Recommend closing/archiving that todo file.

## Tech Debt

**CF-8 / D-11 — `halt(reason: str)` → `HaltReason` signature migration: STILL OPEN (partially landed).**
- Issue: The `HaltReason` enum (D-16/CFG-05) is now defined and all first-party call sites pass `HaltReason.X.value` (typed at the call site), so the off-vocabulary bug (WR-04) is fixed. But the actual function signatures are still untyped `str`: `SafetyController.halt(self, reason: str)` (`itrader/trading_system/safety/safety_controller.py:151`) and the thin facade delegator `LiveTradingSystem.halt(self, reason: str)` (`itrader/trading_system/live_trading_system.py:331`, delegates to `self._safety.halt(reason)`). `HaltReason`'s own docstring calls this migration "P8's job (D-11)" — i.e., still pending despite Phase 8 having landed the CF-1 tripwire that consumes it.
- Files: `itrader/trading_system/safety/safety_controller.py:151`, `itrader/trading_system/live_trading_system.py:331`, `itrader/core/enums/system.py:72-100`.
- Remaining free-string reason (not yet folded into `HaltReason`): `_DEFERRED_PROTECTIVE_OVERFLOW_REASON = "deferred-protective-overflow"` (`itrader/trading_system/safety/safety_controller.py:56`, used at `:413`) — a sixth off-vocabulary halt-reason literal outside the enum.
- Impact: Low-to-moderate — the vocabulary discipline is now enforced by convention (callers pass `.value` from the enum) rather than by the type system; a future caller could still pass an arbitrary string and the type checker would not catch it.
- Fix approach: Change both `halt()` signatures to accept `HaltReason` (not `str`), add `.value` conversion inside the method body for the durable-store/event-bind string boundary, and either fold `deferred-protective-overflow` into `HaltReason` or document it as an intentional exception.

**`LiveTradingSystem` — refactor in progress, not complete.**
- Previously: flagged at **2171 lines**, owner-designated for a full rewrite.
- Now: **1759 lines** (`itrader/trading_system/live_trading_system.py`) — down ~19% via the v1.8 decomposition (safety logic extracted to `itrader/trading_system/safety/safety_controller.py`; error-policy extracted to `itrader/events_handler/error_policy.py`; other collaborators split into `itrader/trading_system/route_registrar.py`, `itrader/trading_system/live_runner.py`, `itrader/trading_system/session_initializer.py`). The class now explicitly documents itself as a thin delegating facade over these collaborators ("Thin safety delegators (§11e)").
- Impact: Change-friction reduced but not eliminated; still the largest live-path module and still `mypy` `ignore_errors=true` (see below).
- Fix approach: Continue the decomposition; the remaining `str`-typed halt signature (CF-8 above) is one of the concrete residual items.

**mypy `ignore_errors` overrides — blindspot confirmed STILL OPEN, unchanged scope.**
- Issue: `pyproject.toml:102-116` still lists `itrader.trading_system.live_trading_system` (D-live), `itrader.trading_system.trading_interface` (D-live — note: this module name is stale, `TradingInterface` was deleted per V17-16; the mypy override entry itself is now a dead reference, mirroring the pattern already flagged for `order_handler/storage/__init__.py:14`), `itrader.price_handler.providers.{ccxt_provider,oanda_provider,exchange_base,binance_stream}` (D-oanda/D-live), and `itrader.screeners_handler.*` (D-screener) all under `ignore_errors = true`. A separate override covers `itrader.strategy_handler.my_strategies.*`.
- Impact: Dead code, unused imports, and type errors in these modules pass `mypy --strict` and the full suite silently — the only backstop is manual code review. Confirmed still the case for `live_trading_system.py` even after the Phase 8–10.1 extraction work shrank it.
- Fix approach: Sweep imports/dead code by hand after any edit to these modules (per project memory `live-facade-mypy-ignore-errors-blindspot`); remove the stale `trading_interface` override entry; retire `D-live` overrides module-by-module as each is folded into the ongoing refactor.

**Stream-supervisor state machine triplicated (DRY) — STILL OPEN, not re-verified as fixed.**
- Issue: `_run_stream_supervisor`-style reconnect/backoff logic still appears to be duplicated across execution/account/price-provider streams.
- Files: `itrader/execution_handler/exchanges/okx.py`, `itrader/portfolio_handler/account/venue.py`, `itrader/price_handler/providers/okx_provider.py`, plus a newer generalized `itrader/connectors/stream_supervisor.py` (introduces `_escalate_halt`, suggesting partial consolidation may already be underway).
- Impact: A resilience fix may still need to land in multiple places.
- Fix approach: Extract one shared supervisor helper (unchanged recommendation); verify whether `connectors/stream_supervisor.py` already supersedes the older per-file copies before treating as still-triplicated.

**`LiveConnector` Protocol contract docstrings — STILL OPEN (not reverified this pass, carried forward).**
- Files: `itrader/connectors/base.py`.
- Not re-audited line-by-line this pass; carried forward from 2026-07-07 pending explicit reverification.

**`D-03a` dual-validator note in `CONVENTIONS.md` — RESOLVED.**
- The `D-03a` paragraph in `CONVENTIONS.md`/`CLAUDE.md` now correctly documents the dual-layer validator overlap as justified-by-decision (defense-in-depth boundary gate), and explicitly notes the original "live bypass" premise is now obsolete post-D-10. No open doc-consistency gap.

**Legacy `my_strategies/` and provider TODOs — STILL OPEN, unchanged.**
- Issue: Scattered `TODO`/`FIXME` markers, several in Italian, confirmed still present verbatim:
  - `itrader/price_handler/providers/ccxt_provider.py:57` — format-validity TODO
  - `itrader/price_handler/providers/oanda_provider.py:36,74` — "da modificare" / "In origine non c'era"
  - `itrader/screeners_handler/screeners/base.py:29` — "da testare"
  - `itrader/screeners_handler/screeners/volume_spyke.py:40` — pandas-ta argument TODO
  - `itrader/order_handler/order.py:451` — "check if i have to store the state changes permanently in sql"
  - New since last pass: `itrader/trading_system/session_initializer.py:144` — forward-looking design-note TODO (not a bug marker; documents an assumption for a future edit)
- Impact: Low — concentrated in deferred/out-of-scope subsystems (my_strategies is excluded from mypy at `pyproject.toml:121`), not the backtest run path.
- Fix approach: Unchanged — address when the owning subsystem is promoted.

## Known Bugs

**WR-01 — margin-mode `total_equity` / `margin_ratio` double-count the borrowed notional: STILL OPEN, owner-gated, unchanged.**
- Symptoms: unchanged. `Portfolio.total_equity` (`itrader/portfolio_handler/portfolio.py:279-285`) is still `return self.total_market_value + self.cash` — for a leveraged long this is `cash + full_notional`, not `cash + unrealised_pnl`, overstating equity by the borrowed amount. `SimulatedMarginAccount.margin_ratio` (`itrader/portfolio_handler/account/simulated.py:856-871`) still reads this inflated equity via `maintenance_margin()`/portfolio's `total_equity`.
- Files: `itrader/portfolio_handler/portfolio.py:279-285`, `itrader/portfolio_handler/portfolio_handler.py`, `itrader/portfolio_handler/position/position_manager.py` (`market_value` still returns full notional), `itrader/portfolio_handler/account/simulated.py:856-871`.
- Trigger: unchanged — opening a leveraged/margin long; dark on the all-spot SMA_MACD oracle.
- Status: `.planning/todos/pending/margin-equity-double-counts-notional-wr01.md` still carries `status: deferred`, owner-gated (tiziaco, 2026-07-01) behind the same 6 frozen, never-externally-cross-validated goldens (`tests/e2e/{levered_long,partial_cover,short_roundtrip,short_scale_in,short_scale_in_partial_cover}/test_*_scenario.py`, `tests/integration/test_pair_flagship_snapshot.py`). No change since 2026-07-07.
- Fix approach: unchanged from prior audit — decide canonical formula, gate on `enable_margin`, re-freeze the 6 goldens with owner sign-off, refresh `CROSS-VALIDATION-ACCOUNTING.md`.

## Security Considerations

**Overall posture remains strong — reverified, no new findings.** No `eval`/`exec`/`pickle`/`os.system`/`subprocess` usage found in `itrader/` this pass. Secret-leak discipline (halt reasons as FIXED literals via `HaltReason.X.value`, never `str(exc)`; exception TYPE name only in provider error paths) is intact and, if anything, strengthened by the typed `HaltReason` enum landed in Phase 8.

## Performance Bottlenecks

**Per-bar portfolio valuation not single-pass — STILL OPEN, unchanged.**
- Files: `itrader/portfolio_handler/portfolio_handler.py` (`update_portfolios_market_value`).
- Detail: `.planning/todos/pending/single-pass-portfolio-valuation.md` (still present, unresolved).

**Deferred large-universe perf guards (PERF-09/10) — STILL OPEN, unchanged.**
- No large-universe dedup/O(n²) guard found added since last pass.

## Fragile Areas

**`LiveBarFeed.backfill_on_resume` unwired — STILL OPEN, unchanged.**
- Files: `itrader/price_handler/feed/live_bar_feed.py:395`; only caller is `tests/integration/test_live_bar_feed_warmup.py`.
- Detail: `.planning/todos/pending/livebarfeed-depandas-time-model-datetime.md` still pending.

**`_relink_bracket` bare subscript — not re-verified this pass, carried forward as open.**
- Files: `itrader/portfolio_handler/reconcile/venue_reconciler.py`.

**Alert egress is log-only — STILL OPEN, unchanged.**
- Files: `itrader/trading_system/live_trading_system.py` (pluggable sink seam still routes only to the ERROR log route via the CF-1 tripwire / `halt()` CRITICAL `ErrorEvent`). Even with the new CF-1 breaker landed, a trip still only emits an `ErrorEvent` into the same log-only sink — no operator push notification exists.
- Fix approach: unchanged — substantive home is the FastAPI control-plane milestone.

**Tab/space indentation hazard — STILL OPEN, confirmed with exact per-file split.**
- Reverified directly: `itrader/trading_system/live_trading_system.py` is **4-space** (356 space-indented lines, 0 tab lines sampled), while `itrader/trading_system/engine_context.py` (50 tab lines), `itrader/trading_system/compose.py` (242 tab lines), and `itrader/trading_system/backtest_trading_system.py` (414 tab lines) are **tab**-indented — confirming the package is split per-file, not uniform (per project memory `live-trading-system-is-space-indented`). Rule stands: measure bytes per file before editing, never assume by directory.
- New collaborator modules extracted in Phase 8-10.1 (`itrader/trading_system/safety/safety_controller.py`, `itrader/events_handler/error_policy.py`, `itrader/trading_system/route_registrar.py`, `itrader/trading_system/live_runner.py`, `itrader/trading_system/session_initializer.py`) should each be checked individually before editing — do not assume they inherit either sibling's convention.

## Scaling Limits

**Live universe / screener still a lean poll seam only — STILL OPEN, unchanged.**

## Dependencies at Risk

**`pandas-ta 0.4.71b0` pinned pre-release — STILL OPEN, unchanged.**

**mypy `--strict` deferred subsystems — STILL OPEN, scope essentially unchanged (see Tech Debt above for the exact current module list and the newly-noted stale `trading_interface` entry).**

## Missing Critical Features

**Pair-strategy live reconfiguration — STILL OPEN, unchanged.** `.planning/todos/pending/pair-strategy-live-reconfiguration.md` still pending.

**Deferred-to-v2 live/realism features — STILL OPEN, unchanged.** Perp realism Phase B (FUND-01..04), TRADE-01 trade-aggregation bar source, Optuna sampler (OPT-01), Turso/libSQL opt-in backend (TURSO-01), multi-currency/calendars/corporate-actions (`D-multiasset`) — no evidence any landed since 2026-07-07; corresponding pending-todo files not found for most of these (tracked in milestone specs, not `.planning/todos/pending/`), so treat as still deferred by default rather than actively verified line-by-line.

**PostgreSQL order storage — RESOLVED (carried forward, no change).** Still resolved via `SqlOrderStorage` (`itrader/order_handler/storage/sql_storage.py`); the stale commented import in `itrader/order_handler/storage/__init__.py` was not re-checked this pass but is a cosmetic non-issue either way.

## Test Coverage Gaps

**ERROR-route circuit breaker — RESOLVED (was: untested-because-unbuilt).** The breaker (`ErrorPolicy` / CF-1 tripwire) is now built (see Resolved section above); test coverage for it was not independently line-audited this pass — recommend confirming `tests/unit/events_handler/` (or equivalent) exercises `error_policy.py`'s per-`FailureClass` trip/reset behavior before treating this as fully closed.

**`backfill_on_resume` — STILL OPEN, unchanged.** Only exercised by `tests/integration/test_live_bar_feed_warmup.py`; no production caller.

**Margin-mode open-position equity — STILL OPEN, unchanged.** No external-oracle assertion exists for non-flat margin equity; `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` still only corroborates final/flat equity. High priority before any live margin consumer; currently owner-gated (WR-01).

## New Since Last Refresh (v1.8 Phases 8–10.1)

**`.planning/todos/pending/` still carries 23 unresolved items** (as of this pass), including several not previously called out in CONCERNS.md — e.g. `04-storage-review-warnings.md`, `07-double-startup-snapshot-in02.md`, `okx-markets-map-freshness-delisting-detection.md`, `operator-emergency-shutdown-command.md`, `operator-force-close-position-command.md`, `unify-backtest-direct-bar-generation.md`, `unify-config-store-save-interface.md`, `warmup-depth-max-concerned-strategy.md`, `shared-strategy-admission-seam.md`, `strategy-timeframe-finer-than-base-resubscribe.md`, `multi-timeframe-consolidator.md`, `native-tagged-multi-timeframe.md`, `synthetic-spread-instrument.md`, `deep-shared-bar-history.md`, `live-ring-resize-fixed-maxlen-deque.md`, `mutable-instrument-refactor.md`, `b2-strategy-subscription-portfolio-id-uuid-column.md`, `claude-md-alembic-migration-chain-path-wrong.md`. These were not individually triaged in this refresh (out of the explicit candidate-concern list given); flagging their existence as an open backlog surface for the next full audit rather than letting them go unmentioned.

**Test suite grew from 1988 to 2606 collected tests** since the last refresh, consistent with the Phase 8–10.1 work (error-policy tripwire, runtime config, strategies registry, strategy-handler refactor) each landing with new coverage — a positive signal, not a concern, noted for context.

---

*Concerns audit: 2026-07-21*
