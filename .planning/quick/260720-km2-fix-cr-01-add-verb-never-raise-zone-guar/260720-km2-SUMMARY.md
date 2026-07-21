---
phase: quick-260720-km2
plan: 01
subsystem: strategy-handler / live-control-plane
tags: [strategy, live-control-plane, error-handling, halt, admission, d-10, cr-01, security-adjacent]
requires:
  - "itrader/strategy_handler/registry/rehydrate.py::build_strategy (unchanged)"
provides:
  - "_add_strategy_verb never-raise contract now holds for ANY construction failure"
affects:
  - "live STRATEGY_COMMAND `add` ingress (D-10) — a bad payload can no longer latch HALT"
tech-stack:
  added: []
  patterns:
    - "zone-based exception guard: untrusted-payload zone guarded broadly, store/emit zone stays fail-loud"
    - "collaborator log spy instead of caplog (ITRADER_DISABLE_LOGS false-green hazard)"
key-files:
  created: []
  modified:
    - itrader/strategy_handler/lifecycle/manager.py
    - tests/unit/strategy/test_strategy_command_verbs.py
    - .planning/todos/completed/add-verb-valueerror-escape-halt-latch.md
decisions:
  - "Zone-based guard (Option B) over a wider catch tuple — init() is arbitrary user code, so the escaping exception set is unbounded by construction"
  - "Two tiers: expected validation kinds -> WARNING; any other Exception -> ERROR with exc_info=True"
  - "Zone 2 (register/persist/emit) deliberately left raising — D-19 fail-loud"
  - "TypeError question answered: subsumed by the tier-2 zone guard, no separate decision"
metrics:
  duration: 12min
  completed: "2026-07-20"
status: complete
---

# Quick Task 260720-km2: Fix CR-01 — `add` verb never-raise zone guard Summary

Closed the never-raise contract hole in `_add_strategy_verb` with a two-tier zone-1 guard, so a
routine bad operator `add` payload can no longer escape as a raise and latch live trading into HALT.

## What Changed

**`itrader/strategy_handler/lifecycle/manager.py`** (TAB-indented — preserved) — edits confined to the
`build_strategy` try/except and the `_add_strategy_verb` docstring:

- **Tier 1:** appended `ValueError` to the existing catch tuple (`UnknownStrategyTypeError`,
  `StrategyConfigError`, `UnknownParamError`, `MissingParamError`), matching the sibling reconfigure
  site at `manager.py:764-770` which already lists it last. The `logger.warning` body — naming
  `type(exc).__name__` and never payload values (P8 declared-fields-only) — is byte-identical.
- **Tier 2:** new `except Exception as exc:` arm → `logger.error(..., exc_info=True)` + `return`.
  Still a loud no-op, but at a tier visibly distinct from operator junk.
- A decision-anchored comment encodes all four required points: the CR-01/D-10 halt-latch chain, why
  no finite tuple suffices, why this does not violate the "never a bare except" doctrine (that
  doctrine governs zone 2), and why the ERROR tier is separate.
- Docstring extended to state the never-raise contract holds for ANY construction failure.

**`tests/unit/strategy/test_strategy_command_verbs.py`** (4-SPACE — preserved) — added `_LogSpy`,
`_BoomStrategy`, and three regression tests.

**Todo** moved `pending/` → `completed/`, `status: resolved`, with a Resolution section.

## Deviations from Plan

**1. [Rule 2 — correctness/clarity] Rewrote the tier-1 comment instead of leaving it byte-identical**

- **Found during:** Task 2
- **Issue:** The plan said the tier-1 arm's body stays byte-identical. Its existing comment ended
  with *"Caught by SPECIFIC type, never a bare except: a store/driver fault must not be silently
  eaten."* Leaving that sentence directly above a new `except Exception` arm would read as a
  self-contradiction and is precisely the kind of thing that invites a future reader to revert the
  fix — the outcome the plan's comment requirement exists to prevent.
- **Fix:** Kept the load-bearing semantics (loud no-op, error KIND only, P8 precedent) and relabelled
  it "Tier 1 — EXPECTED validation kinds"; the doctrine discussion now lives in the tier-2 comment
  where it is correctly scoped to zone 2. The `logger.warning` CALL itself is byte-identical, which
  is what the plan's threat-model item T-km2-02 actually protects.
- **Files modified:** `itrader/strategy_handler/lifecycle/manager.py`
- **Commit:** `b2479e0d`

No other deviations. Nothing from `<out_of_scope>` was touched; the two reconfigure sites at
`manager.py:764-770` and `824-829` were read for message form only and are unedited.

## TDD Gate Compliance

RED and GREEN gates both observed, in separate commits:

- **RED** (`77d9fe0b`, `test(...)`): all three new tests failed, and failed for the RIGHT reason —
  verified by reading the tracebacks. Tests 1–2 showed `ValueError` escaping `manager.py:392`
  (`base.py:292` "tickers must be a non-empty list[str]" and `SMA_MACD_strategy.py:42`
  "short_window must be < long_window"); test 3 showed `ZeroDivisionError` escaping the same line.
  No setup-shaped `KeyError`/`AttributeError`. The other 49 tests in the file passed throughout.
- **GREEN** (`b2479e0d`, `fix(...)`): all three pass, no other test changed state.

No REFACTOR commit — none was needed.

## Verification Results

| Gate | Result |
|------|--------|
| `tests/unit/strategy` | **337 passed** (was 334 + 3 new) |
| `tests/unit` (full) | **2290 passed** |
| `tests/integration` (full) | **204 passed, 2 skipped** (OKX demo creds absent — pre-existing env skips) |
| `tests/integration/test_backtest_oracle.py` | **3 passed** |
| Oracle value (read from `output/summary.json`) | `trade_count: 134`, `final_equity: 46189.87730727451` — **byte-exact** |
| `poetry run mypy` | **Success: no issues found in 273 source files** — clean, no pre-existing errors surfaced |
| `git diff --check` | clean — no whitespace damage, tabs preserved in `manager.py`, spaces in the test file |
| Zone 2 byte-unchanged | Confirmed by reading `git diff itrader/`: the only hunks are the docstring and the `build_strategy` try/except. `add_strategy`/SHORT-01 guard, `_persist_strategy`, `add_portfolio_subscription`, `global_queue.put`, and the F-1 warmability gate are untouched. |

`poetry run pytest` was used throughout; `make test` was deliberately avoided (it exports
`ITRADER_DISABLE_LOGS=true`).

## Known Stubs

None.

## Threat Flags

None — no new network endpoint, auth path, file access, or schema change. T-km2-04 holds:
`strategy_type` still resolves only through the injected closed-dict catalog, and the new
`except Exception` arm sits AFTER resolution so it cannot widen what is instantiable.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 (RED) | `77d9fe0b` | `test(km2-01): add failing CR-01 regression tests for the add-verb never-raise hole` |
| 2 (GREEN) | `b2479e0d` | `fix(km2-02): close the CR-01 never-raise hole in _add_strategy_verb (zone-1 guard)` |
| 3 | `a4ba89cd` | `docs(km2-03): resolve the add-verb ValueError-escape backlog todo` |

## Self-Check: PASSED

- `itrader/strategy_handler/lifecycle/manager.py` — FOUND
- `tests/unit/strategy/test_strategy_command_verbs.py` — FOUND
- `.planning/todos/completed/add-verb-valueerror-escape-halt-latch.md` — FOUND
- `.planning/todos/pending/add-verb-valueerror-escape-halt-latch.md` — correctly ABSENT
- Commits `77d9fe0b`, `b2479e0d`, `a4ba89cd` — all present in `git log`
