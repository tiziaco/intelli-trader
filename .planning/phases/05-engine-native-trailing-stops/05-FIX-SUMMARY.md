---
phase: 05-engine-native-trailing-stops
plan: FIX
subsystem: trailing-stops-gap-closure
tags: [trailing-stop, code-review-fix, CR-01, WR-01, WR-02, WR-03, WR-04, viability-gate, ratchet]

# Dependency graph
requires:
  - phase: 05-engine-native-trailing-stops
    plan: 01
    provides: D-TRAIL-7 dual-layer validator, OrderType.TRAILING_STOP, TrailType
  - phase: 05-engine-native-trailing-stops
    plan: 02
    provides: MatchingEngine ratchet core, TrailState side-table, modify path
  - phase: 05-engine-native-trailing-stops
    plan: 03
    provides: PercentFromFill fill-anchored trailing carve-out
provides:
  - PERCENT trail < 1 construction-time bound (PercentFromFill.__post_init__)
  - PRICE trail viability gate at fill (_create_fill_anchored_children, fail-loud)
  - unbypassable dual-layer trail viability (no silent unprotected position)
  - MODIFY reseeds TrailState for resting TRAILING_STOP
  - removed dead instrument-resolver quantize seam (full-precision stops, D-14)
affects: [trailing-stop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-loud trail viability split by knowability: PERCENT bounded at policy construction (anchor-independent), PRICE bounded at fill (anchor-dependent) — both reject BEFORE a non-viable trail rests"
    - "MODIFY of a stateful resting order must reseed its parallel side-table (the frozen-event replace does not touch engine-owned mutable state)"
    - "Remove documented-but-dead seams rather than leave an unverifiable capability claim (WR-03 wire-vs-remove -> remove, lowest oracle risk)"

key-files:
  created: []
  modified:
    - itrader/core/sizing.py
    - itrader/order_handler/brackets/bracket_manager.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/matching_engine.py
    - tests/unit/core/test_sizing.py
    - tests/unit/order/test_trailing_bracket.py
    - tests/unit/execution/test_matching_engine_trailing.py

decisions:
  - "PRICE-trail rejection mechanism = raise SizingPolicyViolation from _create_fill_anchored_children (fail-loud), NOT a REFUSED FillEvent. Rationale: the reconcile caller (reconcile_manager.py:301) already wraps this call in a try/except that logs with a stack trace and RE-RAISES under backtest fail-fast (its own WR-04 comment) — raising the typed sizing exception is the EXISTING audited convention for a post-fill bracket-construction failure, consistent with backtest fail-fast. A REFUSED route would invent a second disposition for the same class of error."
  - "WR-03 = REMOVE the dead resolver branch (not wire it). The MatchingEngine is a pure dependency-free module (D-14); its sole construction site SimulatedExchange() never passed a resolver, so the quantize path was dead on every run. Removing it is byte-identical (the branch never executed) and oracle-safe; wiring would add an Instrument dependency to a deliberately-pure engine."
  - "Trail viability is gated where the anchor is KNOWN: PERCENT at construction (anchor-independent: a fraction >= 1 is always non-viable), PRICE at fill (anchor-dependent: trail_value >= anchor only knowable once the fill price exists). This is why WR-02 lands in core/sizing.py and CR-01's PRICE half lands in bracket_manager.py."

metrics:
  duration: ~40min
  completed: 2026-06-17
---

# Phase 05 FIX: Code-Review Gap Closure (CR-01 + WR-01..WR-04) Summary

**The real production trailing path no longer bypasses the D-TRAIL-7 viability gate: a non-viable PERCENT trail (>= 1) now fails loud at PercentFromFill construction and a non-viable PRICE trail (>= the entry-fill anchor) now fails loud at the fill boundary, so a non-viable trail can never silently rest a non-positive, never-triggering stop on an unprotected position; a MODIFY of a resting TRAILING_STOP reseeds its ratchet side-table instead of triggering against a stale level; and the dead instrument-resolver quantize seam is removed (trailing stops carry full precision like every other matching price) — all five findings fixed with RED->GREEN tests, full suite 1179 passed, mypy --strict clean, SMA_MACD oracle byte-exact (134 trades / final_equity 46189.87730727451).**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-06-17
- **Findings fixed:** 5 (1 BLOCKER + 4 warnings)
- **Files:** 0 created, 7 modified (4 source + 3 test)

## Findings Fixed

### CR-01 (BLOCKER) + WR-02 + WR-04 — non-viable trail bypasses the D-TRAIL-7 gate

Same root cause: the only path that creates a production trailing stop
(`PercentFromFill` fill-anchored carve-out) never runs `EnhancedOrderValidator`,
so the D-TRAIL-7 viability checks were dead for every trailing SL. A non-viable
trail (PERCENT `trail_value >= 1`, or PRICE `trail_value >= anchor`) constructed,
rested, and seeded a non-positive `current_stop` that can never trigger — a
silently unprotected position with no rejection.

- **WR-02 fix** (`core/sizing.py`, 4-space): `PercentFromFill.__post_init__` now
  raises `SizingPolicyViolation` when `trail_type == TrailType.PERCENT and
  trail_value >= 1`. `TrailType` is imported lazily inside `__post_init__` to
  preserve the core->config dependency direction (config-enum exception). PRICE
  trails keep no construction-time upper bound (the anchor is unknown then).
- **CR-01 PRICE-case fix** (`bracket_manager.py`, TAB): `_create_fill_anchored_children`
  now rejects a non-viable absolute trail (`trail_type == PRICE and
  trail_value >= anchor`) by raising `SizingPolicyViolation` BEFORE building the
  trailing `sl_order`. This is the fail-loud convention: the reconcile caller
  already logs + re-raises under backtest fail-fast. A dead stop is never rested.
- **WR-04 fix** (`simulated.py`, TAB): corrected the `validate_order` dual-layer
  agreement comment — trail viability is now gated upstream (policy + fill) and
  unbypassable, so the exchange admits exactly the trailing orders the domain
  layers deemed viable; the dual layers no longer disagree on trailing coverage.

- **Commits:** `ce8ff51` (WR-02), `642d6fc` (CR-01 + WR-04)

### WR-01 — MODIFY on a resting trailing stop leaves the ratchet side-table stale

`matching_engine.modify` replaced the frozen `OrderEvent` via
`dataclasses.replace` but never touched the parallel `_trails[order_id]`
TrailState, which carries `hwm`/`lwm`/`current_stop` seeded from the ORIGINAL
price. After a price MODIFY the engine kept triggering against the stale level.

- **Fix** (`matching_engine.py`, 4-space): after the replace, when the updated
  order is a `TRAILING_STOP`, `self._trails[order_id] = self._seed_trail(updated)`
  — the ratchet restarts from the new reference. Non-trailing MODIFYs are
  untouched (no spurious TrailState entry).
- **Commit:** `f752d5c`

### WR-03 — dead `_quantize_stop` instrument-resolver path

`MatchingEngine.__init__` accepted an `instrument_resolver`, but the sole
construction site (`SimulatedExchange()`) passed none, so `_instrument_resolver`
was always `None`, `_quantize_stop` always returned `raw`, and the resolver
branch was dead on every run while the docstrings claimed active quantization.

- **Fix** (`matching_engine.py`, 4-space): removed the constructor param, the
  `_instrument_resolver` attribute, the `_quantize_stop` method, and the now-unused
  `Callable`/`Instrument`/`quantize` imports. `_compute_stop` returns the
  full-precision stop directly. Docstrings corrected: trailing stops carry FULL
  precision like every other matching price (D-14 never-round-prices). Behavior
  is byte-identical (the dead branch never executed).
- **Commit:** `6f78d1f`

## Decisions Made

- **PRICE-trail rejection = raise `SizingPolicyViolation` (fail-loud), not a
  REFUSED FillEvent.** The reconcile caller already wraps
  `_create_fill_anchored_children` in a log+re-raise try/except under backtest
  fail-fast — raising the typed sizing exception is the existing audited
  convention for a post-fill bracket-construction failure. A REFUSED route would
  invent a second disposition for the same error class.
- **WR-03 = remove the dead branch, do not wire it.** Lowest oracle risk
  (byte-identical, the branch never executed); wiring would add an Instrument
  dependency to a deliberately-pure engine (D-14).
- **Viability gated by knowability:** PERCENT at construction (anchor-independent),
  PRICE at fill (anchor-dependent).

## Deviations from Plan

None beyond the documented decisions above. Each finding was fixed RED->GREEN as
its own atomic commit; no out-of-scope changes; info items IN-01..IN-04 left
untouched per the brief.

## Tests Added (RED -> GREEN)

- `tests/unit/core/test_sizing.py`: PERCENT trail >= 1 raises (1 and 1.5); PERCENT
  < 1 constructs; PRICE trail has no construction bound. (WR-02)
- `tests/unit/order/test_trailing_bracket.py`: PRICE trail >= entry-fill anchor is
  rejected at fill via `SizingPolicyViolation`. (CR-01)
- `tests/unit/execution/test_matching_engine_trailing.py`: MODIFY reseeds the
  TrailState (modify up to 150 -> hwm 150, stop 140, fills against the new level);
  plain-STOP MODIFY leaves no TrailState; trailing stop carries full precision with
  no `_quantize_stop`/`_instrument_resolver` seam. (WR-01, WR-03)

## Threat Surface

- **T-05-02 (Tampering — unviable trail resting a stop <= 0):** mitigated on the
  REAL path now — PERCENT bounded at construction, PRICE bounded at fill; a
  non-viable trail is rejected fail-loud before it rests. The D-TRAIL-7 gate is no
  longer bypassable via the fill-anchored carve-out (CR-01 closed).
- No new external/network/auth surface; zero package installs.

## Verification Results

- `poetry run pytest tests/unit/order tests/unit/execution -q` -> **402 passed**.
- `poetry run pytest tests/e2e/trailing_long tests/e2e/trailing_short -q` -> **4 passed**.
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` -> **3 passed**
  (loads the frozen `tests/golden/summary.json`: trade_count 134, final_equity
  46189.87730727451 — byte-exact identity asserted against fresh `output/`).
- `poetry run pytest tests -q` -> **1179 passed** (no warnings under
  `filterwarnings=["error"]`; no new skips).
- `poetry run mypy --strict itrader` -> **Success, no issues in 185 source files**.
- `git diff --check` -> clean (TAB files stayed TAB: bracket_manager.py,
  simulated.py; 4-space files stayed 4-space: sizing.py, matching_engine.py).

## SMA_MACD Oracle — Byte-Exact Confirmation

The frozen golden `tests/golden/summary.json` carries `trade_count: 134` and
`final_equity: 46189.87730727451`. The integration oracle test (`test_backtest_oracle.py`)
runs the full 2018->2026 SMA_MACD backtest, writes fresh `output/`, and asserts
identity against the committed golden trade frame + summary. All 3 oracle tests
pass after every fix — the oracle is byte-exact. (All trailing-stop logic remains
oracle-dark: the SMA_MACD spot run declares no trailing brackets.)

## Self-Check: PASSED

- All four source files modified on disk with the documented changes.
- All five findings have RED->GREEN tests; full suite green, mypy clean, oracle byte-exact.
- Atomic commits present: `ce8ff51`, `642d6fc`, `f752d5c`, `6f78d1f`.

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
