# Phase 9: Multi-Entity, Robustness & Metrics Edges - Research

**Researched:** 2026-06-10
**Domain:** E2E golden-coverage authoring on an existing event-driven backtest engine (no new production code beyond thin test scaffolding)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Multi-entity capture vehicle:** New **opt-in per-portfolio summary snapshot** — ONE compact frame, a row per portfolio with `final_cash` / `final_equity` / `trade_count` / `realised_pnl`, following the Phase 8 `cash_operations.csv` opt-in pattern (`exists()`-gated). Single assertion surface for MULTI-03 per-portfolio cash isolation. Determinism-safe columns only (no UUIDs); stable per-portfolio key = `name`/`user_id` from `PortfolioSpec`, **NOT** a raw `PortfolioId`. **Test-harness only** — `_assemble`/`_freeze`/`_diff` iterate the already-built `portfolio_ids` (or `get_active_portfolios()`) and call the EXISTING `build_trade_log`/`build_summary` per portfolio. **No `PortfolioHandler` change, no new production serializer.** Stays out of core `TRADE_COLUMNS`. MULTI-01 rides the EXISTING `trades.csv` (`pair` column spans both tickers). MULTI-04 reuses the EXISTING `cash_operations.csv` ledger.
- **D-02 — MULTI-04 contended-cash determinism (constraint, not a question):** Two strategies competing for ONE portfolio's cash on the same bar resolve deterministically by `spec.strategies` registration order + FIFO dispatch. `StrategiesHandler` emits signals in registration order; `OrderManager` processes FIFO; first BUY reserves cash; second hits the synchronous check-and-reserve gate → `InsufficientFundsError` → audited PENDING→REJECTED (`triggered_by="cash_reservation"`). Leaf asserts one fill + one `cash_reservation` REJECTED.
- **D-03 — ROBUST-01/02 data source:** Real committed ETH/SOL/AAVE data, SLICED to tiny hand-verifiable windows via the Phase 3 `csv_paths` passthrough. ROBUST-02 mid-run listing: AAVE lists 2021-07-15. ROBUST-02 differing end dates: BTC→2026-06-03 vs others 2026-01-08. ROBUST-01 sparse bar: SOL genuinely missing bars. Slices small enough to remain hand-verifiable.
- **D-04 — ROBUST-04 determinism mechanism:** ONE dedicated double-run test, parametrized over the Phase 9 e2e scenarios — run each scenario **twice in-process** and assert the two RAW outputs (trades/equity/summary) are identical to EACH OTHER, independent of the frozen golden. Catches within-process non-determinism a golden-vs-golden diff cannot.
- **D-05 — ROBUST-03 degenerate metrics:** Three separate leaves — **no-trade / flat / losing** — each freezing the `summary.json` `metrics` block PLUS an explicit **assert-no-NaN / no-inf** on the metrics. "flat" = round-trip netting ~zero PnL; "losing" = net-negative run.
- **D-06 — Plan/wave sequencing:** Foundational plan first (per-portfolio snapshot serializer + opt-in wiring + multi-portfolio capture in `_assemble`/`_freeze`/`_diff`, double-run test scaffold, no-NaN guard, ONE canary leaf; re-runs BTCUSD oracle byte-exact), then parallel MULTI/ROBUST waves in isolated worktrees, hand-verify + freeze batched per cluster.

### Claude's Discretion

- Exact per-portfolio snapshot column set, file name (e.g. `golden/portfolios.csv`), and the opt-in append/gate point (subject to D-01).
- Exact real-data slice windows + which tickers per ROBUST-01/02 leaf (subject to D-03).
- The double-run test's parametrization surface (Phase 9 leaves vs all e2e) and comparison mechanic (subject to D-04).
- Exact contrived `bars.csv` authoring for MULTI leaves (subject to one-shape-per-leaf + hand-derivable).
- Exact `tests/e2e/{multi,robust}/` sub-directory names/depth (subject to Phase 4 subsystem grouping).
- Canary choice for the foundational plan and wave composition within MULTI/ROBUST clusters (subject to D-06).
- Leaf↔requirement mapping (~8 leaves, one-shape-per-leaf): MULTI-01..04 (4) + ROBUST-01/02 (real-data) + ROBUST-03 (3 degenerate leaves); ROBUST-04 is a cross-cutting test, not its own leaf.

### Deferred Ideas (OUT OF SCOPE)

