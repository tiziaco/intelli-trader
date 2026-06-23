---
phase: 02-order-storage-indexing
verified: 2026-06-23T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 2: Order-Storage Indexing Verification Report

**Phase Goal:** Order-storage queries stop linear-scanning the full flat {id: order} dict, removing the single largest W1 hotspot (~37% CPU) — with the flat dict still the source of truth (D-20) and the interface designed so a future Postgres backend satisfies the same contract.
**Verified:** 2026-06-23
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | get_orders_by_status, by-portfolio, and active queries resolve via derived secondary indexes maintained over the flat dict — no O(all-orders-ever) rescan on the per-bar on_tick / admission / reconcile path | VERIFIED | `get_active_orders(pid)` uses `_active_by_portfolio[pid]` bucket lookup (line 274); `get_orders_by_status(active)` uses `_by_status[status]` membership filter over `_orders()` (line 260); `get_pending_orders(pid)` uses `_active_by_portfolio` bucket (line 180). The None path retains a `_by_id` scan only (no per-bar hot caller). |
| 2 | The flat {id: order} dict remains the source of truth (D-20); the indexes are caches kept consistent on every insert/transition/terminal write | VERIFIED | `self._by_id` declared as `# SOURCE OF TRUTH (D-20)`. `_index_apply` called in `add_order` (line 137) and `update_order` (line 207). `_index_remove` called in `remove_order` (line 150), `remove_orders_by_ticker` (line 168), and `clear_portfolio_orders` (line 227). All 5 write seams covered. `grep -c "_index_apply"` returns 5 (1 def, 1 task-1 apply comment, 2 call sites + 1 in update_order). Shadow registry (`_last_indexed_status`) prevents duplicate/stale entries. |
| 3 | The OrderStorage interface is designed for extension so a future Postgres backend satisfies the same contract (no in-memory-only assumptions leak into the seam) | VERIFIED | `OrderStorage` ABC in `itrader/order_handler/base.py` is unchanged (0 diff in git log across all phase-2 commits). D-05a seam-audit comment present at lines 232-239 of `in_memory_storage.py`: "every ABC method is SQL-expressible by a future PostgreSQLOrderStorage — insertion order maps to `ORDER BY created_at, id`...". |
| 4 | Gate (a): the byte-exact SMA_MACD oracle is green (134 / 46189.87730727451); mypy --strict clean; determinism double-run byte-identical | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3/3 passed. `poetry run mypy --strict itrader` → "Success: no issues found in 187 source files". `poetry run pytest tests/e2e/robust/test_determinism.py -q` → 9/9 passed. WR-01 fix (commit 6a4cc90) ensures `get_orders_by_status(PARTIALLY_FILLED)` yields add-order not transition-order, preserving byte-equivalence. |
| 5 | Gate (b): the clean W1 benchmark shows a measurable wall-clock improvement vs the Phase 1 re-frozen baseline, re-frozen as the new locked reference | VERIFIED | `W1-BASELINE.json` shows `wall_clock_s: 199.4` (Phase-1 reference preserved as `W1-BASELINE-phase1.json` at `wall_clock_s: 247.5`). Delta = −19.4% on the re-freeze run, −21.6% on the --check run. Threshold was ≥5%; margin is large. Both baseline files are git-tracked (`git check-ignore` exits 1 = no ignore match). Committed in `6cac08b`. |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/order_handler/storage/in_memory_storage.py` | `_active_by_portfolio`, `_by_status`, `_last_indexed_status` indexes + `_index_apply`/`_index_remove` + rerouted active queries | VERIFIED | All three caches present in `__init__`. `_index_apply` and `_index_remove` defined and wired at all 5 write seams. `get_active_orders`, `get_pending_orders`, `get_orders_by_status`(active), `remove_orders_by_ticker`, `clear_portfolio_orders` rerouted. `grep -c "_index_apply"` = 5. |
| `tests/unit/order/test_order_storage.py` | D-09 equivalence test + maintenance-matrix coverage | VERIFIED | 27 tests collected and all green. `-k equivalence` selects 2 tests (`test_active_queries_match_full_scan_equivalence` + `test_partially_filled_status_query_preserves_add_order_equivalence`), both pass. Maintenance-matrix tests present: `test_filled_via_update_drops_from_active_index_terminal_fallback`, `test_remove_orders_by_ticker_keeps_indexes_consistent`, `test_clear_portfolio_orders_keeps_indexes_consistent`, `test_re_add_order_is_idempotent`. |
| `perf/results/W1-BASELINE.json` | Re-frozen at new faster wall_clock_s with intact oracle stamp | VERIFIED | `wall_clock_s: 199.4`, `final_equity: "46189.87730727451"`, `trade_count: 134`, `green_at_freeze: true`. File is git-tracked. |
| `perf/results/W1-BASELINE-phase1.json` | Prior 247.5s reference preserved for auditability | VERIFIED | `wall_clock_s: 247.5`, same oracle stamp, git-tracked. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `in_memory_storage.py::add_order` | `_index_apply` (diff-on-write) | `self._index_apply(order)` after `_by_id[order.id] = order` | WIRED | Line 136-137: truth-dict write followed immediately by index reconcile. |
| `in_memory_storage.py::update_order` | `_index_apply` (diff-on-write) | `self._index_apply(order)` on success branch | WIRED | Lines 205-207: guarded by `if order.id in self._by_id`, index only touched on success. |
| `in_memory_storage.py::remove_order` / `remove_orders_by_ticker` / `clear_portfolio_orders` | `_index_remove` | Called after each `del _by_id[oid]` | WIRED | Lines 150, 168, 227: every delete path paired with `_index_remove`. |
| `in_memory_storage.py::get_active_orders` | `_active_by_portfolio` | Bucket lookup for concrete pid; `_by_id` scan-fallback for None | WIRED | Lines 273-275: `if portfolio_id is not None` → bucket; else → `_by_id.values()` filtered by `_ACTIVE_STATUSES`. |
| `in_memory_storage.py::get_orders_by_status` (active branch) | `_by_status` | Membership filter; yields in `_orders()` add-order | WIRED | Lines 258-260: `if status in _ACTIVE_STATUSES`: bucket = `_by_status.get(status, {})`; returns `[order for order in self._orders(portfolio_id) if order.id in bucket]`. WR-01 fix confirmed at commit 6a4cc90. |
| `make perf-baseline` | `perf/results/W1-BASELINE.json` | `run_w1_benchmark --baseline-out` | WIRED | File exists at new wall_clock_s 199.4 as committed in 6cac08b. |

---

### Data-Flow Trace (Level 4)

Not applicable for this phase — the phase delivers a storage data-structure optimization, not a UI component rendering dynamic data. The behavioral equivalence is verified by the D-09 regression tests and the byte-exact oracle rather than a data-flow trace.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full storage test suite (27 tests) | `poetry run pytest tests/unit/order/test_order_storage.py -q` | 27 passed in 0.10s | PASS |
| D-09 equivalence tests | `poetry run pytest tests/unit/order/test_order_storage.py -k equivalence -q` | 2 passed (both paths) | PASS |
| WR-01 regression test (PARTIALLY_FILLED byte-equivalence) | `poetry run pytest tests/unit/order/test_order_storage.py -k partially_filled -q` | 1 passed | PASS |
| SMA_MACD byte-exact oracle | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed — 134 trades / 46189.87730727451 | PASS |
| Determinism double-run | `poetry run pytest tests/e2e/robust/test_determinism.py -q` | 9 passed | PASS |
| mypy --strict | `poetry run mypy --strict itrader` | Success: no issues found in 187 source files | PASS |

---

### Probe Execution

No probe scripts declared for this phase. Gate (a) is verified by the pytest commands above.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PERF-01 | 02-01, 02-02 | Order-storage queries no longer linear-scan the full flat dict — derived secondary indexes maintained over the dict, which stays the source of truth (D-20). OrderStorage interface designed for extension. | SATISFIED | `_active_by_portfolio` + `_by_status` indexes present and wired. ABC unchanged. D-05a seam-audit comment present. Gate (a) oracle/mypy/determinism all green. Gate (b): −19.4% wall-clock measured vs 247.5s baseline; W1-BASELINE.json re-frozen at 199.4s. REQUIREMENTS.md marks PERF-01 Complete, Phase 2. |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `in_memory_storage.py` | 161, 179, 222, 273 | `# type: ignore[arg-type]` on `_active_by_portfolio.get(portfolio_id, {})` where `portfolio_id: IdLike` | INFO | WR-02 from code review: latent `IdLike` vs native-UUID type divergence. Production callers always pass `PortfolioId` (UUID), so the ignore is safe. Accepted as-is in REVIEW.md resolution. Not a correctness defect. |
| `in_memory_storage.py` | 103-108 | `_index_remove` docstring says "active-only memory posture" — but `_last_indexed_status` also tracks terminal orders | INFO | IN-01 from code review: misleading docstring for the registry. Accepted as informational in REVIEW.md. No correctness impact. |

