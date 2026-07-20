---
phase: quick/260720-qfs
verified: 2026-07-20T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Quick Task 260720-qfs: Close 10.1 Re-Review WR2-01 Verification Report

**Task Goal:** A malformed (supplied-but-unparseable) `portfolio_id` on `add` now rejects
the whole add (warn + return, nothing constructed/registered/persisted), while an absent
`portfolio_id` stays a legal, silent no-op (D-09).

**Verified:** 2026-07-20
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Malformed `portfolio_id` on `add` rejects the whole add: nothing constructed/registered/persisted, exactly one warning | VERIFIED | `manager.py:446-456` gate; `test_add_with_a_malformed_portfolio_id_rejects_the_whole_add` (4 params: `"7"`, `"not-a-uuid"`, `""`, `7`) — all 4 PASS, independently re-run |
| 2 | Absent `portfolio_id` (key missing OR explicit `null`) stays a silent legal no-op — registered, persisted, `subscribed_portfolios == []`, poll emitted, zero warnings | VERIFIED | `test_add_without_a_portfolio_id_is_registered_and_silent`, `test_add_with_an_explicitly_null_portfolio_id_is_registered_and_silent` — both PASS |
| 3 | Valid UUID `portfolio_id` on `add` unchanged: registered, persisted, one subscription row, zero warnings | VERIFIED | `test_add_with_a_valid_portfolio_id_subscribes_and_is_silent` PASS |
| 4 | `subscribe_portfolio` / `unsubscribe_portfolio` on malformed input are byte-unchanged: warn + ignore, strategy stays registered | VERIFIED | diff shows zero hunks touching lines 1126-1154 (the light-verb arms); `test_the_light_portfolio_verbs_keep_warn_and_ignore_on_a_malformed_id` (both verbs) PASS |
| 5 | `_add_strategy_verb` never raises into the queue (D-10); the new arm warns and returns; CR-01 zone-1 guard untouched | VERIFIED | new gate is pure dict reads (no raise); `git diff` shows only 3 hunks (325-359 new helper, 392-433 new gate, 494-508 comment rewrite) — none overlap the `try`/`except (StrategyAdmissionError, ValueError)`/`except Exception` block around `build_strategy` |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Ordering Trace (item 1 of the request)

Read the full body of `_add_strategy_verb` (`manager.py:356-574`) statement-by-statement:

1. `strategy_catalog is None` gate (D-10 access control)
2. `strategy_type` string-presence gate
3. D-02 duplicate-name gate (`any(existing.name == ... )`)
4. **WR2-01 gate** (`manager.py:446-456`) — `portfolio_id = self._portfolio_id_from(event)`; reject if `None` and `_portfolio_id_supplied(event)` is `True`
5. `blob`/`rec` dict construction (feeds `build_strategy`)
6. `build_strategy(...)` inside the CR-01 two-tier guard
7. F-1 warmability gate
8. `self._managed.add_strategy(strategy)` (line 554)
9. `strategy.subscribe_portfolio(portfolio_id)` (reuses the handle from step 4, line 567)
10. `self._persist_strategy(strategy, event)` (line 569)
11. `self.registry_store.add_portfolio_subscription(...)` (line 571)
12. `self.global_queue.put(UniversePollEvent(...))` (line 574)

The gate sits at step 4 — after the D-02 duplicate check, before blob construction,
before `build_strategy`, before `add_strategy`, before `_persist_strategy`. A reject at
step 4 cannot leave anything partially registered or persisted because none of steps
5-12 have run yet. CONFIRMED as claimed.

### D-10 Never-Raise / CR-01 Guard Integrity (item 2)

- The new gate (`_portfolio_id_from` call + `_portfolio_id_supplied` call + `logger.warning`
  + `return`) performs only dict reads (`isinstance`, `.get`) and a UUID parse wrapped in a
  `try/except (ValueError, AttributeError, TypeError)` already inside `_portfolio_id_from` —
  it cannot raise into the caller.
- The gate sits textually and structurally OUTSIDE both tiers of the CR-01 guard: it runs
  at lines 446-456, the guard's `try:` starts at line 470 (`build_strategy(rec, ...)`),
  with `except (StrategyAdmissionError, ValueError)` at 472 and `except Exception` at 487.
- Diffed `cf442de3` (the fix commit) against its parent (`git show cf442de3 -- manager.py`):
  three hunks only — new helper (lines 328-354), new gate (lines 423-456), and a comment
  rewrite at the subscribe site (554-565, replacing the stale "parsed here" comment with
  "parsed above, reused here"). Zero lines inside the `try`/`except`/`except` block were
  touched. Guard NOT widened or restructured — CONFIRMED.

### Absent Still Works (item 3)

- Code: `_portfolio_id_supplied` returns `False` when the key is absent (`config.get(...)
  is not None` is `False` when the key is missing → `.get` returns `None`). The gate's
  condition `portfolio_id is None and self._portfolio_id_supplied(event)` is then `None
  and False` → `False` → no reject. The `add` proceeds through construction, `add_strategy`,
  the `if portfolio_id is not None:` subscribe skip, `_persist_strategy`, and the poll.
- Test: `test_add_without_a_portfolio_id_is_registered_and_silent` — omits the
  `portfolio_id` key entirely, asserts `added is not None`, `subscribed_portfolios == []`,
  `store.get(...) is not None`, `portfolio_subscriptions(...) == []`, queue holds exactly
  one `UniversePollEvent`, `spy.warnings == []`. PASSES independently re-run.

### The Null Decision (item 4)

- Code: `_portfolio_id_supplied` returns `config.get("portfolio_id") is not None` — an
  explicit `None` value makes this `False` (not supplied), matching the plan's design
  exactly. Docstring (lines 345-349) states the FastAPI/Pydantic `str | None = None`
  rationale verbatim as required.
