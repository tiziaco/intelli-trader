---
phase: 03-hot-path-performance
verified: 2026-06-11T00:00:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 3: Hot-Path Performance Verification Report

**Phase Goal:** Eliminate the dominant per-tick perf costs — defensive storage copies, redundant Decimal re-wraps, duplicated per-tick work, and per-tick Bar/MACD churn — with bit-identical values.
**Verified:** 2026-06-11
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | InMemoryPortfolioStateStorage all 5 getters return the live container (no `.copy()`) | ✓ VERIFIED | All 5 getters in `in_memory_storage.py` return `self._X` directly with D-03/D-19 comments; no `.copy()` on any getter return |
| 2 | `snapshot_count()` / `get_latest_snapshot()` exist on the ABC + InMemory and are consumed by `metrics_manager` per-tick path (not `get_snapshots()`) | ✓ VERIFIED | Both accessors exist in `in_memory_storage.py` (lines 105-113) and `base.py` (lines 272-298); `metrics_manager.py` uses `snapshot_count()` for the trim guard and `get_latest_snapshot()` for the latest read; GREEN consumer no-call lock in `test_metrics_manager.py` |
| 3 | `BacktestBarFeed` eager-materializes a `{ticker:{time:Bar}}` map at `__init__`; `current_bars()` is a pure dict lookup with no per-tick `Bar.from_row` | ✓ VERIFIED | `self._prebuilt` dict built in `__init__` loop (lines 180-188); `current_bars()` is a pure `self._prebuilt[ticker].get(time)` dict lookup (lines 318-323); no-call sentinel test GREEN in `test_bar_feed.py` |
| 4 | W1-08 four Decimal re-wraps removed; W1-09 load-time copy dropped | ✓ VERIFIED | `position_manager.py` sums `position.market_value`/`.unrealised_pnl`/`.realised_pnl` directly with W1-08 comments; `csv_store.py` line 169 is `data = raw[expected_cols]` with W1-09 comment |
| 5 | W1-03: `open_position_count` cached once; W1-14: redundant `is_connected` check removed | ✓ VERIFIED | `order_manager.py` lines 934-936 cache `open_count` local before the guard; `simulated.py` shows only the authoritative `is_connected()` call in `validate_order` (line 399), the redundant `_admit_order` check removed |
| 6 | W1-07: `on_fill` non-EXECUTED guard hoisted ABOVE `_operation_context` / correlation-id allocation; W1-13 NOT implemented (descoped — D-10) | ✓ VERIFIED | `portfolio_handler.py` lines 295-301: the `if fill_event.status != FillStatus.EXECUTED: return` appears before the `with self._operation_context` block; no `get_active_portfolios` caching code present |
| 7 | MACD is computed INSIDE the SMA guard in `SMA_MACD_strategy.py` (W1-12); no new SMA_MACD test (D-02) | ✓ VERIFIED | `SMA_MACD_strategy.py` lines 61-73: MACD computation at line 66 is inside `if short_sma.iloc[-1] >= long_sma.iloc[-1]:` with W1-12/D-02 comment; no SMA_MACD test file created/modified |
| 8 | Phase gate: golden master byte-exact (134 trades / final_equity 46189.87730727451); mypy --strict clean; full e2e + unit/integration suite green | ✓ VERIFIED | `pytest tests/integration/test_backtest_oracle.py` — 3 passed; `pytest tests/e2e` — 58 passed; `mypy itrader` — 161 source files, no issues; `pytest -q` — 825 passed |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/storage/in_memory_storage.py` | Copy-free getters + `snapshot_count()`/`get_latest_snapshot()` | ✓ VERIFIED | 5 getters return `self._X`; accessors at lines 105-113 |
| `itrader/portfolio_handler/base.py` | ABC with read-only-view docstrings + `snapshot_count`/`get_latest_snapshot` abstractmethods | ✓ VERIFIED | D-03/D-19 docstrings on all 5 getters; abstractmethods at lines 272-298 |
| `itrader/portfolio_handler/metrics/metrics_manager.py` | Per-tick trim/latest path using count-only/last-only accessors | ✓ VERIFIED | `snapshot_count()` guard at line 174; `get_latest_snapshot()` at line 199 |
| `tests/unit/portfolio/test_state_storage.py` | Object-identity asserts (5 getters) + accessor-behavior asserts | ✓ VERIFIED | 5 `is`-identity tests (lines 150/157/164/171/178) + `test_snapshot_count_and_latest` |
| `tests/unit/portfolio/test_metrics_manager.py` | GREEN consumer-side no-call regression lock | ✓ VERIFIED | `test_trim_uses_snapshot_accessors` exists; monkeypatches `get_snapshots` to raise; asserts `snapshot_count`/`get_latest_snapshot` consumed |
| `itrader/price_handler/feed/bar_feed.py` | Prebuilt `{ticker:{time:Bar}}` map at `__init__`; `current_bars()` dict lookup | ✓ VERIFIED | `self._prebuilt` built at init lines 180-188; dict lookup in `current_bars` lines 318-323 |
| `tests/unit/price/test_bar_feed.py` | No-call `Bar.from_row` sentinel assert for `current_bars()` | ✓ VERIFIED | `test_current_bars_serves_prebuilt_no_from_row_per_tick` at line 229 |
| `itrader/portfolio_handler/position/position_manager.py` | Mark-to-market aggregations without Decimal re-wraps | ✓ VERIFIED | Direct use of `position.market_value`/`.unrealised_pnl`/`.realised_pnl` with W1-08 comments |
| `itrader/portfolio_handler/portfolio_handler.py` | Non-EXECUTED guard hoisted above correlation-id allocation | ✓ VERIFIED | Guard at lines 295-301 precedes `with self._operation_context` at line 303 |
| `tests/unit/portfolio/test_on_fill_status_guard.py` | Non-EXECUTED fill = no-op guard test | ✓ VERIFIED | Existing tests confirm non-EXECUTED fills skip `_operation_context` |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | MACD computed inside SMA guard | ✓ VERIFIED | MACD at line 66, inside `if short_sma.iloc[-1] >= long_sma.iloc[-1]:` guard |
| `.planning/ROADMAP.md` | SC-1 corrected (no `*_snapshot()` variant); SC-2 corrected (no "active-portfolio recompute") | ✓ VERIFIED | `grep "snapshot() variant\|active-portfolio recompute"` returns nothing; SC-1 has D-04 note; SC-2 lacks "active-portfolio recompute" |
| `.planning/REQUIREMENTS.md` | PERF-02 with W1-13 marked descoped (D-10) | ✓ VERIFIED | Line 60: "(W1-13 descoped — D-10)" present; no "active-portfolio recompute" |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `metrics_manager.py` | `in_memory_storage.py` | `snapshot_count()` / `get_latest_snapshot()` calls | ✓ WIRED | Both accessors invoked on per-tick path; `get_snapshots()` blocked via spy in regression test |
| `test_state_storage.py` | `in_memory_storage.py` | `get_X() is get_X()` object-identity assertions | ✓ WIRED | 5 identity tests pass because copies are gone |
| `test_metrics_manager.py` | `metrics_manager.py` | spy/no-call assert on `get_snapshots` | ✓ WIRED | `test_trim_uses_snapshot_accessors` GREEN |
| `bar_feed.py` | `core/bar.py` | `Bar.from_row` called once at `__init__` (prebuild), never in `current_bars` | ✓ WIRED | `grep "Bar.from_row" bar_feed.py` shows call only in init loop |
| `test_bar_feed.py` | `core/bar.py` | `monkeypatch` sentinel on `Bar.from_row` classmethod | ✓ WIRED | Sentinel raises if called per tick; test passes (zero calls) |
| `SMA_MACD_strategy.py` | `tests/integration/test_backtest_oracle.py` | MACD-inside-guard byte-identical proven by oracle | ✓ WIRED | Oracle: 3 passed, exact 134 trades / 46189.87730727451 |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact (134 trades / 46189.87730727451) | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed in 4.95s | ✓ PASS |
| Full e2e suite green | `pytest tests/e2e -q` | 58 passed in 1.29s | ✓ PASS |
| mypy --strict clean | `poetry run mypy itrader` | Success: no issues found in 161 source files | ✓ PASS |
| Full unit+integration suite | `pytest -q` | 825 passed in 11.17s | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PERF-01 | 03-01 | Storage copy-free getters + snapshot accessors | ✓ SATISFIED | 5 getters copy-free; `snapshot_count`/`get_latest_snapshot` on ABC+InMemory; metrics_manager rewired; regression locks GREEN |
| PERF-02 | 03-03 | Decimal re-wraps + duplicated per-tick work eliminated (W1-13 descoped D-10) | ✓ SATISFIED | W1-08/W1-09/W1-03/W1-14/W1-07 all landed; W1-13 explicitly NOT implemented per D-10 |
| PERF-03 | 03-02, 03-04 | MACD inside SMA guard + prebuilt Bar feed | ✓ SATISFIED | `current_bars()` dict lookup; MACD inside guard; no-call sentinel + oracle both green |

---

### Anti-Patterns Found

No TBD/FIXME/XXX markers in any of the 10 modified source files. No stubs. No orphaned artifacts. No unresolved debt markers.

---

### Human Verification Required

None. All must-haves are verified programmatically:
- The byte-exact oracle (134 trades / 46189.87730727451) proves numeric correctness machine-verifiably.
- The behavioral regression-lock tests (identity asserts, no-call sentinels) prove each optimization landed.
- D-02 (no SMA_MACD unit test) is an intentional owner constraint — the oracle is the sole numeric proof, which this verification ran directly.

---

### Gaps Summary

No gaps. All 8 must-have truths verified. All 13 required artifacts exist, are substantive, and are wired. All 3 phase requirements (PERF-01, PERF-02, PERF-03) are satisfied. The four phase-gate checks (oracle, e2e, mypy, full suite) all pass. Locked decisions (D-01 through D-10) are honored — no wall-clock benchmarks, no `*_snapshot()` twin (D-04), no W1-13 cache (D-10), no SMA_MACD test (D-02).

---

_Verified: 2026-06-11_
_Verifier: Claude (gsd-verifier)_
