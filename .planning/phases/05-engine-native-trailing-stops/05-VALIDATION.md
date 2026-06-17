---
phase: 5
slug: engine-native-trailing-stops
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (Poetry-managed; `filterwarnings=["error"]`, `--strict-markers`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit/execution -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60–120 seconds (full suite); execution unit subset ~10s |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/execution -q` (plus the touched
  domain subset — e.g. `tests/unit/order` when the order type / validator changes).
- **After every plan wave:** Run `make test` (full suite must stay green; strict warnings = errors).
- **Before `/gsd:verify-work`:** Full suite green AND `mypy --strict` clean AND determinism
  double-run byte-identical.
- **Max feedback latency:** ~15 seconds (execution unit subset).

---

## Per-Task Verification Map

> Filled concretely by the planner against the final task IDs. Coverage skeleton by requirement:

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-xx | 01 | 1 | TRAIL-01 | — | N/A (internal engine) | unit | `poetry run pytest tests/unit/execution -q` | ❌ W0 | ⬜ pending |
| 05-0x-xx | 0x | x | TRAIL-02 | — | N/A | unit | `poetry run pytest tests/unit/execution -k trailing -q` | ❌ W0 | ⬜ pending |
| 05-0x-xx | 0x | x | TRAIL-03 | — | N/A | integration | `poetry run pytest tests/golden -k trailing -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Nyquist Validation Requirements (per RESEARCH Validation Architecture)

The trailing-stop behavior is **state-machine + intrabar-timing sensitive** — the sampling must be
dense enough to catch ratchet/timing regressions, not just "it triggered once". Mandatory coverage:

- **Ratchet invariant (TRAIL-01):** stop is monotonic favorable (longs non-decreasing, shorts
  non-increasing) across a price path — assert level after each bar, never loosens.
- **Closed-bar / next-bar (TRAIL-02, the correctness core):** an explicit test proving bar N's
  extreme ratchets the stop for bar N+1 and CANNOT trigger off bar N's same-bar low/high. Include a
  "tall bar" case (high and low in one bar) that would falsely trigger under same-bar semantics.
- **Gap-through (D-TRAIL-4):** clean gap past the active stop fills at the open (worse), reusing the
  static-stop rule — assert fill price == open, not stop level.
- **OCO (D-TRAIL-5):** TP-limit vs trailing-SL same-bar resolution uses existing priority; trailing
  SL replaces fixed SL (a bracket never carries both).
- **Validation (D-TRAIL-7):** trail_value that yields initial stop ≤ 0 is rejected before resting.
- **Long AND short symmetry:** BOTH directions need dedicated test sets (shorts added only in
  Phase 3 — do not assume long coverage transfers).
- **Determinism:** double-run of the trailing golden scenario is byte-identical.

---

## Wave 0 Requirements

- [ ] `tests/unit/execution/test_matching_engine_trailing.py` — unit stubs for TRAIL-01/TRAIL-02
      (ratchet, closed-bar/next-bar, gap, OCO; long + short).
- [ ] `tests/unit/order/test_trailing_validation.py` — D-TRAIL-7 non-viable-trail rejection stubs.
- [ ] `tests/unit/order/test_trailing_bracket.py` — D-TRAIL-3/D-TRAIL-5 bracket-declaration stub
      collectible under `-k "trailing and bracket"` (long + short).
- [ ] `tests/golden/` trailing cross-val scenario stub — TRAIL-03 oracle reconciliation
      (backtesting.py `TrailingStrategy` + backtrader `StopTrail`, within 1% relative tolerance,
      trade-level primary; oracle-trails-off-close vs D-TRAIL-1-trails-off-high is a documented
      legitimate difference).
- [ ] Existing pytest infrastructure otherwise covers the phase (no new framework).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Golden re-baseline freeze | TRAIL-03 / XVAL | Owner-gated, result-changing (its OWN re-baseline) | Owner reviews trailing cross-val report + diff vs prior golden; signs off before freezing new reference |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
