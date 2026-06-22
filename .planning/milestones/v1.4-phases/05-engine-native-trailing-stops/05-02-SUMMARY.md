---
phase: 05-engine-native-trailing-stops
plan: 02
subsystem: execution-matching
tags: [trailing-stop, matching-engine, ratchet, look-ahead-safety, side-table, TRAIL-01, TRAIL-02]

# Dependency graph
requires:
  - phase: 05-engine-native-trailing-stops
    plan: 01
    provides: OrderType.TRAILING_STOP, TrailType (PRICE/PERCENT), OrderEvent.trail_type/trail_value, D-TRAIL-7 validation
  - phase: 05-engine-native-trailing-stops
    plan: 00
    provides: collectible pytest.skip matching-engine ratchet/gap/oco stubs (turned GREEN here)
provides:
  - MatchingEngine TRAILING_STOP arm in _evaluate (ratcheted level as trigger, STOP gap-aware fill verbatim)
  - END-of-on_bar ratchet step advancing HWM/LWM from this bar's extreme (D-TRAIL-1/2)
  - engine-owned TrailState side-table (hwm/lwm/current_stop) parallel to _resting (D-TRAIL-6)
  - _pick_bracket_winner + _fill_reason TRAILING_STOP arms (D-TRAIL-5)
  - optional instrument_resolver seam to quantize the stop level (D-TRAIL-8)
  - GREEN long+short ratchet / next-bar (tall-bar) / gap / OCO unit tests
