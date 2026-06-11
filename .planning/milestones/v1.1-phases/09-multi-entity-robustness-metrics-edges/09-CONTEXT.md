# Phase 9: Multi-Entity, Robustness & Metrics Edges - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the v1.1 breadth matrix — the **final scenario wave** — giving the engine's
multi-entity surface and its robustness / degenerate-metrics edges their **first
end-to-end golden coverage**, and proving determinism across every new scenario.
Hand-verified, leaf scenarios authored on the Phase 4 E2E harness (and the Phase
6 scripted-emitter / orders-snapshot + Phase 7 commission-column / exchange-seam +
Phase 8 cash-ledger infra), then `--freeze` regression-locked. Eight requirements:

- **MULTI-01** — one strategy trading two cryptos (multi-ticker) end-to-end.
- **MULTI-02** — multiple strategies running simultaneously.
- **MULTI-03** — a strategy fanned out to >1 portfolio, with per-portfolio cash
  isolation.
- **MULTI-04** — two strategies competing for the same portfolio's cash.
- **ROBUST-01** — a sparse/absent bar for a ticker at T produces no fill and no
  crash.
- **ROBUST-02** — heterogeneous date spans (asset enters mid-run; differing end
  dates) handled over a union window.
- **ROBUST-03** — no-trade / flat / losing runs produce valid metrics (no NaN, no
  div-by-zero in Sharpe / drawdown / profit-factor).
- **ROBUST-04** — determinism: a double-run is byte-identical across all new
  scenarios.

**This is a COVERAGE phase — the engine machinery already ships (scout-confirmed):**
- **Multi-portfolio / multi-strategy wiring already works in the harness** —
  `_build_and_run` (`conftest.py:307-321`) loops `spec.portfolios` calling
  `add_portfolio`, collects every `portfolio_id`, and subscribes EVERY
  `spec.strategies` entry to EVERY portfolio. The gap is purely on the **read
  side**: `_assemble` freezes ONLY `portfolios[0]` + `spec.ticker`
  (`conftest.py:326`, `:338`). The `PortfolioHandler` read surface needed to
  capture all of them already exists (`get_portfolio`, `get_active_portfolios`,
  `get_portfolio_count`) — **no production change**.
- **Multi-ticker** — `build_trade_log(portfolio)` already spans all tickers in a
  portfolio's `closed_positions`; the trade frame carries a `pair` column (the
  `_diff_frame` comment at `conftest.py` already anticipates single-ticker leaves
  omitting it). MULTI-01 rides the existing `trades.csv`.
- **Contended cash** — the synchronous check-and-reserve admission gate
  (`order_manager.py:384-414`, BUY-only) + the `cash_reservation` REJECTED audit
  is exactly the contention-loser path; `cash_operations.csv` (Phase 8 D-02)
  already serializes RESERVATION / RELEASE.
- **Heterogeneous spans / sparse bars** — the Phase 3 `is_active` /
  `active_membership` span primitive + the span-aware feed warn loop + the
  optional `csv_paths` passthrough on `TradingSystem.__init__` (default None →
  byte-identical) already handle mid-run listing, differing ends, and absent bars
  (no fill, no look-ahead). Phase 3 proved this on SYNTHETIC fixtures and
  **explicitly deferred the real ETH/SOL/AAVE E2E to Phase 9 / ROBUST-02**.
- **Degenerate metrics** — `reporting/metrics.py` is ALREADY NaN / div-by-zero
  guarded (`sharpe`: `<2` obs → 0.0, `sd==0` → 0.0; `sortino`: `downside==0` →
  0.0; `profit_factor`: `gross_loss==0` guarded; `cagr` guards). The
  `summary.json` `metrics` block (`build_metrics_block`) is produced every run and
  the harness already exact-diffs the WHOLE metrics dict (`conftest.py:442-447`).

We EXERCISE this behavior; we do not BUILD it. The only new code is thin test
scaffolding (per-portfolio summary snapshot serializer, a dedicated double-run
determinism test, the no-NaN guard for the degenerate leaves) plus the ~8
scenario leaves.

**In scope:**
- ~8 self-contained leaf scenarios under `tests/e2e/multi/` and
  `tests/e2e/robust/` (one-shape-per-leaf), each with VERIFY hand-derivation +
  frozen golden set. MULTI leaves on contrived bars; ROBUST-01/02 on REAL sliced
  data (D-02).
