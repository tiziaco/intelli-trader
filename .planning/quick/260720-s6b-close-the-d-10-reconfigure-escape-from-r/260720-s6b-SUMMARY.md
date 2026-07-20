---
phase: quick-260720-s6b
plan: 01
subsystem: strategy_handler/lifecycle
status: complete
tags: [strategy, admission, exception-policy, D-10, D-13, D-19, zone-guard, TDD]
requires:
  - "itrader/strategy_handler/lifecycle/manager.py::_reconfigure_strategy_verb"
  - "itrader/strategy_handler/lifecycle/manager.py::_emit_reconfigure_apply_failure"
  - "itrader/strategy_handler/base.py::Strategy._run_init"
provides:
  - "zone-1 tier-2 guard at the reconfigure TRIAL site (loud no-op)"
  - "zone-2 widened guard at the reconfigure APPLY site (CRITICAL route)"
  - "permanent regression coverage for both zones incl. NON-ValueError kinds"
affects:
  - "D-10 STRATEGY_COMMAND admission (no arbitrary init() raise can latch HALT)"
tech-stack:
  added: []
  patterns: ["zone-shaped exception guard (km2/CR-01 model) applied verb-uniformly"]
key-files:
  created:
    - .planning/todos/pending/shared-strategy-admission-seam.md
  modified:
    - itrader/strategy_handler/lifecycle/manager.py
    - tests/unit/strategy/test_reconfigure_atomic.py
decisions:
  - "Guard SHAPE follows ZONE, not a single blanket except Exception: zone 1 refuses as a loud no-op, zone 2 routes into the designed CRITICAL path."
  - "No second narrow arm at the APPLY site — both exception classes route to _emit_reconfigure_apply_failure with identical semantics, so a byte-identical narrow arm would be noise."
  - "No try-splitting at the TRIAL site — its existing try body (decode + construct) is the exact scope analog of build_strategy at the add site."
metrics:
  duration: ~25m
  completed: "2026-07-20"
---

# Quick Task 260720-s6b: Close the D-10 Reconfigure Escape Summary

Applied the km2/CR-01 **zone model** uniformly to both `_reconfigure_strategy_verb` sites, so an
arbitrary `init()` exception can no longer escape `on_strategy_command` and latch live trading
into `HALT` — with each guard shaped by its zone rather than one blanket catch.

## What Changed

**`itrader/strategy_handler/lifecycle/manager.py`** (+89 lines, tab-indented, byte-matched):

1. **TRIAL site (zone 1, pre-persist)** — appended a tier-2 `except Exception as exc:` arm after
   the existing `except StrategyAdmissionError` arm: `logger.error(..., exc_info=True)` naming
   only `type(exc).__name__`, then `return`. A loud no-op with the live instance AND the DB
   untouched — the arm sits before `registry_store.upsert`, so returning there persists nothing.
2. **APPLY site (zone 2, post-persist)** — widened `except StrategyAdmissionError as exc:` to
   `except Exception as exc:` with the body byte-identical
   (`_emit_reconfigure_apply_failure(event, strategy, exc)` + `return`). No second narrow arm; no
   change to `_emit_reconfigure_apply_failure` (its `exc` param was already `Exception`).
3. **Policy comments** — both arms now state the VERB-INDEPENDENT rule: *every D-10 verb that
   invokes `_run_init` on operator-supplied input carries a zone guard, and the guard's SHAPE
   follows its zone*. Collaborators are cited by SYMBOL only (`_add_strategy_verb`,
   `build_strategy`, `_run_init`, `_emit_reconfigure_apply_failure`, `Strategy.reconfigure`,
   `StrategyValidationError`) — never by line number — plus the deferred todo by filename.

**`tests/unit/strategy/test_reconfigure_atomic.py`** (+250 lines, 4-space, matched): 6 new test
functions = 8 cases, plus a module-local `_LogSpy` (deliberate clone, documented) and
`_InitBoomStrategy` whose `init()` is *conditionally* armed via a declared `boom` param, so the
initial construction succeeds and only the reconfigure trial raises.

## TDD Evidence (RED was real, not asserted)

RED run before any `manager.py` edit: **6 failed, 14 passed**. Both zones failed for the RIGHT
reason — the exception PROPAGATING out of `on_strategy_command`, not a fixture/import error:

TRIAL site:
```
itrader/strategy_handler/strategies_handler.py:710: in on_strategy_command
itrader/strategy_handler/lifecycle/manager.py:1098: in on_strategy_command
itrader/strategy_handler/lifecycle/manager.py:891: in _reconfigure_strategy_verb   <- trial = cls(**params)
itrader/strategy_handler/base.py:255: in __init__
itrader/strategy_handler/base.py:499: in _run_init
E       ValueError: arbitrary failure inside user-authored init()
```

