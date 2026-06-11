# Phase 4: E2E Harness & Framework - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the whole-system **E2E testing apparatus** that every scenario wave
(Phases 6-9) builds on: a dedicated `tests/e2e/` tree, a registered `e2e`
marker with folder-derived auto-marking, a `make test-e2e` target, and a
shared golden-compare harness (`tests/e2e/conftest.py`) that runs the full
engine on a `(strategy, data)` pair and diffs trades/equity/summary against a
scenario's frozen golden fixtures. Ship **one** contrived canary scenario that
exercises the full path and serves as the copy-template.

**In scope:**
- `tests/e2e/` tree, subsystem-grouped (E2E-01).
- `e2e` marker registered in `pyproject.toml` + folder-derived auto-marking
  (extend the existing `tests/conftest.py` hook), `make test-e2e` (E2E-01).
- Shared `run_scenario` harness in `tests/e2e/conftest.py` (E2E-02).
- A shared `tests/e2e/strategies/` library + a shared `tests/e2e/data/` folder.
- Extract the summary/metrics/slippage assembly out of `scripts/run_backtest.py`
  into shared `itrader.reporting` (CLAR-02 cleanup along a touched path).
- A `--freeze` regen mechanism + a per-scenario hand-derivation VERIFY note
  (E2E-04 discipline).
- Exactly ONE contrived, hand-verifiable canary scenario (E2E-03 dogfood +
  template).
- FL-03 opportunistic cleanup (delete the stale `pytest.skip` in
  `tests/unit/core/test_enums.py:32`).

**Out of scope (own phases):**
- The actual scenario coverage (matching, cost/sizing/sltp, admission,
  multi-entity) — **Phases 6-9**. Phase 4 ships the framework + one canary only.
- Relocating `SMA_MACD_strategy.py` out of `itrader/` — **deferred to Phase 5**
  (it is the committed oracle strategy; Phase 5 re-proves the oracle byte-exact
  and owns the strategy).
- Re-baselining the BTCUSD golden oracle (v1.1 is behavior-preserving — every
  Phase-4 change, incl. the reporting extraction, must be **oracle-dark** on the
  golden run, guarded by `test_backtest_oracle.py`).

</domain>

<decisions>
## Implementation Decisions

### Scenario Contract Shape
- **D-01:** **Per-folder one-line test → shared fixture.** Each leaf folder has
  its own tiny `test_*.py` (`def test_x(run_scenario): run_scenario(HERE)`); the
  shared `run_scenario` fixture in `tests/e2e/conftest.py` builds the
  `TradingSystem`, runs it, and diffs goldens. Chosen over an auto-discovery
  parametrized collector and over a declarative manifest because it is the
  direct descendant of the existing `backtest_engine` factory fixture (pytest
  continuity, no "magic"), it satisfies E2E-03's "self-contained leaf folder"
  literally, and it is **parallel-safe for the Phase 6-9 waves** — adding a
  scenario edits ONLY its own folder, never a shared collector/registry (the
  roadmap flags parallel scenario plans must not edit shared files).

### Scenario Spec (engine knobs)
- **D-02:** **Per-folder `scenario.py` typed spec.** Each leaf exports a
  `ScenarioSpec` dataclass; `run_scenario(HERE)` imports it, wires + runs the
  engine, diffs goldens. Knobs are explicit, IDE-navigable, type-checkable —
  mirrors how `run_backtest.py` wires the system today.
- **D-03:** **`ScenarioSpec` reuses the REAL engine config models.** Its fields
  are the production types: `list[strategy]`, `list[PortfolioConfig]`,
  `ExchangeConfig` (fee/slippage model + params), data path(s), window. No
  parallel/reinvented config schema. Lists handle Phase 9 multi-strategy /
  multi-portfolio composition.
- **D-04:** **Shared `tests/e2e/strategies/` library.** Reusable purpose-built
  test strategies live here; `scenario.py` references one + supplies params
  rather than defining strategies inline (avoids 30× duplication). Mild
  reinterpretation of E2E-03 ("purpose-built strategy" may be shared, not
  folder-local). NOTE: most Phase 6-9 fill scenarios will need NEW tiny
  deterministic strategies (controllable signal emission) — SMA_MACD's 50/100
  crossover is not controllable enough.

### Golden Fixtures & Diff
- **D-05:** **Diff-what's-frozen.** `run_scenario` produces all artifacts in
  memory and diffs ONLY the golden files present in the leaf's `golden/`
  subfolder (presence = assertion; one diff loop, zero per-scenario config).
- **D-06:** **Default freeze = `trades.csv` + `summary.json`; `equity.csv`
  opt-in.** `summary.json` already carries `final_equity` + the full metrics
  block (sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate), so
  degenerate-metrics scenarios (Phase 9) are covered without the raw curve.
  Freeze `equity.csv` only when the per-bar curve SHAPE is the assertion.
