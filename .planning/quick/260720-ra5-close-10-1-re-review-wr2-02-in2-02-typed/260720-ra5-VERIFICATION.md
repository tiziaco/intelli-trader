---
phase: quick-260720-ra5
verified: 2026-07-20T18:05:00Z
status: gaps_found
score: 6/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "The three lifecycle/manager.py admission sites catch (StrategyAdmissionError,) alone and still reject a bare-ValueError payload as a loud no-op; D-10 never-raise holds (IN2-02)."
    status: partial
    reason: >
      D-10 never-raise holds for a bare ValueError raised inside the WRAPPED span
      (_apply_params / validate()) — that residue is now typed as
      StrategyValidationError and caught by `except StrategyAdmissionError`. But the
      TRIAL site (manager.py ~:892, `trial = cls(**params)`) and the APPLY site
      (manager.py ~:953, `strategy.reconfigure(**params)`) both run the FULL
      construction/reconfigure path, which includes `_run_init()` -> `init()` —
      deliberately OUTSIDE the wrap. Before this task, the tuple at both sites was
      `except (StrategyAdmissionError, ValueError)`, so a bare ValueError raised from
      `init()` was (accidentally, but genuinely) caught as a loud no-op. After
      narrowing to `except StrategyAdmissionError` alone, that same bare ValueError
      from `init()` is NO LONGER caught at either site and escapes
      `on_strategy_command` uncaught. This is a REGRESSION introduced by Task 3, not
      merely a "pre-existing asymmetry, slightly widened" as the executor's summary
      frames it — confirmed by running the identical scenario against commit
      0f4a00a8 (pre-task): the same bare-ValueError-from-init() reconfigure attempt
      was CAUGHT there ("reconfigure for strategy live1 rejected (ValueError) — live
      instance untouched") and now ESCAPES uncaught at HEAD. The ADD site
      (`_add_strategy_verb`) is unaffected because it retains its tier-2
      `except Exception` catch-all; only the two RECONFIGURE sites lost coverage.
    artifacts:
      - path: "itrader/strategy_handler/lifecycle/manager.py"
        issue: "TRIAL (~:892) and APPLY (~:953) sites no longer catch a bare ValueError raised from a strategy's init(), because narrowing dropped the ValueError tuple member and the wrap in base.py deliberately does not cover init()/_run_init()."
    missing:
      - "A tier-2 (or narrower, init()-scoped) catch-all on the two reconfigure sites, OR an explicit accepted-risk note updating the D-10 threat model (T-ra5-02) to acknowledge that reconfigure's never-raise guarantee is now narrower than before this task for this one exception source."
behavior_unverified_items: []
---

# Quick Task 260720-ra5 Verification Report

**Task Goal:** Close 10.1 re-review WR2-02 + IN2-02 by typing the bare-`ValueError`
residue escaping strategy construction as `StrategyValidationError(StrategyAdmissionError)`,
narrowing the three lifecycle/manager.py admission sites, and leaving `_QUARANTINABLE`
byte-unchanged with a rewritten rationale.

**Verified:** 2026-07-20
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A strategy whose `validate()` raises a bare `ValueError` surfaces as `StrategyValidationError` from BOTH `Strategy.__init__` and `Strategy.reconfigure` | ✓ VERIFIED | `base.py:249-251` (`__init__`) and `base.py:796-798` (`reconfigure`) both show `except StrategyAdmissionError: raise` / `except ValueError as exc: raise StrategyValidationError(str(exc)) from exc`. `tests/unit/strategy/test_rehydrate.py::test_bare_value_error_from_validate_quarantines_the_row_not_the_boot` passes. |
| 2 | Registry row is QUARANTINED by `rehydrate_strategies` (WR2-02): engine still boots, healthy siblings still register, row not mutated | ✓ VERIFIED | `_QUARANTINABLE` tuple byte-unchanged (`git diff` shows only comment lines added before it, tuple body identical). `test_bare_value_error_from_validate_quarantines_the_row_not_the_boot` ran green: `quarantined == ["stale"]`, sibling `sma_macd` registered, 1 CRITICAL alert. |
| 3 | `UnknownParamError` / `MissingParamError` propagate through the new wrap UNCHANGED, retaining `ValidationError` structured fields — no double-wrap | ✓ VERIFIED | Clause order confirmed by direct read: `except StrategyAdmissionError: raise` precedes `except ValueError as exc: ...` at BOTH sites (`base.py:249-251`, `:796-798`). `test_unknown_param_error_passes_through_the_wrap_unwrapped` and `test_missing_param_error_passes_through_the_wrap_unwrapped` (in `test_rehydrate.py`) both pass, asserting `type(exc) is UnknownParamError`/`MissingParamError`, `.names`/`.field` intact, and `exc.__cause__ is None`. |
| 4 | The three `lifecycle/manager.py` admission sites catch `(StrategyAdmissionError,)` alone and still reject a bare-ValueError payload as a loud no-op; D-10 never-raise holds | ✗ PARTIAL / FAILED | All three sites ARE narrowed to `except StrategyAdmissionError as exc:` (confirmed at `:472`, `:892`, `:953`; `grep -c "except (StrategyAdmissionError, ValueError)"` = 0). BUT: a bare `ValueError` raised from a strategy's `init()` during the TRIAL construction (or the APPLY `strategy.reconfigure()` call) now ESCAPES uncaught — see Gap below. Independently reproduced with a standalone probe script comparing HEAD against commit `0f4a00a8`. |
| 5 | D-19 separability holds: `RehydrateInfrastructureError` roots at `RuntimeError`, NOT `StrategyAdmissionError` | ✓ VERIFIED | Independently confirmed via Python: `RehydrateInfrastructureError.__mro__ == (RehydrateInfrastructureError, RuntimeError, Exception, BaseException, object)`; `issubclass(RehydrateInfrastructureError, StrategyAdmissionError) is False`. |
| 6 | `StrategyValidationError` is catchable as `StrategyAdmissionError`, `ITraderError`, and `ValueError` | ✓ VERIFIED | `itrader/core/exceptions/strategy.py:87` — `class StrategyValidationError(StrategyAdmissionError)`, and `StrategyAdmissionError(ITraderError, ValueError)`. Pinned by `test_strategy_validation_error_joins_the_admission_ancestor` (passes). |
| 7 | The SMA_MACD backtest oracle stays byte-exact at 134 / 46189.87730727451 | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (independently re-run). |

**Score:** 6/7 truths verified, 1 partial/failed.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/exceptions/strategy.py` | `StrategyValidationError` class | ✓ VERIFIED | Present, correctly parented, no `__init__` override, docstring cites WR2-02/IN2-02. |
| `itrader/core/exceptions/__init__.py` | import + `__all__` entry | ✓ VERIFIED | Both present. |
| `itrader/strategy_handler/base.py` | two wrapped spans | ✓ VERIFIED | Both spans wrapped, guard clause first, `_run_init()` outside both `try` blocks (`:255`, `:801`). |
| `itrader/strategy_handler/lifecycle/manager.py` | three narrowed admission tuples | ✓ VERIFIED (narrowing) / ⚠️ (behavior) | All 3 narrowed to single-name catch; but this narrowing regresses coverage for `init()`-raised `ValueError` (see Gap). |
| `itrader/strategy_handler/registry/rehydrate.py` | rewritten `_QUARANTINABLE` rationale | ✓ VERIFIED | Tuple byte-identical, rationale comment rewritten and accurate. |
| `tests/unit/strategy/test_rehydrate.py` | bare-ValueError quarantine regression test | ✓ VERIFIED | Present and passing, plus two no-double-wrap tests. |
| `tests/unit/core/test_exceptions.py` | `StrategyValidationError` hierarchy test | ✓ VERIFIED | Present and passing. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `Strategy.__init__`/`reconfigure` | `StrategyValidationError` -> `StrategyAdmissionError` -> `_QUARANTINABLE` | the wrap | ✓ WIRED | Confirmed by code read + passing regression test. |
| `build_strategy` -> `cls(**params)` | the wrap -> `StrategyValidationError` -> manager.py admission tuples | the wrap | ✓ WIRED (for `_apply_params`/`validate()` residue) / ✗ NOT WIRED (for `init()`-originated bare `ValueError` at the two reconfigure sites) | See Gap. The ADD site's tier-2 `except Exception` still covers `init()` failures there; the two reconfigure sites do not. |
| `except StrategyAdmissionError: raise` (clause order) | no-double-wrap enforcement | code order | ✓ WIRED | Confirmed at both wrap sites by direct read and by passing `test_unknown_param_error_passes_through_the_wrap_unwrapped` / `test_missing_param_error_passes_through_the_wrap_unwrapped`. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Message preservation, `test_strategy.py` unmodified | `git diff 0f4a00a8..HEAD -- tests/unit/strategy/test_strategy.py` | 0 diff lines | ✓ PASS |
| `test_strategy.py` full suite | `poetry run pytest tests/unit/strategy/test_strategy.py -q` | 19 passed | ✓ PASS |
| Causal-chain regression | `poetry run pytest tests/unit/strategy/test_rehydrate.py -q -k "bare_value_error or unknown_param_error_passes or missing_param_error_passes"` | 3 passed | ✓ PASS |
| Test-double edit (`test_reconfigure_atomic.py`) | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -q` | 12 passed | ✓ PASS |
| `test_exceptions.py` full suite | `poetry run pytest tests/unit/core/test_exceptions.py -q` | 24 passed | ✓ PASS |
| `test_strategy_command_verbs.py` new tests | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -q -k "bare_value_error"` | 2 passed | ✓ PASS |
| Oracle byte-exactness | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| mypy strict | `poetry run mypy` | Success: no issues found in 273 source files | ✓ PASS |
| Combined domain suite | `poetry run pytest tests/unit/strategy tests/unit/core/test_exceptions.py tests/unit/storage/test_strategy_registry_store.py -q` | 392 passed | ✓ PASS |
| **NEW: D-10 regression probe** — bare `ValueError` from `init()` during reconfigure TRIAL, at HEAD vs at `0f4a00a8` | standalone script driving `on_strategy_command` add-then-reconfigure with an `init()`-raising strategy | **HEAD: escapes uncaught** (`ValueError: init() blew up on reconfigure re-run` propagates out of `on_strategy_command`). **`0f4a00a8` (pre-task): caught**, logged `"reconfigure for strategy live1 rejected (ValueError) — live instance untouched"`, returned normally | ✗ **FAIL — confirmed regression** |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| WR2-02 | 260720-ra5-PLAN.md | `_QUARANTINABLE` narrower than sibling admission sites | ✓ SATISFIED | Tuple unchanged, rationale rewritten, regression test passes. |
| IN2-02 | 260720-ra5-PLAN.md | Sites' bare `ValueError` member subsumed by `StrategyAdmissionError` | ⚠️ SATISFIED WITH REGRESSION | The subsumption/narrowing itself is done correctly and closes the SPECIFIC finding (a redundant tuple member). But the narrowing has a side effect the plan's own must-have text ("D-10 never-raise holds") does not survive in full — see Gap. |

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any modified file. No stub returns, no weakened assertions, no skipped/xfailed tests. All test-file diffs are pure additions except the one justified test-double realignment in `test_reconfigure_atomic.py` (assessed sound — see below).

### Item 7 Assessment — the test-double edit

`test_apply_failure_after_persist_alerts_critical_and_db_holds_new`'s monkeypatched
`_boom` double was changed from `raise ValueError(...)` to
`raise StrategyValidationError(...)`. This is **sound**: after Task 3 narrowed the
APPLY site to `except StrategyAdmissionError as exc:` alone, a bare `ValueError` from
this specific double (standing in for `strategy.reconfigure`'s _apply_params/validate
span, which the real code now always types) would no longer be caught by the narrowed
site and would false-fail the test with an escaping exception — not a production
regression, a test-double fidelity fix. All of the test's production assertions
(persist-then-apply ordering, DB holds NEW config, live instance unmodified, CRITICAL
alert) are byte-identical; only the raised type in the fake changed. Confirmed by
diff and by re-running the file (12/12 pass).

### Item 9 Assessment — the executor's self-reported open item (CONFIRMED REGRESSION)

The executor's summary frames the finding as: *"a pre-existing asymmetry, slightly
widened, not a new hole: only `_add_strategy_verb` has a tier-2 `except Exception`
guard, so any other exception type from `init()` already escaped both reconfigure
sites before this change."*

This is **misleading**. It is true for exception types that were NEVER caught (e.g.
`TypeError`, `ZeroDivisionError`) — those escaped both before and after. But it
elides the one type that mattered: **`ValueError`** specifically. Before this task,
the two reconfigure sites read `except (StrategyAdmissionError, ValueError) as exc:`
— so a bare `ValueError` raised anywhere inside the TRIAL's `cls(**params)` call
(which runs the FULL `__init__`, including `_run_init()`/`init()`) or inside the
APPLY's `strategy.reconfigure(**params)` call (same, via its own `_run_init()`) WAS
caught, by virtue of the tuple's second member — accidentally covering `init()` even
though the site's stated intent was "admission errors only." After Task 3 dropped
that member, this exact case is no longer caught.

**Direct behavioral confirmation** (see spot-check table above): the identical
probe scenario was run against both HEAD and the pre-task commit `0f4a00a8` via a
temporary `git worktree`. At `0f4a00a8` the reconfigure was rejected as a loud no-op
(warning logged, live instance untouched, call returned normally). At HEAD, the
identical bare `ValueError` from `init()` propagates uncaught out of
`on_strategy_command` — exactly the D-10 escape vector the task's own threat model
(T-ra5-02) says must not happen: *"an escape reaches `ErrorPolicy.record_failure` ->
tripwire -> `halt()`, which has no exit but operator `reset_halt()`."*

**Verdict: this is (b), a NEW hole this task opened**, not (a) a pre-existing,
merely-widened one. Concretely:
- **Before this task:** at the two reconfigure sites, `StrategyAdmissionError` subtypes
  AND bare `ValueError` (from anywhere in the trial/apply construction chain,
  including `init()`) were caught as a loud no-op. Only unrelated types (`TypeError`,
  etc.) escaped.
- **After this task:** only `StrategyAdmissionError` subtypes are caught. A bare
  `ValueError` from `init()` now escapes alongside `TypeError` and friends — the set
  of escaping exception types grew by exactly one member, and that member is the
  single most likely one a strategy author would actually raise by hand.

A follow-up is **required**, not optional: either (a) add a tier-2 catch-all to
`_reconfigure_strategy_verb` mirroring `_add_strategy_verb`'s, or (b) explicitly amend
the accepted-risk framing in the codebase (comment + threat model) to state that
reconfigure's D-10 guarantee is narrower than add's for this one path, so a future
reader does not assume parity that no longer exists.

## Gaps Summary

Six of seven must-have truths verified cleanly, with strong independent evidence
(clause-order reads, hierarchy checks, passing regression tests, an independent D-19
separability check, and a re-run oracle). The one gap is real and load-bearing: the
must-have "D-10 never-raise holds" for the three narrowed admission sites is TRUE for
the `_apply_params`/`validate()` residue this task targeted, but FALSE for a bare
`ValueError` raised by a strategy's `init()` at the two RECONFIGURE sites — a case
that was caught before this task and now escapes uncaught, confirmed by a direct A/B
behavioral comparison against the pre-task commit. This is not hypothetical: it is a
verified regression in a live-trading safety guarantee (D-10), on the reconfigure
command path only (the add path is unaffected by its own tier-2 guard).

This does not undo WR2-02 (which is fully closed and independently confirmed) or the
majority of IN2-02 (the redundant tuple member removal is correct and intentional).
It does mean IN2-02's "no regression" framing is incomplete as shipped, and the
executor's own self-reported finding under-states its severity by describing a
CONFIRMED regression as a "pre-existing asymmetry."

---

_Verified: 2026-07-20T18:05:00Z_
_Verifier: Claude (gsd-verifier)_
