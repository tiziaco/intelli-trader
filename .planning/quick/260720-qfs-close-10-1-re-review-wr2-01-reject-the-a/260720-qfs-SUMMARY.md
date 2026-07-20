---
phase: quick/260720-qfs
plan: 01
subsystem: strategy_handler/lifecycle
tags: [WR2-01, D-09, D-10, CR-01, live-control-plane, security]
requires:
  - itrader/strategy_handler/lifecycle/manager.py::_portfolio_id_from
  - itrader/strategy_handler/lifecycle/manager.py::_add_strategy_verb
provides:
  - itrader/strategy_handler/lifecycle/manager.py::_portfolio_id_supplied
affects:
  - live STRATEGY_COMMAND `add` verb admission (backtest-dark)
tech-stack:
  added: []
  patterns: [reject-without-registering, presence-probe-beside-parser, collaborator-log-spy]
key-files:
  created: []
  modified:
    - itrader/strategy_handler/lifecycle/manager.py
    - tests/unit/strategy/test_strategy_command_verbs.py
decisions:
  - "An explicit `None` VALUE counts as NOT supplied — a FastAPI/Pydantic `portfolio_id: str | None = None` serializes the legal unsubscribed case as a null on every add, so a bare key-presence probe would reject the most likely legal payload shape."
  - "The malformed gate sits after the D-02 duplicate check and before blob construction, so the reject never has to unwind a completed `add_strategy` roster insert."
  - "The two light verbs keep warn-and-ignore (not reject) — they act on an already-registered strategy, where tearing it down over one junk subscription command would be a worse cure than the disease."
metrics:
  duration: ~13 min
  tasks: 3
  files: 2
  completed: 2026-07-20
status: complete
---

# Quick Task 260720-qfs: Close 10.1 Re-Review WR2-01 Summary

A supplied-but-unparseable `config["portfolio_id"]` now rejects the whole `add` loudly instead of silently registering a strategy that fans zero SignalEvents forever; absence stays a silent legal no-op (D-09).

## What Was Built

`StrategyLifecycleManager._add_strategy_verb` treated a MALFORMED `portfolio_id` as the legal
"no subscription requested" state. `_portfolio_id_from` deliberately collapses four outcomes
(config-not-a-dict, key absent, wrong type, unparseable UUID) into one `None`, and the add verb
read that `None` as absence. The result was a registered, persisted, warming strategy with an
empty `subscribed_portfolios` — and since `strategies_handler.on_bar` wraps `SignalEvent`
construction in `for portfolio_id in strategy.subscribed_portfolios:`, that means literally zero
signals, forever, on an engine that looks perfectly healthy.

Three changes, all in `itrader/strategy_handler/lifecycle/manager.py`:

1. **`_portfolio_id_supplied`** — a new presence probe placed immediately after
   `_portfolio_id_from`, so parser and probe read as one pair. It owns the `"portfolio_id"` key
   name and the `isinstance(config, dict)` guard; no call site re-reads `event.config`.
2. **Early reject gate in `_add_strategy_verb`** — placed after the D-02 duplicate-name check and
   before the blob construction that feeds `build_strategy`. Rejects when the parse yields `None`
   AND the probe reports supplied: one `logger.warning` naming the condition (never the payload
   value, per the P8 declared-fields-only precedent) plus `return`.
3. **Parse reuse** — the old `portfolio_id = self._portfolio_id_from(event)` line at the subscribe
   site was deleted and the `if` now reads the handle bound by the gate. `_portfolio_id_from` is
   called exactly once in this method. Its stale comment (which claimed the parse happened there)
   was rewritten to point at the gate by symbol, keeping the D-09 absent-is-legal sentence.

Six new tests were added to the existing verb suite (parametrized to 10 cases).

## TDD RED Evidence (required by the plan)

The malformed-reject test was written and run against unmodified production code first. It failed
for the documented RIGHT reason — the roster assertion, proving the strategy IS currently
registered:

```
>       assert [s.name for s in handler.strategies] == []
E       AssertionError: assert ['malformed_pid'] == []
E         Left contains one more item: 'malformed_pid'
tests/unit/strategy/test_strategy_command_verbs.py:959: AssertionError

================== 4 failed, 9 passed, 48 deselected in 1.81s ==================
```

All four parametrized malformed cases (`"7"`, `"not-a-uuid"`, `""`, `7`) failed on that same
roster assertion. The captured stderr confirms the defect directly:
`New strategy added: malformed_pid`. Not a collection error, import error, `TypeError`, fixture
bug, or a failure on the warning-count assertion. The other five tests (absent, explicit-null,
valid-UUID, and both light-verb drift pins) PASSED against current code as the plan predicted,
confirming current behavior matched the plan's assumptions.

## Key Decisions

**Explicit `None` is ABSENT, not malformed.** A FastAPI/Pydantic model declaring
`portfolio_id: str | None = None` serializes the unsubscribed case as a null on *every* add. A
bare key-presence probe would therefore reject the most likely shape of the legal no-subscription
payload. Every other value — non-`str`, empty `str`, non-UUID `str` — is supplied-and-malformed.
Pinned by `test_add_with_an_explicitly_null_portfolio_id_is_registered_and_silent`.

