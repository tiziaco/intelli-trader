---
phase: 01-instrument-value-object
plan: 03
subsystem: verification
tags: [instrument, byte-exact, oracle, golden-master, mypy-strict, determinism, phase-gate]
requires:
  - "itrader.core.instrument.Instrument + quantize(value, Instrument, kind) (plan 01-01)"
  - "itrader.universe.derive_instruments + Universe + SimulatedExchange.resolve_min_order_size (plan 01-02)"
provides:
  - "Verified byte-exact phase gate: INST-01/02/03 accepted (the phase re-baselines nothing)"
affects: []
tech-stack:
  added: []
  patterns:
    - "Verification-only plan: no production code modified; runs the four phase gates and records pass/fail"
key-files:
  created:
    - .planning/phases/01-instrument-value-object/01-03-SUMMARY.md
  modified: []
decisions:
  - "Phase 1 closes byte-exact: the Instrument seam (metadata + precision-read + Universe min_order_size resolution) drifted no leaf — oracle held 134 / 46189.87730727451 with no re-baseline (D-10, D-01a, D-02a)"
metrics:
  duration_minutes: 2
  tasks_completed: 1
  completed_date: 2026-06-15
requirements-completed: [INST-01, INST-02, INST-03]
---

# Phase 1 Plan 03: Byte-Exact Phase Gate Verification Summary

Proved the `[BLOCKING]` byte-exact phase gate for the Instrument Value Object phase:
with plans 01-01 (Instrument + quantize rewire) and 01-02 (Universe wiring +
ExchangeLimits demotion) landed, the full SMA_MACD backtest reproduces the frozen
oracle byte-for-byte (134 trades / `final_equity 46189.87730727451`), `mypy --strict`
is clean, a double-run is byte-identical, and the frozen golden artifacts are
untouched. This plan modified **no production code** — the phase re-baselines nothing.

## What Was Built

**Task 1 — Run the four phase gates + verify golden artifacts unchanged (verification only).**
No files modified. Ran each gate in order and captured pass/fail:

1. **Byte-exact oracle gate** — `poetry run pytest tests/integration/test_backtest_oracle.py -v`:
   3 passed. `test_oracle_behavioral_identity` and `test_oracle_numeric_values`
   both green against the frozen `tests/golden/summary.json`
   (`final_equity 46189.87730727451`, `trade_count 134`) with `check_exact=True`
   (NO tolerance). `test_golden_run_signal_store_is_non_empty_and_queryable` also passed.
2. **mypy --strict** — `poetry run mypy itrader`: `Success: no issues found in 185
   source files`. New `core/instrument.py`, `universe/instruments.py`,
   `universe/universe.py`, the `Universe` class, and all wiring touch points are
   strict-clean.
3. **Determinism** — `poetry run pytest tests/e2e/robust/test_determinism.py -v`:
   9 passed (all `test_double_run_identical` variants — two_tickers, two_strategies,
   fanout_portfolios, contended_cash, sparse_bar, union_window, no_trade, flat,
   losing). No new nondeterminism introduced.
4. **Full suite** — `make test`: 1023 passed. No regression anywhere; no new
   warnings under `filterwarnings=["error"]`.

**Golden artifacts unchanged** — `git status --short tests/golden/` prints nothing;
the full working tree is clean. The gate asserts against
`tests/golden/{trades,equity}.csv` + `summary.json` and none were regenerated or
edited.

## Verification

- `poetry run pytest tests/integration/test_backtest_oracle.py -v` — 3 passed (byte-exact, 134 / 46189.87730727451).
- `poetry run mypy itrader` — Success: no issues found in 185 source files.
- `poetry run pytest tests/e2e/robust/test_determinism.py -v` — 9 passed (double-run identical).
- `make test` — 1023 passed (full suite green, no warnings under filterwarnings=["error"]).
- `git status --short tests/golden/` — empty (frozen golden artifacts unchanged).
- `git status --short` — empty (no production code modified, as the plan mandates).

**Phase-gate truths confirmed (must_haves):**
- The SMA_MACD spot oracle holds byte-for-byte: 134 trades / `final_equity 46189.87730727451` (D-10, D-02a, D-01a).
- BTCUSD took the declared 8dp branch throughout — inference never touched the oracle symbol (D-10); proven by the oracle holding exactly (inference would have drifted it to ~2-4dp).
- BTCUSD resolved `min_order_size` via the venue fallback `ExchangeLimits(0.001)` byte-identical to pre-phase behavior (D-01a — BTCUSD's declared Instrument omits `min_order_size`, so resolution falls through to the venue min).
- mypy --strict clean across itrader.
- Double-run byte-identical (determinism preserved).
- Frozen golden artifacts unchanged by the phase.

## Deviations from Plan

None — plan executed exactly as written. All four gates passed on the first run; no
drift to localize, so the optional `scripts/run_backtest.py` + `jq` diagnostic diff
was not needed.

## Threat Flags

None. Verification-only plan — no code change, no new input/auth/secret/network/
endpoint surface. The threat register's **T-01-G1** (Tampering — golden oracle
integrity / silent re-baseline) is the anti-tampering control this plan implements:
it asserted the oracle byte-exact and verified `tests/golden/` is unmodified,
confirming neither 01-01 nor 01-02 introduced accidental result drift. **T-01-SC**
(supply-chain) — accepted, not applicable (no package installs; pure stdlib).

## Known Stubs

None. This plan adds no code. The INST-03 margin fields on each `Instrument` remain
intentionally inert (declared-but-unconsumed value-object fields for Phase 2
leverage / Phase 4 liquidation / Phase B funding), consistent with plans 01-01 and
01-02 — by design per INST-03, not stubs.

## Commits

- (this SUMMARY + state docs committed in the final metadata commit — no per-task source commit, as the plan modifies no production code)

## Self-Check: PASSED

SUMMARY.md present on disk at the plan directory. No source files created/modified
(verification-only plan), so no created/modified-file existence claims to verify
beyond this SUMMARY. All four gate commands and the `git status` checks were run
live above and recorded.