- Full per-portfolio golden subdirs (complete `trades.csv`/`summary.json` per portfolio) — set aside for the lighter snapshot.
- Per-leaf `--double-run` mode in `run_scenario` — set aside for one dedicated parametrized test.
- Shorts / real long/short pair trading / margin / leverage → N+2 (v1.2). LONG-ONLY throughout v1.1.
- Production screener / ranking / rebalance → v1.4.
- RNG-driven REFUSED (`simulate_failures`) — deliberately unused; deterministic levers preferred.
- Re-baselining the BTCUSD golden oracle — v1.1 is behavior-preserving.
- CLAR-01/CLAR-02 — map to Phase 1, cross-cutting, NOT Phase 9 deliverables.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MULTI-01 | One strategy trading two cryptos (multi-ticker) end-to-end | EXISTING `build_trade_log` spans both tickers via the `pair` column (`frames.py:24-36`, `:52-63`); one `ScriptedEmitter` over two tickers; rides existing `trades.csv`. ADMIT max_positions leaf is the multi-CSV precedent (`bars.csv` + `bars_eth.csv`). |
| MULTI-02 | Multiple strategies running simultaneously | `_build_and_run` subscribes EVERY `spec.strategies` to EVERY portfolio (`conftest.py:299-318`); two `ScriptedEmitter` instances → two co-running strategies (ADMIT precedent). |
| MULTI-03 | Strategy fanned to >1 portfolio, per-portfolio cash isolation | NEW per-portfolio summary snapshot (D-01) is the assertion surface. `max_portfolios=50` (`config/portfolio.py:42`) — multi-portfolio fits. Read surface exists: `get_portfolio`/`get_active_portfolios`/`get_portfolio_count` (`portfolio_handler.py:168/208/216`). |
| MULTI-04 | Two strategies competing for the same portfolio's cash | `self.strategies` ordered list, registration-order iteration (`strategies_handler.py:46/68/232`) + synchronous BUY-only check-and-reserve gate (`order_manager.py:393-414`); winner RESERVATION vs loser `cash_reservation` REJECTED via EXISTING `cash_operations.csv`. |
| ROBUST-01 | Sparse/absent bar at T → no fill, no crash | Sparse-ticker guard: `event.bars.get(ticker)` is `None` → `continue` (`strategies_handler.py:~80-85`, WR-12) + feed span-aware observability. SOL is genuinely missing **2023-06-24 and 2023-06-25** (verified). |
| ROBUST-02 | Heterogeneous spans (mid-run listing; differing ends), union window | Phase 3 `is_active`/`active_membership` (`universe/membership.py`) + span-aware feed warn loop + `csv_paths` passthrough (`TradingSystem.__init__` line 54; default None → byte-identical). AAVE lists 2021-07-15; BTC ends 2026-06-03 vs others 2026-01-08 (verified). |
| ROBUST-03 | No-trade/flat/losing → valid metrics (no NaN, no div-by-zero) | `metrics.py` ALL degenerate-guarded (`sharpe` `<2`/`sd==0`→0.0; `sortino` `downside==0`→0.0; `profit_factor` `gross_loss==0` guarded; `cagr` guards). `build_metrics_block` (`summary.py:98`) frozen + exact-diffed (`conftest.py:444-447`). Three leaves + explicit no-NaN assert (D-05). |
| ROBUST-04 | Determinism — double-run byte-identical across all new scenarios | ONE dedicated parametrized in-process double-run test (D-04). Engine already deterministic (seeded RNG `performance.rng_seed=42`, injected `BacktestClock`, single-threaded backtest for-loop). |
</phase_requirements>

## Summary

Phase 9 is a **COVERAGE phase, not a build phase** — every engine mechanic it exercises already
ships and is scout-confirmed. I verified each major claim directly against the codebase and the
committed datasets: the multi-portfolio/multi-strategy wiring already loops in `_build_and_run`
(`conftest.py:299-318`); `build_trade_log` already spans tickers via the `pair` column; the
synchronous BUY-only check-and-reserve admission gate (`order_manager.py:393-414`) is the exact
MULTI-04 contention-loser path; the Phase 3 `csv_paths` passthrough (`TradingSystem.__init__`
line 54) and the span-aware sparse-ticker guard (`strategies_handler.py` WR-12) handle ROBUST-01/02;
and `reporting/metrics.py` is fully NaN/div-by-zero guarded with `build_metrics_block` already
exact-diffed in the harness. The ONLY new code is thin **test scaffolding** (a per-portfolio
summary snapshot serializer + opt-in wiring, a parametrized double-run test, a no-NaN guard) plus
~8 hand-verified E2E leaf scenarios.

The single most important new finding is about the **SOL sparse-bar data shape** (ROBUST-01): SOL's
418 missing bars are NOT scattered single-day gaps — they are essentially ONE 416-day block
(2023-07-07 → 2024-08-25) plus exactly one clean 2-day gap (**2023-06-24 and 2023-06-25**, both
present in ETH and AAVE). The 2-day gap is the only genuinely hand-verifiable sparse-bar window;
the planner should target it (or a slice straddling the start of the big block) rather than assume
diffuse sparseness. All other CONTEXT.md span claims (AAVE 2021-07-15 listing, BTC 2026-06-03 vs
others 2026-01-08 end, SOL 1416 vs ETH 1834 rows) verified exactly.

**Primary recommendation:** Build the foundational plan (D-06) exactly mirroring the Phase 8
`cash_operations.csv` opt-in serializer — `exists()`-gated, business-columns-only, keyed by the
stable `PortfolioSpec.name`, out of core `TRADE_COLUMNS`, with one canary leaf proving the wiring
and the BTCUSD oracle re-run byte-exact — then author the ~8 leaves in parallel waves, freezing one
hand-verified leaf at a time (the harness mechanically refuses `--freeze` with >1 selected test).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-portfolio snapshot serialization | Test harness (`tests/e2e/conftest.py`) | reporting (`build_trade_log`/`build_summary`, reused) | D-01: test-harness only; iterate existing `portfolio_ids` and call EXISTING per-portfolio reporting. No production change. |
| Multi-portfolio/multi-strategy wiring | Test harness (`_build_and_run`) | PortfolioHandler/StrategiesHandler (read/registration) | Already loops portfolios+strategies; gap is read-side only. |
| Contended-cash resolution (MULTI-04) | Engine — OrderManager admission gate | CashManager ledger | Synchronous check-and-reserve is the deterministic loser path; serialized via existing `cash_operations.csv`. |
| Sparse/absent bar handling (ROBUST-01) | Engine — StrategiesHandler sparse guard + feed | price store (sliced CSV) | `event.bars.get(ticker) is None → continue`; feed is the span-aware observability owner. |
| Heterogeneous spans / union window (ROBUST-02) | Engine — universe membership + feed | TradingSystem `csv_paths` seam | Phase 3 `is_active`/`active_membership` over the union window. |
| Degenerate metrics (ROBUST-03) | reporting/metrics (guarded) | Test harness (no-NaN assert) | Guards already exist; leaf adds explicit assertion + frozen metrics block. |
| Determinism proof (ROBUST-04) | Test (dedicated double-run) | Engine (seeded RNG, injected clock) | In-process self-compare catches within-run non-determinism. |