- A foundational (non-parallel) plan adding the shared scaffolding (per-portfolio
  snapshot serializer + opt-in wiring + multi-portfolio capture in
  `_assemble`/`_freeze`/`_diff`, the dedicated double-run test, the no-NaN guard)
  and proving it on ONE canary before the parallel scenario waves (Phase 6 D-13 /
  Phase 7 D-16 / Phase 8 D-05).

**Out of scope (own phases / behavior-preserving):**
- Shorts, margin, leverage, real long/short pair trading — **gated to N+2 (v1.2)**
  (LONG-ONLY throughout v1.1).
- Production screener / ranking / rebalance — **deferred to v1.4** (only the
  minimal `membership`-from-availability primitive is in v1.1, shipped Phase 3).
- Re-baselining the BTCUSD golden oracle — v1.1 is behavior-preserving. Every
  Phase 9 leaf runs on its OWN contrived/sliced data + configured spec, so
  oracle-darkness is automatic; `tests/integration/test_backtest_oracle.py` is
  never touched, and the per-portfolio snapshot serializer stays out of core
  `frames.py::TRADE_COLUMNS` (opt-in only).
- **CLAR-01/CLAR-02** (codebase clarity / opportunistic cleanup) — these map to
  Phase 1 in the traceability matrix and are a CROSS-CUTTING practice verified at
  milestone close, NOT Phase 9 deliverables.

</domain>

<decisions>
## Implementation Decisions

### Multi-entity capture vehicle (MULTI-01 / MULTI-03 / MULTI-04)
- **D-01:** **New opt-in per-portfolio summary snapshot.** The harness today
  freezes only `portfolios[0]`. Add a serializer producing ONE compact frame —
  **a row per portfolio** with `final_cash` / `final_equity` / `trade_count` /
  `realised_pnl` — following the Phase 8 `cash_operations.csv` **opt-in pattern**
  (only written when the placeholder golden already exists; `exists()`-gated). It
  is the single assertion surface for MULTI-03 per-portfolio **cash isolation**
  (portfolio A's numbers provably independent of B's). Determinism-safe columns
  only (no UUIDs); a stable per-portfolio key (the `name` / `user_id` from
  `PortfolioSpec`, NOT a raw `PortfolioId`).
  - **Test-harness only.** `_assemble`/`_freeze`/`_diff` iterate the already-built
    `portfolio_ids` (or `get_active_portfolios()`) and call the EXISTING
    `build_trade_log` / `build_summary` per portfolio for the snapshot rows. **No
    `PortfolioHandler` change, no new production serializer.** Oracle-dark: stays
    out of core `TRADE_COLUMNS`; existing single-portfolio leaves emit exactly one
    portfolio and only freeze the snapshot if they opt in.
  - **MULTI-01 (two cryptos)** rides the EXISTING `trades.csv` — `build_trade_log`
    already spans both tickers via the `pair` column; no new vehicle.
  - **MULTI-04 (contended cash)** reuses the EXISTING `cash_operations.csv` ledger
    (Phase 8 D-02) to show the winner's RESERVATION vs the loser's
    `cash_reservation` REJECTED — no extra vehicle.

### MULTI-04 contended-cash determinism (constraint, derived — NOT a question)
- **D-02:** Two strategies competing for ONE portfolio's cash on the same bar
  resolve **deterministically by `spec.strategies` registration order + FIFO
  dispatch**: `StrategiesHandler` emits signals in registration order, the
  `OrderManager` processes them FIFO, the first BUY reserves the cash, and the
  second hits the synchronous check-and-reserve gate → `InsufficientFundsError` →
  audited PENDING→REJECTED (`triggered_by="cash_reservation"`). The contention
  outcome is therefore fully deterministic and hand-verifiable. The leaf asserts
  one fill + one `cash_reservation` REJECTED (orders-snapshot + cash-ledger).

