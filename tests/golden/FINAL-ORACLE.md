# FINAL Authoritative Numerical Oracle — Program Freeze + Definition-of-Done Evidence (D-11 / D-13)

**Plan:** 08-09 — the TERMINAL plan of the iTrader Backtest-Correctness Refactor.
**Status:** FINAL FREEZE DECLARATION. This is a terminal freeze declaration + DoD
evidence record, not a diff/re-freeze note (no artifact bytes change in this plan).

---

## 1. Declaration (D-11)

The current `tests/golden/{summary.json, trades.csv, equity.csv}` set is hereby declared
the **FINAL authoritative numerical oracle** of the program.

Per PROJECT.md's golden-master discipline (the numerical oracle re-baselines at exactly
two sanctioned points — after M2 and after M5), **Phase 8 (M5c) is the last sanctioned
change point** and this is the **last state**. The oracle reached this state through:

- **08-01 → 08-03** — the golden-path float→Decimal cleanup (`Portfolio.total_*`
  properties retyped to `Decimal`; float boundary moved out to statistical-ratio metric
  inputs only). Re-frozen as a SHIFT in `REFREEZE-M5C-DECIMAL.md` (owner-approved).
- **08-04 → 08-07** — the cross-validation harness + reconciliation against three
  independent reference engines (backtesting.py 0.6.5, backtrader 1.9.78.123,
  nautilus-trader 1.227.0), all script-only (D-10), all reconciling 134/134 trades EXACT.
- **08-08** — every cross-validation divergence root-caused and dispositioned (D-05):
  **0 BUG / 4 LEGITIMATE-DIFFERENCE**, owner-approved, **NO re-freeze**. iTrader's
  post-M5b numbers are kept.

This declaration is the program's definition-of-done artifact: with the DoD checklist
(§5) green against this frozen oracle, iTrader's backtest path is **correct,
deterministic, type-clean, Decimal-money, single-UUID-scheme, and regression-locked**.

---

## 2. Frozen Values

Quoted verbatim from the frozen `tests/golden/summary.json`.

| Field | Frozen value |
|---|---|
| `trade_count` | **134** |
| `final_equity` | 46189.87730727451 |
| `final_cash` | 46189.87730727451 |
| `total_realised_pnl` | 36189.87730727451 |
| `starting_cash` | 10000.0 |
| `metrics.cagr` | 0.19910032815485068 |
| `metrics.max_drawdown` | -0.538256823181407 |
| `metrics.profit_factor` | 1.291149869385797 |
| `metrics.sharpe` | 0.6583614133806527 |
| `metrics.sortino` | 1.038504038796619 |
| `metrics.win_rate` | 0.3656716417910448 |
| Equity-curve points | 3076 |

**Run window / configuration:** `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv`,
window **2018-01-01 → 2026-06-03**, **BTCUSD 1d**, $10,000 starting cash, zero fee /
zero slippage (exchange defaults pinned by `scripts/run_backtest.py`; `final_cash ==
final_equity`). Serialization knobs: `FLOAT_FORMAT = "%.10f"`, `json.dump(..., indent=2,
sort_keys=True)` — deterministic, no wall-clock fields.

---

## 3. Lineage (M5-C re-freeze)

The state frozen here carries forward from the **single** M5-C re-freeze note:

- **`tests/golden/REFREEZE-M5C-DECIMAL.md`** (08-03, branch a, SHIFT, owner-approved):
  the golden-path Decimal cleanup. `trades.csv` byte-identical (134 trades); headline
  money byte-exact (`final_equity` / `final_cash` = 46189.87730727451); only 19/3076
  equity points (+8 derived `total_pnl`) and 3 equity-derived ratio metrics
  (`max_drawdown`, `sharpe`, `sortino`) moved by ~1 ULP. That is the last value shift.

There is **no `REFREEZE-M5C-<bug>.md` note** — the conditional 08-08 bug-fix re-freeze was
correctly a **no-op** (0 BUG rows). The golden artifacts are byte-identical to the 08-03
freeze; the prior frozen state carries forward unchanged into this final declaration.

---

## 4. Cross-Validation Evidence (D-10)

`tests/golden/CROSS-VALIDATION.md` is the committed cross-validation evidence (D-10) — it
is **evidence, this oracle is the gate (D-11)**, and it is **not wired into `make test`/CI**.
It records:

- **D-02 PRIMARY gate fully GREEN:** all 134 trades align EXACTLY (entry + exit dates)
  across iTrader, backtesting.py, backtrader, and nautilus — zero SHIFT, zero MISSING.
