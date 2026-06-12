---
phase: 02-strategy-authoring-surface
fixed_at: 2026-06-12T00:00:00Z
review_path: .planning/phases/02-strategy-authoring-surface/02-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 6
skipped: 1
status: partial
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-06-12T00:00:00Z
**Source review:** .planning/phases/02-strategy-authoring-surface/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (4 warning + 3 info; fix_scope = all)
- Fixed: 6 (WR-01, WR-02, WR-04, IN-01, IN-02, IN-03)
- Skipped: 1 (WR-03 — owner-deferred to Phase 3)

All fixes were verified by re-read (Tier 1), `mypy --strict` on the touched
source modules (Tier 2), and the full strategy unit suite + the byte-exact
oracle / reservation integration suite (30 tests green). The golden oracle pin
**46189.87730727451** is intact after every fix (verified against the freshly
regenerated `output/summary.json`).

## Fixed Issues

### WR-01: Mutable class-attr default aliased across all instances

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 24943df
**Applied fix:** Added `import copy` and, in `_apply_params`, the class-attr
default fallback now `copy.deepcopy`s the default when it is a `list`/`dict`/`set`
before `setattr` — so a declared mutable class default is no longer shared across
instances. Followed the review's suggested snippet exactly; tabs preserved
(`base.py` is tab-indented). Immutable defaults (the common case) are unchanged.

### WR-02: `to_dict()` config snapshot omitted timeframe, tickers, subclass knobs

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 0d93d12
**Applied fix:** Rewrote `to_dict()` to introspect the full declared surface via
`get_type_hints(type(self))` — every declared knob (`tickers`, `max_window`,
`warmup`, and subclass windows like `short_window`/`long_window`) is now captured,
with enums serialized via `.value` and policies via `repr`. The timeframe (a
timedelta at runtime) is serialized as the stable `timeframe_alias` string. The
prior identity/runtime fields and bespoke serializations are preserved verbatim
and take precedence via a trailing `snapshot.update({...})`. Verified the SIG-02
snapshot is now faithful (timeframe_alias/tickers/windows present) and that the
oracle path still produces identical numbers.

### WR-04: Reconfigure preserves prior value over a changed class default (footgun)

**Files modified:** `itrader/strategy_handler/base.py`, `tests/unit/strategy/test_strategy.py`
**Commit:** a77e20c
**Applied fix:** Documented the asymmetric fallback explicitly in
`reconfigure.__doc__` (omitted kwarg keeps the PRIOR value, never resets to the
class default; resetting requires an explicit kwarg). Added
`test_reconfigure_omitted_field_keeps_prior_not_default` pinning the behavior:
omit-on-reconfigure freezes the prior value, and an explicit kwarg is the only
reset path. This is a documentation + test fix only — no behavior change (the
semantic is intentional per RESEARCH Open Question 1), so no oracle risk.

### IN-01: Dead `tuple`-pair branch in `get_strategies_universe`

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** fa9b200
**Applied fix:** Removed the dead `isinstance(strategy.tickers[0], tuple)` pairs
branch and its `pair`/`sym` comprehension; the loop now unconditionally extends
`traded_tickers` with `strategy.tickers` (the declared `list[str]` contract).
Replaced the stale WR-04 comment with an IN-01 note that a typed pairs API will
replace it if pairs trading returns. Tabs preserved (`strategies_handler.py` is
tab-indented). The strategy unit suite and oracle still pass — the branch was
provably unreachable on every supported path.

### IN-02: `SignalRecord.config` test asserted self-consistency, not fidelity

**Files modified:** `tests/unit/strategy/test_signal_store.py`, `tests/integration/test_backtest_oracle.py`
**Commit:** 1330d0b
**Applied fix:** Replaced `assert record.config == strategy.to_dict()` (which
only proves self-consistency) in both the unit signal-store test and the oracle
integration test with explicit field assertions against the specific params that
matter — `strategy_name`, `direction`, `sizing_policy`, and (post WR-02) the
`timeframe_alias`/`tickers`/window knobs the snapshot now carries. Both tests
green.

### IN-03: Module-level oracle constants/helper duplicated across integration tests

**Files modified:** `tests/integration/_oracle_harness.py` (new), `tests/integration/test_backtest_oracle.py`, `tests/integration/test_reservation_inertness.py`
**Commit:** b8e74be
**Applied fix:** Created a new shared helper module `tests/integration/_oracle_harness.py`
holding `_REPO_ROOT`/`_RUN_BACKTEST`/`_OUTPUT_DIR`/`_GOLDEN_DIR` and a
parameterized `load_run_backtest_module(module_name)` (the module name lets the
two in-process copies register under distinct `sys.modules` keys, preserving the
prior `run_backtest` vs `run_backtest_inertness` distinction). Both integration
tests now import from the harness and keep a thin `_load_run_backtest_module()`
shim for their existing call sites. Verified `tests` resolves as a namespace
package under pytest collection (no `__init__.py` needed) and both files collect
and run green.

**New file created:** `tests/integration/_oracle_harness.py` — required by the
review's explicit "extract into one shared conftest/helper module" fix.

## Skipped Issues

### WR-03: `generate_signal` precondition crash — relocated warmup guard

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:52-95`
**Reason:** Skipped — **owner-deferred to Phase 3 (IND-01)**. The REVIEW.md body
carries an explicit "Status: DEFERRED → Phase 3" directive (recorded in STATE.md
Decisions): the structural fix is framework-derived warmup (Phase 3's declared-
indicator framework auto-derives `warmup`/`max_window` from declared indicator
lookbacks), which cannot be done while indicators remain inline `ta.*` calls in
this method. The interim defensive guard was intentionally NOT taken to keep the
D-15 handler-side gating clean. Per the explicit fix-pass instruction, no fix was
applied for WR-03 even though `fix_scope` is `all`. (Phase-3 hard constraint on
record: derived warmup for `SMAMACDStrategy` MUST equal exactly 100 or the oracle
drifts off 46189.87730727451.)
**Original issue:** The in-strategy `if len(bars) < self.max_window: return None`
guard was removed (D-15) and relocated to the handler's `strategy.warmup`
short-circuit; `generate_signal` now reaches `MACDhist.iloc[-2]` unconditionally
and raises `IndexError` if ever called with a sub-warmup frame (safe on the
golden path, fragile for a future low/zero-warmup author).

---

_Fixed: 2026-06-12T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
