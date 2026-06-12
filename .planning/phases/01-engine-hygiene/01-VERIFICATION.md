---
phase: 01-engine-hygiene
verified: 2026-06-12T00:00:00Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
---

# Phase 1: Engine Hygiene Verification Report

**Phase Goal:** Close the SAFE hygiene debt — the private-internals test asserts, the stale config/typing residue, and the three v1.2 Phase-6 review leftovers — without touching the run path or the golden numbers.
**Verified:** 2026-06-12
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | `test_position_manager.py` asserts only through public PositionManager query APIs — no `pm._storage` reach remains | VERIFIED | `grep -n "_storage" tests/unit/portfolio/test_position_manager.py` returns no output. All 14 replaced asserts confirmed at lines 62, 63, 79, 80, 118, 135, 136, 148, 149, 354, 361, 362, 393, 426 use `pm.get_all_positions()` / `pm.get_closed_positions()`. |
| 2  | The stale `events_handler.screener_event_handler` mypy override is gone from `pyproject.toml`; the live `screeners_handler.*` wildcard is preserved | VERIFIED | `grep "screener_event_handler" pyproject.toml` returns nothing. `grep "screeners_handler" pyproject.toml` returns line 95 with the live wildcard. |
| 3  | The dead `TOLERANCE = 1e-3` float constant is gone from `portfolio_handler/portfolio.py` | VERIFIED | `grep "TOLERANCE" itrader/portfolio_handler/portfolio.py` returns nothing. |
| 4  | `validate_transaction_data` takes strict `decimal.Decimal` params AND its `isinstance` guards check `decimal.Decimal`, not `(int, float)` | VERIFIED | Lines 22-25 show `price: decimal.Decimal`, `quantity: decimal.Decimal`, `commission: decimal.Decimal`. Lines 36, 39, 42 show `isinstance(..., decimal.Decimal)`. The `(int, float)` at line 77 is in the protected sibling `validate_portfolio_data` — D-07 scope honored. |
| 5  | `order_manager.py` imports no `StrategyId` — verified already removed in prior commit | VERIFIED | `grep "StrategyId" itrader/order_handler/order_manager.py` returns nothing. `order.py` and `bracket_book.py` keep their legitimate uses (protected). |
| 6  | A single public `ONE = Decimal("1")` lives in `core/money.py`; all three local `_ONE` copies are gone and all three consumer modules import the canonical `ONE` | VERIFIED | `grep "ONE = Decimal" itrader/core/money.py` → line 30 confirms canonical public constant. `grep -rn "_ONE" itrader/core itrader/order_handler` returns nothing. All three consumers import via `from itrader.core.money import ONE` (sizing.py:45), `from itrader.core.money import ONE, to_money` (sizing_resolver.py:37), `from ...core.money import ONE` (levels.py:22). |
| 7  | `_ZERO` in `core/sizing.py` is untouched | VERIFIED | `grep "_ZERO" itrader/core/sizing.py` returns lines 59 and 64, confirming `_ZERO = Decimal("0")` untouched (D-05). |
| 8  | The `levels.py` module docstring no longer claims `_ONE` is a module-private constant living in that file | VERIFIED | Docstring (lines 11-14) reads: "The `ONE` constant used by `_bracket_levels` now lives in `core/money.py` as the single canonical public money primitive (D-01/D-03) and is imported here; the former module-private copy was removed." No `_ONE` token remains in prose. |
| 9  | The `reconcile_manager.py` TYPE_CHECKING docstring no longer claims `BracketManager` is not loaded at runtime | VERIFIED | Docstring lines 25-29 read: "The `BracketManager` type is imported only under `TYPE_CHECKING`; this keeps the annotation NAME off the module's runtime name bindings only — it does NOT avoid loading the class, which the runtime `from ..brackets import BracketBook` import (line 41) already pulls in transitively (harmless — no import cycle)." |
| 10 | Golden master byte-exact: 134 trades / `final_equity 46189.87730727451`; e2e 58/58; full suite green; `mypy --strict` clean | VERIFIED | `mypy`: "Success: no issues found in 172 source files". Integration oracle: 12/12 passed (`tests/golden/summary.json` asserts `trade_count: 134`, `final_equity: 46189.87730727451`). e2e: 58/58 passed. Full suite: 851/851 passed. |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/money.py` | Canonical public `ONE` money primitive | VERIFIED | Line 30: `ONE = Decimal("1")` with D-02/D-04 docstring; string-path literal. |
| `tests/unit/portfolio/test_position_manager.py` | Public-API-only position-manager assertions | VERIFIED | All 14 former `pm._storage.*` reaches replaced with `pm.get_all_positions()` / `pm.get_closed_positions()`. 19 tests green. |
| `itrader/portfolio_handler/validators.py` | Strict-Decimal `validate_transaction_data` (signature + `isinstance` guards) | VERIFIED | Lines 22-25: three params typed as `decimal.Decimal`. Lines 36, 39, 42: `isinstance` guards check `decimal.Decimal`. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/core/sizing.py` | `itrader/core/money.py::ONE` | `from itrader.core.money import ONE` | WIRED | Line 45 confirmed; used at line 72 in `if not (_ZERO < value <= ONE)`. |
| `itrader/order_handler/sizing_resolver.py` | `itrader/core/money.py::ONE` | `from itrader.core.money import ONE, to_money` | WIRED | Line 37 confirmed; appended to existing money import. Used at line 161. |
| `itrader/order_handler/brackets/levels.py` | `itrader/core/money.py::ONE` | `from ...core.money import ONE` | WIRED | Line 22 confirmed; used at lines 39-40 in `_bracket_levels`. |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase touches constants, test assertions, type annotations, a docstring, a dead float constant, and a stale config entry. No data-rendering components modified.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 19 position-manager unit tests pass (public API asserts) | `PYTHONPATH="$PWD" poetry run pytest tests/unit/portfolio/test_position_manager.py -q` | 19 passed in 0.07s | PASS |
| mypy --strict clean across 172 source files | `PYTHONPATH="$PWD" poetry run mypy itrader` | "Success: no issues found in 172 source files" | PASS |
| Integration oracle byte-exact | `PYTHONPATH="$PWD" poetry run pytest tests/integration/ -q` | 12 passed in 8.35s | PASS |
| e2e suite 58/58 | `PYTHONPATH="$PWD" poetry run pytest tests/e2e/ -q` | 58 passed in 1.11s | PASS |
| Full suite green | `PYTHONPATH="$PWD" poetry run pytest -q` | 851 passed in 10.43s | PASS |

