---
phase: 08-admission-position-management-cash-edges
verified: 2026-06-10T16:30:00Z
status: passed
score: 13/13
overrides_applied: 0
---

# Phase 8: Admission & Position Management E2E — Verification Report

**Phase Goal:** E2E golden-locked coverage of scale-in (pyramiding), partial scale-out, `max_positions` rejection, exit-then-re-entry, and the cash reservation/release lifecycle.
**Verified:** 2026-06-10T16:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ADMIT-01: `allow_increase=True` scale-in pyramiding works E2E with golden-locked leaf | VERIFIED | `tests/e2e/admission/scale_in/` exists, substantive scenario with `allow_increase=True`, frozen `trades.csv` (1 aggregated round-trip, `total_bought=8000`, `realised_pnl=0`), passing in diff mode |
| 2 | CASH-01: Over-cash scale-in add is rejected with NO orphan reservation in cash ledger | VERIFIED | `golden/cash_operations.csv` shows 7-row ledger with ORDER-1 and ORDER-3 RESERVATION/RELEASE pairs (two successful adds), no RESERVATION row for the over-cash third add; passes diff mode |
| 3 | ADMIT-02: Partial scale-out via `exit_fraction < 1` keeps position open between sells and closes at end | VERIFIED | `tests/e2e/admission/scale_out/` leaf with 3-sell script (`exit_fraction=0.5` twice + full close); `golden/trades.csv` shows `avg_sold=135` (proves 40/20/20 partial sizing), `realised_pnl=2800`; passes diff mode |
| 4 | ADMIT-03: `max_positions` cap rejection produces audited REJECTED order with `triggered_by=admission_max_positions` | VERIFIED | `tests/e2e/admission/max_positions/` multi-ticker leaf; `golden/orders.csv` shows `STANDALONE,BTCUSD,MARKET,BUY,REJECTED,100,0,0` (quantity=0 = gate-before-sizing); passes diff mode |
| 5 | ADMIT-04: Full exit then re-entry on same ticker produces two clean round-trips | VERIFIED | `tests/e2e/admission/re_entry/` leaf; `golden/trades.csv` shows 2 rows (entry `2020-01-03/04`, entry `2020-01-05/06`), both with `net_quantity=0`, `realised_pnl=400` each; passes diff mode |
| 6 | CASH-02 CANCELLED: Operator-cancelled resting LIMIT BUY produces positive RELEASE_RESERVATION in cash ledger | VERIFIED | `tests/e2e/cash/release_cancelled/golden/cash_operations.csv` shows `ORDER-1,RESERVATION,3200` + `ORDER-1,RELEASE_RESERVATION,3200` pair; passes diff mode |
| 7 | CASH-02 REFUSED: Over-`max_order_size` BUY refused by exchange produces positive RELEASE_RESERVATION | VERIFIED | `tests/e2e/cash/release_refused/` uses deterministic `ExchangeConfig(limits=ExchangeLimits(max_order_size=Decimal("10")))` lever (not RNG); `golden/cash_operations.csv` shows `ORDER-1,RESERVATION,4000` + `ORDER-1,RELEASE_RESERVATION,4000` pair; passes diff mode |
| 8 | CASH-02 REJECTED: Rejection at/before reserve leaves NO orphan RESERVATION in cash ledger | VERIFIED | `tests/e2e/cash/release_rejected/golden/cash_operations.csv` is header-only (zero data rows) — the honest negative no-orphan assertion; passes diff mode |
| 9 | Cash-ledger serializer (`cash_operations.py`) is determinism-safe: excludes `operation_id`, `reference_id`, `timestamp` | VERIFIED | `CASH_OPERATION_COLUMNS = ["correlation", "operation_type", "amount", "balance_before", "balance_after"]` — none of the excluded fields present; `correlation` derives stable `ORDER-{n}` ordinal; `mypy --strict` clean |
| 10 | Opt-in `cash_operations.csv` is oracle-dark (fires only when placeholder exists) | VERIFIED | Conftest `_freeze`/`_diff` both guarded by `(golden_dir / "cash_operations.csv").exists()`; `frames.py::TRADE_COLUMNS` unchanged; existing smoke/sizing leaves unaffected |
| 11 | `ScriptedEmitter` carries `allow_increase: bool = False` and `max_positions: int = 1` with behavior-preserving defaults | VERIFIED | `scripted_emitter.py` lines 87-88 show `allow_increase: bool = False, max_positions: int = 1`; threaded to `BaseStrategyConfig` at lines 110-111; existing 30 e2e leaves still green |
| 12 | BTCUSD oracle remains byte-exact (134 trades / `final_equity 46189.87730727451`) | VERIFIED | `tests/integration/test_backtest_oracle.py` all 3 tests pass; serializer is out of `frames.py::TRADE_COLUMNS` and fires only opt-in |
| 13 | All 7 Phase 8 scenario leaves pass in diff mode (not `--freeze`) | VERIFIED | `PYTHONPATH="$PWD" poetry run pytest tests/e2e/admission tests/e2e/cash -v` → 7 passed; full 37-leaf suite also passes |

