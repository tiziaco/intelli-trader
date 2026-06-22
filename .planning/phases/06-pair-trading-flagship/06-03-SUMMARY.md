---
phase: 06
plan: 03
subsystem: strategy_handler
tags: [pair-trading, dispatch, exit-safety, wave-2, PAIR-01]
requires:
  - "itrader/strategy_handler/pair_base.py::PairStrategy (Plan 06-01 — evaluate_pair seam, _entry explicit-quantity constructor)"
  - "itrader/strategy_handler/strategies_handler.py::_dispatch_pair (Plan 06-01 — two-leg dispatch branch + _emit_intent)"
  - "itrader/order_handler/admission/admission_manager.py (side-agnostic reduction :784, SHORT_ONLY direction gate :441)"
  - "itrader/order_handler/sizing_resolver.py::resolve_exit (clamp-to-flat :147-186)"
provides:
  - "tests/unit/strategy/test_pair_dispatch.py — dispatch contract lock (both-legs emit, both-present guard, β-weighted + LONG_SHORT)"
  - "tests/integration/test_pair_exit_safety.py — live D-12 close-only / safe-when-flat exit proof"
  - "tests/integration/pair_exit_safety/bars.csv — synthetic flat-OHLC fixture (oracle protected)"
affects: []
tech-stack:
  added: []
  patterns:
    - "Module-local _StubPair(PairStrategy) returning a FIXED β-weighted entry pair — exercises the dispatch contract independent of the concrete ETH/BTC strategy (parallel-safe)"
    - "SHORT_ONLY synthetic-ticker scenario mirroring partial_cover wiring — proves the engine-level safe-when-flat no-op via a REJECTED flat-state cover"
key-files:
  created:
    - "tests/integration/pair_exit_safety/bars.csv"
  modified:
    - "tests/unit/strategy/test_pair_dispatch.py"
    - "tests/integration/test_pair_exit_safety.py"
decisions:
  - "Dispatch tests use a tiny _StubPair with no β/z math (Plan 06-02 owns that), so this plan ran in parallel with the reference-strategy plan against the fixed 06-01 contracts"
  - "The D-12 safe-when-flat no-op is proven at the ENGINE level: the flat-state quantity-free cover is REJECTED at the SHORT_ONLY direction gate (admission:441), not silently dropped — asserted on the order mirror"
  - "Synthetic ticker PXSAFEUSD (never BTCUSD) + a local flat-OHLC bars.csv protect the SMA_MACD oracle (byte-exact, untouched)"
metrics:
  duration: ~12 min
  completed: 2026-06-22
---

# Phase 6 Plan 03: Pair Dispatch + D-12 Exit-Safety Tests Summary

Locked the two engine contracts the pair-trading flagship depends on — the
two-leg dispatch fan-out (D-01/D-02/D-08/D-14) and the quantity-free close-only /
safe-when-flat exit (D-12 / 06-RESEARCH Pitfall 1) — with tests that exercise the
real engine paths via a tiny test-local `_StubPair` and a SHORT_ONLY synthetic-ticker
scenario, NOT the concrete ETH/BTC strategy (so this plan ran in parallel with
06-02). SMA_MACD oracle byte-exact (134 / 46189.87730727451); `mypy --strict` clean.

## What Was Built

### Task 1 — dispatch contract unit tests (`test_pair_dispatch.py`, 4 spaces) — commit 14c2c52
- `_StubPair(PairStrategy)`: declares the pair contract (`tickers=["ETHUSD","BTCUSD"]`,
  `z_lookback`/`beta_warmup`/`max_window`, a `FixedQuantity` sizing policy) and
  `evaluate_pair` ignores the windows, returning a FIXED β-weighted entry pair via the
  base's `_entry` constructor: SELL N=3 of the rich leg, BUY β·N=6 of the cheap leg.
  No β/z statsmodels math — the dispatch contract is exercised in isolation.
- `_StubFeed.window(...)` returns a frame longer than `beta_warmup + z_lookback` so the
  warmup short-circuit clears and `evaluate_pair` is reached.
- `test_both_legs_emit_once_per_tick` (`-k both_legs`): both legs present → EXACTLY 2
  SignalEvents, one per leg ticker (D-01).
- `test_both_present_guard_skips_when_one_absent` (`-k both_present`): a BarEvent missing
  one leg's bar → ZERO SignalEvents (D-02 — skip silently, no forward-fill).
