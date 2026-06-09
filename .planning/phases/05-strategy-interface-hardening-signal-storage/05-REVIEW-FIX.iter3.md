---
phase: 05-strategy-interface-hardening-signal-storage
fixed_at: 2026-06-09T00:00:00Z
review_path: .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-06-09
**Source review:** .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: `to_dict()` is still JSON-unsafe — `subscribed_portfolios` holds runtime UUID `PortfolioId`s

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** a328f1c
**Applied fix:** Stringified the portfolio ids at the serialization edge in
`StrategyBase.to_dict()`, exactly as the prior IN-03 fix did for `strategy_id`.
Changed `"subscribed_portfolios": self.subscribed_portfolios` to
`"subscribed_portfolios": [str(pid) for pid in self.subscribed_portfolios]`.
This closes the `TypeError: Object of type UUID is not JSON serializable` that
`json.dumps(strategy.to_dict())` raised on every real run path (where
`PortfolioHandler.add_portfolio` returns a `uuid.UUID` and that handle is
subscribed). `str()` is safe for both int and UUID handles. Added a comment
referencing WR-01/IN-03 explaining the serialization-edge rationale.

**Verification:** Tier 1 (re-read confirmed fix present and code intact) + Tier 2
(`ast.parse` syntax check passed).

### IN-01: `_publish_and_continue` imports `sys` / `ErrorEvent` inside the method body on every handler failure

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 19b16d1
**Applied fix:** Hoisted `import sys` to module scope (stdlib, no side effects)
and added `ErrorEvent` to the existing module-level
`from itrader.events_handler.events import ...` line (line 26). Removed the two
in-method imports from `_publish_and_continue` and replaced them with a comment
documenting that the deferred-import rationale does not apply to this module —
it already imports `EventType`/`TimeEvent`/`OrderEvent` from the same events
package at module scope, so re-importing on the hot error path bought nothing.
No behavior change; removes redundant per-invocation imports on the live error
path.

**Verification:** Tier 1 (re-read confirmed fix present) + Tier 2 (`ast.parse`
syntax check passed) + actual module import (`import
itrader.trading_system.live_trading_system` succeeds with both `sys` and
`ErrorEvent` resolvable at module scope).

---

_Fixed: 2026-06-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