- **D-07:** **Fresh results stay in memory; no `output/` folder in the leaf.**
  Diff directly against loaded `golden/` files. Use pytest `tmp_path`
  (ephemeral, parallel-safe) only if disk artifacts are ever needed for
  debugging — never write into the committed folder. Avoids dirty-tree / write
  contention in Phase 6 parallel worktree runs.
- **D-08:** **Exact diff, no float tolerance.** Reuse the existing
  `assert_frame_equal` identity-vs-numeric column mechanic from
  `test_backtest_oracle.py` and the existing reporting builders.

### Input Data
- **D-09:** **Committed CSVs through the real `CsvPriceStore`** (Phase 3
  `csv_paths` passthrough — no mock, real store→feed path). `scenario.py`'s
  `data` field takes a path.
- **D-10:** **Contrived leaf-local + shared `tests/e2e/data/`.** Scenario-
  specific CONTRIVED tiny CSVs live in the leaf (self-contained); reusable
  inputs (a BTCUSD slice for the canary/smoke; refs to the real ETH/SOL/AAVE
  datasets for the Phase 9 spans scenario) live in shared `tests/e2e/data/`.
- **D-11:** **Fill scenarios use CONTRIVED bars, NOT slices of real data.** A
  slice of real BTCUSD cannot produce limit-touch / gap-through / same-bar
  OCO-priority / never-fill shapes on demand — that works against the
  hand-verify-once discipline. Slices are appropriate only for smoke/canary.

### Phase-4 Scope & Canary
- **D-12:** **Ship exactly ONE contrived, hand-verifiable canary scenario**
  (e.g. a deterministic single MARKET buy → one known trade). It exercises the
  full harness path end-to-end and doubles as the copy-template for Phase 6-9
  authors. It proves the new scaffolding is wired right (the engine itself is
  already proven by `test_backtest_oracle.py`); it is NOT the BTCUSD slice
  (whose trades aren't hand-derivable).

### Freeze / Hand-Verify Discipline (E2E-04)
- **D-13:** **Deliberate `--freeze` regen flag + per-scenario VERIFY note.**
  Normal runs are DIFF-ONLY and fail on drift (goldens never auto-heal);
  `--freeze` (pytest option / env var) WRITES the goldens. Each scenario commits
  a short hand-derivation note (a `VERIFY.md` or a `scenario.py` docstring)
  stating expected fills/PnL and WHY — the committed human-verification artifact
  a reviewer checks. Mirrors the existing `tests/golden/REFREEZE-*.md` /
  `FINAL-ORACLE.md` pattern.

### Tree Grouping & Marker/Target Wiring
- **D-14:** **Group by engine subsystem** (stable domain names, not phase
  numbers): top-level dirs like `tests/e2e/matching/`, `cost/`, `sizing/`,
  `sltp/`, `admission/`, `position/`, `cash/`, `multi/`, `robustness/`,
  `metrics/`; scenarios are self-contained leaf folders within. Maps 1:1 to the
  Phase 6-9 requirement clusters and parallel waves. (Exact dir names/depth left
  to planning, subject to subsystem-grouped + stable names.)
- **D-15:** **`e2e` marker, NOT `slow`, included in default `make test`.**
  Extend the `tests/conftest.py` folder-derived auto-marking hook so
  `tests/e2e/` → `e2e`; register `e2e` in `pyproject.toml`. Scenarios are tiny
  (~10 bars) so they are NOT `slow` and stay in the default suite (regression
  safety); add `make test-e2e` (`-m e2e`) as the focused bucket per the locked
  "run-as-a-bucket" decision.

### Shared Serialization Seam
- **D-16:** **Extract summary/metrics/slippage assembly into shared
  `itrader.reporting`.** `build_summary` / `build_metrics_block` /
  `attach_slippage` currently live as locals inside `scripts/run_backtest.py`;
  move them into shared `itrader.reporting` (alongside `frames.py` / `metrics.py`),
  parameterizing the pinned constants (TICKER / window / cash). Both the oracle
  generator AND the harness then import ONE assembly path so e2e goldens match
  the oracle format exactly and cannot drift. Must stay **oracle-dark** — the
  existing `test_backtest_oracle.py` byte-exact gate guards the refactor.
  (`build_trade_log` / `build_equity_curve` are already shared in
  `itrader.reporting.frames`.) CLAR-02 cleanup along a Phase-4-touched path.

### Claude's Discretion
- Exact `tests/e2e/` directory names/depth (subject to D-14 subsystem-grouping).
- Exact `ScenarioSpec` field set/shape and the `run_scenario` signature (subject
  to D-02/D-03 — reuse real config, type-safe, multi-entity capable).
- Whether the VERIFY artifact is a `VERIFY.md` file or a `scenario.py` docstring
  (subject to D-13 — must be a committed, reviewable hand-derivation).
- How contrived CSVs are authored (hand-written vs a small committed emit-helper
  from a compact spec), subject to D-09/D-11 (committed CSVs, real store path,
  contrived bars).
- The precise `--freeze` mechanism (pytest `--freeze` option vs env var).
- The canary's exact strategy/data shape (subject to D-12 — contrived, one known
  trade, hand-verifiable, reusable as template).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The harness analog (closest existing pattern — generalize this)
