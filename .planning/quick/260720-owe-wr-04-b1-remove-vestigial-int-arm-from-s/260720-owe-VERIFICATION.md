---
phase: quick-260720-owe
verified: 2026-07-20T00:00:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: No — initial verification
---

# Quick Task 260720-owe: Remove the Vestigial int Arm from subscribed_portfolios (WR-04) — Verification Report

**Task Goal:** WR-04 B1 — remove the vestigial `int` arm from `subscribed_portfolios` in iTrader.
**Verified:** 2026-07-20
**Status:** passed
**Commits reviewed:** `7adfcfa5` (fixtures) → `d2b96089` (narrowing) → `c29ea3c2` (comments), baseline `1c747356`

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `Strategy.subscribed_portfolios` is a homogeneous `list[PortfolioId]`; the vestigial `int` arm is gone from every strategy-domain source file | VERIFIED | `git diff 1c747356 c29ea3c2 -- itrader/strategy_handler/base.py` shows `list[PortfolioId | int]` → `list[PortfolioId]`; `subscribe_portfolio`/`unsubscribe_portfolio` params narrowed to `PortfolioId` |
| 2 | `StrategyLifecycleManager.portfolio_read_model` is declared as the real `PortfolioReadModel` protocol, so mypy actually checks `get_position` in `_strategy_is_flat` | VERIFIED | `manager.py` diff: `Optional[Any]` → `Optional[PortfolioReadModel]` for both param and attribute; module-top import added; SUMMARY's deliberate-break test (reverted before commit) is consistent with this wiring |
| 3 | A non-UUID portfolio subscription id reaches each resolver's pre-existing loud-failure arm; failure semantics unchanged (rehydrate raises `StrategyConfigError`, manager returns `None`) | VERIFIED | `rehydrate.py` diff: second `int(raw)` parse deleted, `except` now falls straight to the existing `raise StrategyConfigError(...) from exc`; `manager.py` diff: second parse deleted, falls straight to existing `return None` |
| 4 | The fan-out constructs `SignalEvent.portfolio_id` with no bridging cast | VERIFIED | `strategies_handler.py` diff: `cast(PortfolioId, portfolio_id)` → `portfolio_id`; `cast` import removed; `grep -c 'cast' itrader/strategy_handler/strategies_handler.py` = 0 |
| 5 | Every surviving String-column justification cites serialization, never the removed arm | VERIFIED | All 4 comment sites (`strategy_registry_store.py` x2, `test_strategy_registry_store.py`, `strategy_catalog.py`, migration) rewritten to cite `str(pid)`/`rehydrate` round trip; no remaining reference to the union as justification |
| 6 | `mypy --strict` is clean over 273 source files, zero new type-ignore comments, zero widened annotations | VERIFIED | Re-ran `poetry run mypy` → `Success: no issues found in 273 source files`; diffed added lines repo-wide for `type: ignore` → none added |
| 7 | Full gates hold: 2299 unit passed, 204 integration passed + 2 skipped, oracle byte-exact 134 / 46189.87730727451 | VERIFIED | Re-ran independently (see Behavioral Spot-Checks below) — all numbers match exactly |

