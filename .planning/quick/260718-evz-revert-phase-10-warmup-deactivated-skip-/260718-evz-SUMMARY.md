---
phase: quick-260718-evz
plan: 01
subsystem: price_handler/feed + strategy_handler/registry
status: complete
tags: [revert, warmup, rehydrate, WR-01, WR-02, IN-01, phase-10-re-review]
requires: []
provides:
  - "derive_warmup_depth sizes the warmup ring from ALL registered strategies (active + disabled) again"
  - "WR-02 uniform-quarantine rationale documented at the rehydrate warmability check"
affects:
  - itrader/price_handler/feed/cache_registration.py
  - tests/unit/price_handler/test_cache_registration.py
  - itrader/strategy_handler/registry/rehydrate.py
tech-stack:
  added: []
  patterns: [git-driven reverse-patch revert, regression-pinned pre-provisioning guarantee, doc-only rationale anchor]
key-files:
  created: []
  modified:
    - itrader/price_handler/feed/cache_registration.py
    - tests/unit/price_handler/test_cache_registration.py
    - itrader/strategy_handler/registry/rehydrate.py
decisions:
  - "Reverted 40e73430 via `git show -R | git apply` (not `git revert`) so it stages as normal working-tree edits with no revert-sequencer state — the two files were touched by exactly that commit, unentangled with abd74861's rehydrate quarantine, and nothing touched them since"
  - "Kept the rehydrate warmability check ungated (uniform quarantine) — documented WHY rather than gating on `enabled`"
metrics:
  duration: ~8min
  tasks: 2
  files: 3
  completed: 2026-07-18
---

# Phase quick-260718-evz Plan 01: Revert Phase-10 Warmup Deactivated-Skip Summary

Reverted the phase-10 warmup "deactivated-skip" (commit `40e73430`, flagged by the 2nd re-review as
WR-01 + IN-01) so `derive_warmup_depth` again sizes the `LiveBarFeed` ring from ALL registered
strategies — restoring the pre-provisioning guarantee the guardless `enable` verb relies on — and
documented the WR-02 uniform-quarantine rationale at the rehydrate warmability check (logic
unchanged).

## What Was Done

### Task 1 — Revert the deactivated-skip in cache_registration + tests; add the pre-provisioning regression test

