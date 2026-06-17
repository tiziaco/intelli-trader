---
phase: 05-engine-native-trailing-stops
plan: 03
subsystem: order-domain
tags: [trailing-stop, bracket, fill-anchored, e2e, ratchet, TRAIL-01, TRAIL-02]

# Dependency graph
requires:
  - phase: 05-engine-native-trailing-stops
    plan: 01
    provides: OrderType.TRAILING_STOP, TrailType, Order.new_trailing_stop_order, OrderEvent trail carriage, D-TRAIL-7 validation
  - phase: 05-engine-native-trailing-stops
    plan: 02
    provides: MatchingEngine TRAILING_STOP ratchet core (side-table, gap-aware fill, OCO); order.price = HWM/LWM anchor
  - phase: 05-engine-native-trailing-stops
    plan: 00
    provides: collectible pytest.skip bracket + e2e long/short stubs (turned GREEN here)
provides:
  - PercentFromFill optional trail_type/trail_value (declares a trailing SL leg, D-TRAIL-5 EITHER/OR)
  - BracketManager fill-anchored trailing-SL child via Order.new_trailing_stop_order (D-TRAIL-3 entry-fill seed)
  - _PendingBracket carries trail_type/trail_value across the arm->fill round-trip
  - fee/slippage model _KNOWN_ORDER_TYPES accept trailing_stop (triggered TRAILING_STOP fills/fees like a STOP)
  - GREEN end-to-end long+short trailing scenarios through the full run path (ratcheted-exit assertions, determinism)
