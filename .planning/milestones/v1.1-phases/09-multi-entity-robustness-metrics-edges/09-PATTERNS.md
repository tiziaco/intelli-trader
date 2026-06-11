# Phase 9: Multi-Entity, Robustness & Metrics Edges - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 13 (1 harness edit + 1 determinism test + 8 leaf scenarios + 8 one-line leaf tests + golden placeholders; counted as logical units)
**Analogs found:** 13 / 13 (every new file has an exact in-repo precedent)

> COVERAGE phase. No production source changes. The only non-test edit is `tests/e2e/conftest.py`
> (per-portfolio snapshot serializer + opt-in wiring). Everything else is new test scaffolding +
> hand-verified leaf fixtures cloned from existing leaves. Indentation in ALL these files is **4
> spaces** (matches `tests/conftest.py` / the e2e package house style) — handler-module tabs do NOT
> apply here.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/e2e/conftest.py` (MODIFY) | harness serializer + opt-in gate | transform / file-I/O | `cash_operations.csv` opt-in path already IN this file (`_assemble:344`, `_freeze:516-519`, `_diff:573-577`) + `reporting/cash_operations.py` | exact (same-file precedent) |
| `tests/e2e/robust/test_determinism.py` (NEW) | determinism test | request-response / batch | `tests/e2e/cash/release_rejected/test_scenario.py` (one-line body) + `conftest._build_and_run`/`_assemble` | role-match |
| `tests/e2e/multi/two_tickers/scenario.py` (MULTI-01) | e2e leaf (contrived) | event-driven (fills) | `tests/e2e/admission/max_positions/scenario.py` (multi-CSV) + `smoke/single_market_buy` | exact |
| `tests/e2e/multi/two_strategies/scenario.py` (MULTI-02) | e2e leaf (contrived) | event-driven | `tests/e2e/admission/max_positions/scenario.py` (two co-subscribed emitters) | exact |
| `tests/e2e/multi/fanout_portfolios/scenario.py` (MULTI-03, canary) | e2e leaf (per-portfolio snapshot) | CRUD / transform | `smoke/single_market_buy/scenario.py` + NEW `portfolios.csv` opt-in | role-match |
| `tests/e2e/multi/contended_cash/scenario.py` (MULTI-04) | e2e leaf (cash-ledger) | event-driven (REJECTED audit) | `tests/e2e/sizing/over_cash_reject/scenario.py` + `tests/e2e/cash/release_rejected` | exact |
| `tests/e2e/robust/sparse_bar/scenario.py` (ROBUST-01) | e2e leaf (real sliced data) | event-driven (no-fill) | `tests/integration/test_universe_spans.py` (sparse-dict guard) + any leaf | role-match |
| `tests/e2e/robust/union_window/scenario.py` (ROBUST-02) | e2e leaf (real sliced data) | event-driven (union window) | `tests/integration/test_universe_spans.py` (mid-run listing + differing ends) | role-match |
| `tests/e2e/robust/no_trade/scenario.py` (ROBUST-03a) | e2e leaf (metrics block) | transform (degenerate metrics) | `tests/e2e/sizing/over_cash_reject` (zero closed trades) + `smoke` | role-match |
| `tests/e2e/robust/flat/scenario.py` (ROBUST-03b) | e2e leaf (metrics block) | transform | `smoke/single_market_buy/scenario.py` (round-trip) | role-match |
| `tests/e2e/robust/losing/scenario.py` (ROBUST-03c) | e2e leaf (metrics block) | transform | `smoke/single_market_buy/scenario.py` (round-trip, inverted PnL) | role-match |
| `tests/e2e/{multi,robust}/*/test_scenario.py` (NEW, ~8) | one-line leaf test | request-response | `tests/e2e/cash/release_rejected/test_scenario.py` | exact |
| `tests/e2e/{multi,robust}/*/golden/*` (NEW placeholders) | golden fixtures | file-I/O | existing `golden/` dirs (`cash_operations.csv` empty placeholder, `orders.csv`, `summary.json`) | exact |

## Pattern Assignments

### `tests/e2e/conftest.py` — per-portfolio summary snapshot (D-01, MULTI-03)

**Analog:** the `cash_operations.csv` opt-in lifecycle ALREADY in this same file. The new
`portfolios.csv` snapshot mirrors it byte-for-byte in shape. Build rows from the EXISTING
`build_summary`/`build_trade_log` per portfolio — NO new production serializer, NO `PortfolioHandler` change.

**Module-local column constant** (clone of `COMMISSION_COLUMN` `:97` and `CASH_OPERATION_COLUMNS`).
DELIBERATELY harness-local — must NOT enter `reporting.frames.TRADE_COLUMNS` (oracle-dark, Pitfall 3):
```python
# Suggested name; sits beside COMMISSION_COLUMN at conftest.py top-of-file.
PORTFOLIO_SNAPSHOT_COLUMNS = [
    "portfolio",      # stable key = PortfolioSpec.name (NOT the UUIDv7 PortfolioId — Pitfall 2)
    "final_cash",
    "final_equity",
    "trade_count",
    "realised_pnl",
]
_PORTFOLIO_IDENTITY_COLUMNS = ["portfolio"]
_PORTFOLIO_SORT_KEYS = ["portfolio"]
```

**Construction in `_assemble`** — iterate the already-built `portfolio_ids` (threaded out of
`_build_and_run`; see note below), reuse existing read surface + builders. Pattern from RESEARCH §Pattern 2:
```python
# After the existing single-portfolio assembly (conftest.py:330-401). Uses ONLY the existing
# read surface: get_portfolio (portfolio_handler.py:168) + build_trade_log/build_summary.
# spec.portfolios[i] aligns with portfolio_ids[i] by construction order in _build_and_run.
rows = []
for spec_pf, pid in zip(spec.portfolios, portfolio_ids):
    pf = system.portfolio_handler.get_portfolio(pid)
    pf_trades = build_trade_log(pf)
    pf_summary = build_summary(
        pf, pf_trades, ticker=spec.ticker, timeframe=spec.timeframe,
        start_date=spec.start, end_date=spec.end, starting_cash=spec_pf.cash)
    rows.append({
        "portfolio": spec_pf.name,
        "final_cash": pf_summary["final_cash"],
        "final_equity": pf_summary["final_equity"],
        "trade_count": pf_summary["trade_count"],
        "realised_pnl": pf_summary["total_realised_pnl"],
    })
portfolios_frame = pd.DataFrame(rows, columns=PORTFOLIO_SNAPSHOT_COLUMNS)
```

**Freeze gate** — clone of the `cash_operations.csv` exists()-gate (`conftest.py:516-519`):
```python
if (golden_dir / "portfolios.csv").exists():
    portfolios_frame[PORTFOLIO_SNAPSHOT_COLUMNS].to_csv(
        golden_dir / "portfolios.csv", index=False, float_format=FLOAT_FORMAT)
```

**Diff gate** — clone of `conftest.py:573-577`:
```python
portfolios_golden = golden_dir / "portfolios.csv"
if portfolios_golden.exists():
    gold = pd.read_csv(portfolios_golden)
    fresh = _roundtrip(portfolios_frame, PORTFOLIO_SNAPSHOT_COLUMNS)
    _diff_frame(fresh, gold, _PORTFOLIO_IDENTITY_COLUMNS, _PORTFOLIO_SORT_KEYS)
```

**Threading note (load-bearing):** `_build_and_run` today returns only `(system, portfolio, portfolio_ids[0])`
(`conftest.py:327`) and `_assemble`/`_freeze`/`_diff`/`_run` only carry `portfolio_id`. The new snapshot
needs the FULL `portfolio_ids` list + `spec.portfolios`. Extend the return tuple of `_build_and_run`
to include `portfolio_ids`, thread it through `_assemble` (which already takes `spec`+`system`) and into
the new `portfolios_frame`, then add it to the `_freeze`/`_diff` signatures alongside the other frames.
This is the same additive-tuple pattern the cash_ops frame already followed (`_assemble` returns a 5-tuple
`trades, equity, summary, orders, cash_ops` at `:401`; extend to 6 with `portfolios_frame`).

---

### `tests/e2e/robust/test_determinism.py` (NEW, D-04, ROBUST-04)

**Analog:** the one-line leaf test body (`tests/e2e/cash/release_rejected/test_scenario.py`) for the
folder-derived `e2e` marker convention; the harness internals `_load_spec`/`_build_and_run`/`_assemble`
for the mechanic (RESEARCH §Pattern 3).

**Test body** (parametrized over Phase 9 leaves; run twice in-process, self-compare raw outputs):
```python
import pathlib
import pandas.testing as pdt
import pytest
from tests.e2e.conftest import _load_spec, _build_and_run, _assemble  # real importable module

_E2E_ROOT = pathlib.Path(__file__).resolve().parents[1]  # tests/e2e/
PHASE9_LEAVES = [
    _E2E_ROOT / "multi" / "two_tickers",
    _E2E_ROOT / "multi" / "two_strategies",
    _E2E_ROOT / "multi" / "fanout_portfolios",
    _E2E_ROOT / "multi" / "contended_cash",
    _E2E_ROOT / "robust" / "sparse_bar",
    _E2E_ROOT / "robust" / "union_window",
    _E2E_ROOT / "robust" / "no_trade",
    _E2E_ROOT / "robust" / "flat",
    _E2E_ROOT / "robust" / "losing",
]

@pytest.mark.parametrize("leaf_dir", PHASE9_LEAVES, ids=lambda p: p.name)
def test_double_run_identical(leaf_dir):
    def once():
        spec = _load_spec(leaf_dir / "scenario.py")
        system, portfolio, *rest = _build_and_run(spec)
        return _assemble(spec, system, portfolio, *rest)  # match the extended signature
    a = once()
    b = once()
    pdt.assert_frame_equal(a[0], b[0])  # trades
    pdt.assert_frame_equal(a[1], b[1])  # equity
    assert a[2] == b[2]                 # summary dict incl. metrics block
```
**Pitfall 6 (RESEARCH):** the trio is private to `conftest.py` but `conftest.py` IS a real importable
module — import directly (recommended) rather than promoting to a separate `_harness.py`. Decide and
lock this in the foundational plan. The `_build_and_run` return arity must stay in sync with the D-01
tuple extension above (hence `*rest`).

---

### `tests/e2e/multi/two_tickers/scenario.py` (MULTI-01)

**Analog:** `tests/e2e/admission/max_positions/scenario.py` (the FIRST multi-CSV leaf — two CSVs in
`data={...}`). MULTI-01 differs: ONE emitter over TWO tickers (not two emitters). Rides the EXISTING
`trades.csv` — `build_trade_log` spans both tickers via the `pair` column; no new vehicle.

**Multi-CSV `data` map + multi-ticker emitter** (from `admission/max_positions:146-154`, adapted):
```python
# data carries BOTH tickers; ONE ScriptedEmitter declares BOTH in its tickers list.
SCENARIO = ScenarioSpec(
    start=..., end=..., timeframe="1d", ticker="BTCUSD", starting_cash=10_000,
    data={"BTCUSD": HERE / "bars.csv", "ETHUSDT": HERE / "bars_eth.csv"},
    strategies=[ScriptedEmitter("1d", ["BTCUSD", "ETHUSDT"], script=_SCRIPT, sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(user_id=1, name="two_tickers_pf", cash=10_000)],
    exchange=None,
)
```
**Note:** `spec.ticker` is the single orders-snapshot query key (`conftest.py:338`); a two-ticker
`trades.csv` golden will carry `pair` rows for BOTH tickers (the `_diff_frame` `pair` identity column
`:104` is already there). ETHUSDT is in the default supported-symbol set; BTCUSD is added on the instance.

---

### `tests/e2e/multi/two_strategies/scenario.py` (MULTI-02)

**Analog:** `tests/e2e/admission/max_positions/scenario.py` — the two-co-subscribed-`ScriptedEmitter`
precedent (`:147-152`). MULTI-02 is the clean version: two emitters, one portfolio, both fill (no cap).
```python
strategies=[
    ScriptedEmitter("1d", ["BTCUSD"], script=_BTC_SCRIPT, sizing_policy=_SIZING),
    ScriptedEmitter("1d", ["ETHUSDT"], script=_ETH_SCRIPT, sizing_policy=_SIZING),
],
portfolios=[PortfolioSpec(user_id=1, name="two_strategies_pf", cash=...)],
```
`_build_and_run` subscribes EVERY strategy to EVERY portfolio (`conftest.py:316-317`) — no wiring change.

---

### `tests/e2e/multi/fanout_portfolios/scenario.py` (MULTI-03, foundational canary)

**Analog:** `smoke/single_market_buy/scenario.py` (copy-template + VERIFY note) extended with TWO
portfolios. This is the canary that proves the D-01 `portfolios.csv` serializer end-to-end.

**Multi-portfolio spec with ASYMMETRIC cash** (RESEARCH §Undersampled-Edges mitigation — isolation must
be OBSERVABLE, not merely plausible; pick distinct `name`s = the stable snapshot key, Pitfall 2):
```python
portfolios=[
    PortfolioSpec(user_id=1, name="pf_a", cash=10_000),
    PortfolioSpec(user_id=2, name="pf_b", cash=5_000),   # asymmetric → A's numbers provably != B's
],
strategies=[ScriptedEmitter("1d", ["BTCUSD"], script=_SCRIPT, sizing_policy=_SIZING)],
```
**Golden:** commit an EMPTY `golden/portfolios.csv` placeholder to opt this leaf into the new snapshot
(same mechanic as the empty `cash_operations.csv` placeholder — see Shared Patterns). The two rows
(`pf_a`, `pf_b`) with differing `final_cash`/`final_equity` ARE the cash-isolation assertion.

---

### `tests/e2e/multi/contended_cash/scenario.py` (MULTI-04, D-02)

**Analog:** `tests/e2e/sizing/over_cash_reject/scenario.py` — the exact `cash_reservation` REJECTED
audit path, plus `tests/e2e/cash/release_rejected` for the cash-ledger opt-in. MULTI-04 = two emitters,
ONE portfolio, first BUY reserves all cash, second hits the synchronous check-and-reserve gate →
`InsufficientFundsError` → audited PENDING→REJECTED (`triggered_by="cash_reservation"`).

**Determinism source (D-02):** `spec.strategies` registration order → `StrategiesHandler` FIFO emit →
`OrderManager` FIFO. The winner is `spec.strategies[0]`; the loser is `[1]`. Hand-verifiable.

**Assertion vehicles (BOTH existing, opt-in):**
- `golden/orders.csv` — the loser's STANDALONE/MARKET/BUY/REJECTED row (clone the
  `over_cash_reject/scenario.py:62-63` table; `o.status.name` → `REJECTED`, quantity = the SIZED qty
  since `cash_reservation` fires AFTER sizing — distinct from the unsized `admission_max_positions` reject).
- `golden/cash_operations.csv` — the winner's RESERVATION row; the loser produces NO orphan reservation
  (gate fires before reserve). Commit empty placeholders for BOTH to opt in.

---

### `tests/e2e/robust/sparse_bar/scenario.py` (ROBUST-01, D-03)

**Analog:** `tests/integration/test_universe_spans.py` (the sparse-dict no-fill guard
`event.bars.get(ticker) is None → continue`) re-proven on REAL sliced SOL data via `csv_paths`.

**Data source:** REAL committed `data/SOLUSD_1d_ohlcv.csv`, SLICED to a tiny hand-verifiable window.
**Pitfall 1 (RESEARCH, load-bearing):** SOL's 418 missing bars are ONE 416-day block (2023-07-07→2024-08-25)
plus exactly one clean 2-day gap (**2023-06-24, 2023-06-25**, both present in ETH+AAVE). Target the 2-day
gap (or a slice straddling 2023-07-07) — NOT a "random" SOL window. Position the gap so a signal/position
is LIVE across it (proves no fill AND no crash on the matching path, not just a warmup gap).
```python
# csv_paths passthrough — same data= shape as every leaf, but pointing at a SLICED real CSV.
data={"SOLUSD": HERE / "sol_sliced.csv"},   # hand-cut tiny window around 2023-06-24/25
```
Slices are small committed CSVs; the slice file lives beside `scenario.py` like every `bars.csv`.

---

### `tests/e2e/robust/union_window/scenario.py` (ROBUST-02, D-03)

**Analog:** `tests/integration/test_universe_spans.py` — the synthetic-fixture proof of mid-run listing
+ differing end dates over a union window. ROBUST-02 re-proves on REAL sliced AAVE (lists **2021-07-15**)
+ another asset, OR a differing-end slice (BTC→2026-06-03 vs others 2026-01-08).
```python
# Union window spanning AAVE's listing: bars before 2021-07-15 produce NO AAVE fill (hand-verifiable).
data={"BTCUSD": HERE / "btc_sliced.csv", "AAVEUSD": HERE / "aave_sliced.csv"},
start="2021-07-10", end="2021-07-20",   # straddles the 2021-07-15 listing
```
**Discretion (RESEARCH §Undersampled):** one-shape-per-leaf favors NOT cramming mid-run-listing AND
differing-ends into one slice; consider two folds if both edges matter. The engine's `active_membership`
/ `is_active` span primitive + the union ping grid handle this with NO production change.

---

### `tests/e2e/robust/{no_trade,flat,losing}/scenario.py` (ROBUST-03, D-05)

**Analog:** `no_trade` → `sizing/over_cash_reject` (zero closed trades, EMPTY `trades.csv`,
`trade_count = 0`); `flat`/`losing` → `smoke/single_market_buy` round-trip with engineered PnL. Each
freezes the `summary.json` `metrics` block (the harness already exact-diffs the whole metrics dict,
`conftest.py:444-447`) PLUS an explicit no-NaN/no-inf assert.

**Metric guards already exist — DO NOT rebuild** (`reporting/metrics.py`, verified): `sharpe` `<2`/`sd==0`→0.0
(`:62-67`); `sortino` empty/`downside==0`→0.0 (`:77-82`); `profit_factor` empty/all-loss→0.0,
**all-WIN→`inf`** (`:91-98`); `cagr` empty/non-positive→0.0 (`:109-118`); `win_rate` empty→0.0; `max_drawdown`
empty→0.0. ROBUST-03 COVERS these guards.

**no-NaN/no-inf guard helper (D-05)** — a small foundational helper the three leaves invoke (or a harness
hook). Per RESEARCH §Pitfall 5, exact-equality alone fails confusingly on NaN; the explicit assert is the
ROBUST-03 contract. stdlib `math.isfinite` over the tiny 6-key metrics dict:
```python
import math
def assert_metrics_finite(metrics: dict[str, float]) -> None:
    bad = {k: v for k, v in metrics.items() if not math.isfinite(v)}
    assert not bad, f"ROBUST-03: degenerate metrics must be finite (no NaN/inf), got {bad}"
```
**Authoring constraint (RESEARCH §Code-Examples / A3):** `profit_factor` returns `inf` for an all-WIN
frame. Author "flat" = a round-trip netting ~zero PnL (a small win + small loss, so PF is finite) and
"losing" = net-negative — both naturally finite. Keep all six metrics finite rather than whitelisting `inf`.

---

### `tests/e2e/{multi,robust}/*/test_scenario.py` (one-line leaf tests, ~8 new)

**Analog:** `tests/e2e/cash/release_rejected/test_scenario.py` — the ONLY allowed leaf-test body.
Folder-derived `e2e` marker; NO assert/diff logic in the leaf (the harness owns it):
```python
import pathlib
HERE = pathlib.Path(__file__).resolve().parent

