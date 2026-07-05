---
phase: quick-260705-fqe
plan: 01
subsystem: tests/e2e (OKX sandbox reconciliation)
tags: [test-only, okx, live-sandbox, recon, D-20, RECON-01, RECON-03]
requires: [RECON-01, RECON-03, D-20]
provides:
  - "TEST-ONLY venue-position seed helper (_seed_believed_position_to_venue)"
  - "delta-based settlement assertions in _assert_settlement"
affects:
  - tests/e2e/test_okx_sandbox_recon.py
key-files:
  created: []
  modified:
    - tests/e2e/test_okx_sandbox_recon.py
decisions:
  - "Position DELTA (pos.net_quantity - position_before) is the settlement assertion, not the absolute post-fill net_quantity — the online proof runs on a NON-FLAT OKX EEA demo account."
  - "Seed reads the live venue BTC balance READ-ONLY via a throwaway sandbox connector (system connector not yet connected pre-start); set_position is cash-neutral (D-06), so cash_before is unaffected."
metrics:
  duration: ~4min
  completed: 2026-07-05
---

# Quick Task 260705-fqe: Adapt e2e OKX sandbox recon test to run on a non-flat demo account

## One-liner

Made the two online start()-driven OKX-demo settlement tests reach `RUNNING` on the only demo
account available (non-flat, EEA/MiCA can't sell flat) by seeding the engine's believed BTC/USDC
position to the live venue balance before `start()`, and switched `_assert_settlement` to assert
the BUY's position DELTA instead of the absolute post-fill quantity.

## What changed

**File touched (ONLY):** `tests/e2e/test_okx_sandbox_recon.py`

### Task 1 — venue-position seed helper (commit 9b79681c)
- Added module-level `_seed_believed_position_to_venue(system, portfolio_id)` after
  `_build_demo_connector`. All imports LAZY (inside the body): `datetime`, `uuid_utils.compat`,
  `TransactionType`, `TransactionId`, `to_money`, `Position`, `Transaction`.
- Reads the live venue BTC balance READ-ONLY via a throwaway sandbox connector
  (`_build_demo_connector()`), reading `bal["total"]["BTC"]`, disconnect in a `finally`
  (clean teardown under `filterwarnings=["error"]`).
- `base_raw is None` OR `to_money(str(base_raw)) == 0` → returns `Decimal("0")` (flat account,
  seed is a no-op — original flat-start path intact).
- Otherwise constructs a `Transaction(BUY, BTC/USDC, venue_qty)` (Decimal edge via `to_money`,
  never `Decimal(float)`), `Position.open_position(txn)`, and
  `portfolio.position_manager._storage.set_position(_OKX_SYMBOL, position)` (pure dict write,
  cash-neutral per D-06). Returns `venue_qty`.
- Wired the seed into BOTH start()-driven tests immediately AFTER `_assert_sandbox_routed(system)`
  and BEFORE `system.start()`: `test_demo_order_produces_real_fill_event` and
  `test_venue_account_reconciles_post_fill_within_tolerance`. Test (iii)
  `test_restart_rehydrate_then_venue_reconcile_no_spurious_halt` UNTOUCHED (never calls `start()`).

### Task 2 — delta-based settlement assertions (commit f2070431)
- `_assert_settlement` signature gained `position_before` (now
  `(system, portfolio_id, order, emitted, cash_before, position_before)`).
- Replaced the three absolute position assertions with DELTA assertions on
  `delta_qty = pos.net_quantity - position_before`: `delta_qty > 0`, `delta_qty <= filled_qty`,
  `delta_qty >= filled_qty * (1 - _SETTLE_QTY_FEE_BAND)`. Failure-message style preserved.
- CASH / STATUS-not-HALTED / spot `fetch_positions()==[]` assertions left UNCHANGED (cash is
  already a delta and `cash_before` is snapshotted after the cash-neutral seed).
- Returned dict gained `position_before` and `position_delta` (ARCH-3 capture records the delta).
- `test_demo_order_produces_real_fill_event` snapshots `position_before` alongside `cash_before`
  after `start()` and passes it to `_assert_settlement`.
- ARCH-3 Wave-1 capture prints `position_before` (seeded baseline) and `position_delta`
  (fill-induced).

## Deviations from Plan

None — plan executed exactly as written. No production (`itrader/`) source was modified.

## Verification (OFFLINE only — the live `-m live` credential-gated test was NOT run)

**1. AST parse:**
```
PARSE OK
```

**2. Credential-free collect-only:**
```
============================= test session starts ==============================
platform darwin -- Python 3.13.1, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/tizianoiacovelli/Desktop/projects/intelli-trader
configfile: pyproject.toml
plugins: cov-7.1.0, asyncio-1.4.0, metadata-3.1.1, html-4.2.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 3 items

<Dir intelli-trader>
  <Dir tests>
    <Package e2e>
      <Module test_okx_sandbox_recon.py>
        <Function test_demo_order_produces_real_fill_event>
        <Function test_venue_account_reconciles_post_fill_within_tolerance>
        <Function test_restart_rehydrate_then_venue_reconcile_no_spurious_halt>

========================== 3 tests collected in 0.03s ==========================
```

Module parses clean and COLLECTS credential-free (lazy imports keep collection network-free; the
module-level `skipif` keeps it from running without demo creds). The online GREEN gate remains
human-triggered (`-m live`).

## Commits

- `9b79681c` — test(quick-260705-fqe): seed believed venue position before start() in online recon tests
- `f2070431` — test(quick-260705-fqe): assert BUY position DELTA in _assert_settlement for non-flat demo

## Self-Check: PASSED
- `tests/e2e/test_okx_sandbox_recon.py` modified (only file) — FOUND
- Commit 9b79681c — FOUND
- Commit f2070431 — FOUND
- `_seed_believed_position_to_venue` helper present, lazy imports, cash-neutral seed — FOUND
- `position_before` threaded through `_assert_settlement`, delta assertions in place — FOUND
- Offline parse + collect-only both green — PASSED
