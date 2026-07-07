# Codebase Concerns

**Analysis Date:** 2026-07-07

> Refreshed at v1.7 "Live Trading Readiness" milestone close (archived 2026-07-07). The backtest
> path is regression-locked and oracle-backed (SMA_MACD spot golden `134 / 46189.87730727451`,
> 1988 tests collected, `mypy --strict` clean over the in-scope set). Nearly all concerns below are
> **live-path** items that are dark on the backtest oracle. Provenance for the live items is the
> v1.7 Phase-5 adversarial-review roadmap (archived at `.planning/milestones/v1.7-review/`) and the
> milestone-close disposition sweep (39-row FIXED/OPEN table, 2026-07-07): 32 FIXED-IN-HEAD, 7
> genuinely-open, 0 regressions. Every CRITICAL/WARNING V17 defect (V17-01…16) is fixed in HEAD.

## Tech Debt

**`LiveTradingSystem` — flagged for a full refactor (next milestone):**
- Issue: Largest module in the codebase at **2171 lines** (`itrader/trading_system/live_trading_system.py`), owner-designated for a full rewrite in the next milestone. Carries lifecycle, threading, error policy, DB wiring, halt logic, and status reporting in one class.
- Files: `itrader/trading_system/live_trading_system.py`
- Impact: High change-friction; deferred from `mypy --strict` (`pyproject.toml:104`, tag `D-live`) so type safety is not enforced here. Several other live concerns below (halt vocabulary, circuit breaker, alert egress) are intentionally parked to land inside this refactor rather than as isolated patches.
- Fix approach: Full refactor owned by the next milestone; split lifecycle / error-policy / halt-record / status surfaces; land a typed `mypy --strict` pass by removing the `D-live` override.

**Stream-supervisor state machine triplicated (DRY):**
- Issue: `_run_stream_supervisor` (~100-line reconnect/backoff state machine) is reimplemented three times. The V17-07 fix (adding a supervisor to the previously-bare account/position streams) replicated it a third time.
- Files: `itrader/execution_handler/exchanges/okx.py:708`, `itrader/portfolio_handler/account/venue.py:356`, `itrader/price_handler/providers/okx_provider.py:462`
- Impact: Three copies drift independently; a resilience fix must be applied in three places or silently diverge.
- Fix approach: Extract one shared supervisor helper (was a LOW-batch item, worsened by the V17-07 fix).

**`LiveConnector` Protocol contract docstrings missing:**
- Issue: The call-site fixes landed (V17-07/09/15) but the central Protocol still lacks the CONTRACT text implementers read (timeout ≠ did-not-happen → reconcile; never call from the loop thread; disconnect is best-effort, streams may still emit after it returns).
- Files: `itrader/connectors/base.py` (`call`/`spawn`/`disconnect`, ~lines 53–92)
- Impact: A future connector author can re-introduce a timeout-cancels or call-from-loop-thread bug with nothing in the Protocol to stop them.
- Fix approach: Paste the three docstring blocks written verbatim in the archived `v17_audit_results.md` §4c.

**`D-03a` dual-validator note absent from `CONVENTIONS.md` (doc-consistency):**
- Issue: The substance (V17-16: `add_event` fail-closed + OKX preflight; `TradingInterface` deleted) is carried in `CLAUDE.md`'s D-03a note (W4-09), but the paragraph update to the cited authoritative home was never applied.
- Files: `.planning/codebase/CONVENTIONS.md` (D-03a paragraph)
- Impact: Low — a planner reading CONVENTIONS.md sees a stale justification for the dual-layer order-validator overlap.
- Fix approach: Ready-to-paste replacement in archived `v17_audit_results.md` §6d.

**Legacy `my_strategies/` and provider TODOs (mostly out-of-scope / relocated):**
- Issue: Scattered `TODO`/`FIXME` markers, several in Italian, in strategy filters and legacy providers (e.g. "da spostare in order_handler.compliance", "da testare", "da modificare").
- Files: `itrader/strategy_handler/my_strategies/**` (relocated to a separate repo per STATE.md; excluded from `mypy` via `pyproject.toml:121`), `itrader/price_handler/providers/oanda_provider.py:36,74`, `itrader/price_handler/providers/ccxt_provider.py:57`, `itrader/screeners_handler/screeners/*` (deferred subsystem), `itrader/order_handler/order.py:451`.
- Impact: Low — concentrated in deferred/out-of-scope subsystems, not the backtest run path.
- Fix approach: Address when the owning subsystem is promoted; do not touch on the in-scope path.

## Known Bugs