### ROBUST-01 (sparse bar) + ROBUST-02 (heterogeneous spans) data source
- **D-03:** **Real committed ETH/SOL/AAVE data, SLICED** to tiny hand-verifiable
  windows via the Phase 3 `csv_paths` passthrough — honoring Phase 3's explicitly
  deferred "real ETH/SOL/AAVE E2E" intent and exercising the REAL ingestion path
  end-to-end (Phase 3 already proved the mechanic on synthetic fixtures; repeating
  that would be duplication). Confirmed real edges (spans verified at discussion):
  - **ROBUST-02 mid-run listing / union window** — AAVE lists **2021-07-15** while
    BTC/ETH/SOL already trade; a window such as ~2021-07-10→07-20 is hand-verifiable
    (bars before 07-15 produce NO AAVE fill).
  - **ROBUST-02 differing end dates** — BTC runs to 2026-06-03 vs the others'
    2026-01-08 (available in the same data family for an end-edge leaf).
  - **ROBUST-01 sparse/absent bar** — SOL has 1416 rows over the same span where
    ETH has 1834 — genuinely **missing ~418 bars**; a real SOL window is the
    sparse-bar source (no contrivance). Absent bar at T → no fill, no crash.
  - Slices are SMALL enough to remain hand-verifiable per the freeze discipline.

### ROBUST-04 determinism mechanism
- **D-04:** **One dedicated double-run test**, parametrized over the Phase 9 e2e
  scenarios: run each scenario **twice in-process** and assert the two RAW outputs
  (trades / equity / summary) are identical **to each other** — independent of the
  frozen golden. This catches within-process non-determinism (state leakage, dict
  ordering, RNG misuse) that a golden-vs-golden diff cannot. A single new test, no
  per-leaf change to `run_scenario`.

### ROBUST-03 degenerate-metrics coverage + NaN guard
- **D-05:** **Three separate leaves — no-trade / flat / losing** — each freezing
  the `summary.json` `metrics` block (the harness already exact-diffs the whole
  metrics dict), **PLUS an explicit assert-no-NaN / no-inf** on the metrics for
  these leaves. The explicit guard self-documents that "no NaN" IS the ROBUST-03
  requirement and catches a NaN a hand-verifier might otherwise silently freeze
  (exact-equality alone fails on NaN since `NaN != NaN`, but the explicit assertion
  is the clearer contract). "flat" = a round-trip netting ~zero PnL; "losing" =
  a net-negative run.

### Plan / wave sequencing (carried forward — Phase 6 D-13 / Phase 7 D-16 / Phase 8 D-05)
- **D-06:** **Foundational plan first, then parallel waves.**
  - **Plan 1 (non-parallel):** the per-portfolio summary snapshot serializer +
    opt-in wiring + multi-portfolio capture in `_assemble`/`_freeze`/`_diff`
    (D-01), the dedicated double-run determinism test scaffold (D-04), the no-NaN
    guard (D-05), and ONE canary leaf proving the wiring end-to-end. **Re-runs the
    BTCUSD oracle gate byte-exact** (new serializer must stay out of core
    `TRADE_COLUMNS`; only fires opt-in).
  - **Then parallel waves** grouped MULTI / ROBUST; generate in isolated worktrees
    (Phase 6 leaf isolation), hand-verify + freeze **batched per cluster**
    (roadmap "not 12-at-once" + "shared infra committed first" preconditions).

### Claude's Discretion
- Exact per-portfolio snapshot column set, file name (e.g.
  `golden/portfolios.csv`), and the opt-in append/gate point (subject to D-01:
  determinism-safe, no UUIDs, stable per-portfolio key, orders/cash-snapshot
  opt-in pattern, out of core `TRADE_COLUMNS`).
- Exact real-data slice windows + which tickers per ROBUST-01/02 leaf (subject to
  D-03: real sliced data, small + hand-verifiable, genuine listing/end/gap edge).
- The double-run test's parametrization surface (Phase 9 leaves vs all e2e) and
  comparison mechanic (subject to D-04: in-process twice, raw-output self-compare).
- Exact contrived `bars.csv` authoring for the MULTI leaves (subject to
  one-shape-per-leaf + hand-derivable).
- Exact `tests/e2e/{multi,robust}/` sub-directory names/depth (subject to Phase 4
  subsystem grouping).
- Canary choice for the foundational plan and wave composition within the
  MULTI / ROBUST clusters (subject to D-06).
- Leaf↔requirement mapping (target ~8 leaves, one-shape-per-leaf): MULTI-01..04
  (4) + ROBUST-01/02 (real-data span/sparse) + ROBUST-03 (3 degenerate leaves);
  ROBUST-04 is a cross-cutting test, not its own leaf. Folds only where a contrast
  is the point (Phase 7 D-11 / Phase 8 D-04 precedent).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The harness + scenario infra this phase builds on (read FIRST)