def test_<leaf_name>(run_scenario):
    run_scenario(HERE)
```
Name the function after the leaf (e.g. `test_two_tickers`, `test_contended_cash`) for readable -k selection.

## Shared Patterns

### Opt-in `exists()`-gated golden serializer (the D-01 backbone)
**Source:** `tests/e2e/conftest.py` cash_operations lifecycle (`_assemble:344`, `_freeze:516-519`,
`_diff:573-577`) + `itrader/reporting/cash_operations.py` (the duck-typed rows→DataFrame→sort→reset idiom).
**Apply to:** the new `portfolios.csv` snapshot (D-01) AND every MULTI-04 / ROBUST-03 leaf that opts into
`cash_operations.csv` / `orders.csv`.
**Mechanic:** a serializer ALWAYS produces its frame in `_assemble`, but `_freeze`/`_diff` only write/compare
it when the leaf has committed a placeholder golden file (`if (golden_dir / "X.csv").exists()`). This keeps
the new serializer ORACLE-DARK — single-portfolio leaves that do not commit `portfolios.csv` are byte-identical.
**Opt-in placeholder:** commit an EMPTY (header-only) CSV in the leaf's `golden/` to switch the snapshot on
(see `tests/e2e/cash/release_rejected/golden/cash_operations.csv` — one header line, zero rows).

### Determinism-safe golden columns (no UUIDs, no wall-clock)
**Source:** `itrader/reporting/cash_operations.py:13-33` (the THREE excluded fields rationale) +
`COMMISSION_COLUMN`/`CASH_OPERATION_COLUMNS` module-local constants in `conftest.py:97/121`.
**Apply to:** `PORTFOLIO_SNAPSHOT_COLUMNS`.
**Rule (Pitfall 2):** key the per-portfolio snapshot on `PortfolioSpec.name` — NEVER the `PortfolioId`
(a UUIDv7, `portfolio.py:52`, non-deterministic). `spec.portfolios[i]` aligns with `portfolio_ids[i]` by
`_build_and_run` construction order. Author distinct `name`s per scenario (Assumption A1).

### Oracle-dark: stay out of core `TRADE_COLUMNS`
**Source:** `conftest.py:89-97` (`COMMISSION_COLUMN` comment) + RESEARCH §Pitfall 3.
**Apply to:** the entire D-01 snapshot.
**Rule:** `reporting.frames.TRADE_COLUMNS` feeds `scripts/run_backtest.py` + the BTCUSD oracle
(`test_backtest_oracle.py`). Adding ANY new column there breaks byte-exactness. The snapshot constants
live module-local in `conftest.py`. The foundational plan MUST re-run `make test-integration` (the BTCUSD
oracle) byte-exact after the serializer lands (D-06, Wave 0).

### Exact no-tolerance diff via `_diff_frame`
**Source:** `conftest.py:404-438` (`_diff_frame`) + `:522-538` (`_roundtrip`).
**Apply to:** the `portfolios.csv` diff.
**Mechanic:** sort both sides by the sort key, assert identity columns exact, auto-derive the numeric
remainder from the golden header, assert exact — NO float tolerance. The fresh frame is round-tripped
through `to_csv(float_format=FLOAT_FORMAT)`→`read_csv` first so both sides share dtypes/precision.

### VERIFY-note-before-freeze discipline
**Source:** `smoke/single_market_buy/scenario.py:16-92` (the canonical VERIFY block) + every leaf's
`================ VERIFY ================` docstring (see `admission/max_positions`, `sizing/over_cash_reject`).
**Apply to:** ALL 8 new leaves.
**Rule:** each leaf's module docstring IS its hand-derivation — contrived/sliced bars, which bar fires,
fill prices, the resulting frozen numbers, WHY each number is what it is. A human verifies it matches
`golden/` BEFORE `--freeze`. Freeze ONE hand-verified leaf at a time (the harness mechanically refuses
`--freeze` with >1 selected test, `conftest.py:607-613`). Freeze per-cluster batches, not 12-at-once (D-06).

### Real-data slicing via `csv_paths` (ROBUST-01/02 only)
**Source:** `tests/integration/test_universe_spans.py:129-134` (`csv_paths=` constructor arg) + the
`data=` map every leaf already passes (`conftest.py:268`).
**Apply to:** `sparse_bar`, `union_window`.
**Rule:** the sliced real CSV is a small committed file beside `scenario.py`; `data={ticker: HERE / "x.csv"}`
points at it. `csv_paths` default None → byte-identical (no production change). Hand-verify the exact bar
dates POST-slice (Assumption A2: tz localization to Europe/Paris can shift a boundary day; the emitter
already `tz_convert("UTC")`s — `scripted_emitter.py:132`).

## No Analog Found

None. Every new file has a direct in-repo precedent — this is the eighth coverage phase on the same harness.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All 13 logical units have exact or role-match analogs (see table). |

## Metadata

**Analog search scope:** `tests/e2e/` (conftest, scenario_spec, strategies, smoke/admission/cash/sizing
leaves), `tests/integration/test_universe_spans.py`, `itrader/reporting/` (summary, metrics, cash_operations),
`itrader/portfolio_handler/portfolio_handler.py` read surface.
**Files scanned:** 11 read in full/targeted + directory listing of all 30 e2e leaves.
**Pattern extraction date:** 2026-06-10
**Indentation for all new/modified files:** 4 spaces (e2e package + reporting house style; NOT handler tabs).