**WR-01 — margin-mode `total_equity` / `margin_ratio` double-count the borrowed notional (owner-gated):**
- Symptoms: For a freshly opened leveraged long, `total_equity ≈ cash + full_notional`, overstating true equity (`cash + unrealised_pnl`) by the borrowed amount. `SimulatedMarginAccount.margin_ratio` reads this inflated equity, so it would never read a sub-1 margin-call value.
- Files: `itrader/portfolio_handler/portfolio.py:245-252`, `itrader/portfolio_handler/portfolio_handler.py:311-326`, `itrader/portfolio_handler/position/position_manager.py` (`market_value` returns full notional), `itrader/portfolio_handler/account/simulated.py:836-854` (`margin_ratio`).
- Trigger: Opening a leveraged/margin long. **Dark on the all-spot SMA_MACD oracle** (formula degenerates to the correct `cash + market_value`); the actual liquidation engine uses `_isolated_liq_price` against bar close, not `margin_ratio`.
- Workaround / status: **Owner-gated deferral** (tiziaco, 2026-07-01). The reviewer's fix (gate on `enable_margin`; spot arm byte-exact, margin arm `cash + Σ unrealised PnL`) was applied, verified green, then rolled back because it breaks **6 owner-frozen accounting goldens** (D-17) that hand-assert open-position equity as `balance + market_value`. Critically, those disputed open-position values (`30000`/`28000`) were **never externally cross-validated** — `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` only corroborates final/flat equity (`14000`). "Frozen" here does not mean "oracle-backed."
- Fix approach (before any live margin/leverage/short consumer reads margin equity): decide canonical formula (recommend futures-correct `cash + Σ unrealised PnL`), gate on `enable_margin`, add a margin-mode unit assertion, **correct + re-freeze the 6 goldens with owner sign-off**, and refresh `CROSS-VALIDATION-ACCOUNTING.md` so open-position equity is oracle-backed. Full detail: `.planning/todos/pending/margin-equity-double-counts-notional-wr01.md`, `.planning/notes/margin-leverage-shorts-999.4.md` §9 item 6. The 6 goldens: `tests/e2e/{levered_long,partial_cover,short_roundtrip,short_scale_in,short_scale_in_partial_cover}/test_*_scenario.py`, `tests/integration/test_pair_flagship_snapshot.py`.

**WR-04 — session-start baseline guard halts with an off-vocabulary reason `'baseline-residual'`:**
- Symptoms: The post-reconcile baseline guard calls `self.halt('baseline-residual')` with a free-string reason not enumerated in the halt vocabulary (`itrader/core/enums/system.py:20-23`) nor listed in the `halt()` docstring. Any operator/monitoring/UI layer classifying halts by known reason falls this into an "unknown/other" bucket.
- Files: `itrader/trading_system/live_trading_system.py:~810` (`halt('baseline-residual')`), `halt()` at `:813`, `itrader/core/enums/system.py:20-23`.
- Trigger: Guard halts on a non-flat account at session start (reachable live-path halt; captured in the 05.1 CONF-B online run, `.planning/debug/05.1-confb-2026-07-04.md`). **Dark on the backtest oracle** (baseline guard is live-only).
- Workaround / status: No data/correctness impact — the guard halts correctly (freeze-in-place is the right fail-safe); only the *reason label* is off-vocabulary. **Deferred by owner decision** into the next-milestone `live_trading_system.py` full refactor + halt-vocabulary review (a typed `HaltReason` enum owned there, not an isolated patch). A cosmetic doc-only patch was explicitly rejected as not addressing the real weakness (untyped free-string halt reasons). Detail: `.planning/todos/pending/off-vocabulary-halt-reason-baseline-residual-wr04.md`.

## Security Considerations

**Overall posture is strong — no critical findings.** No `eval`/`exec`/`pickle`/`os.system`/`subprocess` usage in `itrader/`. No f-string SQL — all SQL is parameterized SQLAlchemy Core (SEC-01 / T-03-03). Credentials are `SecretStr` and read only via `.get_secret_value()` at construction, never logged.

**Secret-leak discipline in error paths (mitigated, keep enforcing):**
- Risk: An exception message from a venue call could carry a secret if surfaced verbatim.
- Files: `itrader/price_handler/providers/okx_provider.py:443,535,777`, `itrader/trading_system/live_trading_system.py:778,829,1126`, `itrader/connectors/okx.py:46,157-159`.
- Current mitigation: Halt reasons are FIXED literals (never `str(exc)`); providers pass exception TYPE name only (Pitfall 16, T-05-27). A hardcoded DB credential in a connection URL (VCS-history leak) was closed — the credential is now sourced from `SqlSettings` `ITRADER_DATABASE_*` `SecretStr` fields (`itrader/price_handler/store/sql_store.py:6-9`).
- Recommendations: Preserve the "exception type only, never `str(exc)`" convention in any new live-path error handling; keep `.env` (present at repo root, gitignored) out of VCS.

## Performance Bottlenecks