- `.planning/phases/08-admission-position-management-cash-edges/08-CONTEXT.md` —
  the directly preceding sibling coverage phase: the **cash-ledger snapshot
  opt-in serializer** (D-02 — the exact pattern D-01's per-portfolio snapshot
  mirrors), the first **multi-ticker single-portfolio** leaf (`max_positions`,
  two co-subscribed `ScriptedEmitter`s — the multi-ticker precedent MULTI-01/02
  extend), `cash_reservation` REJECTED vs no-orphan contrast (the MULTI-04 loser
  path), foundational-plan-first + batched verify (D-05), and the explicit
  **"multi-portfolio / contended cash deferred to Phase 9 MULTI-03/04"** note.
- `.planning/phases/07-cost-sizing-sltp-scenarios/07-CONTEXT.md` — commission
  column append (D-07/D-08, the oracle-dark out-of-`TRADE_COLUMNS` precedent),
  the `spec.exchange` re-init seam (D-14), `ScriptedEmitter` extension precedent
  (D-12), one-leaf-per-requirement slicing (D-10).
- `.planning/phases/06-order-matching-scenarios/06-CONTEXT.md` — scripted-emitter
  (D-01), one-shape-per-leaf (D-11), the **opt-in orders-snapshot for no-trade /
  REJECTED outcomes** (D-08/D-09 — the MULTI-04 loser + ROBUST-03 no-trade
  vehicle), foundational-plan-first (D-13).
- `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` — base harness
  contract: per-folder one-line test → `run_scenario`; `ScenarioSpec` reuses real
  config; diff-what's-frozen; exact no-tolerance diff; CONTRIVED bars; `--freeze`
  + per-scenario VERIFY note; subsystem grouping.
- `.planning/phases/03-minimal-real-universe/03-CONTEXT.md` — the `is_active` /
  `active_membership` span primitive (D-01/D-03), the span-aware feed warn loop
  (D-04), and the optional `csv_paths` passthrough (D-06) that **explicitly
  defers the real ETH/SOL/AAVE E2E to Phase 9 / ROBUST-02** — D-03's data seam.
