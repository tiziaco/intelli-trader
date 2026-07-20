---
phase: quick-260720-s6b
verified: 2026-07-20T19:10:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: N/A (this task closes a gap FOUND by 260720-ra5-VERIFICATION.md, not a re-verification of a prior s6b VERIFICATION.md)
  previous_score: N/A
  gaps_closed:
    - "260720-ra5 gap: a bare ValueError raised from a strategy's init() during a reconfigure TRIAL or APPLY escaped on_strategy_command uncaught (D-10 regression). Independently reproduced by this verifier at ra5 HEAD; independently confirmed CLOSED at s6b HEAD for ValueError, TypeError, and KeyError at BOTH sites."
  gaps_remaining: []
  regressions: []
behavior_unverified_items: []
---

# Quick Task 260720-s6b: Close the D-10 Reconfigure Escape Verification Report

**Task Goal:** Close the D-10 reconfigure escape that quick task `260720-ra5` opened, by applying
the zone model uniformly to the two reconfigure sites in `manager.py` — TRIAL (zone 1) gets a
km2-style tier-2 loud no-op; APPLY (zone 2) routes arbitrary exceptions into the existing
`_emit_reconfigure_apply_failure` CRITICAL path unchanged.

**Verified:** 2026-07-20T19:10:00Z
**Status:** passed
**Re-verification:** No — this is the first verification of `260720-s6b` (it closes a gap found
in the separate `260720-ra5-VERIFICATION.md` report, not a prior `s6b` verification).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A bare `ValueError` from `init()` during TRIAL is a loud no-op: live instance + DB untouched, nothing escapes `on_strategy_command` | ✓ VERIFIED | Independent A/B probe (script, not the shipped tests) drove `_InitBoomStrategy` with `boom="value_error"` through the real `on_strategy_command` path: no exception propagated; `strategy.boom` stayed `"none"`. Shipped test `test_trial_init_bare_value_error_is_a_loud_no_op` independently confirms `store.get(...) is None` and no `ErrorEvent` on the queue. Both pass. |
| 2 | Arbitrary NON-`ValueError` exceptions (`TypeError`, `KeyError`) from `init()` are caught identically at BOTH sites — coverage that never existed | ✓ VERIFIED | My own standalone probe (independent of the shipped tests) drove all three kinds (`ValueError`/`TypeError`/`KeyError`) through BOTH the TRIAL path (payload-driven) and the APPLY path (monkeypatch-driven, matching the file's established double idiom) against the real `manager.py` code. All six scenarios returned "no-escape" with the apply-site cases producing exactly one CRITICAL `ErrorEvent` on the queue (`error_type == "TypeError"` confirmed directly by draining the queue). This is the exact case `260720-ra5-VERIFICATION.md` flagged as never having existed and the exact case that would fail if only `ValueError` were re-added. |
| 3 | A bare `ValueError` at APPLY routes into `_emit_reconfigure_apply_failure`: CRITICAL `ErrorEvent`, DB HOLDS THE NEW CONFIG, live instance unmodified | ✓ VERIFIED | Code read (`manager.py:1002-1035`): the widened `except Exception as exc:` body is byte-identical to the pre-`s6b` narrow arm's body (`self._emit_reconfigure_apply_failure(event, strategy, exc); return`), and `_emit_reconfigure_apply_failure` itself (`:791-823`) is a zero-diff, untouched CRITICAL-emit-and-return with no rollback. `test_apply_init_bare_value_error_routes_to_the_critical_path` passes and asserts `row["config"]["long_window"] == 120` (new config persisted) + `strategy.long_window == 100` (live unmodified) + exactly one CRITICAL `ErrorEvent`. |
| 4 | `StrategyAdmissionError` subclasses still take their existing arms unchanged: TRIAL WARNING tier-1 (never ERROR tier-2), APPLY byte-identical emit | ✓ VERIFIED | Clause order in the code is `except StrategyAdmissionError as exc:` BEFORE `except Exception as exc:` at both sites (Python tries the narrower/first-matching clause first — `StrategyAdmissionError` instances never fall through to the catch-all). `test_trial_admission_error_still_takes_the_warning_tier` passes, asserting `spy.warnings` non-empty and `spy.errors == []` for a `StrategyValidationError` trial failure. |
| 5 | D-19 zone-2 fail-loud NOT weakened: `registry_store.upsert` stays OUTSIDE the widened APPLY try | ✓ VERIFIED | Direct read of `manager.py:990-1004`: `self.registry_store.upsert(...)` (lines 990-996) sits structurally BEFORE `try: strategy.reconfigure(**params)` (line 1002-1003) — the widened `try` body is the single `reconfigure` call, containing no store code. `test_apply_store_fault_still_propagates` (T6) uses `_RaisingStore` and asserts `pytest.raises(RuntimeError)` around `_reconfigure(...)`, `upsert_calls == 1`, and the live instance unchanged. Passes. |
| 6 | Tier-2 is a genuine fallback, not a shadow — same at add site for reference | ✓ VERIFIED | The pre-existing `_add_strategy_verb` tier-1/tier-2 pair (`manager.py:472/494`) is untouched (zero diff in that region); the new TRIAL arm mirrors its shape and clause order exactly. `test_trial_admission_error_still_takes_the_warning_tier` (T5) proves the tier-2 arm is unreachable when tier-1 matches. |
| 7 | The comments state the VERB-INDEPENDENT policy, cited by SYMBOL, and the backlog todo exists | ✓ VERIFIED | Both arms' rationale comments (`manager.py:909-952`, `:1005-1034`) state the zone-independent rule verbatim ("every D-10 verb that invokes `_run_init` on operator-supplied input carries a zone guard, and the guard's SHAPE FOLLOWS ITS ZONE") and cite collaborators exclusively by symbol (`_add_strategy_verb`, `build_strategy`, `_run_init`, `_emit_reconfigure_apply_failure`, `Strategy.reconfigure`, `StrategyValidationError`) — no line numbers found in either comment block. `.planning/todos/pending/shared-strategy-admission-seam.md` exists with the required front matter and content. |

**Score:** 7/7 truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/strategy_handler/lifecycle/manager.py` | tier-2 TRIAL arm + widened APPLY arm, both with rationale | ✓ VERIFIED | `git diff 68eff52a..HEAD` shows exactly two hunks: the new `except Exception as exc:` block after the trial's existing `except StrategyAdmissionError` (lines ~908-958), and the widened `except Exception as exc:` replacing the narrow `except StrategyAdmissionError` at the apply site (~1004-1035). Nothing else in the file changed. |
| `tests/unit/strategy/test_reconfigure_atomic.py` | 6 new test functions / 8 cases (RED-first) | ✓ VERIFIED | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -q` → 20 passed (12 pre-existing + 8 new: T1(1) + T2(2 parametrized) + T3(1) + T4(2 parametrized) + T5(1) + T6(1) = 8). |
| `.planning/todos/pending/shared-strategy-admission-seam.md` | deferred shared-seam refactor | ✓ VERIFIED | File exists with correct front matter (`status: open`, `source: quick task 260720-s6b`, tags, `resolves_phase: ""`) and substantive body naming the four-finding root cause and the deferred design. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_reconfigure_strategy_verb` TRIAL arm | loud no-op → D-10 never-raise | tier-2 `except Exception` | ✓ WIRED | Confirmed by code read + independent probe + T1/T2. |
| `_reconfigure_strategy_verb` APPLY arm | `_emit_reconfigure_apply_failure` → CRITICAL `ErrorEvent` | widened `except Exception` | ✓ WIRED | Confirmed by code read (call body byte-identical) + independent probe draining the queue + T3/T4. |
| `Strategy.__init__`/`Strategy.reconfigure` | `_run_init()` → `init()` | outside `StrategyValidationError` wrap | ✓ WIRED (unchanged) | `base.py` has ZERO diff in this range (`git diff 68eff52a..HEAD -- itrader/strategy_handler/base.py` empty) — confirms the plan's premise about `_run_init`'s position was not itself altered by this task. |
| `registry_store.upsert` | stays OUTSIDE the widened APPLY `try` | structural code order | ✓ WIRED | Confirmed by direct line read (`:990-1004`) and T6. |

### Independent Behavioral Verification (beyond the shipped tests)

Per the task brief's explicit instruction not to rely on the new tests alone (they were written
by the same agent that wrote the fix), I built a standalone probe script exercising the real
`on_strategy_command` path directly, independent of `test_reconfigure_atomic.py`'s fixtures and
assertions:

| Scenario | Exception kind | Site | Result |
|----------|----------------|------|--------|
| Reconfigure with `init()` raising | `ValueError` | TRIAL | No escape — caught, logged at ERROR |
| Reconfigure with `init()` raising | `TypeError` | TRIAL | No escape — caught, logged at ERROR |
| Reconfigure with `init()` raising | `KeyError` | TRIAL | No escape — caught, logged at ERROR |
| Reconfigure with `reconfigure()` raising (monkeypatch double) | `ValueError` | APPLY | No escape — routed to CRITICAL |
| Reconfigure with `reconfigure()` raising (monkeypatch double) | `TypeError` | APPLY | No escape — routed to CRITICAL; queue drain confirmed one `ErrorEvent(severity=CRITICAL, error_type="TypeError")` |
| Reconfigure with `reconfigure()` raising (monkeypatch double) | `KeyError` | APPLY | No escape — routed to CRITICAL |

This reproduces (and closes) the exact regression `260720-ra5-VERIFICATION.md` documented — that
verification's own probe showed the identical `ValueError`-from-`init()` scenario escaping
uncaught at ra5 HEAD. Re-running the same class of scenario at `s6b` HEAD, plus the two
non-`ValueError` kinds the ra5 gap explicitly called out as never having been covered, shows
nothing escapes at either site.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full atomic-reconfigure test file | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -q` | 20 passed | ✓ PASS |
| Full unit suite | `poetry run pytest tests/unit -q` | 2324 passed (matches claimed 2316 baseline + 8 new) | ✓ PASS |
| Integration: registry restart + oracle + inertness | `poetry run pytest tests/integration/test_strategy_registry_restart.py tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q` | 13 passed | ✓ PASS |
| mypy strict | `poetry run mypy` | Success: no issues in 273 source files (main-checkout count, matches claim) | ✓ PASS |
| Diff scope — do-not-touch files | `git diff 68eff52a..HEAD -- itrader/strategy_handler/base.py itrader/strategy_handler/registry/rehydrate.py` | empty | ✓ PASS |
| Diff scope — SHORT-01/WR2-01/km2 gates | `grep -n "SHORT-01\|except ValueError" manager.py` cross-checked against diff hunks | all occurrences outside the two changed hunks | ✓ PASS |
| Zone-guard count | anchored 2-tab `except Exception as exc:` count | exactly 3 (`:494` add tier-2, `:908` new trial tier-2, `:1004` widened apply) | ✓ PASS |
| Added-line indentation | `git diff -U0 68eff52a..HEAD -- manager.py \| grep added-non-tab-lines` | 0 matches | ✓ PASS |
| Debt markers | `grep -nE "TBD\|FIXME\|XXX" manager.py test_reconfigure_atomic.py` | 0 matches | ✓ PASS |
| Test-diff weakening scan | `git diff 68eff52a..HEAD -- test_reconfigure_atomic.py \| grep '^-'` | 3 removed lines, all refactor-only (import widened, `_reconfigure` delegates to new `_reconfigure_named` helper) — no assertion, skip, or xfail removed | ✓ PASS |
| Commit provenance | `git log --oneline --all \| grep -E "5515d790\|4214cb35\|40d9f214"` | all 3 commits found, matching SUMMARY.md's Self-Check | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| D-10-RECONFIGURE-ESCAPE | 260720-s6b-PLAN.md | Close the reconfigure-path D-10 escape opened by `ra5` | ✓ SATISFIED | All 7 must-have truths verified; independent probe confirms closure for `ValueError`, `TypeError`, `KeyError` at both sites. |

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in either modified source file. No stub returns, no weakened/skipped/xfailed tests. The only test-file line removals are a refactor (import widening + helper delegation), not assertion weakening.

### Human Verification Required

None.

## Gaps Summary

No gaps. All 7 must-have truths from the plan frontmatter are verified against the actual
codebase — not just the shipped tests. I independently reproduced the exact regression scenario
`260720-ra5-VERIFICATION.md` found (a bare `ValueError` from a strategy's `init()` escaping
`on_strategy_command` during reconfigure), confirmed it is now caught at both the TRIAL and APPLY
sites, and additionally drove `TypeError`/`KeyError` through both sites via a standalone probe
independent of the executor's own tests — the coverage-that-never-existed claim holds. D-19's
fail-loud contract for `registry_store.upsert` is structurally unweakened (the store call sits
outside the widened `try`, confirmed by direct line read and by `test_apply_store_fault_still_propagates`).
The tier-2 TRIAL arm is a genuine fallback, not a shadow (confirmed by clause order and
`test_trial_admission_error_still_takes_the_warning_tier`). `do_not_touch` items (`base.py`,
`rehydrate.py`, the `_add_strategy_verb` tier-2, the WR2-01 gate, the SHORT-01 `except ValueError`)
show zero diff. All gates (mypy, unit suite, the three integration files, oracle byte-exactness)
re-ran clean with counts matching the executor's claims. The backlog todo for the shared
admission seam is filed with substantive content.

---

_Verified: 2026-07-20T19:10:00Z_
_Verifier: Claude (gsd-verifier)_