**Per-bar portfolio valuation is not single-pass (deferred, profile-first gated):**
- Problem: Portfolio market-value update is not a correct single-pass per-bar valuation.
- Files: `itrader/portfolio_handler/portfolio_handler.py` (`update_portfolios_market_value`).
- Cause: Repeated valuation work per bar rather than one pass.
- Improvement path: Deferred to a future perf phase, profile-first gated. Detail: `.planning/todos/pending/single-pass-portfolio-valuation.md`. (Note: the prior real hotspot — per-tick `searchsorted` in `bar_feed.window()` — was already addressed; see memory `perf06-real-w2-hotspot`.)

**Deferred large-universe perf guards (PERF-09 / PERF-10):**
- Problem: Strategy-level dedup and an O(n²)-in-symbol guard are not implemented.
- Impact: Only material at large universes; the current crypto-first reference run (single/few symbols) is unaffected.
- Improvement path: Deferred to a future perf milestone.

## Fragile Areas

**AUD-3 — ERROR-route has no aggregate circuit breaker (HIGH — real safety gap, unblocked):**
- Files: `itrader/trading_system/live_trading_system.py:686` (`_publish_and_continue`), `:706` (`errors_count` increment), `:813` (`halt`).
- Why fragile: `_publish_and_continue` increments `errors_count` and emits one `ErrorEvent` per failure, then continues **forever** — there is no aggregate tripwire. A money route (e.g. FILL → portfolio/order settlement) that fails on *every* event produces an infinite green-looking run. This is the "V17-01 ran an entire e2e suite green with zero settlements" class of failure. The `halt` references elsewhere are the ARCH-4 durable-halt record, not an error-rate breaker.
- Safe modification: Its hard dependency — the ARCH-4 HALTED latch (V17-03) — has landed, so a breaker `halt()` will no longer be clobbered back to RUNNING; the item is now **unblocked**. Spec drafted in archived `v17_audit_results.md` §3b: a route-classified ring on the `_publish_and_continue` seam (SETTLEMENT halts on first failure; ORDER-IO N=3/60s; ADMISSION N=3/300s; FILL-TRANSLATION emits a counted `ErrorEvent` then treats as SETTLEMENT; LOOP-BACKSTOP N=5/60s), guarded by `_stats_lock`, tripping the existing idempotent `halt(reason)`, surfacing counters + last-trip reason in `get_status()`. Must preserve the WR-06 terminal ERROR-route swallow and leave backtest fail-fast untouched.
- Test coverage: No breaker test exists (the breaker itself is unbuilt); live lifecycle is otherwise covered by COV-01 (`tests/integration/test_live_paper_lifecycle.py`, `tests/unit/trading_system/`).

**`LiveBarFeed.backfill_on_resume` is unwired (up-to-one-bar resume stall):**
- Files: `itrader/price_handler/feed/live_bar_feed.py:395`; only caller is `tests/integration/test_live_bar_feed_warmup.py`.
- Why fragile: No production resume path invokes it, so a reconnect straddling a bar close recovers only at the next delivered bar — up to one bar-period stall (1d at daily cadence).
- Safe modification: Now **unblockable** — the V17-15 loop-native gap-backfill redesign landed (`_replaying_backfill` guard + `spawn_gap_backfill`), so wiring it **loop-natively** (on the connector loop via the reconnect callback, per AUD-5 §5d) is now safe. Wiring it on the engine thread remains unsafe (second concurrent writer racing the connector-loop `update()` on ring/guard state).
- Detail: `.planning/todos/pending/livebarfeed-depandas-time-model-datetime.md` and the carry-forward index.

**`_relink_bracket` bare `matched["id"]` subscript (minor robustness):**
- Files: `itrader/portfolio_handler/reconcile/venue_reconciler.py:411` (`venue_id = str(matched["id"])`).
- Why fragile: No guard — `KeyError` if a fallback-matched resting order carries no `id`.
- Safe modification: Fail-loud at restart, **not** a silent money bug. Add a guard / typed error (LOW-batch item).

**Alert egress is log-only (no operator notification):**
- Files: `itrader/trading_system/live_trading_system.py:668` (pluggable sink seam routes only to the ERROR log route).
- Why fragile: A 3am halt reaches nobody — a halted live system is silent to operators.
- Safe modification: Pairs with the ARCH-4 Layer-2 durable halt record and the FastAPI control-plane milestone (memory `fastapi-application-layer-plan`); the substantive home is the FastAPI milestone, not a v1.7 fix. Documented as ARCH-4 F/U-10.

**Tab/space indentation hazard (codebase-wide edit trap):**
- Files: handler/manager modules under `itrader/` use **tabs**; `config/`, `core/`, `price_handler/feed/`, `events_handler/events/`, and newer live modules use **4 spaces**.
- Why fragile: A mixed-indentation diff in a tab file breaks the file; `pyproject.toml` `filterwarnings=["error"]` + `--strict-markers`/`--strict-config` also mean any stray warning or undeclared marker fails the whole suite.
- Safe modification: ALWAYS match the indentation of the file being edited; never normalize. Documented convention (CONVENTIONS.md).