- `tests/integration/conftest.py` — the `backtest_engine` factory fixture
  (deferred construction) + `golden_*` path fixtures. `run_scenario` is the
  descendant of this pattern.
- `tests/integration/test_backtest_oracle.py` — the exact-diff mechanic to
  reuse: in-process full run, pandas `assert_frame_equal` with
  `check_exact=True`, identity-column vs numeric-column split, no float
  tolerance, trades/equity/summary triplet. Also the `_load_run_backtest_module`
  in-process invocation pattern.
- `scripts/run_backtest.py` — the oracle generator: `TradingSystem` wiring
  (`exchange="csv"`, add_strategy, add_portfolio, subscribe_portfolio, run),
  the result-read-after-run (queue-only) pattern, and the assembly functions to
  EXTRACT (D-16): `build_summary`, `build_metrics_block`, `attach_slippage`,
  plus `FLOAT_FORMAT`, `TRADE_COLUMNS`, `SLIPPAGE_COLUMNS`.

### Reporting builders (already shared — reuse directly)
- `itrader/reporting/frames.py` — `build_trade_log`, `build_equity_curve`,
  `TRADE_COLUMNS`, `EQUITY_COLUMNS` (importable today).
- `itrader/reporting/metrics.py` — `sharpe`, `sortino`, `cagr`, `max_drawdown`,
  `profit_factor`, `win_rate`, `compute_returns` (the metrics-block formula
  source). The extracted summary assembly (D-16) lands beside these.

### Marker / config wiring
- `tests/conftest.py` — `pytest_collection_modifyitems` folder-derived TYPE
  auto-marking hook (`unit` / `integration` + `slow`); EXTEND for `tests/e2e/`
  → `e2e` (D-15). Also holds the shared `make_bar` / `make_bar_struct` fixtures.
- `pyproject.toml` `[tool.pytest.ini_options]` — `markers` (the single
  registration home — add `e2e`), `filterwarnings = ["error", ...]` (scenarios
  must run warning-clean), `--strict-markers` / `--strict-config`.
- `Makefile` — existing `test` / `test-unit` / `test-integration` targets; add
  `test-e2e` (`-m e2e`). `make test` keeps running everything.

### Engine construction + data path
- `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.__init__`
  (incl. the Phase-3 oracle-dark `csv_paths` passthrough, default `None`) and
  `run()`; `_initialise_backtest_session` (membership derivation + union ping
  grid for heterogeneous spans).
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore` (`csv_paths` =
  the data-subscription seam scenarios use to load contrived CSVs).
- `itrader/config/` — `ExchangeConfig`, `PortfolioConfig`, `SystemConfig` (the
  real config models `ScenarioSpec` reuses, D-03; fee/slippage model selection).
- `itrader/execution_handler/fee_model/`, `slippage_model/` — the pluggable
  models scenarios vary (Phase 7 substrate).

### Deferred-from-Phase-3 forward pointer
- `.planning/phases/03-minimal-real-universe/03-CONTEXT.md` — the real
  ETH/SOL/AAVE differing-spans E2E run was deferred to Phase 9/ROBUST and runs
  THROUGH this harness; the synthetic-fixture approach there informs the
  contrived-CSV design here.

### Phase / requirements / decisions / cleanup
- `.planning/ROADMAP.md` §"Phase 4: E2E Harness & Framework" — goal + 4 success
  criteria; §"Phase 6" REMINDER (parallel-wave preconditions — shared infra
  committed FIRST, parallel plans must not edit shared files).
- `.planning/REQUIREMENTS.md` — **E2E-01** (tree/marker/auto-marking/make
  target), **E2E-02** (shared conftest harness diffs trades/equity/summary),
  **E2E-03** (self-contained leaf folder, warning-clean), **E2E-04**
  (hand-verify-once before freeze).
- `.planning/PROJECT.md` Key Decisions (lines ~161-162) — dedicated `tests/e2e/`
  + `e2e` marker; hand-verify-once-then-regression-lock; behavior-preserving
  (BTCUSD oracle not re-baselined).
- `.planning/codebase/FIX-LIST.md` — **FL-03** (stale
  `pytest.skip("pending M2-07: FillStatus...")` at
  `tests/unit/core/test_enums.py:32` masks a now-passing test — Phase-4-eligible
  cleanup); **FL-04** is Phase 5 (not here).
- `.planning/codebase/CLEANUP-STANDARD.md` — the 4-gate opportunistic-cleanup
  checklist FL-03 + the D-16 extraction execute under.
- `tests/golden/REFREEZE-*.md` + `tests/golden/FINAL-ORACLE.md` — the existing
  human-verification artifact pattern D-13's per-scenario VERIFY note mirrors.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backtest_engine` factory fixture** (`tests/integration/conftest.py`) — the
  deferred-construction pattern `run_scenario` extends; currently only takes
  exchange/dates, so the harness generalizes it to the full `ScenarioSpec`.