---

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes declared for this phase. Step 7c: SKIPPED.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| HYG-01 | 01-01-PLAN.md | SAFE engine-hygiene slice: test asserts, stale override, dead constants, validator retype, three v1.2 Phase-6 residues | SATISFIED | All 7 enumerated items verified in codebase; all 4 ROADMAP success criteria verified. |

No orphaned requirements — REQUIREMENTS.md maps only HYG-01 to Phase 1 (traceability table line 139).

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None found | — | No debt markers (TBD/FIXME/XXX), no stubs, no empty implementations in any of the 9 files modified by this phase. |

---

### Human Verification Required

None. All must-haves are mechanically verifiable and confirmed green by automated checks.

---

### Gaps Summary

No gaps. All 10 must-have truths verified against the actual codebase with live command execution.

**Note on SUMMARY.md golden value discrepancy:** The SUMMARY.md reports `final_equity 53229.68512642488` as the oracle value, while the PLAN and the actual `tests/golden/summary.json` both assert `46189.87730727451`. This is a documentation error in the SUMMARY — the actual frozen golden file (`tests/golden/summary.json`) holds `46189.87730727451`, the integration oracle test passed against that file (12/12 green), and there was no run-path behavior change. The discrepancy is in SUMMARY prose only and does not affect phase correctness.

---

_Verified: 2026-06-12_
_Verifier: Claude (gsd-verifier)_