- Test: `test_add_with_an_explicitly_null_portfolio_id_is_registered_and_silent` sets
  `config["portfolio_id"] = None` explicitly (distinct from omitting the key) and asserts
  identical behavior to the absent case — registered, persisted, poll emitted, zero
  warnings. PASSES independently re-run. This is a dedicated test, not a reuse of the
  absent-key test.

### Light Verbs Unchanged (item 5)

- `git diff 2002be87..HEAD -- itrader/strategy_handler/lifecycle/manager.py` shows exactly
  3 hunks (line ranges 325-359, 392-433, 494-508 in the diff's post-image numbering). None
  overlaps `on_strategy_command`'s `subscribe_portfolio` (lines 1126-1139) or
  `unsubscribe_portfolio` (lines 1140-1154) arms — both still call `self._portfolio_id_from
  (event)` directly and warn unconditionally on `None`, with no reject/roster-removal path.
- Drift-pin test `test_the_light_portfolio_verbs_keep_warn_and_ignore_on_a_malformed_id`
  (parametrized over both verbs, malformed `{"portfolio_id": "7"}`) asserts the strategy
  STAYS in the roster (`[s.name for s in handler.strategies] == [_NAME]`), no subscription
  written, exactly one warning. PASSES independently re-run.

### No Weakened Tests (item 6)

- `git diff 2002be87..HEAD --shortstat -- tests/unit/strategy/test_strategy_command_verbs.py`
  → `1 file changed, 152 insertions(+)` — **zero deletions**. Every changed line in the test
  file is a pure addition; no pre-existing assertion was touched, loosened, skipped, or
  removed. Confirmed by reading the full diff: the only content is five new test functions
  (one parametrized ×4, one parametrized ×2) appended after
  `test_add_of_a_pair_strategy_succeeds`.
- `manager.py` shows `69 insertions(+), 5 deletions(-)` — the 5 deletions are exactly the
  old re-parse line + its 4-line stale comment at the subscribe site, replaced by a 6-line
  comment (net +1 line there); no test assertions live in this file.

### The Defect Is Actually Dead (item 7)

- Independently re-ran (not trusting the SUMMARY's quoted output) the exact scenario
  described in the task goal — `add` with `{"portfolio_id": "7"}` — via
  `test_add_with_a_malformed_portfolio_id_rejects_the_whole_add[7_0]`:
  ```
  tests/unit/strategy/test_strategy_command_verbs.py::test_add_with_a_malformed_portfolio_id_rejects_the_whole_add[7_0] PASSED
  ```
  The test asserts (and the pass confirms): `[s.name for s in handler.strategies] == []`
  (nothing registered), `store.get("malformed_pid") is None` (nothing persisted),
  `store.portfolio_subscriptions("malformed_pid") == []` (no child row), queue drained to
  `[]` (no `UniversePollEvent`), exactly one warning, zero errors. The original failure
  mode — a registered, persisted, zero-subscription strategy silently fanning to nobody —
  cannot occur for `{"portfolio_id": "7"}` in the current tree. CONFIRMED DEAD.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/strategy_handler/lifecycle/manager.py` | new `_portfolio_id_supplied` helper + early reject gate + parse reuse | VERIFIED | present, wired, exactly matches plan's placement/behavior spec |
| `tests/unit/strategy/test_strategy_command_verbs.py` | 5 new test functions (10 parametrized cases) | VERIFIED | present, all pass, zero deletions from pre-existing tests |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| WR2-01 gate | D-02 duplicate check | statement ordering | WIRED | gate at line 446, duplicate check ends at line 421 — gate strictly after |
| WR2-01 gate | `build_strategy`/CR-01 guard | statement ordering | WIRED | gate at 446-456, guard `try:` begins at 470 — gate strictly before and outside |
| Subscribe-site `if portfolio_id is not None` | WR2-01 gate | variable reuse, not re-parse | WIRED | `_portfolio_id_from` called exactly once in `_add_strategy_verb` (grep confirms) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Malformed `add` scenarios (4 params) reject | `pytest ... -k portfolio_id -v` | 11 passed | PASS |
| mypy --strict | `PYTHONPATH="$PWD" poetry run mypy` | "Success: no issues found in 273 source files" | PASS |
| Strategy + exceptions suite | `PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy tests/unit/core/test_exceptions.py -q` | 367 passed | PASS |
| Byte-exact oracle | `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| WR2-01 | `260720-qfs-PLAN.md` | Malformed `portfolio_id` on `add` must reject the whole add; absent must stay silent legal no-op | SATISFIED | gate present, wired, tested; defect scenario independently reconfirmed dead |

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in the diffed hunks. No
empty implementations, no hardcoded-empty stub patterns, no console-log-only bodies.

### Human Verification Required

None. All must-haves are code-observable (dict-read logic, statement ordering, diff
scoping) and are backed by passing automated tests re-run independently by this verifier,
not merely quoted from the SUMMARY.

### Gaps Summary

No gaps. All 5 must-have truths, all 3 key links, and all 7 specifically requested
verification items were independently confirmed against the actual codebase (not the
SUMMARY's claims): statement ordering traced by reading the method; the CR-01 guard's
integrity confirmed by diffing the fix commit against its parent; the absent/null/valid-UUID
paths traced through the code and re-run via tests; the light verbs' arms confirmed
untouched by diff-hunk-range comparison; the test file diff confirmed zero-deletion (no
weakened tests); and the original defect scenario (`{"portfolio_id": "7"}` on `add`)
independently re-run and confirmed to no longer produce a registered/persisted
zero-subscription strategy. All three gates (mypy, strategy+exceptions suite, byte-exact
oracle) were re-run fresh by this verifier and matched the SUMMARY's claims exactly.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
</content>