**Score:** 7/7 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/strategy_handler/base.py` | Homogeneous `list[PortfolioId]`, narrowed mutators | VERIFIED | Confirmed via diff, tab-indentation preserved (0 stray space lines) |
| `itrader/strategy_handler/registry/rehydrate.py` | `_resolve_portfolio_id` returns `PortfolioId` only, second parse deleted | VERIFIED | Confirmed via diff; 7 legitimate space-indented docstring lines preserved unchanged |
| `itrader/strategy_handler/lifecycle/manager.py` | Real `PortfolioReadModel` type, `_portfolio_id_from` narrowed | VERIFIED | Confirmed via diff; module-top import (not `TYPE_CHECKING`), matching DECOMP-02 |
| `itrader/strategy_handler/strategies_handler.py` | No `cast` token | VERIFIED | `grep -c cast` = 0; import list confirms `cast` dropped, `Any`/`Optional`/`TYPE_CHECKING` kept |
| `itrader/storage/strategy_registry_store.py` | Comments cite serialization, not removed arm | VERIFIED | Confirmed via diff; 0 tab-indented lines (space-file integrity preserved) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `base.py` `subscribed_portfolios` element type | `strategies_handler.py` `SignalEvent.portfolio_id` field type | direct assignment, no cast | WIRED | Types now identical (`PortfolioId`); cast removed and mypy clean confirms no mismatch |
| `base.py` `subscribed_portfolios` element type | `manager.py` `_strategy_is_flat` → `PortfolioReadModel.get_position` | real protocol annotation | WIRED | `portfolio_read_model` attribute now typed `Optional[PortfolioReadModel]`; call site is genuinely checked (confirmed by SUMMARY's deliberate-break-then-revert test, and independently by current clean mypy run) |
| `base.py` `to_dict` `str(pid)` serialization | `strategy_portfolio_subscriptions.portfolio_id` String column | rehydrate `_resolve_portfolio_id` parse | WIRED | Round trip intact; all 4 justification comments now correctly describe this path |
| `rehydrate._resolve_portfolio_id` failure arm | `StrategyConfigError` → D-19 quarantine | unchanged raise | WIRED | Confirmed byte-level: exception type, `from exc` chaining, and quarantine path all untouched; only the message text and the removed fallback branch changed |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| mypy strict clean | `poetry run mypy` | `Success: no issues found in 273 source files` | PASS |
| Unit suite | `PYTHONPATH="$PWD" poetry run pytest tests/unit -q` | `2299 passed` | PASS |
| Integration suite | `PYTHONPATH="$PWD" poetry run pytest tests/integration -q` | `204 passed, 2 skipped` (OKX creds, pre-existing) | PASS |
| Oracle | `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -v` | `3 passed` (behavioral identity, numeric values, signal-store non-empty) | PASS |
| Repo-wide union survivors | `grep -rn 'PortfolioId | int' --include='*.py' .` | exactly 2 hits: `transaction.py:36`, `position.py:44` | PASS |
| No new `type: ignore` | diff of added lines repo-wide for `type: ignore` | 0 added | PASS |
| Bare-int test fixtures | `grep -rEn 'subscribe_portfolio\([0-9]' tests/` | 0 | PASS |
| Migration comment-only | `git diff 1c747356 c29ea3c2 -- migrations/versions/p10_strategy_portfolio_subs.py` | 1 file, 3 insertions/1 deletion, all within a comment block; no `sa.Column`/`op.create_table`/`revision`/`down_revision` line changed | PASS |
| Indentation cross-contamination guard | measured tab/space counts per touched file vs. `1c747356` baseline | space-count in tab files stays 0 (base.py, manager.py, strategies_handler.py) or 7 legitimate lines (rehydrate.py, unchanged); tab-count in `strategy_registry_store.py` stays 0. Net line-count deltas (e.g. base.py 867→870, strategies_handler.py 720→715, rehydrate.py 241→237, store 332→333) are attributable to actual code edits, not style contamination | PASS |

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in any of the 15 modified files. No stub returns, no empty handlers introduced.

### Deviation Judgment (item 9 — rehydrate error message text)

The executor changed the `StrategyConfigError` message from `"is neither a UUID nor an int"` to `"is not a UUID"`, deviating from the plan's instruction to keep the message "EXACTLY as they are." Verified:

- `grep -rn "neither a UUID nor an int\|is not a UUID"` across `tests/` and `itrader/` finds the string only at its single definition site in `rehydrate.py` — **no test asserts on this message text**, so the deviation causes no regression.
- The old text was factually stale post-narrowing (it described an "int" arm that no longer exists), so leaving it verbatim would have been actively misleading. The rewrite is a correct, minimal, and disclosed fix to keep the error message truthful.
- Exception type (`StrategyConfigError`), `from exc` chaining, and the D-19 quarantine path are all byte-identical — the substantive failure semantics the plan actually cared about (per must_have #3 and the plan's <done> criteria) are unchanged.

Judgment: acceptable deviation, correctly disclosed in the SUMMARY, no test/behavior impact. Not treated as a gap.

## Requirements Coverage

WR-04 (10.1-REVIEW.md finding) — SATISFIED. The review's cited defect (`portfolio_read_model: Optional[Any]` erasing the `get_position` call-site type check in `_strategy_is_flat`) is closed: the attribute now carries the real `PortfolioReadModel` protocol type, and the union narrowing makes the call genuinely checkable end-to-end.

## Gaps Summary

None. All 9 specific-things-to-confirm items were independently re-measured against the current codebase (not taken from SUMMARY claims) and all passed:

1. Union survives at exactly the 2 named out-of-scope sites — confirmed by direct grep.
2. No `type: ignore` added, union not re-widened — confirmed by diffing added lines.
3. mypy clean over 273 files — re-run, confirmed.
4. Unit suite 2299 passed — re-run, confirmed.
5. Integration suite 204 passed + 2 skipped (pre-existing OKX skips) — re-run, confirmed.
6. Oracle byte-exact 134 / 46189.87730727451 — re-run, confirmed via `test_backtest_oracle.py`.
7. Indentation regression check — no cross-contamination in any of the 5 touched non-test source files; net line-count deltas are attributable to legitimate edits.
8. Migration file edit is comment-only — confirmed by diff (no DDL/revision line touched).
9. Message-text deviation is safe and correctly disclosed — confirmed no test depends on the old string.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