Mechanism (as planned): reverse-applied the exact commit diff with `git show -R 40e73430 | git apply`,
NOT `git revert`. Rationale verified during execution:
- `git show 40e73430 --stat` → touched EXACTLY `cache_registration.py` + `test_cache_registration.py`
  (no entanglement with `abd74861`'s rehydrate quarantine).
- `git show -R 40e73430 | git apply --check` → exit 0 (reverse patch clean).
- `git apply` mutates the working tree with no revert-sequencer/commit-message state, so the GSD
  commit step staged and committed it normally.

Revert end-state (verified by eye + grep):
- `_SupportsWarmup` Protocol no longer carries an `is_active` member (grep for `is_active` in
  `cache_registration.py` → 0 hits).
- `derive_warmup_depth` sizes from ALL strategies in BOTH branches: the unscaled
  `max(NEWEST_BAR_ONLY, max((s.warmup for s in strategies), default=1))` and the scaled
  `required_base_depth(...) for s in strategies` branch — with the `NEWEST_BAR_ONLY` floor KEPT (the
  floor predates the skip via commit `4c039357`).
- Accurate floor-only comment/docstring restored; the stale IN-01 "a DEACTIVATED finer-than-base
  strategy can no longer raise from the ladder" justification is gone.
- The three now-invalid deactivated tests removed
  (`test_register_strategy_warmup_skips_deactivated_strategies`,
  `test_derive_warmup_depth_skips_deactivated_unwarmable_strategy`,
  `test_derive_warmup_depth_all_deactivated_roster_floors_at_newest_bar`); `_StubStrategy` reverted to
  two-arg `(warmup, timeframe)`.

Added one regression test in the `# --- derive_warmup_depth ---` section immediately after
`test_derive_warmup_depth_non_empty_all_zero_warmup_floors_at_newest_bar`:
`test_derive_warmup_depth_includes_disabled_deep_strategy_provisions_ring` — a shallow active
`_StubStrategy(50, _1H)` + a deep `_StubStrategy(100, _4H)` with `.is_active = False` set directly on
the instance (a plain attribute the reverted ladder does NOT read), asserting
`derive_warmup_depth([shallow, deep], base_timeframe=_1H) == 400`. If a future edit re-introduces an
`if s.is_active` filter, the deep stub is excluded and this drops to 50 and fails loudly. 4-space
indentation preserved.

### Task 2 — Document the WR-02 uniform-quarantine rationale at the rehydrate warmability check

Pure doc-only change (no logic edit). The per-instance `required_base_depth(...)` warmability check
remains ungated over ALL rows — the guard stays `if base_timeframe is not None:` (NOT conjoined with
`rec["enabled"]`), and `_QUARANTINABLE` still lists `UnwarmableTimeframeError`.

Added a TAB-indented comment paragraph (rehydrate.py is tabs end-to-end) immediately above the
`base_timeframe = getattr(` line, headed `WR-02 — uniform quarantine (do NOT gate on enabled)`,
recording rationale (a)–(d): illusory position ownership of a dark unwarmable row; loud-quarantine vs
silently-inert dark strategy (D-19 preference); non-destructive/self-recovering (row not mutated);
consistency with every other `_QUARANTINABLE` class — plus the load-bearing note that once the
deactivated-skip is reverted (Task 1) the ladder again includes disabled strategies, so uniform
quarantine is REQUIRED (not merely acceptable) to stop one stale disabled-unwarmable row becoming a
self-inflicted boot outage.

## Deviations from Plan

None — plan executed exactly as written. The reverse patch applied cleanly (no hand-edit fallback
needed).

## Verification

Full gate (run from repo root; not `make test`). ACTUAL output:

- `poetry run pytest tests/unit/strategy/ tests/unit/price_handler/test_cache_registration.py tests/integration/test_strategy_registry_restart.py tests/integration/test_strategy_add_warmup.py`
  → **322 passed, 5 skipped in 3.07s**. The 5 skips are the PostgreSQL-container integration cases in
  `test_strategy_registry_restart.py` (env: "PostgreSQL container unavailable — skipped (D-11)"), not
  related to this change.
- `poetry run mypy itrader` → **Success: no issues found in 266 source files**.
- `poetry run pytest tests/integration/test_okx_inertness.py` → **4 passed in 1.16s** (confirms the
  revert did not disturb the backtest import graph).

Task-local checks:
- `poetry run pytest tests/unit/price_handler/test_cache_registration.py -q` → 11 passed (includes the
  new pre-provisioning test).
- `grep -F 'max((s.warmup for s in strategies), default=1)' cache_registration.py` → present.
- `grep -c 'WR-02' rehydrate.py` → 1; `grep -F 'if base_timeframe is not None:'` → exact match
  present; `grep -c 'UnwarmableTimeframeError' rehydrate.py` → 3 (still in `_QUARANTINABLE`).

## Indentation

- `cache_registration.py` + `tests/unit/price_handler/test_cache_registration.py` — 4-space
  (`price_handler/feed/` convention), preserved.
- `rehydrate.py` — tabs end-to-end; the inserted WR-02 block is 3-tab indented (all 22 inserted lines
  start with a tab), matching the surrounding `for`/`try` body.

## Commits

- `a00a2033` revert(260718-evz): remove warmup deactivated-skip; restore pre-provisioning
- `fe15923a` docs(260718-evz): record WR-02 uniform-quarantine rationale at rehydrate

## Self-Check: PASSED

- itrader/price_handler/feed/cache_registration.py — FOUND
- tests/unit/price_handler/test_cache_registration.py — FOUND
- itrader/strategy_handler/registry/rehydrate.py — FOUND
- Commit a00a2033 — FOUND
- Commit fe15923a — FOUND