## Standard Stack

No new packages. This phase uses ONLY the existing toolchain.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.4.2 | E2E leaf test runner; `e2e` marker; `run_scenario` fixture | Already the project's only test runner; `make test-e2e` wired (`Makefile:39-41`). |
| pandas | 2.3.3 | Frame assembly/diff for goldens (`assert_frame_equal`) | The harness diff mechanic and all reporting builders are pandas. |
| numpy | >=2.2.3,<2.3 | Underlying metric math (`np.sqrt`, `np.clip`) | Used by `reporting/metrics.py`; `np.isnan`/`np.isfinite` for the D-05 no-NaN guard. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `math.isnan`/`math.isfinite` (stdlib) | 3.13 | Per-scalar NaN/inf guard on the metrics dict (D-05) | Simplest for iterating a `dict[str, float]`; no extra import beyond stdlib. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `math.isnan`/`math.isfinite` per value | `np.isfinite(np.array(list(metrics.values())))` | numpy vectorizes but the metrics block is tiny (6 keys); stdlib is clearer and avoids array construction. Either is fine (D-05 discretion). |
| Per-portfolio summary snapshot (D-01) | Full per-portfolio golden subdirs | LOCKED to the lighter snapshot; full subdirs deferred. |

**Installation:** None — no new dependencies. `mypy --strict` over `itrader` is unaffected (test scaffolding lives under `tests/`, which is not in `[tool.mypy].files`).

## Package Legitimacy Audit

Not applicable — this phase installs **no external packages**. All work uses the existing
committed toolchain (pytest, pandas, numpy, stdlib). slopcheck/registry verification is moot.

## Architecture Patterns

### System Architecture Diagram — the `run_scenario` build→run→read→assemble→diff flow

```
leaf scenario.py (SCENARIO: ScenarioSpec)
        │  _load_spec (unique sys.modules name per leaf path — Pitfall 4)
        ▼
_build_and_run(spec)
        │  TradingSystem(exchange="csv", start/end/timeframe, csv_paths=spec.data)
        │  [optional] apply spec.exchange (fee/slippage seam, D-14) — None for most leaves
        │  for strategy in spec.strategies:  add_strategy
        │  for pf in spec.portfolios:        add_portfolio → portfolio_id
        │                                    for strategy: strategy.subscribe_portfolio(pid)
        │  system.run(on_tick=_make_on_tick(spec, portfolio_ids[0]))   # actions=() → None hook
        ▼
   read AFTER run (queue-only, D-07)
        │  TODAY: portfolio = get_portfolio(portfolio_ids[0])   ◄── MULTI-03 READ GAP
        ▼
_assemble(spec, system, portfolio, portfolio_id)
        │  trades  = build_trade_log(portfolio)          # spans tickers via `pair` (MULTI-01)
        │  equity  = build_equity_curve(portfolio)
        │  orders  = build_orders_snapshot(get_orders_by_ticker(spec.ticker, pid))  # opt-in
        │  cash_ops= build_cash_operations(portfolio.cash_manager.get_cash_operations())  # opt-in (MULTI-04)
        │  + attach_slippage, + always-on commission column
        │  summary = build_summary(...); summary["metrics"] = build_metrics_block(...)  # ROBUST-03
        │  ◄── NEW (D-01): iterate portfolio_ids → per-portfolio build_summary rows → portfolios.csv
        ▼
   --freeze ?  ──yes──►  _freeze(golden_dir, ...)   # exists()-gated opt-in writes
        │ no
        ▼
_diff(golden_dir, ...)  # presence = assertion; exact no-tolerance assert_frame_equal
                        # + _diff_summary: whole metrics dict == + scalar key-set ==
```

### Recommended Project Structure (Claude's discretion under D-01/D-06)

```
tests/e2e/
├── conftest.py                  # EXTEND: per-portfolio capture in _assemble/_freeze/_diff
├── scenario_spec.py             # UNCHANGED (plural strategies/portfolios already supported)
├── strategies/scripted_emitter.py  # UNCHANGED (multi-instance + multi-ticker ready)
├── multi/                       # MULTI cluster (contrived bars)
│   ├── two_tickers/             # MULTI-01: one emitter, two tickers
│   ├── two_strategies/          # MULTI-02: two emitters, one portfolio
│   ├── fanout_portfolios/       # MULTI-03: one strategy → >1 portfolio (canary candidate)
│   └── contended_cash/          # MULTI-04: two emitters compete for one portfolio's cash
└── robust/                      # ROBUST cluster
    ├── sparse_bar/              # ROBUST-01: REAL sliced SOL over the 2023-06-24/25 gap
    ├── union_window/            # ROBUST-02: REAL sliced AAVE mid-run listing + differing ends
    ├── no_trade/                # ROBUST-03a: zero closed trades
    ├── flat/                    # ROBUST-03b: round-trip ~zero PnL
    └── losing/                  # ROBUST-03c: net-negative run
tests/e2e/robust/test_determinism.py   # ROBUST-04: parametrized in-process double-run (D-04)
```