No TBD / FIXME / XXX markers found in modified files. No unreferenced debt markers. No stub implementations.

---

### Code Review WR-01 Fix Confirmation

The code review identified WR-01: `get_orders_by_status(PARTIALLY_FILLED)` returned results in status-transition order instead of add-order, violating the D-06/D-08/D-09 byte-equivalence contract. This was fixed in commit `6a4cc90`:

- Implementation: `get_orders_by_status` active branch now uses `_by_status` only as a membership filter, yielding in `_orders(portfolio_id)` add-order (line 260). WR-01 + WR-02 note are present in the method docstring at lines 248-256.
- Regression test: `test_partially_filled_status_query_preserves_add_order_equivalence` added (commit 6a4cc90), verified to pass at HEAD (1/1 green). The test directly reproduces the divergence scenario (order2 added second transitions to PARTIALLY_FILLED before order1) and asserts add-order is returned.
- Oracle impact: Gate (a) oracle passes 3/3 byte-exact — the fix did not disturb the oracle stamp.

### Human Verification Required

None. All must-haves are verifiable programmatically. Gate (b) was a human-gated measurement checkpoint at execution time (Plan 02-02 Task 1 required a human to read the printed Delta); the re-frozen `W1-BASELINE.json` and preserved `W1-BASELINE-phase1.json` are the auditable artifacts of that human gate.

---

## Gaps Summary

No gaps. All five success criteria are verified against the live codebase:

1. Active queries route through indexes (not flat-scan) for every hot-path method.
2. `_by_id` remains the sole source of truth; indexes are maintained at all 5 write seams.
3. `OrderStorage` ABC unchanged; D-05a SQL-expressibility seam audit recorded in-code.
4. Gate (a): oracle 3/3 byte-exact, mypy clean over 187 files, determinism 9/9. WR-01 fix (6a4cc90) ensures byte-equivalence holds on PARTIALLY_FILLED, proven by a new regression test.
5. Gate (b): −19.4% wall-clock improvement measured and re-frozen. `W1-BASELINE.json` locked at 199.4s as Phase 3's reference.

PERF-01 is complete. Phase 3 may proceed.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
