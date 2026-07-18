---
phase: quick-260718-evz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/price_handler/feed/cache_registration.py
  - tests/unit/price_handler/test_cache_registration.py
  - itrader/strategy_handler/registry/rehydrate.py
autonomous: true
requirements: [WR-01, WR-02, IN-01]

must_haves:
  truths:
    - "derive_warmup_depth sizes the warmup ring from ALL registered strategies (active AND disabled) in both branches, keeping the NEWEST_BAR_ONLY floor — restoring the pre-provisioning guarantee the enable verb relies on"
    - "The _SupportsWarmup Protocol no longer carries an is_active member (nothing outside cache_registration consumed it)"
    - "A disabled deep-warmup strategy still sizes the live ring at boot (regression-pinned by one new test)"
    - "The rehydrate warmability quarantine still runs UNGATED over every row and now documents the WR-02 uniform-quarantine rationale (logic unchanged)"
  artifacts:
    - itrader/price_handler/feed/cache_registration.py
    - tests/unit/price_handler/test_cache_registration.py
    - itrader/strategy_handler/registry/rehydrate.py
  key_links:
    - "register_strategy_warmup -> derive_warmup_depth -> LiveBarFeed fixed-maxlen ring (must include disabled strategies so enable finds capacity already provisioned)"
    - "rehydrate warmability check -> required_base_depth (must stay ungated so a disabled-unwarmable row is quarantined loudly, not loaded present-but-dark to crash the reverted ladder at boot)"
---

<objective>
Revert the phase-10 warmup "deactivated-skip" (commit `40e73430`) flagged by the 2nd re-review
(WR-01 + IN-01) and document the uniform-quarantine rationale in rehydrate (WR-02).

The skip added an `is_active` filter to `derive_warmup_depth` so the `LiveBarFeed` ring was sized
from ACTIVE strategies only. That was net-negative: it broke the pre-provisioning guarantee that
makes `disabled -> enable` safe (the `enable` verb has NO capacity guard and the ring is a
fixed-`maxlen` deque that cannot resize), while the filter's only stated benefit — stopping a
deactivated finer-than-base strategy raising from the ladder — defended an UNREACHABLE case (the
rehydrate quarantine already stops every finer-than-base row, enabled or disabled, before the
ladder). Net: silent warmup under-provisioning on a guardless path, for zero real protection.

Purpose: restore the pre-provisioning guarantee; keep the rehydrate quarantine uniform and record
WHY.
Output: reverted `cache_registration.py` + tests, one new pre-provisioning regression test, and a
WR-02 doc comment in `rehydrate.py`.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/10-strategies-registry/10-REVIEW.md
@itrader/price_handler/feed/cache_registration.py
@itrader/strategy_handler/registry/rehydrate.py
@tests/unit/price_handler/test_cache_registration.py

# Mechanism note (verified during planning, read-only):
#  - `git show 40e73430 --stat` -> touched EXACTLY cache_registration.py + test_cache_registration.py
#    (no entanglement with abd74861, which touched only rehydrate.py + test_rehydrate.py).
#  - `git show -R 40e73430 | git apply --check` -> exit 0 (reverse patch applies cleanly).
#  - `git log 40e73430..HEAD -- <those 2 files>` -> empty (nothing touched them since).
#  - The NEWEST_BAR_ONLY floor predates the skip (commit 4c039357) -> reverting 40e73430 KEEPS it.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Revert the deactivated-skip in cache_registration + tests; add the pre-provisioning regression test</name>
  <files>itrader/price_handler/feed/cache_registration.py, tests/unit/price_handler/test_cache_registration.py</files>
  <action>
MECHANISM CHOSEN — reverse-apply the exact commit diff, NOT `git revert`. Run
`git show -R 40e73430 | git apply` to reverse-apply commit 40e73430 to the working tree. Rationale
(state this in the SUMMARY): `git show 40e73430 --stat` confirms it touched EXACTLY these two files
and did not entangle with abd74861's rehydrate quarantine; the reverse patch was proven clean via
`git show -R 40e73430 | git apply --check` (exit 0); and no commit has touched these two files since.
`git apply` mutates the working tree with NO revert-sequencer/commit-message state (unlike
`git revert`), so the GSD commit step stages and commits it normally alongside Task 2. HARD
indentation: both files are 4-SPACE (`price_handler/feed/` + `tests/unit/price_handler/`
convention) — the reverse patch preserves this; never normalize.