- **4 SECONDARY metric divergences, all dispositioned LEGITIMATE-DIFFERENCE (D-05):**
  - 3× sortino (backtesting.py / backtrader / nautilus) → a single iTrader entry-bar
    equity-marking convention (backtrader is the smoking gun: byte-identical trade log
    AND final equity, yet divergent sortino → the gap lives only in the per-bar equity
    path; exactly 134 differing bars map one-to-one onto the 134 trade-entry dates).
  - 1× nautilus win_rate (48 vs 49 winners) → nautilus NETTING fill arithmetic on a 2025
    rapid-round-trip cluster; iTrader's 49-winner count corroborated by BOTH gating
    engines (backtesting.py and backtrader).
- **Owner sign-off APPROVED** (2026-06-08): 0 BUG / 4 LEGITIMATE-DIFFERENCE; no defect;
  no re-freeze; iTrader's numbers are kept — the explicit basis for this final freeze.

This satisfies ROADMAP SC#1 ("metrics reconciled and any divergence explained").

---

## 5. Definition-of-Done Evidence Block (D-13)

The program-level definition of done (PROJECT.md / REFACTOR-BRIEF §1). Each row is a
discrete automated acceptance criterion, run live in 08-09 Task 1 against this frozen
oracle. **All eight checks PASS.**

| # | DoD criterion | Command | Result |
|---|---|---|---|
| 1 | End-to-end run: non-trivial trade log + multi-point equity curve | `make backtest` | **PASS** — wrote `output/{trades.csv,equity.csv,summary.json}`; `trade_count = 134` (matches frozen golden); `final_equity = 46189.87730727451`; **3076** equity points (full 2018→2026 daily grid) |
| 2 | Type cleanliness (mypy --strict over `itrader/`) | `make typecheck` | **PASS** — `Success: no issues found in 151 source files`, exit 0 |
| 3 | No float money on the golden path | inspect `Portfolio.total_*` + `grep float(` | **PASS** — all five `total_market_value` / `total_equity` / `total_unrealised_pnl` / `total_realised_pnl` / `total_pnl` return `Decimal`; residual `float(` only on derived statistical-ratio inputs (equity-series → drawdown/sharpe/sortino, the `max_position_value / total_equity` reporting ratio), never on a money member. Live-path float leaks OUT (D-09). |
| 4 | Single UUIDv7 scheme on the result path | `grep -rn 'uuid4\|uuid1' itrader/ --include='*.py'` | **PASS** — sole hit is `portfolio_handler.py:88 _generate_correlation_id()` (a log/error-event correlation id, non-result-bearing, excluded per the plan's interfaces note). All order/fill/trade/portfolio-state IDs flow from `idgen.generate_order_id()` (uuid-utils UUIDv7). |
| 5 | Determinism: two runs byte-identical | `make backtest` ×2 → `diff -r run_a run_b` | **PASS** — byte-identical `trades.csv` / `equity.csv` / `summary.json` (no differences) |
| 6 | Full live suite green at the real collected count | `pytest --collect-only -q` then `make test` | **PASS** — **724** tests collected; **724 passed**, 0 failures, under `filterwarnings=["error"]` / `--strict-markers` / `--strict-config` (the real count, not the historic 274) |
| 7 | Run-path integration test against the FINAL oracle | `pytest tests/integration/test_backtest_oracle.py -v` | **PASS** — 2 passed (`test_oracle_behavioral_identity` + `test_oracle_numeric_values`); byte-exact frame-equal diff of a fresh run vs frozen `tests/golden/*`, no float tolerance |
| 8 | Cross-validation evidence present (SC#1) | `test -f tests/golden/CROSS-VALIDATION.md && grep -qi 'root-cause' …` | **PASS** — `CROSS-VALIDATION.md` exists with per-divergence root-cause dispositions (owner-approved in 08-08) |

**DoD verdict: GREEN.** Every program-level definition-of-done criterion holds against
the frozen oracle. The run-path integration test (byte-exact, no tolerance) is the
permanent regression gate; a fresh run matches the frozen oracle, so silent oracle
tampering fails the gate.

---

## 6. Owner Sign-Off

Golden-master discipline requires owner sign-off on the final oracle freeze (Phase 6/7
D-21/D-11 law). This sign-off freezes the final oracle and closes the program.

**Status:** **APPROVED — final oracle FROZEN, program CLOSED.**

The project owner reviewed the FINAL-ORACLE declaration and the D-13 definition-of-done
evidence block (§5, all eight checks GREEN) at the 08-09 blocking human-verify checkpoint
and signed off.

> Owner: tiziaco   Date: 2026-06-08   Signal: "approved"

With this sign-off the `tests/golden/{summary.json, trades.csv, equity.csv}` set is the
**final authoritative numerical oracle**. No further re-baseline is sanctioned. The
iTrader Backtest-Correctness Refactor program is **complete**: the backtest path is
correct, deterministic, type-clean, Decimal-money, single-UUID-scheme, and
regression-locked by the byte-exact run-path integration gate.