affects: [05-03, 05-04, trailing-stop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Engine-owned side-table for mutable ratchet state parallel to the frozen-event resting book (D-TRAIL-6)"
    - "Ratchet-AFTER-evaluate ordering: level on bar N derived from bars <= N-1 (D-TRAIL-2 look-ahead safety)"
    - "Optional instrument_resolver callable seam — quantize the stop when injected, full-precision no-op otherwise (preserves D-14 never-round-prices default)"

key-files:
  created: []
  modified:
    - itrader/execution_handler/matching_engine.py
    - tests/unit/execution/test_matching_engine_trailing.py

decisions:
  - "order.price is the fill-anchored REFERENCE price (seed for HWM/LWM), NOT the initial stop level — confirmed against the D-TRAIL-7 validator which calls order.price the 'reference price' and gates trail_value < order.price. _seed_trail seeds hwm=lwm=order.price and computes the initial stop from it (D-TRAIL-3). This resolves the wording tension between 05-01-SUMMARY ('price carries initial stop') and the 05-02 plan ('initialize from the order's price')."
  - "Quantize seam made optional (instrument_resolver callable, default None). The pure MatchingEngine has no Instrument access and is quantization-free by design (D-14 never-round-prices); threading a mandatory Instrument would be an architectural change and conflict with D-14. With no resolver the stop is carried at full precision (byte-exact default); HWM/LWM are ALWAYS full precision regardless (the real D-TRAIL-8 risk — quantizing the running extreme — is avoided unconditionally)."
  - "_run_ratchet_step extracted and called before BOTH on_bar return points (the early 'no candidates' return and the normal end) so resting trailing orders ratchet on EVERY bar, fill or no fill."

metrics:
  duration: ~15min
  completed: 2026-06-17
---

# Phase 05 Plan 02: MatchingEngine TRAILING_STOP Ratchet Core Summary

**A resting TRAILING_STOP now ratchets its stop favorably-only from closed-bar extremes (longs non-decreasing off HIGH, shorts non-increasing off LOW), becomes active on the NEXT bar via an END-of-on_bar ratchet step (proved by the tall-bar test), reuses the existing STOP gap-aware fill + STOP-beats-LIMIT OCO priority verbatim, and keeps its mutable HWM/LWM/current_stop in a leak-free engine-owned side-table — mypy --strict clean, oracle byte-exact.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-06-17
- **Tasks:** 2 (both TDD: implementation verified GREEN against the 05-00 stubs)
- **Files:** 0 created, 2 modified

## Accomplishments

- **`TrailState` side-table** (`@dataclass(slots=True)`, mutable `hwm`/`lwm`/`current_stop`) keyed by `OrderId` parallel to `_resting` (D-TRAIL-6). Seeded on `submit` for any `TRAILING_STOP`; popped at EVERY `_resting.pop` site (cancel, pass-1 parent fill, pass-2 chosen children, OCO cancels) so no entry leaks.
- **`_evaluate` TRAILING_STOP arm** — reads `current_stop` from the side-table (derived from bars <= N-1) as the trigger and runs the EXACT SELL/BUY gap-aware `min/max(open_, trigger)` comparison from the STOP branch (D-TRAIL-4 verbatim reuse). Explicit `elif` arm, not fallthrough (mypy --strict).
- **`_run_ratchet_step` at the END of `on_bar`** (D-TRAIL-1/D-TRAIL-2) — runs AFTER both fill passes and OCO cancels resolve. Long: `hwm = max(hwm, bar.high)`; short: `lwm = min(lwm, bar.low)` (extremes, not close). Recomputes the candidate stop and applies the favorably-only ratchet (long `current_stop = max(...)`, short `min(...)`). Called before BOTH `on_bar` return points so trailing orders advance on every bar.
- **`_compute_stop` / `_seed_trail` / `_quantize_stop` helpers** — PRICE/PERCENT formulas at full precision off the full-precision watermark; `quantize(..., "price")` applied ONLY to the returned stop level and ONLY when an instrument resolver is injected (D-TRAIL-8).
- **`_pick_bracket_winner`** preference widened to `order_type in (OrderType.STOP, OrderType.TRAILING_STOP)` (D-TRAIL-5 — trailing SL keeps STOP-beats-LIMIT priority). **`_fill_reason`** TRAILING_STOP arm returns `"trailing stop triggered"`.
- **6 GREEN unit tests** (long + short): ratchet favorably-only, tall-bar next-bar activation, gap-through fill at open (long + short), trailing-SL vs TP-limit OCO. The tall-bar test is the D-TRAIL-2 centerpiece — a bar whose high ratchets the stop to 140 AND whose low (130) pierces 140 produces NO same-bar fill (active level still 90), then fills next bar at 140.

## Side-Table Layout (D-TRAIL-6)

`MatchingEngine._trails: dict[OrderId, TrailState]`, parallel to `_resting`, where:

```
TrailState(hwm, lwm, current_stop)   # all Decimal
  hwm/lwm        : full 28-digit precision running extreme (D-TRAIL-8), seed = order.price (reference/anchor)
  current_stop   : the active ratcheted level (quantized if a resolver is injected), trigger source for _evaluate
```

Only the relevant water-mark advances (hwm for a long sell-stop, lwm for a short buy-stop); the other is inert. Popped at all four `_resting.pop` sites — verified no leak by the tests asserting `oid not in engine._trails` after fill/OCO.

## Ratchet-AFTER-Evaluate Ordering (D-TRAIL-2) — CONFIRMED

The ratchet runs in `_run_ratchet_step`, invoked at the **END** of `on_bar` (after pass 1, pass 2, and OCO cancels), AND before the early `if not candidates: return` path. The level a trailing order triggers against on bar N is therefore always derived from bars <= N-1. The forbidden same-bar ratchet-and-trigger anti-pattern is structurally impossible: `_evaluate` reads `current_stop` and never advances it. Proven by `test_trailing_next_bar_activation_not_same_bar`.

## Task Commits

1. **Task 1: TRAILING_STOP ratchet arm + side-table** - `78cf28f` (feat)
2. **Task 2: long+short ratchet/next-bar/gap/OCO unit tests** - `29948eb` (test)

## Decisions Made

- **`order.price` = reference/anchor, not initial stop.** The D-TRAIL-7 validator (05-01) compares `trail_value >= order.price` and labels `order.price` the "reference price". So `_seed_trail` seeds `hwm = lwm = order.price` and computes the initial stop from it (D-TRAIL-3). This is the internally-consistent reading across the validator, the 05-02 plan action, and D-TRAIL-3.
- **Optional quantize seam.** See Deviations — the pure engine has no Instrument; a mandatory one would be architectural and conflict with D-14.
- **Single ratchet step before both returns.** Extracted `_run_ratchet_step` so the early no-candidates return does not skip the ratchet.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking: quantize needs an Instrument the pure engine lacks] Made the D-TRAIL-8 quantize seam optional**
- **Found during:** Task 1
- **Issue:** The plan/PATTERNS interface specifies `quantize(stop, instrument, "price")` in the ratchet step, but `MatchingEngine` is a pure, dependency-free module (D-14: matching is quantization-free; `_evaluate` does NO quantization). `core.money.quantize` requires an `Instrument`, which the engine has no access to. Threading a mandatory `Instrument`/`Universe` into the constructor would be an architectural change (Rule 4) AND would contradict the engine's never-round-prices contract.
- **Fix:** Added an optional `instrument_resolver: Callable[[str], Optional[Instrument]] | None = None` constructor arg. When injected, the computed stop level is `quantize(..., "price")`'d (honoring D-TRAIL-8); when absent (the default, byte-exact for every existing construction including `SimulatedExchange`'s `MatchingEngine()`), the stop is carried at full Decimal precision exactly like every other matching price. Critically, HWM/LWM are ALWAYS full precision regardless of the resolver — the genuine D-TRAIL-8 risk (quantizing the running extreme, causing ratchet drift) is avoided unconditionally.
- **Files modified:** itrader/execution_handler/matching_engine.py
- **Verification:** mypy --strict clean; integration oracle byte-exact (16 passed); full suite 1166 passed.
- **Commit:** 78cf28f