- `tests/e2e/conftest.py` — the `run_scenario` harness. **The multi-portfolio
  read gap lives here:** `_build_and_run` (`:299-326`, builds N portfolios,
  subscribes every strategy to every portfolio, then reads only
  `portfolio_ids[0]`); `_assemble` (`:330-401`, the per-portfolio capture
  extension point — pins `portfolios[0]` + `spec.ticker` today); the
  summary-metrics exact-diff (`:442-447`); the cash-ledger + orders opt-in gates
  (the per-portfolio snapshot's pattern).
- `tests/e2e/scenario_spec.py` — `ScenarioSpec` (`start`/`end`/`timeframe`/
  `data` ticker→CSV map / `strategies` (plural) / `portfolios` (plural) /
  `exchange` / `actions`) + `PortfolioSpec` (`user_id`/`name`/`cash` — the stable
  per-portfolio key D-01 uses) + `Action`. Field names are a consuming contract —
  do not rename.
- `tests/e2e/strategies/scripted_emitter.py` — the generic emitter reused per leaf
  (already supports `sizing_policy` / `sltp_policy` / `allow_increase` /
  `max_positions` / per-bar `side`/`sl`/`tp`/`exit_fraction`). Multiple instances
  → MULTI-02/04; one instance over two tickers → MULTI-01.
- `tests/e2e/smoke/single_market_buy/scenario.py` — the `scenario.py` + VERIFY-note
  copy-template each leaf clones.
- `tests/integration/test_backtest_oracle.py` — the byte-exact BTCUSD oracle gate
  the per-portfolio snapshot (D-01) must stay DARK against (must NOT enter core
  `TRADE_COLUMNS`; opt-in only).
- `tests/integration/test_universe_spans.py` — Phase 3's synthetic-fixture span
  integration test; the mechanic ROBUST-01/02 now re-prove on REAL sliced data.

### System under test — multi-entity / cash (already implemented)
- `itrader/portfolio_handler/portfolio_handler.py` — `add_portfolio` (`:124`),
  `get_portfolio` (`:168`), `get_active_portfolios` (`:208`),
  `get_portfolio_count` (`:216`), `_portfolios` map (`:76`) — the read surface
  D-01's per-portfolio capture uses (NO change needed).
- `itrader/order_handler/order_manager.py` — the synchronous BUY-only
  check-and-reserve admission gate (`~L384-414`, `InsufficientFundsError` →
  REJECTED `triggered_by="cash_reservation"`) — the MULTI-04 contention-loser path.
- `itrader/portfolio_handler/cash/cash_manager.py` — `reserve_cash`,
  `release_reservation`, `get_cash_operations`, the `CashOperation` ledger
  (RESERVATION / RELEASE_RESERVATION / TRANSACTION_*) — the MULTI-04 evidence.
- `itrader/strategy_handler/strategies_handler.py` — strategy registration +
  per-bar signal emission in registration order (the D-02 determinism source);
  `add_strategy`, `subscribe_portfolio`.

### System under test — universe / spans / data (already implemented)
- `itrader/universe/membership.py` — `is_active` / `active_membership` /
  `derive_membership` (Phase 3 span primitive; ROBUST-02 union window).
- `itrader/price_handler/feed/bar_feed.py` — the span-aware warn loop + the
  look-ahead-safety bar-timing contract; `generate_bar_event` (absent bar at T →
  no `BarEvent` → no fill; ROBUST-01).
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore` + the `csv_paths`
  passthrough (the real-sliced-data seam, D-03).
- `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.__init__`
  optional `csv_paths` (default None → byte-identical); `run(on_tick=...)` hook.
- Real datasets (D-03, spans verified): `data/BTCUSD_1d_ohlcv_2018_2026.csv`
  (2018-01-01→2026-06-03), `data/ETHUSD_1d_ohlcv.csv` (2021-01-01→2026-01-08),
  `data/SOLUSD_1d_ohlcv.csv` (2021-01-01→2026-01-08, **~418 bars missing** —
  sparse), `data/AAVEUSD_1d_ohlcv.csv` (**2021-07-15**→2026-01-08 — mid-run
  listing).

### System under test — metrics (already implemented + guarded)
- `itrader/reporting/metrics.py` — `sharpe` (`<2` obs → 0.0; `sd==0` → 0.0),
  `sortino` (`downside==0` → 0.0), `profit_factor` (`gross_loss==0` guarded),
  `cagr`, `max_drawdown`, `win_rate`, `compute_returns` — ALL degenerate-input
  guarded (ROBUST-03 is coverage of these guards, not new code).
- `itrader/reporting/summary.py` — `build_metrics_block` (the nested `metrics`
  dict frozen in `summary.json`), `build_summary` — the ROBUST-03 assertion
  surface.
- `itrader/reporting/frames.py` — `TRADE_COLUMNS` (the oracle-pinned core list,
  D-01 must NOT touch), `build_trade_log` (spans tickers → MULTI-01),
  `build_equity_curve`.

### Phase / requirements / roadmap
- `.planning/ROADMAP.md` §"Phase 9: Multi-Entity, Robustness & Metrics Edges" —
  goal + 4 success criteria + the Phase 6 parallelization REMINDER.
- `.planning/REQUIREMENTS.md` — MULTI-01..04 (`~L77-80`), ROBUST-01..04
  (`~L88-91`); CLAR-01/02 map to Phase 1 (cross-cutting, NOT Phase 9 work).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`run_scenario` harness + `--freeze`** (`tests/e2e/conftest.py`) — full
  build-run-diff machinery; already builds N portfolios + subscribes N strategies.
  Phase 9 extends only its READ side (`_assemble`) for per-portfolio capture.
- **`cash_operations.csv` opt-in snapshot** (Phase 8 D-02) — the exact pattern
  D-01's per-portfolio summary snapshot mirrors; reused verbatim for MULTI-04.
- **Opt-in orders-snapshot** (Phase 6 D-08) — the MULTI-04 loser REJECTED +
  ROBUST-03 no-trade outcome vehicle.
- **`csv_paths` passthrough + span primitive** (Phase 3) — the real-sliced-data
  seam for ROBUST-01/02; `TradingSystem.__init__(csv_paths=...)` default None =
  byte-identical.
- **`reporting/metrics.py` guards + `build_metrics_block`** — ROBUST-03 covers the
  EXISTING guards; the `summary.json` metrics block + exact-diff are the assertion.
- **`ScriptedEmitter` + `ScenarioSpec` (plural `strategies`/`portfolios`) + leaf
  copy-template** — multiple emitters → MULTI-02/04; one emitter over two tickers →
  MULTI-01; one strategy + multiple portfolios → MULTI-03.
- **All multi-entity / span / metrics engine logic already exists** — Phase 9
  COVERS it, does not build it.

### Established Patterns
- **Self-contained, parallel-safe leaf folders** — basis for the leaf slicing +
  parallel waves.
- **Diff-what's-frozen / presence=assertion / exact no-tolerance diff** — the
  per-portfolio snapshot, MULTI-04 cash-ledger, ROBUST-03 metrics block all follow.
- **Behavior-preserving / oracle-dark** — own contrived/sliced data + configured
  spec; the BTCUSD oracle is never touched; the per-portfolio serializer stays out
  of core `TRADE_COLUMNS` and only fires opt-in.
- **Foundational-plan-first** (Phase 6 D-13 / Phase 7 D-16 / Phase 8 D-05) — shared
  scaffolding + one canary + oracle re-run byte-exact before the parallel wave.

### Integration Points
- Per-portfolio snapshot: iterate `portfolio_ids` in `_assemble` → existing
  `build_trade_log`/`build_summary` per portfolio → opt-in golden (cash-ops pattern).
- MULTI-04: `spec.strategies` registration order → `StrategiesHandler` FIFO emit →
  `OrderManager` reserve gate → `cash_operations.csv` + orders-snapshot.
- ROBUST-01/02: real sliced CSVs via `csv_paths` → `active_membership` / span-aware
  feed → trades/summary over the union window.
- ROBUST-03: no-trade/flat/losing leaf → `build_metrics_block` → frozen
  `summary.json` metrics + explicit no-NaN assert.
- ROBUST-04: dedicated double-run test → each Phase 9 scenario run twice → raw
  output self-compare.
- `tests/e2e/{multi,robust}/` leaves ← built on all the above in the parallel waves.

</code_context>

<specifics>
## Specific Ideas

- **The multi-portfolio gap is read-side only (D-01).** The user confirmed the
  capture vehicle is the lighter opt-in per-portfolio summary snapshot (not full
  per-portfolio golden subdirs) after verifying it touches ONLY the test harness —
  `PortfolioHandler` already exposes `get_portfolio`/`get_active_portfolios`, so no
  production class changes. Isolation is proven by a compact "row per portfolio"
  frame.
- **Real data over synthetic re-proof (D-03).** The user chose the REAL committed
  ETH/SOL/AAVE datasets (sliced) for ROBUST-01/02 — honoring Phase 3's explicit
  deferral of the "real E2E" and exercising the actual ingestion path — over
  re-running Phase 3's synthetic-fixture mechanic. The real spans were verified to
  genuinely contain a mid-run listing (AAVE 2021-07-15), differing end dates, and
  sparse bars (SOL ~418 missing) — all three edges, no contrivance.
- **Explicit no-NaN over implicit equality (D-05).** Even though the frozen-golden
  exact-equality already fails on a NaN metric, the user chose an explicit
  assert-no-NaN guard for the degenerate leaves because "no NaN" IS the ROBUST-03
  contract — the assertion documents intent and prevents a hand-verifier silently
  freezing a NaN.
- **In-process double-run over golden-lock-suffices (D-04).** The user chose a real
  double-run self-compare (not "the golden regression is enough") to catch
  within-process non-determinism a golden-vs-golden diff cannot.

</specifics>

<deferred>
## Deferred Ideas

- **Full per-portfolio golden subdirs** (a complete `trades.csv`/`summary.json`
  per portfolio) — considered for D-01 and set aside in favor of the lighter
  opt-in per-portfolio summary snapshot. Revisit only if a future multi-portfolio
  scenario needs full per-portfolio trade-level evidence (not just isolation
  roll-ups).
- **Per-leaf `--double-run` mode in `run_scenario`** — considered for D-04 and set
  aside in favor of one dedicated parametrized test; revisit only if determinism
  needs to be asserted inline for every leaf.
- **Shorts / real long/short pair trading / margin / leverage** — the "short half"
  of breadth; hard-gated by the LONG_ONLY guard + the CR-01 cover-arm hole →
  **N+2 (v1.2)**.
- **Production screener / ranking / rebalance loop** — only the minimal
  `membership` primitive is in v1.1 → **v1.4**.
- **RNG-driven REFUSED (`simulate_failures`)** (carried from Phase 8) — still
  deliberately unused; deterministic levers preferred.

None of these block Phase 9 — discussion stayed within scope.

</deferred>

---

*Phase: 9-Multi-Entity, Robustness & Metrics Edges*
*Context gathered: 2026-06-10*