## Scaling Limits

**Live universe / screener is a lean poll seam only:**
- Current capacity: v1.7 shipped only the lean poll seam (Phase 6/7), not a production screener/ranking/rebalance loop.
- Limit: No production-grade dynamic universe selection at scale; PERF-09/10 large-universe guards are unbuilt.
- Scaling path: Production screener/ranking/rebalance deferred to v2 (`D-screener`).

## Dependencies at Risk

**`pandas-ta 0.4.71b0` — pinned pre-release (beta):**
- Risk: A beta release pinned exactly; upstream is unstable and the pin blocks routine `poetry update`.
- Impact: Used in strategy filters and SLTP models (mostly in the out-of-scope `my_strategies/`); no type stubs (`mypy` `ignore_missing_imports`, `pyproject.toml:130`).
- Migration plan: Reassess against a stable `pandas-ta` release or migrate indicators to the primary `ta` library when the strategy surface is next revisited.

**`mypy --strict` deferred subsystems (type-safety debt, documented not silent):**
- Risk: `live_trading_system`, `trading_interface`, ccxt/oanda/binance providers, and `screeners_handler.*` are excluded from `--strict` via `[[tool.mypy.overrides]] ignore_errors=true` (`pyproject.toml:102-123`).
- Impact: New code in these modules is not type-checked; the `D-live` set overlaps the pending `live_trading_system.py` refactor.
- Migration plan: Each override is tagged with its owning-milestone deferral category; strict-clean lands with that milestone. Do not rely on these modules being typed; new in-scope code must be strict-clean.

## Missing Critical Features

**Pair-strategy live reconfiguration (atomic ordered-pair leg swap):**
- Problem: v1.7 shipped only a **refusal guard** (07 CR-01); atomic ordered-pair leg swap on a running live pair strategy is unbuilt.
- Blocks: Reconfiguring a live pairs strategy's legs without a stop/restart.
- Status: Deferred by design to the next milestone. Detail: `.planning/todos/pending/pair-strategy-live-reconfiguration.md`.

**Deferred-to-v2 live/realism features (tracked, non-blocking):**
- Perp realism Phase B — FUND-01..04 (funding accrual, mark-price liq, funding pipeline, freqtrade oracle).
- TRADE-01 trade-aggregation bar source (klines now, trades later).
- Optuna sampler + sweep loop (OPT-01) — v1.6 shipped only the FK-ready substrate.
- Turso/libSQL `sqlalchemy-libsql` opt-in backend (TURSO-01) — interface stays Turso-ready.
- Multi-currency accounting, trading calendars, corporate actions (`D-multiasset`) — deferred indefinitely (crypto-first).

**Resolved / stale-note correction — PostgreSQL order storage:**
- The historical `PostgreSQLOrderStorage` `NotImplementedError` placeholder is **RESOLVED** (D-05). The retired stub was replaced by a concrete `SqlOrderStorage` on the shared SQL spine (`itrader/order_handler/storage/sql_storage.py`, parameterized SQLAlchemy Core, full `OrderStorage` ABC, quarantined from the SQL-free backtest import path). The remaining commented import in `itrader/order_handler/storage/__init__.py:14` is a stale reference to the deleted class, not an active gap. No open concern here.

## Test Coverage Gaps

**ERROR-route circuit breaker — untested (because unbuilt):**
- What's not tested: Aggregate error-rate tripwire behavior on `_publish_and_continue` (see Fragile Areas / AUD-3).
- Files: `itrader/trading_system/live_trading_system.py:686-706`.
- Risk: A money route failing on every event runs infinitely green with no settlement — the highest-priority open safety gap.
- Priority: High.

**`backfill_on_resume` — exercised only by an integration warmup test, no production caller:**
- What's not tested: The production resume path (there is none yet).
- Files: `itrader/price_handler/feed/live_bar_feed.py:395`, `tests/integration/test_live_bar_feed_warmup.py`.
- Risk: The resume/backfill wiring can regress unnoticed because nothing production invokes it.
- Priority: Medium.

**Margin-mode open-position equity — no oracle-backed assertion:**
- What's not tested against an external oracle: Open-position (non-flat) margin equity; only final/flat equity is cross-validated.
- Files: `tests/golden/CROSS-VALIDATION-ACCOUNTING.md`, the 6 frozen goldens listed under WR-01.
- Risk: The disputed `30000`/`28000` open-position values are iTrader-internal hand-computation, so the WR-01 fix decision has no external ground truth.
- Priority: High (before any live margin consumer); currently owner-gated.

---

*Concerns audit: 2026-07-07*