- `test_beta_weighted_leg_quantities` (`-k beta_weighted`): the two SignalEvents carry
  quantities N vs β·N, `direction is LONG_SHORT` on EACH (D-14), SELL on the rich leg /
  BUY on the cheap leg (D-08), both MARKET entries.
- Handler built with `allow_short_selling=True, enable_margin=True` so `add_strategy`
  admits the LONG_SHORT pair strategy (T-06-10 — else the registration gate raises).

### Task 2 — D-12 exit-safety integration test (`test_pair_exit_safety.py`, 4 spaces) — commit d80e30d
- `_CloseOnlyShortStrategy` (SHORT_ONLY, synthetic ticker `PXSAFEUSD`, NEVER BTCUSD):
  SELL-to-open a short on 2020-01-02, a quantity-free `exit_fraction=Decimal("1")` full
  cover on 2020-01-04 (closes to flat), then ANOTHER quantity-free `exit_fraction=1`
  cover on 2020-01-06 while ALREADY FLAT. Every exit is quantity-free — the safe
  close-only path; the explicit-quantity hazard (Pitfall 1) is never emitted.
- Wiring mirrors the `partial_cover` e2e (BacktestTradingSystem + csv_paths; both
  short/margin flags set on the handler, the portfolio `trading_rules`, the
  admission_manager and the order_validator); a local flat-OHLC `bars.csv` fixture +
  a synthetic `Instrument` keep the SMA_MACD oracle untouched.
- Asserts: (1) the SELL-to-open opens SHORT 10; (2) the quantity-free cover clamps the
  short to flat (net 0, 1 closed position — `resolve_exit` D-07 no-op returns the full
  magnitude); (3) the flat-state quantity-free close opens NO position; (4) order-level
  proof of the loud no-op — exactly 3 orders, 2 FILLED (open + cover) and 1 REJECTED
  (the flat-state cover, rejected at the SHORT_ONLY direction gate, admission:441).

## Verification Results

- `poetry run pytest tests/unit/strategy/test_pair_dispatch.py -q` — 3 passed.
- `poetry run pytest tests/integration/test_pair_exit_safety.py -q` — 1 passed.
- `poetry run pytest tests/unit/strategy/test_pair_dispatch.py
  tests/integration/test_pair_exit_safety.py tests/integration/test_backtest_oracle.py -q`
  — 7 passed (oracle byte-exact: 134 trades / final_equity 46189.87730727451, untouched).
- `poetry run mypy` — Success: no issues found in 164 source files (strict; no itrader
  source touched this plan).
- Indentation: both test files 4 spaces (no tab lines). Oracle protected — no BTCUSD
  short, no `tests/golden/{trades,equity}.csv` writes.
- Live engine trace confirmed: the flat-state cover produces a REJECTED order with
  "direction violation: SHORT_ONLY strategy cannot open a long (BUY with no open short)"
  — the D-12 safe-when-flat no-op is engine-enforced, not test-asserted in a vacuum.

## Deviations from Plan

None — plan executed exactly as written. Two additions strengthen the tests without
changing scope: (1) Task 1 asserts both legs are MARKET entries (a natural consequence
of the `_entry` constructor); (2) Task 2 adds an order-mirror assertion (3 orders, 2
FILLED + 1 REJECTED) so the flat-state no-op is proven LOUD (rejected), guarding against
a false-positive pass where no signal fired at all.

## Authentication Gates

None.

## Known Stubs

None. Both Wave-0 collectible stubs in scope (`test_pair_dispatch.py` 3 functions,
`test_pair_exit_safety.py::test_close_only_exit_noop_when_flat`) are now fully
implemented and GREEN. The Wave-0 `pytest.skip` bodies were replaced with real tests
using the exact pinned function names so the 06-VALIDATION.md `-k` selectors still match.

## Threat Flags

None — this plan adds only tests + a fixture CSV; no new network/auth/file/schema
surface. The threat register dispositions (T-06-08/09/10) are mitigated by the two
tests as planned.

## Self-Check: PASSED

- FOUND: tests/unit/strategy/test_pair_dispatch.py
- FOUND: tests/integration/test_pair_exit_safety.py
- FOUND: tests/integration/pair_exit_safety/bars.csv
- FOUND commit 14c2c52 (Task 1), d80e30d (Task 2)