**Score:** 13/13 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `itrader/reporting/cash_operations.py` | CASH_OPERATION_COLUMNS + build_cash_operations serializer | VERIFIED | Exists, substantive (97 lines), excludes `operation_id`/`reference_id`/`timestamp`, mypy-strict clean |
| `tests/e2e/strategies/scripted_emitter.py` | `allow_increase` + `max_positions` ctor params | VERIFIED | Lines 87-88 add both params with behavior-preserving defaults; wired to BaseStrategyConfig |
| `tests/e2e/conftest.py` | Opt-in cash_operations.csv wiring in `_assemble`/`_freeze`/`_diff` | VERIFIED | Lines 76-78 import; line 338 `build_cash_operations`; lines 497-499 `_freeze` opt-in gate; lines 554-558 `_diff` opt-in gate |
| `tests/e2e/admission/scale_in/scenario.py` | ADMIT-01 + CASH-01 fold canary with allow_increase=True | VERIFIED | Substantive with full VERIFY block; `allow_increase=True`, FixedQuantity(40), 4-step script |
| `tests/e2e/admission/scale_in/golden/cash_operations.csv` | Frozen cash-ledger snapshot (opt-in placeholder) | VERIFIED | 8 lines (1 header + 7 data rows): 2 RESERVATION/RELEASE pairs + 2 TRANSACTION_DEBIT + 1 TRANSACTION_CREDIT |
| `tests/e2e/admission/scale_in/golden/trades.csv` | Frozen filled adds (one aggregated round-trip) | VERIFIED | 2 lines: 1 row showing `total_bought=8000, total_sold=8000, realised_pnl=0` |
| `tests/e2e/admission/scale_out/scenario.py` | ADMIT-02 partial scale-out leaf | VERIFIED | Substantive with VERIFY block; 3-sell script with `exit_fraction=0.5` twice then full close |
| `tests/e2e/admission/scale_out/golden/trades.csv` | Multi-partial-sell trade log | VERIFIED | 2 lines: `avg_sold=135` proves 40/20/20 partial sizing, `realised_pnl=2800` |
| `tests/e2e/admission/max_positions/scenario.py` | ADMIT-03 multi-ticker max_positions rejection leaf | VERIFIED | Two ScriptedEmitter instances (ETHUSDT occupier + BTCUSD over-cap entry), `max_positions=1` |
| `tests/e2e/admission/max_positions/golden/orders.csv` | ADMIT-03 REJECTED orders-snapshot (opt-in) | VERIFIED | `STANDALONE,BTCUSD,MARKET,BUY,REJECTED,100,0,0` — quantity=0 confirms gate-before-sizing |
| `tests/e2e/admission/re_entry/scenario.py` | ADMIT-04 two-round-trip re-entry leaf | VERIFIED | BUY/SELL/BUY/SELL script on same ticker; defaults `allow_increase=False, max_positions=1` correct |
| `tests/e2e/admission/re_entry/golden/trades.csv` | Two-round-trip trade log | VERIFIED | 3 lines: 2 rows, distinct (entry_date, exit_date), each `realised_pnl=400` |
| `tests/e2e/cash/release_cancelled/golden/cash_operations.csv` | CASH-02 CANCELLED positive release | VERIFIED | `ORDER-1,RESERVATION,3200` + `ORDER-1,RELEASE_RESERVATION,3200` pair |
| `tests/e2e/cash/release_refused/golden/cash_operations.csv` | CASH-02 REFUSED positive release | VERIFIED | `ORDER-1,RESERVATION,4000` + `ORDER-1,RELEASE_RESERVATION,4000` pair; deterministic max_order_size trigger confirmed |
| `tests/e2e/cash/release_rejected/golden/cash_operations.csv` | CASH-02 REJECTED negative no-orphan | VERIFIED | Header-only (zero data rows) — the negative assertion that no RESERVATION was ever recorded |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `conftest._assemble` | `portfolio.cash_manager.get_cash_operations()` | `build_cash_operations(...)` | WIRED | Line 338: `cash_ops = build_cash_operations(portfolio.cash_manager.get_cash_operations())` |
| `conftest._freeze` | `golden/cash_operations.csv` | `exists()` opt-in gate | WIRED | Lines 497-499: `if (golden_dir / "cash_operations.csv").exists(): cash_ops[...].to_csv(...)` |
| `conftest._diff` | `golden/cash_operations.csv` | `exists()` opt-in gate | WIRED | Lines 554-558: `cash_ops_golden = golden_dir / "cash_operations.csv"` with exists check |
| `scale_in script` | `order_manager allow_increase` | `allow_increase=True` in ScriptedEmitter → BaseStrategyConfig | WIRED | `scenario.py` line 158: `allow_increase=True`; emitter lines 110-111 thread to `BaseStrategyConfig` |
| `scale_out script` | `sizing_resolver.resolve_exit` | `exit_fraction < 1` partial close | WIRED | `scenario.py` lines 112-113: `"exit_fraction": Decimal("0.5")` per-bar keys; engine resolve_exit confirmed |
| `max_positions emitter` | `order_manager admission gate` | `open_position_count >= max_positions` REJECTED | WIRED | Two emitters with `max_positions=1`; `golden/orders.csv` shows `REJECTED,quantity=0` confirming gate-before-sizing |
| `release_refused spec.exchange` | `simulated._admit_order validate_order` | `FillEvent REFUSED → terminal release` | WIRED | `ExchangeConfig(limits=ExchangeLimits(max_order_size=Decimal("10")))` in scenario; conftest seam re-derives `_max_order_size` from applied config (lines 290-291) |
| `release_cancelled actions timeline` | `order_manager local-cancel release` | `operator cancel → RELEASE_RESERVATION` | WIRED | `actions=(Action(bar_date="2020-01-03", kind="cancel", ticker="BTCUSD"),)` in scenario; `golden/cash_operations.csv` shows RELEASE_RESERVATION fired |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `admission/scale_in golden/cash_operations.csv` | cash-ledger ops trail | `portfolio.cash_manager.get_cash_operations()` → `build_cash_operations` | Yes — 7 non-trivial rows with RESERVATION/RELEASE/DEBIT/CREDIT ops matching hand-derived cash trail | FLOWING |
| `admission/scale_in golden/trades.csv` | closed positions | `build_trade_log(closed_positions)` | Yes — 1 row, `total_bought=8000, realised_pnl=0` matches BTCUSD flat-price round-trip | FLOWING |
| `admission/max_positions golden/orders.csv` | BTCUSD order mirror | `get_orders_by_ticker(spec.ticker)` | Yes — 1 REJECTED row with `quantity=0` proving gate-before-sizing semantic | FLOWING |
| `cash/release_rejected golden/cash_operations.csv` | cash-ledger ops | `build_cash_operations(...)` | Yes — header-only is the legitimate negative assertion (no ops recorded before atomic reserve failure) | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 7 Phase 8 scenario leaves pass in diff mode | `PYTHONPATH="$PWD" poetry run pytest tests/e2e/admission tests/e2e/cash -v` | 7 passed in 0.24s | PASS |
| BTCUSD oracle byte-exact (134 trades / 46189.87730727451) | `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed in 5.68s | PASS |
| All 37 e2e leaves green (existing leaves not regressed) | `PYTHONPATH="$PWD" poetry run pytest tests/e2e/ -q` | 37 passed in 0.79s | PASS |
| `cash_operations.py` mypy strict clean | `poetry run mypy --strict itrader/reporting/cash_operations.py` | Success: no issues found | PASS |
| `CASH_OPERATION_COLUMNS` excludes non-deterministic fields | import + column check | `operation_id`, `reference_id`, `timestamp` all absent from columns | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ADMIT-01 | 08-01 | `allow_increase=True` scale-in works E2E | SATISFIED | `tests/e2e/admission/scale_in/` — `allow_increase=True`, two successful adds aggregated into one position, golden-locked |
| ADMIT-02 | 08-02 | Partial scale-out via `exit_fraction < 1` | SATISFIED | `tests/e2e/admission/scale_out/` — three-sell script with `exit_fraction=0.5` twice; `avg_sold=135` proves per-leg sizing |
| ADMIT-03 | 08-02 | `max_positions` cap produces audited new-entry REJECTED | SATISFIED | `tests/e2e/admission/max_positions/` — multi-ticker leaf, `orders.csv` shows REJECTED `quantity=0` (gate-before-sizing) |
| ADMIT-04 | 08-02 | Full exit then re-entry on same ticker | SATISFIED | `tests/e2e/admission/re_entry/` — two clean round-trips, `trades.csv` 2 rows, each `realised_pnl=400` |
| CASH-01 | 08-01 | Insufficient funds → audited `cash_reservation` rejection | SATISFIED | `scale_in` leaf cash-ledger no-commit lens: no RESERVATION row for over-cash third add; available_cash intact at 2000 |
| CASH-02 | 08-03 | Reservation release on every terminal state (CANCELLED/REJECTED/REFUSED) | SATISFIED | Three leaves: `release_cancelled` (RESERVATION+RELEASE pair), `release_refused` (pair, deterministic max_order_size), `release_rejected` (header-only no-orphan) |

All 6 requirements (ADMIT-01, ADMIT-02, ADMIT-03, ADMIT-04, CASH-01, CASH-02) mapped to concrete frozen E2E leaves with passing tests. REQUIREMENTS.md traceability table marks all 6 as Complete for Phase 8.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/e2e/conftest.py` | 337, 496 | "placeholder" in a comment | Info | Describes the opt-in mechanism intentionally (not a stub) — the word "placeholder" refers to the empty golden file that activates the opt-in gate, which is by design |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 8 modified files. No return-null/return-{}/return-[] stubs. No hardcoded empty data that flows to rendering.