APPLY site:
```
itrader/strategy_handler/lifecycle/manager.py:952: in _reconfigure_strategy_verb   <- strategy.reconfigure(**params)
E       KeyError: 'arbitrary failure out of _run_init -> init()'
```

Note the trial trace passes through `_run_init` (`base.py:499`) — confirming the raise is a BARE
`ValueError`, outside the `StrategyValidationError` wrap, which is exactly why the narrowed
`except StrategyAdmissionError` could not see it.

RED was run with `PYTHONPATH="$PWD"` (worktree); mypy reported **251 source files**, the worktree
count, confirming the tests exercised this tree and not the main checkout via the editable
`.venv` (a false-green would also have faked the RED).

GREEN: **20 passed** in the same file.

## Gates

| Gate | Result |
|------|--------|
| `mypy` | Success, no issues in **251** source files (worktree count) |
| `pytest tests/unit` | **2324 passed** = 2316 baseline + exactly 8 new cases; no new failure or skip |
| `test_strategy_registry_restart.py` + `test_backtest_oracle.py` + `test_okx_inertness.py` | 13 passed |
| Oracle | **BYTE-EXACT: trade_count 134 / final_equity 46189.87730727451** (fresh run compared to golden) |
| Indentation | 0 space-indented lines ADDED to the tab file (added-diff-lines scan, not whole-file) |
| Zone-guard count | anchored 2-tab `except Exception as exc:` == **3** (add tier-2 untouched, new trial tier-2, widened apply) |
| Backlog todo | filed |

## Invariants Held

- **Tier-2 is a genuine fallback, not a shadow** (T5): a `StrategyValidationError` from the trial
  still takes the tier-1 WARNING arm and never reaches the ERROR tier — `spy.errors == []`.
- **D-19 zone-2 fail-loud unweakened** (T6): `registry_store.upsert` stays OUTSIDE the widened
  `try`, whose body is the single `strategy.reconfigure(...)` call. A `_RaisingStore` fault still
  propagates as `RuntimeError` out of the verb, with `upsert_calls == 1`.
- **D-13 asymmetry preserved**: apply-stage failure emits CRITICAL and does NOT roll back — the DB
  holds the NEW config (`long_window == 120`) while the live instance is unmodified
  (`long_window == 100`).
- **T-s6b-03 (information disclosure)**: both arms name `type(exc).__name__` only, never payload
  values — the P8 declared-fields-only precedent. An arbitrary `init()` message may quote operator
  config, so it is never echoed.
- **`<do_not_touch>` respected**: `git diff --stat` against the base shows only the three expected
  files. `base.py` and `rehydrate.py` have a zero-line diff. The only lines REMOVED from
  `manager.py` are the APPLY arm's own clause + its superseded comment — `_add_strategy_verb`'s
  km2/CR-01 guard, the WR2-01 portfolio_id gate, the SHORT-01 `except ValueError`,
  `RehydrateInfrastructureError`, `_QUARANTINABLE`, and the `StrategyValidationError` wrap are all
  untouched.

## Deviations from Plan

None — the plan executed exactly as written. Every pre-flight claim it made about the code held
on inspection (both zone characterizations, `_emit_reconfigure_apply_failure` being a
CRITICAL-emit-and-return with an `Exception`-typed param, `_run_init` sitting outside both
`base.py` wraps, and the pure-tab / 4-space indentation split).

One plan instruction was correctly non-applicable as written: its `<pre_flight_verification>`
says "this is the MAIN checkout, so no `PYTHONPATH` prefix is required". Execution happened in a
worktree, so `PYTHONPATH="$PWD"` was prepended to every pytest/mypy call per the plan's own
worktree clause and the executor brief. This is the documented conditional, not a deviation.

## Known Stubs

None.

## Threat Flags

None — no new network endpoint, auth path, file access pattern, or schema change. The task adds
zero dependencies (`pyproject.toml` untouched), so the v1.8 inertness gate is unaffected;
`test_okx_inertness.py` is green.

## Follow-up Filed

`.planning/todos/pending/shared-strategy-admission-seam.md` — the shared admission seam that would
own the zone-1/zone-2 guard shapes ONCE, so policy stops being duplicated per call site (the root
cause behind the `ljn` / CR-01 / WR2-02 / `s6b` series). Deferred as a phase, candidate after
Phase 11.

## Self-Check: PASSED

- `itrader/strategy_handler/lifecycle/manager.py` — FOUND (modified, committed `4214cb35`)
- `tests/unit/strategy/test_reconfigure_atomic.py` — FOUND (modified, committed `5515d790`)
- `.planning/todos/pending/shared-strategy-admission-seam.md` — FOUND (created, committed `40d9f214`)
- Commits `5515d790`, `4214cb35`, `40d9f214` — all FOUND in `git log`