This reverse patch delivers the full revert end-state: (a) removes the `is_active` member from the
`_SupportsWarmup` Protocol (grep-confirmed no consumer outside this file — rehydrate imports only
`required_base_depth`/`UnwarmableTimeframeError`, not the Protocol); (b) restores `derive_warmup_depth`
to size the ring from ALL strategies in BOTH branches — unscaled `max(NEWEST_BAR_ONLY, max((s.warmup
for s in strategies), default=1))` and the scaled `required_base_depth(...)` branch over `for s in
strategies` — with the `NEWEST_BAR_ONLY` floor kept (the floor predates the skip via commit 4c039357);
(c) restores the accurate floor-only comment/docstring, dropping the stale IN-01 "a DEACTIVATED
finer-than-base strategy can no longer raise from the ladder" justification; (d) removes the three
now-invalid deactivated tests (`test_register_strategy_warmup_skips_deactivated_strategies`,
`test_derive_warmup_depth_skips_deactivated_unwarmable_strategy`,
`test_derive_warmup_depth_all_deactivated_roster_floors_at_newest_bar`) and reverts `_StubStrategy`
from three-arg back to two-arg `(warmup, timeframe)`.

Then ADD one regression test to `tests/unit/price_handler/test_cache_registration.py`, placed in the
`# --- derive_warmup_depth ---` section immediately after
`test_derive_warmup_depth_non_empty_all_zero_warmup_floors_at_newest_bar`. Name it
`test_derive_warmup_depth_includes_disabled_deep_strategy_provisions_ring`. In the body: construct a
shallow active `_StubStrategy(50, _1H)` and a DEEP `_StubStrategy(100, _4H)`, then set the deep stub's
`.is_active` attribute to False directly on the instance (a plain attribute the reverted ladder does
NOT read — `_StubStrategy` no longer defines it). Assert `derive_warmup_depth([shallow, deep],
base_timeframe=_1H) == 400` (the deep 100 @ 4h == 400 base bars sizes the ring EVEN THOUGH it stands
for a disabled strategy). Docstring: this pins the pre-provisioning guarantee the `enable` verb
relies on — the ring is a fixed-`maxlen` deque that cannot resize and `enable`
(`strategies_handler.py:1351-1372`) has NO capacity guard, so a disabled deep strategy MUST size the
ring at boot; if a future edit re-introduces an `if s.is_active` filter, the deep stub is excluded and
this assertion drops to 50 and fails loudly, guarding the reverted contract. 4-SPACE indentation.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/price_handler/test_cache_registration.py -q && grep -F 'max((s.warmup for s in strategies), default=1)' itrader/price_handler/feed/cache_registration.py && poetry run mypy itrader</automated>
  </verify>
  <done>
The `is_active` Protocol member and both filtered ladder branches are gone; `derive_warmup_depth`
sizes from all strategies in both branches with the `NEWEST_BAR_ONLY` floor intact; the accurate
floor-only comment/docstring is restored (no IN-01 finer-than-base justification); the three
deactivated tests are removed and `_StubStrategy` is two-arg again; the new
`..._includes_disabled_deep_strategy_provisions_ring` test passes (== 400); 4-space indentation
preserved; `poetry run mypy itrader` clean.
  </done>
</task>

<task type="auto">
  <name>Task 2: Document the WR-02 uniform-quarantine rationale at the rehydrate warmability check (logic unchanged)</name>
  <files>itrader/strategy_handler/registry/rehydrate.py</files>
  <action>
KEEP the rehydrate warmability quarantine EXACTLY as-is. The per-instance `required_base_depth(...)`
check (~rehydrate.py:341-344) MUST remain ungated over ALL rows — the guard stays
`if base_timeframe is not None:`; do NOT change it to `if base_timeframe is not None and
rec["enabled"]:`, and do NOT touch `_QUARANTINABLE`. This is a pure doc-only change: no logic edit.

ADD a TAB-indented comment paragraph (rehydrate.py is TABS end-to-end — never spaces) extending the
existing F-1 warmability comment block, positioned immediately above the `base_timeframe = getattr(`
line (~:341). Head it with the anchor token `WR-02 — uniform quarantine (do NOT gate on enabled)` and
record WHY the check is NOT gated on the row's `enabled` state:
  (a) an unwarmable strategy can never reach `is_ready`, so a disabled row loaded present-but-dark
      would only have ILLUSORY position "ownership" — it could never warm enough to manage those
      positions out;
  (b) quarantine is LOUD (one CRITICAL alert on the halt egress) whereas loading it present-but-dark
      is a SILENTLY-inert dark strategy — and D-19 rates "appears healthy while trading nothing" as
      worse than failing to start, so loud-quarantine is the D-19-consistent choice;
  (c) the row is NOT mutated, so the quarantine is non-destructive and self-recovering — fix the
      base-cadence config and restart and the row reloads warmable (nothing to un-flip by hand);
  (d) consistent with every other `_QUARANTINABLE` class (codec / param drift / portfolio-id), none
      of which get present-but-dark treatment.
