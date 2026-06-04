# Refactor Brief — iTrader Backtest-Correctness Program

> **Purpose of this file:** the goal/scope context to feed `/gsd:new-project` so it doesn't
> re-interrogate decisions already made. This is **input** to GSD's questioning/`PROJECT.md` step —
> *not* a roadmap. GSD generates `ROADMAP.md` / `REQUIREMENTS.md` / `STATE.md` itself (via
> `gsd-roadmapper`) from the analysis docs + this brief.
>
> **Read alongside:** `.planning/codebase/ARCHITECTURE-REVIEW.md` (40 design findings),
> `.planning/codebase/CONCERNS.md` (65 concrete defects), `.planning/COVERAGE-INDEX.md`
> (every finding + defect → milestone, the 100%-coverage checklist).

---

## 1. Goal (one sentence)

Make iTrader **run correctly in backtest mode** end-to-end on a single reference strategy
(`SMA_MACD`) over a fixed golden dataset, **refactoring every structural issue** surfaced in the
review, and leave behind an engine whose results are **trustworthy and regression-locked**.

**Definition of done (program-level):**
- `SMA_MACD_strategy` runs end-to-end on `data/BTCUSD_1d_ohlcv_2018_2026.csv` and produces
  a non-trivial trade log + equity curve.
- `mypy --strict` clean; **no `float` money** (Decimal end-to-end); a **single UUIDv7 ID scheme**.
- Runs are **deterministic** (seeded RNG + injected clock).
- The 274 existing component tests stay green (migrated to pytest) **plus** a run-path integration
  test exists.
- Reported metrics are **cross-validated** against `backtesting.py` and `backtrader` on the same
  strategy + data; the final numerical reference output is frozen.

---

## 2. Scope

### In scope — structural refactor for backtest correctness
Everything required to make the backtest path import, run, be deterministic, be correctly typed,
compute money/IDs correctly, and produce trustworthy results & metrics. See `COVERAGE-INDEX.md` for
the exhaustive item list grouped by milestone M1–M5.

### Out of scope — deferred to later milestones (explicit, recorded)
These are **intentionally not** part of this program. They have their own milestone later:

| Deferred area | Why deferred | Tag |
|---|---|---|
| **Screener wiring** (rebalance loop: screener→universe→strategy) | A feature, not a correctness blocker; backtest runs a fixed ticker set | `D-screener` |
| **SQL persistence backends** (order storage, price store, reporting-to-SQL, config JSONB) | Backtest uses in-memory + the golden CSV; SQL is a live/persistence concern | `D-sql` |
| **Live mode** (Binance streaming, WebSocket reconnection, restart sync, venue reconciliation, `TradingInterface`/API order path, live threading lifecycle) | Whole separate risk surface; backtest-first | `D-live` |
| **Compliance layer** (`long_only`/`short_only` centralization) | Tied to strategy relocation + a future order-handler feature | `D-compliance` |
| **OANDA + Binance adapters** | Not on the CSV-backed backtest path | `D-oanda` / `D-live` |
| **Secrets hardening** (env-only credentials, no defaults) | Matters when live/SQL come online | `D-live` |

### Handled out-of-band (not a GSD work item)
- **`itrader/strategy_handler/my_strategies/*`** — contains IP; **the user will move it to a separate
  repo before the refactor starts.** It is gitignored and untracked today. Tagged `OUT` in the
  coverage index. The findings/defects that only touch `my_strategies/*` are therefore resolved by
  removal, not refactor.

---

## 3. Locked decisions (do not re-litigate during execution)

| Decision | Choice | Affects findings |
|---|---|---|
| Money representation | **Decimal end-to-end** | #17, #22, #23, #28, #39 |
| ID strategy | **UUIDv7 via the Rust-backed package** (`uuid-utils`) | #10, #11, #18, #19 |
| Correctness priority | **Backtest-correctness-first** (live later) | program-wide |
| Event bus | **Keep in-house** dispatch registry (no library) | #1, #2 |
| Config | **Collapse `config/` to Pydantic models** + `pydantic-settings` | #12, #13, #34 |
| Position sizing | **Strategy declares sizing *policy* + SL/TP; order/risk layer resolves the per-portfolio quantity** | #24, #31 |
| Universe | **Collapse to a thin symbol-set derivation, keep as a documented stub** | #33 |
| Screener | **Wire in a later milestone**; until then no silent dead output | #32 |

---

## 4. Golden-master discipline (the spine of the program)