affects: [05-04, trailing-stop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Trailing SL declared via the existing PercentFromFill fill-anchored carve-out (a trailing SL has no static price at declaration, so it rides the fill-anchored arm naturally)"
    - "Trailing child price = the ENTRY FILL anchor (the engine's _seed_trail reads order.price as the HWM/LWM seed, NOT the initial stop — 05-02 decision)"
    - "TrailType imported under TYPE_CHECKING in core/sizing.py and order-domain bracket_book.py (config-enum exception — keep the core->config dependency direction, no runtime config import)"

key-files:
  created:
    - tests/e2e/trailing_long/bars.csv
    - tests/e2e/trailing_short/bars.csv
  modified:
    - itrader/core/sizing.py
    - itrader/order_handler/brackets/bracket_manager.py
    - itrader/order_handler/brackets/bracket_book.py
    - itrader/execution_handler/slippage_model/base.py
    - itrader/execution_handler/fee_model/base.py
    - tests/unit/order/test_trailing_bracket.py
    - tests/e2e/trailing_long/test_trailing_long_scenario.py
    - tests/e2e/trailing_short/test_trailing_short_scenario.py

decisions:
  - "Trailing intent expressed by extending PercentFromFill with optional trail_type/trail_value (all-or-nothing) rather than a new SLTPPolicy variant — minimal, no SLTPPolicy union change, no new assert_never arm, and it rides the existing fill-anchored carve-out exactly (the plan's recommended A2 path). is_trailing property gates the trailing branch."
  - "The trailing child's `price` is the ENTRY FILL price (anchor), NOT the computed initial stop — honoring the 05-02 decision that MatchingEngine._seed_trail reads order.price as the HWM/LWM seed and computes the initial stop from it. The anchor is a positive price so BOTH dual-layer positive-price gates pass, and D-TRAIL-7 gates trail_value < anchor for the PRICE type (continuity)."
  - "TP-limit leg unchanged (D-TRAIL-5 EITHER fixed-SL OR trailing-SL): the trailing SL REPLACES the fixed STOP leg only; the LIMIT TP and OCO linkage are byte-identical to a non-trailing PercentFromFill bracket."

metrics:
  duration: ~25min
  completed: 2026-06-17
---

# Phase 05 Plan 03: Trailing-SL Bracket Declaration + End-to-End Long/Short Summary

**A strategy can now DECLARE a trailing stop end-to-end: a `PercentFromFill` carrying a trail descriptor builds its SL leg as an engine-native `TRAILING_STOP` seeded from the ENTRY FILL price (D-TRAIL-3, the engine's HWM/LWM anchor), replacing the fixed STOP leg (D-TRAIL-5) while the TP-limit and OCO linkage stay unchanged — proven through the full run path by GREEN long AND short e2e scenarios that ratchet favorably-only and trigger at the RATCHETED level (long 135 vs seed 90, short 55 vs seed 110), beating the initial-stop exit; the order handler declares + reconciles but NEVER matches (D-18); mypy --strict clean; SMA_MACD oracle byte-exact.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-17
- **Tasks:** 2 (both TDD)
- **Files:** 2 created, 8 modified

## Accomplishments

- **`PercentFromFill` trail descriptor** (`core/sizing.py`, 4-space) — optional `trail_type`/`trail_value`, all-or-nothing (`__post_init__` raises `SizingPolicyViolation` on a half-set descriptor; `trail_value` must be positive). New `is_trailing` property. Both default `None` so every non-trailing `PercentFromFill` is byte-identical (oracle-dark). `TrailType` imported under `TYPE_CHECKING` (config-enum exception — no runtime config import that would invert the core->config layering).
- **`_PendingBracket` trail carriage** (`bracket_book.py`, TAB) — `trail_type`/`trail_value` survive the arm->fill round-trip so the fill-anchored SL child can be declared as a trailing stop. `TrailType` under `TYPE_CHECKING`.
- **Fill-anchored trailing-SL declaration** (`bracket_manager.py`, TAB) — `_create_fill_anchored_children` branches: when the pending bracket carries a trail descriptor, the SL child is built via `Order.new_trailing_stop_order(...)` with `price = anchor` (the entry fill, the engine's seed) and the trail descriptor attached; otherwise the fixed `new_stop_order` path (untouched). The arm site copies the policy's trail fields into `_PendingBracket`. The TP-limit leg and `parent_order_id`/`child_order_ids` linkage are unchanged (D-TRAIL-5). No matching added (D-18 / T-05-07).
- **2 GREEN bracket unit tests** (`test_trailing_bracket.py`) — long + short: the SL child is a `TRAILING_STOP` priced at the entry fill (102 long / 98 short) with the trail descriptor; the TP is an unchanged LIMIT; two-directional linkage verified.
- **2 GREEN e2e scenarios** (long + short) driving the full `TradingSystem` run path (signal -> trailing bracket declaration -> resting -> ratchet -> fill -> mirror reconcile), each with a determinism sibling test. Synthetic tickers (`TRAILUSD`/`TRAILSHORTUSD` — NEVER BTCUSD).

## E2E Ratchet Proof (TRAIL-01/TRAIL-02)

Both scenarios prove the ratchet earned a strictly better exit than a fixed initial stop:

| Scenario | Entry fill | Seed stop | Ratcheted exit | Realised PnL | Initial-stop PnL (counterfactual) |
|----------|-----------|-----------|----------------|--------------|-----------------------------------|
| long  | 100 | 90  | **135** (HWM 150 × 0.90) | **+350** | −100 |
| short | 100 | 110 | **55** (LWM 50 × 1.10) | **+450** | −100 |

The trailing stop ratchets favorably-only off CLOSED-bar extremes and is live for the NEXT bar (D-TRAIL-2 look-ahead safety, owned in the execution layer). Note the one-bar arming delay: the SL child is created at the parent's fill and submitted AFTER that bar's matching pass, so its first ratchet step is on the following bar (documented inline in both scenario docstrings).

## Task Commits

1. **Task 1 RED: failing trailing-SL bracket tests + PercentFromFill trail fields** - `1d878b5` (test)
2. **Task 1 GREEN: fill-anchored trailing-SL bracket declaration** - `45352dd` (feat)
3. **Task 2: long+short e2e scenarios + fee/slippage trailing_stop fix** - `272d0bc` (test)

## Decisions Made

- **Trailing intent = extended `PercentFromFill`, not a new SLTPPolicy variant.** Minimal, no SLTPPolicy union change (so no new `assert_never` arm needed in the `_assemble_bracket_and_emit` match), and it rides the existing fill-anchored carve-out exactly — the plan's recommended A2 path. A trailing SL has no static price at declaration, so the fill-anchored arm naturally supplies the entry fill price for the D-TRAIL-3 seed.
- **Trailing child `price` = entry fill anchor (NOT the computed initial stop).** Honors the load-bearing 05-02 decision: `MatchingEngine._seed_trail` reads `order.price` as the HWM/LWM seed and computes the initial stop from it. The anchor is a positive price so both dual-layer positive-price gates pass; D-TRAIL-7 gates `trail_value < anchor` for the PRICE type. (The literal plan text said "pass the computed initial stop as price" — the prior-wave context and 05-02-SUMMARY override this in favor of the anchor, which is the internally-consistent reading.)
- **D-TRAIL-5 EITHER/OR realized as a branch in `_create_fill_anchored_children`**: the trailing SL replaces the fixed STOP leg only; the TP-limit and OCO linkage are byte-identical to a non-trailing bracket.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking: TRAILING_STOP rejected at the fee/slippage model boundary] Added trailing_stop to _KNOWN_ORDER_TYPES**
- **Found during:** Task 2 (first e2e run)
- **Issue:** Once a resting `TRAILING_STOP` triggered and the exchange applied fee/slippage, both `fee_model/base.py` and `slippage_model/base.py` raised `ValidationError("order_type", "TRAILING_STOP", "must be one of ['limit','market','stop']")` — their `_KNOWN_ORDER_TYPES` sets predate the new order type. The exchange swallowed it as a per-exchange match error, so the SL never filled and the position never closed.
- **Fix:** Added `"trailing_stop"` to `_KNOWN_ORDER_TYPES` in both model bases. A triggered `TRAILING_STOP` is a taker fill that behaves exactly like a `STOP` at the cost boundary (`is_maker` is False for it, matching STOP), so it is accepted as a known type. No fee/slippage math changed — only the validation allow-list widened.
- **Files modified:** itrader/execution_handler/slippage_model/base.py, itrader/execution_handler/fee_model/base.py
- **Verification:** both e2e scenarios fill the trailing SL and reconcile; full suite 1172 passed; mypy --strict clean; oracle byte-exact.
- **Commit:** 272d0bc

**Total deviations:** 1 (a blocking-issue auto-fix at the execution cost-model boundary, directly caused by the trailing-stop feature reaching fill; no behavior change beyond accepting the new known type).

## Threat Surface

- **T-05-07 (Elevation of privilege — matching leaking into the order handler):** mitigated — `BracketManager` only DECLARES the trailing leg via `parent_order_id`/`child_order_ids` and reconciles its mirror from `FillEvent`s; the e2e tests assert the SL fills via the execution layer and the mirror reaches FILLED. ALL ratchet/trigger logic stays in `MatchingEngine` (D-18, verified by the unit-level trace: the order handler never advances `current_stop`).
- **T-05-08 (Tampering — trailing SL with no positive declaration price failing the dual-layer validators):** mitigated — the D-TRAIL-3 fill-anchored seed sets `price` = the (positive) entry fill, which passes both positive-price gates; D-TRAIL-7 gates `trail_value < anchor` (PRICE). No order rests at a non-positive price.
- No new external/network/auth surface; zero package installs.

## Verification Results

- `poetry run pytest tests/e2e -k "trailing_long or trailing_short"` -> 4 passed (2 scenarios + 2 determinism), no skips.
- `poetry run pytest tests -k "trailing and bracket"` -> 2 passed (the compound selector turned GREEN).
- `poetry run pytest tests/unit/order/test_sltp_policy.py tests/unit/core/test_sizing.py` -> 35 passed (non-trailing PercentFromFill regression intact).
- `poetry run mypy --strict itrader` -> Success, no issues in 185 source files (every OrderType arm armed; assert_never untouched — no new SLTPPolicy variant).
- `git diff --check` -> clean (TAB bracket files stayed TAB; 4-space core/sizing.py + execution model bases stayed 4-space).
- Oracle byte-exact: `poetry run pytest tests/integration` -> 16 passed.
- Full suite: `poetry run pytest tests` -> **1172 passed, 0 skipped** (all Phase-5 Wave-0 stubs across 05-00/01/02/03 are now GREEN; no skips remain).
- No `backtesting`/`backtrader` import under the trailing e2e leaves; folder-derived `e2e` marker only.

## Known Stubs

None introduced. The 2 bracket unit stubs and the 2 e2e long/short stubs from 05-00 were turned GREEN. No Phase-5 Wave-0 stubs remain skipped.

## Self-Check: PASSED

- `itrader/order_handler/brackets/bracket_manager.py` contains `new_trailing_stop_order` (the fill-anchored trailing branch).
- `tests/e2e/trailing_long/test_trailing_long_scenario.py` + `tests/e2e/trailing_short/test_trailing_short_scenario.py` exist with implemented (non-skip) ratcheted-exit assertions; `bars.csv` exists for both (synthetic tickers).
- All 3 task commits present in git log (1d878b5, 45352dd, 272d0bc).

## Next Phase Readiness

- 05-04 (the trailing-stop owner-gated re-baseline / TRAIL-03 cross-validation) builds on a now end-to-end-proven declaration path: a strategy declares a trailing SL via `PercentFromFill(trail_type=..., trail_value=...)`, it rests, ratchets, and triggers at the ratcheted level for both long and short through the full run path. The architecture constraint (order handler declares, execution layer matches) is locked by the e2e tests.

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
