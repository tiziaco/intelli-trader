---
phase: 03-running-pnl-accumulator
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position_manager.py
  - tests/unit/portfolio/test_realised_pnl_accumulator.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

This phase (PERF-02, commit `07ec0b4`) replaces the per-bar dual open+closed re-sum
in `PositionManager.get_total_realized_pnl` with an O(1) running accumulator
(`_realised_pnl_accumulator`), fed a realised increment from both `Portfolio` settle
arms (`_process_transaction_spot`, `_process_transaction_margin`) via
`apply_realised_increment`.

The replaced re-sum was **self-correcting**: it read `position.realised_pnl` (a derived
property) over every open and closed position on each call, so it could never drift from
the true state regardless of which path mutated a position. The accumulator trades that
self-correction for an incremental contract — correctness now depends on **every** path
that changes `realised_pnl` (or that moves/removes a position carrying it) calling
`apply_realised_increment` exactly once with the right increment. The Decimal end-to-end
discipline is clean (no float reintroduced, no mid-sum quantize, `Decimal('0.00')` seed
preserves byte-identity), and the increment arithmetic on the spot/margin arms is correct
for the paths it covers.

The findings below are about the **completeness and verification** of that incremental
contract, not the arithmetic of the covered paths. The most material issue is a real
equivalence break on the `close_all_positions` path (WR-01) and the absence of any
accumulator test for the margin arm and SHORT/multi-position lifecycles (WR-02), which is
exactly where an incremental accumulator is most likely to silently diverge.

No critical (BLOCKER) issues: the divergent `close_all_positions` path is not wired into
the backtest or live run path today, and the covered spot LONG path is correct.

## Warnings

### WR-01: `close_all_positions` bypasses the accumulator — realised PnL silently dropped

**File:** `itrader/portfolio_handler/position/position_manager.py:445-464`
**Issue:** `close_all_positions` calls `_close_position` directly, moving each position to
the closed list **without** calling `apply_realised_increment`. Under the prior re-sum,
those closed positions' `realised_pnl` was still counted by `get_total_realized_pnl`
(it summed the closed list). With the accumulator, that realised PnL is **silently
dropped from the total** — a genuine equivalence break, not just a refactor.

This is the core hazard of swapping a self-correcting re-sum for an incremental
accumulator: any position-close path that does not flow through the `Portfolio` settle
funnel desyncs the total. `close_all_positions` is documented as an "emergency function"
and is not currently wired into the backtest/live run path (only exercised in
`test_position_manager.py::test_close_all_positions`), so it is dormant — hence WARNING
not BLOCKER. But the next caller that wires it (e.g. a liquidation/shutdown hook) will get
a wrong `total_realised_pnl` with no failure signal.

**Fix:** Feed the accumulator from the close funnel, or route emergency closes through the
same increment path. Minimal fix inside `_close_position` (so every close path is covered,
not just the two settle arms):
```python
def _close_position(self, position: Position, price: Decimal | float, time: datetime) -> None:
    # Capture realised BEFORE close_position (close only moves current_price, but
    # keep the capture symmetric with the Portfolio settle arms).
    prior_realised = position.realised_pnl
    position.close_position(price, time)
    self._storage.remove_position(position.ticker)
    self._storage.add_closed_position(position)
    # Keep the accumulator consistent for ALL close paths, not only the
    # Portfolio settle funnel (WR-01 — close_all_positions bypasses it).
    self.apply_realised_increment(position.realised_pnl - prior_realised)
    ...
```
NOTE: if this fix is adopted, the two `Portfolio` settle arms must **not** also call
`apply_realised_increment` for the same fill, or the close will be double-counted. Pick a
single funnel (manager-level `_close_position`, or Portfolio settle arms) and assert it is
the only one — do not leave both live.

### WR-02: No accumulator test covers the margin arm, SHORT, or multi-position lifecycles

**File:** `tests/unit/portfolio/test_realised_pnl_accumulator.py:74-105`
**Issue:** The only non-trivial test drives a single LONG spot lifecycle
(open → scale-in → partial close → full close) on one ticker. The margin settle arm
(`_process_transaction_margin`, portfolio.py:543-548) — which has its own
`apply_realised_increment` wiring and the more complex partial/full-close economics — has
**zero** accumulator-equivalence coverage. SHORT positions (whose `realised_pnl` property
takes a different branch, position.py:188-196) and multi-ticker portfolios (where a
per-ticker desync would not show on a single-ticker re-sum) are also untested. The phase
explicitly wires both arms; only one is verified.