**Placement is load-bearing.** The gate is a pure payload check with no dependency on the
constructed object, so it belongs ahead of every state mutation. Rejecting at the old parse site
would have had to undo a completed `_managed.add_strategy` roster insert. It also sits outside
both tiers of the CR-01 zone-1 guard, which stays scoped to the single `build_strategy` call —
the guard was not widened, moved, or restructured (verified: no diff hunk inside it). The new arm
raises nothing, so D-10 never-raise holds and routine bad operator input still cannot reach the
failure-rate tripwire → `halt()`.

**The light verbs were deliberately left alone.** `subscribe_portfolio` / `unsubscribe_portfolio`
act on an already-registered strategy, so "reject" for them correctly means warn-and-ignore with
the strategy left in the roster. A parametrized drift-pin test locks this so the fix cannot leak.

## Deviations from Plan

### Verify-gate correction (not a code change)

**1. [Rule 3 - Blocking] Task 2's `grep -c` symbol-count gate false-failed**
- **Found during:** Task 2 verification
- **Issue:** The gate asserts `grep -c '_portfolio_id_supplied' == 2` and
  `grep -c '_portfolio_id_from' == 4`. Actual raw counts were 3 and 6, so the gate reported
  failure while the code was correct.
- **Cause:** `grep -c` counts *every* line mentioning the symbol, including prose. The plan itself
  mandates "cite by SYMBOL, never by line number", so the new docstring and comment block
  necessarily name both symbols in text. The gate and the plan's own citation requirement are in
  direct conflict — this is the same class of defect as the known tab-gate false-failure pattern
  (whole-file scans instead of added-diff-line scans).
- **Resolution:** Re-ran the gate restricted to code occurrences (`def <sym>` or `self.<sym>`):
  ```
  supplied: 2    from: 4
  ```
  Exactly the plan's intended counts. Definition + one call for `_portfolio_id_supplied`;
  definition + one call in `_add_strategy_verb` + two in the light verbs for `_portfolio_id_from`.
  No production code was changed to satisfy the gate, and no test or gate was weakened.
- **Note:** `grep -E '\s'` does not work under BSD grep on macOS (silently undercounts); use
  `[[:space:]]`.

No other deviations. No Rule 4 architectural decisions were needed. Zero new dependencies.

## Verification Results

| Gate | Result |
|------|--------|
| `mypy --strict` over `itrader` | **Success: no issues found in 251 source files** |
| `tests/unit/strategy` + `tests/unit/core/test_exceptions.py` | **367 passed** |
| Verb suite (`test_strategy_command_verbs.py`) | **61 passed** (was 51; +10 parametrized cases) |
| Byte-exact backtest oracle | **3 passed** — 134 trades (`trades.csv` 135 lines incl. header), final equity `46189.8773072745` |
| Indentation — `manager.py` (TABS) | 0 space-indented lines added (added-diff-lines only) |
| Indentation — test file (4-SPACE) | 0 tab-indented lines added (added-diff-lines only) |
| CR-01 zone-1 guard | No diff hunk inside the `try` / `except (StrategyAdmissionError, ValueError)` / `except Exception` block |

The oracle result is the expected one: this change is live-control-plane-only and backtest-dark —
no backtest path emits a `STRATEGY_COMMAND` verb — so byte-exactness confirms nothing unintended
was touched. No re-baselining occurred.

## Threat Model Outcome

- **T-qfs-01 (silent DoS, high, mitigate)** — Closed. The malformed add is now a loud refusal that
  creates no state.
- **T-qfs-02 (info disclosure, low, mitigate)** — Honored. The warning names `event.strategy_name`
  and the condition only; it never echoes the operator-supplied `portfolio_id` value.
- **T-qfs-03 (halt latch, high, accept)** — Holds. The new arm warns and returns, raises nothing,
  and sits outside the zone-1 guard, which is byte-unchanged.
- **T-qfs-04 (dependency tampering, low, accept)** — No package installs, no `poetry` change, zero
  new dependencies. No Package Legitimacy Audit required.

No new threat surface was introduced — no new endpoint, auth path, file access, or schema change.

## Known Stubs

None.

## Commits

| Task | Type | Commit | Description |
|------|------|--------|-------------|
| 1 | test | `6538dc6f` | Failing WR2-01 malformed-reject test + 5 behavior pins (RED) |
| 2 | fix | `cf442de3` | `_portfolio_id_supplied` probe + early reject gate + parse reuse (GREEN) |

Task 3 was gates-only and produced no code changes, so it carries no commit.

## Self-Check: PASSED

- `itrader/strategy_handler/lifecycle/manager.py` — FOUND
- `tests/unit/strategy/test_strategy_command_verbs.py` — FOUND
- Commit `6538dc6f` — FOUND
- Commit `cf442de3` — FOUND
