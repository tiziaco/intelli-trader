---
phase: 05-naming-encapsulation
reviewed: 2026-06-11T18:49:18Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/execution_handler.py
  - itrader/order_handler/base.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/order_handler/storage/postgresql_storage.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - scripts/run_backtest.py
  - tests/e2e/conftest.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_reservation_inertness.py
  - tests/integration/test_universe_spans.py
  - tests/unit/events/test_dispatch_registry.py
  - tests/unit/execution/exchanges/test_simulated_exchange.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/strategy/test_strategy_config.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-11T18:49:18Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

This is a behavior-preserving naming & encapsulation refactor (NAME-01..04):
identifier renames (`events_queue→global_queue`, `_routes→routes`,
`get_orders_summary/get_orders_count_by_status→count_orders_by_status`, strategy
classes to PascalCase, strategy-config `FAST/SLOW/WIN→*_window`), a new public
`SimulatedExchange.register_symbol()` seam replacing direct `_supported_symbols`
mutation, and test rewrites that swap private-internals access for public surfaces.

I took an adversarial stance and focused on the highest-risk failure mode for a
rename refactor: **stale references** to old identifiers that the rename missed,
**call-site breakage** (especially keyword-argument callers of the renamed
`OrderHandler.__init__` parameter), and **semantic drift** in the new
`register_symbol` seam and the rewritten `test_correlation_id_generation`.

Verification performed:
- Whole-repo grep for every old identifier (`events_queue`, `_routes`,
  `get_orders_summary`, `get_orders_count_by_status`, old strategy class names,
  `.FAST/.SLOW/.WIN`). No stale references in production/test code on the run
  path. The only surviving `events_queue` hits are inside the deferred,
  mypy-ignored `strategy_handler/my_strategies/` subsystem (self-contained
  `self.events_queue` attributes unrelated to `OrderHandler`) — out of scope and
  not a regression.
- All 10 `OrderHandler(...)` construction sites use **positional** args; none
  passes `events_queue=` as a keyword, so the parameter rename does not break any
  caller. Confirmed.
- Ran the affected unit suites (100 tests) + the three touched integration tests
  (5 tests): all green. `mypy --strict` clean on all 8 changed source modules.
- Traced the rewritten `test_correlation_id_generation`: an EXECUTED fill against
  an unknown portfolio publishes a `PortfolioErrorEvent` on `global_queue`
  *before* re-raising (`portfolio_handler.py:341-344`), so `global_queue.get()`
  resolves and the test is sound (not a hang risk).

The refactor is mechanically clean and the golden master is preserved
(`register_symbol`'s set-union and the old `set(...) | {...}` line are
byte-identical; the strategy-attribute renames are pure identifier swaps that feed
the same `trend.MACD` args). No BLOCKER-tier defects found. One WARNING and three
INFO items below concern encapsulation fidelity and cosmetic consistency, not
correctness.

## Warnings

### WR-01: `register_symbol` seam is bypassed by `update_config`, silently dropping registered symbols

**File:** `itrader/execution_handler/exchanges/simulated.py:472-481` (and `:655-656`)
**Issue:** The new `register_symbol()` docstring states the goal is to make
`_supported_symbols` "written only via `__init__`, this method, and the
update_config re-derivation block." But the `update_config` re-derivation block
(`:655-656`) **unconditionally re-aliases** `self._supported_symbols =
self.config.limits.supported_symbols` whenever any of `supported_symbols`,
`min_order_size`, or `max_order_size` is updated. Because `register_symbol`
rebinds to a fresh local union set (correctly *not* mutating the shared config
set), any symbol registered via the new seam is **silently discarded** the next
time `update_config` touches limits — e.g. a later `update_config(min_order_size=...)`
wipes a previously-registered `BTCUSD`.

This is a *pre-existing* latent quirk (the old direct-mutation line had identical
semantics), so it is **not a regression** and does not affect the golden run
(which never calls `update_config` after registration). I flag it as WARNING
rather than ignoring it because the refactor's stated intent was to *encapsulate*
this attribute's write discipline, and the new docstring asserts a write-invariant
that `update_config` violates — encapsulating the mutation without reconciling the
two writers leaves a footgun that the seam's existence now implicitly endorses.
**Fix:** Either have `register_symbol` route through config
(`self.config.limits.supported_symbols`) so `update_config` re-derivation
preserves registrations, or have the `update_config` limits block *union* rather
than *replace*:
```python
# :655-656 — preserve seam-registered symbols across a limits update
if any(k in ['supported_symbols', 'min_order_size', 'max_order_size'] for k in kwargs):
    self._supported_symbols = set(self.config.limits.supported_symbols) | set(self._supported_symbols)
    ...
```
If the drop-on-reconfigure behavior is intentional, state it explicitly in the
`register_symbol` docstring (it currently implies durability).

## Info

### IN-01: `SMA_MACD` logger component name not updated to match the new class name

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:13`
**Issue:** The strategy class was renamed `SMA_MACD_strategy → SMAMACDStrategy`,
but the module-level bound logger still uses the old name:
`logger = get_itrader_logger().bind(component="SMA_MACD_strategy")`. Log lines
will now reference a class identifier that no longer exists, which can mislead a
reader grepping logs for the class. Cosmetic only — no behavior impact.
**Fix:** `logger = get_itrader_logger().bind(component="SMAMACDStrategy")` (or keep
the strategy-name string deliberately and add a one-line note that it is the
log-facing name, not the class name).

### IN-02: Stale class names in docstrings / comments after the rename

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:10` (docstring
reference is updated, OK), `scripts/run_backtest.py:11` (`SMA_MACD code defaults`
comment), `scripts/crossval/indicators.py:32-33,88`,
`scripts/crossval/backtrader_run.py:9`, `scripts/crossval/backtesting_py_run.py:9,67`,
`scripts/normalize_data.py:116`
**Issue:** Several comments/docstrings still spell the old class/file identity
`SMA_MACD_strategy` and the old config field names `FAST/SLOW/WIN`. Most are
correct *file-path* references (the module file is still named
`SMA_MACD_strategy.py`), so these are mostly accurate. The `scripts/crossval/*`
and `scripts/normalize_data.py` notes that name `FAST=6, SLOW=12, WIN=3` as "the
strategy defaults" are now stale wording (the fields are `fast_window/slow_window/
signal_window`), though the *values* they document are unchanged and the crossval
oracles do not import the renamed class (they define their own
`SMAMACDBacktrader`/`SMAMACDBacktesting`/`SMAMACDNautilus`). Documentation drift
only; no executable reference is broken.
**Fix:** When convenient, update the crossval/normalize comments to cite
`fast_window/slow_window/signal_window` so the param names match the live config.

### IN-03: `test_universe_spans` WR-02 guard comment references a removed numbered finding

**File:** `tests/integration/test_universe_spans.py:144` (and the analogous comment
block)
**Issue:** The inline comment still opens with `# WR-02: fail loudly at setup ...`.
That `WR-02` tag is a label from a *prior* review cycle carried into the comment
body; it no longer corresponds to a current finding ID and can confuse a reader who
greps for `WR-02`. The assertion itself is correct and now uses the public
`get_supported_symbols()` surface (good — this is exactly the encapsulation the
phase wanted). Purely a stale-tag nit.
**Fix:** Drop the `WR-02:` prefix or replace with a neutral rationale lead-in
(e.g. `# Fail loudly at setup if the supported-symbol set drifts ...`).

---

_Reviewed: 2026-06-11T18:49:18Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