| Term | Artifact |
|---|---|
| **Golden dataset** | `data/BTCUSD_1d_ohlcv_2018_2026.csv` (frozen input) |
| **Golden strategy** | `itrader/strategy_handler/SMA_MACD_strategy.py` (fixed params, frozen) |
| **Reference output** | Snapshot of a full backtest run: trade log (entry/exit time + side), equity curve, final cash/metrics |
| **Characterization tests** | The existing 274 component tests (portfolio/position/transaction/order/exec) — the *unit-level* oracle; migrate to pytest, keep |

**Two-layer oracle rule:**
- **Behavioral oracle** (which trades fire, and when) — computed from SMA/MACD over OHLC via the `ta`
  library, in float, price-driven → **invariant to the Decimal/UUID foundations**. Must stay
  unchanged through M2–M4. If a "pure refactor" changes trade timing, that's a regression.
- **Numerical oracle** (exact cash/equity/qty/metrics) — **re-baselines at exactly two declared
  points:** after **M2** (float→Decimal precision shift) and after **M5** (look-ahead/fill-realism
  fixes legitimately change results). Every other milestone must reproduce it.

**Milestone behavior contract:** M2–M4 are **behavior-preserving** (the behavioral oracle is law).
**M5 is the one milestone allowed to change results** — there, the oracle becomes **external
cross-validation** against `backtesting.py` + `backtrader` rather than the old snapshot.

**Catch-22 note:** the reference output **cannot be captured until M1 makes the engine run** (#34).
So M1's second deliverable (right after the smoke test) is **capture + commit the reference output**.
Until then every later phase is flying blind.

---

## 5. Milestone plan (proposed — GSD's roadmapper produces the authoritative phase structure)

| M | Name | Goal | Exit criteria |
|---|------|------|---------------|
| **M1** | **Ignition + lock the oracle** | `SMA_MACD` runs on the golden CSV and produces real trades; capture the reference output; stand up the test skeleton | `make backtest` runs → non-trivial trade log; smoke + integration tests green; **reference output committed**; 274 char tests still green |
| **M2** | **Foundations** | UUIDv7, Decimal, mypy-strict + frozen DTOs, real ABCs, determinism, config→Pydantic, type placement, time_parser final | `mypy --strict` clean; one ID scheme; no float money; deterministic; **behavioral oracle unchanged, numerical oracle re-frozen** |
| **M3** | **Event & dispatch core** | Immutable events w/ linkage IDs, race-free dispatch, unified errors/logging | events frozen w/ `event_id`; dispatch race-free; behavioral oracle unchanged |
| **M4** | **Money & transaction correctness** | Cash through `CashManager` (Critical), atomic transactions, decoupling, order facade, exec DTOs | cash ledger correct; transactions atomic; **value-preserving** (any numeric diff explained); oracle holds |
| **M5** | **Backtest validity, fills, metrics, strategy/data** | Make the numbers trustworthy, then calibrate | engine **cross-validated vs backtesting.py + backtrader**; metrics correct; **final numerical oracle frozen** |

**Span findings** (started in M1, completed later — tracked explicitly in `COVERAGE-INDEX.md`):
#34 (M1→M2), #35 (M1 backtest-part; live-part deferred), #36 (M1→M2), #24/#31 (M1 minimal sizing →
M5 full policy). M1's minimal sizing is implemented **in the architecturally-correct seam** (order/risk
layer) so M5 *extends* rather than *replaces* it.

---

## 6. Standing constraints (from `CLAUDE.md`)

- **Event-driven only:** components communicate via the shared `global_queue`; never call across
  domains directly — emit an event.
- **Indentation:** source uses **tabs** in handler modules (config/ and newer modules use spaces) —
  match the file being edited.
- **Test strictness:** `pyproject.toml` sets `filterwarnings = ["error", ...]`, `--strict-markers`,
  `--strict-config`. Any unexpected warning fails the suite; every marker must be declared.
- **Import side effects:** `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons
  on import.

---

## 7. How this feeds GSD

1. Run `/gsd:new-project`, `@`-referencing `ARCHITECTURE-REVIEW.md`, `CONCERNS.md`, this brief, and
   `COVERAGE-INDEX.md` as the idea/required-reading.
2. GSD's questioning step reads §1–§6 here instead of re-asking.
3. `gsd-roadmapper` derives phases (likely ≈ M1–M5) and **validates 100% requirement coverage** — use
   `COVERAGE-INDEX.md` as the requirement source so no finding/defect is orphaned.
4. `STATE.md` becomes the **living fixed-vs-not ledger** as phases execute.