Close with the load-bearing note: once the deactivated-skip is reverted (Task 1), the warmup ladder
AGAIN includes disabled strategies, so a loaded disabled-unwarmable row would crash boot inside
`register_strategy_warmup` — uniform quarantine at rehydrate is therefore REQUIRED (not merely
acceptable) to stop one stale disabled row becoming a self-inflicted boot outage.
  </action>
  <verify>
    <automated>grep -c 'WR-02' itrader/strategy_handler/registry/rehydrate.py && grep -F 'if base_timeframe is not None:' itrader/strategy_handler/registry/rehydrate.py && poetry run pytest tests/unit/strategy/test_rehydrate.py -q && poetry run mypy itrader</automated>
  </verify>
  <done>
A TAB-indented WR-02 uniform-quarantine comment block sits directly above the `base_timeframe =
getattr(` line recording rationale (a)-(d) plus the "required once the skip is reverted" note; the
warmability guard is unchanged and still ungated (`if base_timeframe is not None:` exact, no
`rec["enabled"]` conjunction); `_QUARANTINABLE` still lists `UnwarmableTimeframeError`;
`tests/unit/strategy/test_rehydrate.py` passes; `poetry run mypy itrader` clean; tabs preserved.
  </done>
</task>

</tasks>

<source_coverage>
Locked decisions -> tasks (all covered; no scope reduction):
- Decision 1 (revert skip in cache_registration; keep floor; drop is_active Protocol member + stale
  IN-01 rationale; mechanism = git-driven reverse patch, justified) -> Task 1
- Decision 2 (remove the deactivated tests + revert _StubStrategy; add ONE pre-provisioning
  regression test) -> Task 1
- Decision 3 (keep rehydrate quarantine ungated; add WR-02 uniform-quarantine doc comment) -> Task 2
Review findings addressed: WR-01 (Task 1 filter removal restores provisioning), IN-01 (Task 1
docstring/comment revert), WR-02 (Task 2 rationale doc — quarantine intentionally uniform).
No deferred ideas planned. No new packages, no new dependency, no external surface.
</source_coverage>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Internal revert + doc-only change; no new input/parse/network/package surface. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-evz-01 | Tampering (correctness) | derive_warmup_depth ring sizing | medium | mitigate | Revert restores sizing from ALL strategies (no silent under-provisioning on the guardless `enable` path); new regression test pins that a disabled deep strategy still sizes the ring. |
| T-evz-02 | Denial of Service (boot) | rehydrate warmability check | low | accept | Uniform quarantine (documented, unchanged) keeps one stale disabled-unwarmable row from crashing the reverted ladder at boot; loud CRITICAL alert, row not mutated. |
</threat_model>

<verification>
Full gate (run from the repo root; NOT `make test` — it exports ITRADER_DISABLE_LOGS and can abort
on missing .env):

- `poetry run pytest tests/unit/strategy/ tests/unit/price_handler/test_cache_registration.py tests/integration/test_strategy_registry_restart.py tests/integration/test_strategy_add_warmup.py`
- `poetry run mypy itrader`
- `poetry run pytest tests/integration/test_okx_inertness.py`

All three green. The inertness gate confirms the revert did not disturb the backtest import graph
(cache_registration stays stdlib-only; rehydrate stays lazy-imported behind the build_live_system gate).
</verification>

<success_criteria>
- `derive_warmup_depth` sizes the ring from ALL strategies (active + disabled) in both branches, with
  the `NEWEST_BAR_ONLY` floor kept; `_SupportsWarmup` has no `is_active` member.
- The three deactivated tests are gone; `_StubStrategy` is two-arg; the new pre-provisioning
  regression test passes.
- The rehydrate warmability check is unchanged (ungated) and carries the WR-02 uniform-quarantine
  doc comment.
- Full gate green: targeted unit + integration suites, `mypy itrader`, and OKX inertness.
- Indentation preserved per file (cache_registration + tests = 4-space; rehydrate = tabs).
</success_criteria>

<output>
Create `.planning/quick/260718-evz-revert-phase-10-warmup-deactivated-skip-/260718-evz-SUMMARY.md` when done.
</output>