### Pattern 1: Opt-in serializer mirroring `cash_operations.csv` (D-01)
**What:** A new per-portfolio summary snapshot that materializes ONLY when the leaf commits a
placeholder golden, and is diffed only if present.
**When to use:** MULTI-03 (and any future per-portfolio-isolation leaf).
**Example (the exact pattern to mirror — `conftest.py` `_freeze`/`_diff` gates):**
```python
# Source: tests/e2e/conftest.py:512-519 (cash_operations opt-in freeze gate)
if (golden_dir / "cash_operations.csv").exists():
    cash_ops[CASH_OPERATION_COLUMNS].to_csv(
        golden_dir / "cash_operations.csv", index=False, float_format=FLOAT_FORMAT)
# _diff mirror (conftest.py:573-577):
cash_ops_golden = golden_dir / "cash_operations.csv"
if cash_ops_golden.exists():
    gold = pd.read_csv(cash_ops_golden)
    fresh = _roundtrip(cash_ops, CASH_OPERATION_COLUMNS)
    _diff_frame(fresh, gold, _CASH_OPS_IDENTITY_COLUMNS, _CASH_OPS_SORT_KEYS)
```
The per-portfolio snapshot follows the identical shape: a `portfolios.csv` (suggested name),
`exists()`-gated in both `_freeze` and `_diff`, built by iterating `portfolio_ids` and calling
the EXISTING `build_summary`/`build_trade_log` per portfolio.

### Pattern 2: Per-portfolio snapshot construction (D-01, harness-only)
**What:** Iterate the already-built portfolio ids, build one row per portfolio.
**When to use:** In `_assemble`, after the existing single-portfolio assembly.
**Example (construction sketch — uses ONLY existing read surface):**
```python
# Stable key = PortfolioSpec.name (NOT the UUIDv7 PortfolioId — D-01).
# spec.portfolios[i].name aligns with portfolio_ids[i] by construction order.
rows = []
for spec_pf, pid in zip(spec.portfolios, portfolio_ids):
    pf = system.portfolio_handler.get_portfolio(pid)          # existing read (handler:168)
    pf_trades = build_trade_log(pf)                            # existing builder
    pf_summary = build_summary(pf, pf_trades, ticker=spec.ticker, timeframe=spec.timeframe,
                               start_date=spec.start, end_date=spec.end, starting_cash=spec_pf.cash)
    rows.append({
        "portfolio": spec_pf.name,                            # stable, determinism-safe key
        "final_cash": pf_summary["final_cash"],
        "final_equity": pf_summary["final_equity"],
        "trade_count": pf_summary["trade_count"],
        "realised_pnl": pf_summary["total_realised_pnl"],
    })
portfolios_frame = pd.DataFrame(rows, columns=PORTFOLIO_SNAPSHOT_COLUMNS)
```
Identity column for `_diff_frame` = `["portfolio"]`; sort key = `["portfolio"]`. No UUIDs, no
wall-clock, all determinism-safe.

### Pattern 3: Parametrized in-process double-run (D-04, ROBUST-04)
**What:** Run each Phase 9 scenario twice in one process; assert raw outputs equal each other.
**When to use:** The single dedicated determinism test (not per-leaf).
**Example (mechanic — reuses `_build_and_run`/`_assemble`, NOT the golden diff):**
```python
# Source: derived from conftest._build_and_run + _assemble (conftest.py:252-401)
@pytest.mark.parametrize("leaf_dir", PHASE9_LEAVES)   # discretion: Phase 9 leaves vs all e2e
def test_double_run_identical(leaf_dir):
    def once():
        spec = _load_spec(leaf_dir / "scenario.py")
        system, portfolio, pid = _build_and_run(spec)
        return _assemble(spec, system, portfolio, pid)   # (trades, equity, summary, orders, cash_ops)
    a = once(); b = once()
    pdt.assert_frame_equal(a[0], b[0])                    # trades
    pdt.assert_frame_equal(a[1], b[1])                    # equity
    assert a[2] == b[2]                                    # summary dict (incl. metrics block)
```
NOTE: the harness's private `_load_spec`/`_build_and_run`/`_assemble` are module-level functions
in `conftest.py` — the determinism test will need them exposed (import from conftest, or promote
the trio to a small importable module). This is a foundational-plan wiring decision.

### Anti-Patterns to Avoid
- **Keying the per-portfolio snapshot by `PortfolioId`:** It is a UUIDv7 (`portfolio.py:52`,
  `idgen.generate_portfolio_id()`) — non-deterministic across runs. Use `PortfolioSpec.name`.
- **Adding the per-portfolio columns to core `TRADE_COLUMNS`:** That pin feeds
  `scripts/run_backtest.py` + the BTCUSD oracle (`test_backtest_oracle.py`) — touching it breaks
  byte-exactness. Keep the snapshot harness-local, like `COMMISSION_COLUMN` (`conftest.py:97`).
- **Blind multi-leaf `--freeze` sweep:** The harness refuses `--freeze` with >1 selected test
  (`conftest.py:607-613`). Freeze one hand-verified leaf at a time.
- **Assuming SOL is diffusely sparse:** It is NOT — the 418 missing bars are ~one 416-day block.
  Target the clean 2-day gap (2023-06-24/25) for the hand-verifiable ROBUST-01 slice.