---

### Human Verification Required

None. All verification items for this phase are automatable E2E test assertions. The three blocking `checkpoint:human-verify` gates in the plans (Task 3 of 08-01, Tasks 1-2 of 08-02, Tasks 1-2 of 08-03) were all approved by the human reviewer during execution (documented in each SUMMARY.md with "approved" confirmation). The automated diff-mode test suite now regression-locks those human-verified truths.

---

### Gaps Summary

No gaps. All 13 must-haves are VERIFIED:

- The cash-ledger serializer exists, is determinism-safe (excludes 3 non-deterministic fields), and passes `mypy --strict`.
- The opt-in `exists()` gate is wired in `_assemble`/`_freeze`/`_diff`; the oracle is dark.
- `ScriptedEmitter` carries `allow_increase`/`max_positions` with behavior-preserving defaults; 30 pre-existing leaves remain green.
- All 7 Phase 8 scenario leaves are substantive (hand-verified VERIFY blocks, frozen goldens, passing in diff mode).
- The BTCUSD oracle is byte-exact (3/3 tests pass, 134 trades / `final_equity 46189.87730727451` unchanged).
- All 6 requirement IDs (ADMIT-01 through ADMIT-04, CASH-01, CASH-02) map 1:1 to concrete frozen leaves.
- CASH-01 and CASH-02 REJECTED use distinct triggers and lenses from Phase 7 SIZE-03 (non-duplication D-01 contract honored).

---

_Verified: 2026-06-10T16:30:00Z_
_Verifier: Claude (gsd-verifier)_
