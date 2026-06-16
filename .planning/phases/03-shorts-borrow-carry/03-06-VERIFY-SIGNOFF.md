# Phase 3 Gate — Owner-Gated Parked-Scenario Sign-Off (03-06-T3, D-10)

**Status: APPROVED by the owner ("approved") — 2026-06-15**

This is the VERIFY note for the Phase-3 (`03-shorts-borrow-carry`) phase gate. It records the
owner's explicit sign-off that the three PARKED e2e short scenarios are hand-verified and approved,
that **NOTHING was `--freeze`d**, and that the accounting-core golden re-baseline stays the single
owner-gated freeze deferred to **Phase 4 / XVAL-01** (cross-validation + owner sign-off).

This is a **PARKED** sign-off, NOT a frozen golden. The scenarios assert HAND-COMPUTED literals on
the engine's real `SIGNAL → ORDER → FILL → PORTFOLIO` path; they do not use the golden-diff harness
and no new artifact was written under `tests/golden/`.

## What the owner signed off

The Phase-3 shorts + borrow-carry feature, default-off and oracle-dark:

- **SHORT-01** — two-flag short registration (`allow_short_selling` AND `enable_margin`).
- **SHORT-02** — side-agnostic BUY-to-cover arm + clamp-to-flat (the cover dispatches on `side`,
  never on a sign of the unsigned read-model magnitude); closes the `SHORT_ONLY` cover-arm hole
  (CR-01, surfaced at v1.0 Phase 7 / 07-REVIEW).
- **SHORT-03** — first-class short realised PnL = `|size| × (entry − exit) − commissions`.
- **CARRY-01** — per-bar `BORROW_INTEREST` carry accrual on held shorts.
- **D-09** — the FRAGILE margin/settlement seam hardened ONCE: WR-01 settlement-side solvency
  assertion, WR-03 lock/release symmetry, WR-05 per-lock open-commission accumulator, WR-02
  universe-unwired `StateError` (not a bare `AttributeError`) at the `maintenance_margin` AND carry
  read sites. The CR-02-residual over-close guard is KEPT (defense-in-depth).

## Parked e2e scenarios (PARKED, NOT `--freeze`d — D-10)

| Scenario | Path | Proves |
|----------|------|--------|
| Pure short round-trip | `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py` | SELL-to-open → BUY-to-cover; realised short PnL settled; margin lock released (SHORT-02/03) |
| Short-with-carry | `tests/e2e/short_carry/test_short_carry_scenario.py` | multi-bar held short; per-bar `BORROW_INTEREST` debits; equity = PnL − Σ carry; determinism double-run byte-identical (CARRY-01) |
| Partial cover | `tests/e2e/partial_cover/test_partial_cover_scenario.py` | BUY-cover with `exit_fraction < 1` reduces (not closes) the short; remainder carries on (SHORT-02) |

Each drives the REAL run path with a SYNTHETIC instrument (e.g. `SHORTUSD` — **never BTCUSD**; the
only `BTCUSD` tokens in the files are the "NEVER BTCUSD" docstring negations) and asserts on the
live read-model + cash/position state with every number a hand-computed literal with the arithmetic
shown inline.

## Gate evidence (verified before sign-off)

- **Byte-exact spot oracle held:** `make test-integration` → **134 trades / `46189.87730727451`**
  (SMA_MACD; shorts-off / carry-off defaults — all Phase-3 changes oracle-dark).
- **Full suite green:** `make test` (filterwarnings=["error"], strict markers/config) — no failures,
  no warnings-as-errors.
- **`mypy --strict` clean** across `itrader`.
- **Determinism double-run** on the carry scenario byte-identical (carry amounts + timestamps; no
  wall clock — reuse the seeded RNG + injected `BacktestClock`).
- **NOTHING `--freeze`d:** no new golden artifact under `tests/golden/`; working tree clean of any
  golden-write.

## Re-baseline disposition (LOCKED)

Phase 3 freezes **NO** new golden. The accounting-core re-baseline (margin P2 + shorts P3 +
liquidation P4) remains the **single owner-gated freeze at Phase 4 / XVAL-01**, gated by external
cross-validation (`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123) + explicit owner sign-off with
full attribution. Freezing a Phase-3 short golden now would corrupt that single re-baseline's
attribution (threat T-03-18) — so it is deliberately deferred.

## Task commits this sign-off closes

- `88af0c7` — WR-01/02/03/05 margin-seam hardening (D-09), CR-02 guard intact, oracle-dark.
- `d6ed565` — three parked e2e short scenarios + `SHORT_ONLY` cover-gate fix (D-10).

---
*Phase: 03-shorts-borrow-carry — Plan 06, Task 3 (owner-gated human-verify checkpoint)*
*Owner response: "approved" — 2026-06-15*