- **`test_backtest_oracle.py` diff machinery** — in-process run + exact
  `assert_frame_equal` identity/numeric split; the e2e harness reuses this exact
  comparison approach per scenario.
- **`itrader.reporting.frames` / `.metrics`** — already-shared builders; the
  summary/metrics/slippage assembly (D-16) joins them so oracle + harness share
  one serialization path.
- **`CsvPriceStore` + `csv_paths` passthrough** (Phase 3, oracle-dark) — lets a
  scenario pin its own contrived tiny CSV through the real store path.
- **Folder-derived auto-marking hook** (`tests/conftest.py`) — extend, don't
  reinvent, for the `e2e` marker.

### Established Patterns
- **Folder = marker** (D-13/D-15 existing): test TYPE is derived from its folder,
  not hand-added; `tests/e2e/` → `e2e` follows the same rule.
- **Self-contained + parallel-safe leaf folders**: each scenario is independent
  (own folder, own test, own golden/) so Phase 6-9 waves run in parallel
  worktrees without shared-file merge conflicts.
- **Exact, no-tolerance golden diff** (D-12/D-16 oracle discipline): a real
  behavior change fails immediately; tolerance would mask regressions.
- **Behavior-preserving / oracle-dark**: the D-16 reporting extraction must keep
  the BTCUSD golden run byte-identical (guarded by `test_backtest_oracle.py`).
- **Queue-only reads after run**: the harness reads `portfolio` state AFTER
  `system.run()` (like `run_backtest.py`), never calls handlers mid-run.

### Integration Points
- `run_scenario` (new, `tests/e2e/conftest.py`) → builds `TradingSystem` from
  `ScenarioSpec` → runs → reads portfolio → shared reporting assembly → diffs
  `golden/`.
- Extracted reporting assembly (new, `itrader.reporting`) ← imported by BOTH
  `scripts/run_backtest.py` and `tests/e2e/conftest.py`.
- `e2e` marker ← `tests/conftest.py` hook + `pyproject.toml` registration;
  `make test-e2e` ← `Makefile`.

</code_context>

<specifics>
## Specific Ideas

- **Pytest continuity drove the contract shape.** The user explicitly wanted to
  stay simple and build on the existing pytest system — D-01 (per-folder test +
  shared fixture) is the direct descendant of the existing `backtest_engine`
  factory, not a custom collector or manifest DSL.
- **CSV-file inputs over in-code bars.** The user preferred committed CSV files
  for scenario data (D-09); the correctness nuance (D-11) is that fill scenarios
  must use CONTRIVED bars, not slices of real BTCUSD, to stay hand-computable.
- **SMA_MACD is the oracle, not a throwaway.** The user's instinct that it's
  test/reference-oriented is right, but it is wired into `scripts/run_backtest.py`
  + 5 tests + Phase 5's byte-exact contract — so its relocation is deferred to
  Phase 5 (its natural home), not done in Phase 4.

</specifics>

<deferred>
## Deferred Ideas

- **Relocate `SMA_MACD_strategy.py` out of `itrader/strategy_handler/`** → decide
  in **Phase 5** (which hardens the strategy base class and re-proves the oracle
  byte-exact). It is test/reference-oriented, but it is the committed oracle
  strategy imported by `scripts/run_backtest.py` and 5 tests; the destination
  needs care since `run_backtest.py` would otherwise import from `tests/`
  (inverted dependency — a `reference/` strategy area may fit better than
  `tests/e2e/strategies/`).
- **The actual E2E scenario coverage** (matching, cost/sizing/sltp, admission/
  position/cash, multi-entity/robustness/metrics) → **Phases 6-9**, built on this
  harness.
- **The real ETH/SOL/AAVE differing-spans E2E run** → **Phase 9** (ROBUST), run
  through this harness using the full committed datasets (carried forward from
  Phase 3's deferral).

</deferred>

---

*Phase: 4-E2E Harness & Framework*
*Context gathered: 2026-06-09*
