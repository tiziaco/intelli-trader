---
phase: 01-instrument-value-object
fixed_at: 2026-06-15T00:00:00Z
review_path: .planning/phases/01-instrument-value-object/01-REVIEW.md
iteration: 2
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-06-15
**Source review:** .planning/phases/01-instrument-value-object/01-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 1
- Fixed: 1
- Skipped: 0

## Fixed Issues

### WR-01: `ConfigurationError` raised with message in the `config_key` slot

**Files modified:** `itrader/trading_system/backtest_runner.py`
**Commit:** fcc6db1
**Applied fix:** Both `ConfigurationError` raises (the WR-03 desync assert at the
membership/instruments invariant, and the empty-store guard before deriving the
ping clock) passed the entire human-readable message as the first positional
argument, landing it in `config_key` and leaving `reason=None`. Confirmed
`ConfigurationError.__init__` signature is `(config_key=None, config_value=None,
reason=None)` in `itrader/core/exceptions/base.py:31`, and that the dominant call
convention elsewhere (`order_manager.py:194`, `portfolio.py:178`,
`simulated.py:739`, `bar_feed.py:230`) passes the message via `reason=`. Both
raises were rewritten to pass the message as the `reason=` keyword so
`exc.reason` carries the diagnostic and `exc.config_key` is left unset (None)
rather than holding a full prose sentence. Tab indentation preserved (file uses
tabs); no control-flow change — the fix is oracle-neutral.

## Verification

Run directly on the main checkout (NOT an isolated worktree), so the editable
install (`itrader.pth`) imports the edited code and these results are
byte-exact-accurate:

- `poetry run pytest tests/integration/test_backtest_oracle.py -q` — **3 passed**
  (oracle invariant 134 trades / 46189.87730727451 holds; unchanged).
- `poetry run mypy itrader` — **Success: no issues found in 185 source files**
  (strict-clean; unchanged).
- `poetry run pytest -q` — **1023 passed** (unchanged).

`tests/golden/` was not touched.

## Skipped Issues

None.

---

_Fixed: 2026-06-15_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