- **Injecting raw `OrderEvent(MODIFY/CANCEL)` for MULTI leaves:** Not needed here; MULTI leaves are
  fill/reservation shapes, not operator round-trips.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-portfolio summary rows | A new production serializer in `reporting/` | EXISTING `build_summary`/`build_trade_log` per portfolio, harness-local (D-01) | No production change needed; the read surface already exists. |
| Multi-portfolio wiring | A new build loop | EXISTING `_build_and_run` portfolio/strategy loops (`conftest.py:307-318`) | Already subscribes every strategy to every portfolio. |
| Multi-ticker trade frame | A per-ticker merge | EXISTING `build_trade_log` (`pair` column spans tickers) | MULTI-01 rides `trades.csv` unchanged. |
| Contended-cash loser detection | Custom cash check | EXISTING synchronous reserve gate → `cash_reservation` REJECTED (`order_manager.py:393-414`) | The engine already produces the audited loser. |
| Sparse/absent-bar skip | Custom feed filtering | EXISTING `event.bars.get(ticker) is None → continue` + span-aware feed | The no-fill-no-crash mechanic already exists. |
| Union-window span logic | Custom date math | EXISTING `active_membership`/`is_active` (`universe/membership.py`) | Phase 3 primitive, already proven on synthetic fixtures. |
| Degenerate-metrics guards | Custom NaN handling in metrics | EXISTING guards in `reporting/metrics.py` | Every denominator already guarded; only ADD an explicit assert in the leaf. |
| Real-data slicing | A new loader | EXISTING `csv_paths` passthrough (`TradingSystem.__init__:54`) | Default None = byte-identical; slices are just small committed CSVs. |
| Determinism diff | Custom comparator | EXISTING `pdt.assert_frame_equal` + dict `==` | The harness already uses exact no-tolerance compares. |

**Key insight:** The entire phase is "wire the existing read surface into the existing harness and
author small hand-verified fixtures." Every temptation to build engine logic is a sign the leaf is
mis-scoped — the machinery already ships.

## Runtime State Inventory

> Rename/refactor inventory. This phase is **additive test scaffolding + new test fixtures only** —
> no rename, no production data migration. Each category answered explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — leaves run in-memory (D-07, no `output/` folder); backtest uses in-memory order storage. | None — verified: harness reads portfolio state after run, no persistence. |
| Live service config | None — backtest-only, no external services. | None. |
| OS-registered state | None — pytest leaves, no OS registration. | None. |
| Secrets/env vars | None — no new env vars; `csv_paths` is a constructor arg, not env. | None. |
| Build artifacts | New committed test CSVs (sliced real data under `tests/e2e/robust/*/`) + new golden fixtures + a new `portfolios.csv` golden per opt-in leaf. The foundational plan re-runs the BTCUSD oracle byte-exact (D-06) to confirm no artifact drift. | Commit new fixtures; verify oracle byte-exact after the serializer lands. |

## Common Pitfalls

### Pitfall 1: SOL sparse-bar shape is one big block, not scattered gaps
**What goes wrong:** Authoring ROBUST-01 assuming SOL has many small gaps to slice anywhere.
**Why it happens:** CONTEXT.md says "~418 bars missing" which reads like diffuse sparseness.
**How to avoid:** The missing bars are ONE 416-day block (2023-07-07 → 2024-08-25) plus exactly
one 2-day gap (2023-06-24, 2023-06-25). Use the 2-day gap (both dates present in ETH+AAVE as the
"asset trades, SOL absent" control) or a slice straddling 2023-07-07. Verified directly against
`data/SOLUSD_1d_ohlcv.csv`.
**Warning signs:** A slice that picks a "random" SOL window will be either fully dense or fully
inside the 416-day hole — neither is a clean single-absent-bar demonstration.

### Pitfall 2: Keying the per-portfolio snapshot on a non-deterministic id
**What goes wrong:** Frozen golden differs every run → unfreezable.
**Why it happens:** `add_portfolio` returns a UUIDv7-based `PortfolioId` (`portfolio.py:52`).
**How to avoid:** Key on `PortfolioSpec.name` (D-01). `spec.portfolios[i]` aligns with
`portfolio_ids[i]` by construction order in `_build_and_run`.
**Warning signs:** Golden rows containing UUID strings, or rows that reorder between runs.

### Pitfall 3: Breaking the BTCUSD oracle by widening a core pin
**What goes wrong:** Adding the per-portfolio columns to `TRADE_COLUMNS` → oracle byte-diff.
**Why it happens:** `TRADE_COLUMNS` feeds `run_backtest.py` + the oracle (`frames.py:24`).
**How to avoid:** Keep the snapshot harness-local (a new module-level `PORTFOLIO_SNAPSHOT_COLUMNS`
in `conftest.py` or a sibling), exactly like the always-on `COMMISSION_COLUMN` (`conftest.py:97`)
and the opt-in `CASH_OPERATION_COLUMNS`. Re-run `make test-integration` / the oracle test after.
**Warning signs:** `test_backtest_oracle.py` fails after the serializer lands.

### Pitfall 4: `filterwarnings=["error"]` turns any warning into a failure
**What goes wrong:** A pandas FutureWarning or empty-slice RuntimeWarning fails the leaf.
**Why it happens:** `pyproject.toml` sets `filterwarnings=["error"]` + `--strict-markers`.
**How to avoid:** Use pandas-2-safe idioms (`.iloc`, explicit empty guards) — the existing
`metrics.py` already does this. The no-trade/flat/losing leaves (ROBUST-03) run on equity curves
with few/degenerate observations; the metrics functions are already guarded, but verify the leaf
itself adds no unguarded numpy op. Every new leaf must carry the `e2e` marker (folder-derived).
**Warning signs:** A green-locally leaf failing in CI on a warning, or an undeclared-marker error.