**Total deviations:** 1 (a blocking-issue auto-fix that keeps the engine pure and the default byte-exact; D-TRAIL-8's core invariant — full-precision extremes — is fully honored).

## Threat Surface

- **T-05-04 (Tampering — look-ahead leak, same-bar ratchet-and-trigger):** mitigated — ratchet runs at END of `on_bar`; `_evaluate` only reads `current_stop`, never advances it; the tall-bar test asserts no same-bar fill.
- **T-05-05 (Information disclosure — stale side-table entry):** mitigated — `_trails` popped at all four `_resting.pop` sites; tests assert `oid not in engine._trails` after fill/OCO.
- **T-05-06 (Tampering — Decimal drift from quantizing the running extreme):** mitigated — HWM/LWM unconditionally full precision; only the computed stop level is quantize-able (and only when a resolver is injected).
- No new external/network/auth surface; zero package installs.

## Verification Results

- `poetry run pytest tests/unit/execution -k trailing` → 6 passed (long, short, next_bar, gap x2, oco). All 05-00 matching stubs GREEN; no skips remain in `test_matching_engine_trailing.py`.
- Selector ACs: `trailing and long` → 2; `trailing and short` → 2; `trailing and next_bar` → 1; `trailing and gap` → 2; `trailing and oco` → 1 — all pass.
- `poetry run mypy --strict itrader` → Success, no issues in 185 source files (every OrderType arm armed; no fallthrough).
- `git diff --check` → clean (matching_engine.py stayed 4-SPACE).
- Existing matching-engine tests: 41 passed (no regression to STOP/LIMIT/bracket behavior).
- Integration oracle byte-exact: `poetry run pytest tests/integration` → 16 passed.
- Full suite: `poetry run pytest tests` → **1166 passed, 4 skipped** (only the 05-03 bracket + e2e Wave-0 stubs remain).

## Known Stubs

None introduced. The 6 matching-engine Wave-0 stubs from 05-00 were turned GREEN. The remaining 4 skipped stubs belong to 05-03 (bracket declaration + e2e long/short) by design.

## Self-Check: PASSED

- `itrader/execution_handler/matching_engine.py` exists with TRAILING_STOP arms in `_evaluate`, `_fill_reason`, and `_pick_bracket_winner`, plus `_run_ratchet_step` and `TrailState`.
- `tests/unit/execution/test_matching_engine_trailing.py` exists with 6 implemented (non-skip) tests.
- Both task commits present in git log (78cf28f, 29948eb).

## Next Phase Readiness

- 05-03 (BracketManager fill-anchored trailing-SL declaration + e2e) builds on the now-GREEN engine: declare a `TRAILING_STOP` child via `Order.new_trailing_stop_order` with `parent_order_id`, seeding `price` from the entry fill (the engine's `_seed_trail` reads that as the anchor). The ratchet, gap, and OCO machinery are proven at the unit level.

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