The accumulator's whole risk surface is "does every mutation path feed the right
increment?" — leaving the margin arm and SHORT path unverified leaves the highest-risk
half of the contract unguarded. The `==` drift-lock is sound for what it covers, but its
scope does not match the scope of the change.

**Fix:** Add equivalence cases (same `_resum_realised` oracle, same `==` assertion) for:
(1) a margin portfolio (`enable_margin=True`) open → partial close → full close;
(2) a SHORT lifecycle (sell to open, buy to cover) through the spot funnel;
(3) two tickers interleaved, asserting the accumulator equals the cross-ticker re-sum
after each close. These reuse the existing oracle and fixture pattern.

### WR-03: Accumulator silently desyncs when `process_position_update` is called outside the funnel

**File:** `itrader/portfolio_handler/position/position_manager.py:103-123, 318-331`
**Issue:** `PositionManager.process_position_update` and `_close_position` are public-ish
manager entry points that mutate/close positions and change `realised_pnl`, but the
accumulator is only ever fed from the `Portfolio` settle arms. Any caller that drives the
manager directly (the existing `test_position_manager.py` suite does this ~30 times, and
the docstring at line 56-61 explicitly contemplates a "standalone-constructed" manager)
will leave `get_total_realized_pnl` reading a stale `Decimal('0.00')` while positions
carry real realised PnL — a divergence the old re-sum could never exhibit. This is the
same class of bug as WR-01, generalized: the accumulator's correctness is coupled to an
external caller (Portfolio) honoring the contract, with no manager-level enforcement.

**Fix:** Make the manager self-consistent so the field cannot silently lie. Either
(preferred) feed the increment inside `_close_position`/`process_position_update` so the
accumulator is correct regardless of caller (see WR-01 fix), or — if the funnel-only
contract is intentional — add a debug-mode/assert seam (gated, not on the hot path) that
recomputes the re-sum and asserts equality so a desync fails loud in tests rather than
producing a quietly wrong number. The current docstrings assert the contract in prose
("Fed only from the Portfolio close funnel") but nothing enforces it.

## Info

### IN-01: Non-deterministic naive `datetime.now()` in test fixtures

**File:** `tests/unit/portfolio/test_realised_pnl_accumulator.py:36, 55, 62`
**Issue:** The `portfolio` fixture and `_buy`/`_sell` builders stamp transactions with
`datetime.now()` (wall clock, naive/no tz). The project pins determinism as a core
constraint and elsewhere threads business time, not wall clock. For this equivalence test
the timestamp does not affect `realised_pnl`, so it is not a correctness defect — but it
diverges from the determinism convention and would matter if these helpers are reused for
a carry/time-sensitive case.
**Fix:** Use a fixed `datetime(2024, 1, 1, tzinfo=UTC)` (or a frozen clock) in the
builders for determinism and timezone-awareness consistency.

### IN-02: Money passed as `int`/`float` into a Decimal-end-to-end portfolio

**File:** `tests/unit/portfolio/test_realised_pnl_accumulator.py:36, 53-64`
**Issue:** Cash (`150000`) and prices/quantities (`38000`, `2`, etc.) are passed as
`int`/`float`. The construction boundaries (`to_money`, `Decimal(str(...))`) normalize
these safely, so this is not a defect — but it mirrors the production-discouraged
`float`-for-money entry and slightly weakens the test as a money-discipline example. The
fixture comment says it "mirrors test_portfolio.py", so this matches existing convention.
**Fix:** Optional — pass `Decimal` literals (e.g. `Decimal("38000")`) to model the
intended money discipline in the value-equality assertions.

### IN-03: Docstring/method name overstates what `get_total_realized_pnl` now does

**File:** `itrader/portfolio_handler/position/position_manager.py:325-331`
**Issue:** The method is named/docstringed "Calculate total realized P&L from open and
closed positions" but now simply returns a cached field and never inspects open/closed
positions. This is harmless but the stale "from open and closed positions" phrasing
invites a future reader to assume it re-derives from position state (and to "fix" a
suspected desync by re-adding a loop, re-paying the cost this phase removed).
**Fix:** Update the one-line docstring to state it returns the running accumulator (the
detailed comment below already does); the WR-03 enforcement note should reference it.

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