### Pitfall 5: Freezing a NaN silently (the reason D-05 mandates an explicit assert)
**What goes wrong:** Exact-equality "passes" on a NaN only if both sides are NaN — but `NaN != NaN`,
so a frozen NaN actually FAILS the diff confusingly, and a hand-verifier might mis-read it.
**Why it happens:** `summary["metrics"]` is dict-compared (`conftest.py:444-447`); `float('nan')`
breaks `==`.
**How to avoid:** D-05 — add an explicit `assert all(math.isfinite(v) for v in metrics.values())`
in the ROBUST-03 leaves BEFORE freezing, so "no NaN" is the documented contract.
**Warning signs:** A metrics-block diff that fails with NaN on both sides.

### Pitfall 6: The double-run test needs harness internals exposed
**What goes wrong:** `_build_and_run`/`_assemble`/`_load_spec` are private conftest functions; a
separate `test_determinism.py` can't import them cleanly.
**Why it happens:** They live in `conftest.py` (auto-imported as a fixture module, not a normal
import target across directories).
**How to avoid:** Foundational plan exposes the trio — either import from `tests.e2e.conftest`
directly (works since it's a real module) or promote the build/assemble helpers to a small
importable `tests/e2e/_harness.py`. Decide this in Plan 1.
**Warning signs:** `ImportError` or fixture-scope confusion in the determinism test.

## Code Examples

### Verifying real dataset spans (the D-03 evidence, reproducible)
```python
# Source: ran against committed data/*.csv on 2026-06-10
import pandas as pd
sol = pd.read_csv("data/SOLUSD_1d_ohlcv.csv", parse_dates=["Open time"])
d = pd.to_datetime(sol["Open time"]).dt.tz_localize(None).dt.normalize()
full = pd.date_range(d.min(), d.max(), freq="D")
missing = full.difference(d)
# → 418 missing: one 416-day block 2023-07-07..2024-08-25 + a 2-day gap 2023-06-24..2023-06-25
```

### Existing degenerate-metrics guards (ROBUST-03 covers these — do NOT rebuild)
```python
# Source: itrader/reporting/metrics.py:57-98
def sharpe(returns, periods=PERIODS):
    if len(returns) < 2: return 0.0          # no-trade / single-obs guard
    sd = returns.std(ddof=1)
    if sd == 0: return 0.0                    # flat guard
    return float(np.sqrt(periods) * returns.mean() / sd)

def profit_factor(trades):
    if trades.empty: return 0.0               # no-trade guard
    ...
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0.0 else 0.0   # all-win → inf (D-05: assert NOT inf for these leaves)
    return gross_profit / gross_loss
```
NOTE for D-05: `profit_factor` returns `inf` for an all-winning frame. The "flat" and "losing"
leaves must be authored so `profit_factor` is finite (flat → a round-trip with a real loss leg or
a defined PF; losing → net-negative). The explicit no-NaN/no-inf assert must account for this — for
the "no-trade" leaf PF is `0.0` (finite); design the "flat"/"losing" leaves to keep all six metrics
finite, or the assert must whitelist a deliberately-`inf` metric (cleaner to author finite leaves).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-portfolio capture in `_assemble` (`portfolios[0]`) | Iterate `portfolio_ids` for the per-portfolio snapshot | Phase 9 (D-01) | Enables MULTI-03 isolation assertion; harness-only. |
| Synthetic-fixture span proof (Phase 3) | REAL sliced ETH/SOL/AAVE E2E | Phase 9 (D-03) | Exercises the real ingestion path; Phase 3 explicitly deferred this. |
| Golden-vs-golden regression only | + dedicated in-process double-run | Phase 9 (D-04) | Catches within-run non-determinism a golden diff cannot. |

**Deprecated/outdated:** None relevant — the legacy `performance.py`/`statistics.py` metric paths
already died (replaced by the pure `reporting/metrics.py`); no Phase 9 interaction.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `PortfolioSpec.name` is unique per scenario (used as the per-portfolio golden key) | Pattern 2 / Pitfall 2 | If two portfolios share a `name`, the snapshot rows collide on the identity key → `_diff_frame` row-count or many-to-one ambiguity. MITIGATION: leaf authors must give distinct names; consider asserting uniqueness in the serializer. LOW risk — author-controlled. |
| A2 | The `csv_store` localizes sliced real-data CSVs to the Europe/Paris config timezone identically to the full datasets (so date-keyed scripts/asserts align) | ROBUST-01/02 | If a sliced CSV's tz handling differs, the absent-bar/listing date could shift by a day near a boundary. The emitter/operator already `tz_convert("UTC")` (WR-03) to neutralize this; LOW risk but the ROBUST leaves should hand-verify the exact bar dates post-slice. |
| A3 | Designing "flat"/"losing" ROBUST-03 leaves to keep `profit_factor` finite is preferable to whitelisting an `inf` in the no-NaN assert | Code Examples / D-05 | If a leaf legitimately needs an all-win shape, the assert must permit `inf`. Author's choice; CONTEXT.md D-05 says "flat" = round-trip ~zero PnL, "losing" = net-negative — both are naturally finite. LOW risk. |

**Note:** All factual claims about the codebase and datasets in this document are `[VERIFIED:
codebase grep/read]` or `[VERIFIED: pandas inspection of committed CSVs]` — read directly this
session. The three items above are forward-looking authoring assumptions for the planner, not
unverified facts.

## Open Questions

1. **Where to expose the harness build/assemble trio for the double-run test (D-04)?**
   - What we know: `_build_and_run`/`_assemble`/`_load_spec` are private `conftest.py` functions.
   - What's unclear: import-from-conftest vs promote-to-`_harness.py`.
   - Recommendation: import from `tests.e2e.conftest` (it is a real importable module); only promote
     to a shared `_harness.py` if the import proves awkward across the `robust/` subdir. Decide in
     the foundational plan (Plan 1).

2. **Double-run parametrization surface: Phase 9 leaves only, or all e2e leaves?**
   - What we know: D-04 says "parametrized over the Phase 9 e2e scenarios"; discretion allows wider.
   - What's unclear: ROBUST-04 literally requires "all NEW scenarios"; widening to ALL e2e would
     also re-prove determinism for Phases 6-8 (free coverage, slightly slower suite).
   - Recommendation: parametrize over Phase 9 leaves to satisfy ROBUST-04 exactly; optionally widen
     to all e2e if runtime is acceptable (the engine is fast on tiny fixtures). Cluster discretion.

3. **`flat` leaf metric design to keep all six metrics finite (D-05).**
   - What we know: `profit_factor` returns `inf` for all-win frames; `0.0` for empty/all-loss.
   - What's unclear: exact contrived bars for a "round-trip netting ~zero PnL" that yields finite PF.
   - Recommendation: author "flat" as a small loss + small win (or a single ~breakeven round-trip)
     so PF is finite; hand-verify before freeze. Covered by leaf authoring discretion.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | 3.13.1 | — |
| pytest | E2E leaves | ✓ | 8.4.2 | — |
| pandas | Harness diff / reporting | ✓ | 2.3.3 | — |
| numpy | Metrics | ✓ | 2.2.x | — |
| Committed real datasets | ROBUST-01/02 | ✓ | BTC/ETH/SOL/AAVE present | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None. No PostgreSQL/Docker/external services needed
(backtest, in-memory, committed CSVs only).

## Validation Architecture

> Nyquist validation is ENABLED (`config.json: nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/e2e/<cluster> -m e2e -x` |
| Full suite command | `make test` (full) / `make test-e2e` (e2e only) |

### Sampling-Adequacy Framing (test-coverage phase)
This phase's "behavior space" is the multi-entity × robustness × degenerate-metrics matrix. The
~8 hand-verified leaves are the SAMPLES; the double-run test (ROBUST-04) is the **sampling-adequacy
proof** that each sample is itself reproducible. Ground truth is established by hand-derived VERIFY
notes (per leaf, mirroring `smoke/single_market_buy/scenario.py`) BEFORE the `--freeze` lock — a
frozen golden proves *stability*, not *correctness*.

### Phase Requirements → Test Map
| Req ID | Behavior sampled | Test Type | Automated Command | Fixture Exists? |
|--------|-------------------|-----------|-------------------|-----------------|
| MULTI-01 | one strategy, two tickers | e2e leaf | `pytest tests/e2e/multi/two_tickers -m e2e` | ❌ Wave (new leaf) |
| MULTI-02 | two strategies, one portfolio | e2e leaf | `pytest tests/e2e/multi/two_strategies -m e2e` | ❌ Wave |
| MULTI-03 | one strategy → >1 portfolio, cash isolation | e2e leaf (per-portfolio snapshot) | `pytest tests/e2e/multi/fanout_portfolios -m e2e` | ❌ Foundational canary + serializer |
| MULTI-04 | two strategies contend for one portfolio's cash | e2e leaf (cash-ledger) | `pytest tests/e2e/multi/contended_cash -m e2e` | ❌ Wave |
| ROBUST-01 | SOL absent bar (2023-06-24/25) → no fill, no crash | e2e leaf (real sliced) | `pytest tests/e2e/robust/sparse_bar -m e2e` | ❌ Wave |
| ROBUST-02 | AAVE mid-run listing + differing ends, union window | e2e leaf (real sliced) | `pytest tests/e2e/robust/union_window -m e2e` | ❌ Wave |
| ROBUST-03 | no-trade / flat / losing → finite metrics | 3 e2e leaves + no-NaN assert | `pytest tests/e2e/robust/{no_trade,flat,losing} -m e2e` | ❌ Wave + no-NaN guard (foundational) |
| ROBUST-04 | double-run byte-identical across all new scenarios | parametrized determinism test | `pytest tests/e2e/robust/test_determinism.py -m e2e` | ❌ Foundational (double-run scaffold) |

### Sampling Rate
- **Per task / leaf:** the leaf's own `pytest tests/e2e/<leaf> -m e2e` (fast, tiny fixture).
- **Per wave merge:** `make test-e2e` (full e2e tree) + the determinism test.
- **Phase gate:** `make test` full suite green (incl. BTCUSD oracle byte-exact) before `/gsd:verify-work`.

### Wave 0 Gaps (foundational plan — D-06)
- [ ] `tests/e2e/conftest.py` — per-portfolio snapshot serializer + `exists()`-gated opt-in wiring in `_assemble`/`_freeze`/`_diff` (D-01).
- [ ] `tests/e2e/robust/test_determinism.py` (+ exposing `_build_and_run`/`_assemble`) — double-run scaffold (D-04).
- [ ] No-NaN/no-inf guard helper for ROBUST-03 leaves (D-05).
- [ ] ONE canary leaf (MULTI-03 fanout candidate) proving the wiring end-to-end.
- [ ] BTCUSD oracle re-run byte-exact (`make test-integration`) after the serializer lands.

### Undersampled Edges the ~8 leaves might miss (flag for the planner)
- **MULTI-03 isolation is asserted by roll-up, not trade-level.** Two portfolios with *identical*
  cash/trades would still pass if the engine accidentally shared state but produced symmetric
  numbers. MITIGATION: author the two fanout portfolios with **asymmetric starting cash** (e.g.
  10_000 vs 5_000) so A's numbers are provably ≠ B's — independence is then observable in the
  snapshot, not just plausible.
- **MULTI-04 is one bar / one contention.** It does not sample the loser *recovering* on a later
  bar (cash freed → second strategy admits next bar). That is arguably out-of-shape for one leaf;
  note as a possible fold only if a contrast is the point (Claude's discretion in D-01).
- **ROBUST-02 union window** can sample mid-run-listing OR differing-end-dates but one leaf cleanly
  shows one edge. CONTEXT.md treats them as one requirement; consider whether one slice can show
  BOTH (a window spanning AAVE's 2021-07-15 listing AND running past one asset's end) or whether
  two folds are clearer. Author's discretion — one-shape-per-leaf favors NOT cramming both.
- **ROBUST-01 absent-bar at the strategy-decision tick vs the matching tick:** the SOL 2-day gap
  should be positioned so a signal/position is live across the gap (proving no fill AND no crash on
  the matching path), not merely a gap during warmup where nothing is at stake.

## Security Domain

`security_enforcement` is absent in `config.json` (treated as enabled), but this phase has **no
production-facing security surface**: it adds test scaffolding + fixtures to an offline backtest
engine. No authn/authz, no network input, no untrusted data ingestion (the sliced CSVs are
hand-committed by the author). The one relevant cross-cutting invariant is **determinism /
non-tampering of the event dispatch** (ROBUST-04 proves runs are reproducible; the engine's
`_dispatch` raises on unrouted events to prevent silent drops). No ASVS category applies to a
test-only, offline phase. STRIDE: the only relevant category is *Tampering* (a non-deterministic
or silently-mutated golden), which ROBUST-04 + the no-tolerance exact diff + the single-leaf
`--freeze` guard already mitigate.

## Sources

### Primary (HIGH confidence — read this session)
- `tests/e2e/conftest.py` (full) — `run_scenario` harness; `_build_and_run:252-327`, `_assemble:330-401`, `_freeze:470-519`, `_diff:541-583`, `_diff_summary:441-467`, opt-in gates, `--freeze` single-leaf guard `:601-613`.
- `tests/e2e/scenario_spec.py` (full) — `ScenarioSpec`/`PortfolioSpec`/`Action` consuming contract.
- `tests/e2e/strategies/scripted_emitter.py` (full) — multi-instance/multi-ticker emitter.
- `tests/e2e/admission/max_positions/scenario.py` (full) — multi-CSV / two-co-subscribed-emitter precedent.
- `tests/e2e/smoke/single_market_buy/scenario.py` (full) — VERIFY-note copy-template.
- `tests/e2e/cash/release_rejected/test_scenario.py` — one-line leaf test body.
- `itrader/reporting/metrics.py`, `summary.py`, `frames.py`, `cash_operations.py` (full) — metric guards, `build_metrics_block`, `TRADE_COLUMNS`, opt-in serializer pattern.
- `itrader/portfolio_handler/portfolio_handler.py:60-228` — `add_portfolio`/`get_portfolio`/`get_active_portfolios`/`get_portfolio_count`; `PortfolioId` UUIDv7.
- `itrader/order_handler/order_manager.py:375-424` — synchronous BUY-only check-and-reserve gate.
- `itrader/strategy_handler/strategies_handler.py:46-95,232` — registration-order list + sparse-ticker `None`-skip guard (WR-12).
- `itrader/trading_system/backtest_trading_system.py:48-246` — `csv_paths` passthrough + `on_tick` hook.
- `data/{BTCUSD,ETHUSD,SOLUSD,AAVEUSD}*.csv` — span/row-count/gap inspection via pandas (verified all D-03 claims + the SOL gap shape).
- `.planning/config.json` — `nyquist_validation: true`; no Brave/Exa/Firecrawl; `security_enforcement` absent.
- `pyproject.toml` / `Makefile` — `e2e` marker, `filterwarnings=["error"]`, `make test-e2e`.

### Secondary (MEDIUM confidence)
- `.planning/phases/0{3,4,6,7,8}-*/0?-CONTEXT.md` (referenced via CONTEXT.md canonical_refs) — pattern lineage; not re-read in full this session (CONTEXT.md summarizes them and was scout-confirmed).

### Tertiary (LOW confidence)
- None — no web sources needed; this is a closed-codebase coverage phase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; existing toolchain read directly.
- Architecture (harness extension points): HIGH — `conftest.py` read in full; extension points are exact line ranges.
- Real-data spans/gaps (D-03): HIGH — verified by pandas inspection of the committed CSVs (including the non-obvious SOL gap shape).
- Pitfalls: HIGH — derived from read code + verified data, not training data.
- Validation architecture: HIGH — framework and commands confirmed against `pyproject.toml`/`Makefile`.

**Research date:** 2026-06-10
**Valid until:** 2026-07-10 (stable — closed codebase, no fast-moving external dependencies). Re-verify only if the harness `conftest.py` or the committed datasets change.
