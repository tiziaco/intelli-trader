---
phase: 8
slug: m5c-cross-validation-final-oracle
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (strict: `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.mypy]` strict=true) |
| **Quick run command** | `poetry run pytest tests/ -q -x` (or a targeted `make test-*` for the edited domain) |
| **Full suite command** | `make test` (`poetry run pytest tests/ -v`) |
| **Estimated runtime** | ~30–90 seconds (716 tests collected) |

---

## Sampling Rate

- **After every task commit:** Run the targeted quick command for the edited domain (e.g. `make test-portfolio` after Portfolio Decimal edits).
- **After every plan wave:** Run `make test` (full suite) + `make typecheck` (mypy --strict).
- **Before `/gsd:verify-work`:** Full suite green + `make typecheck` clean + a regenerated oracle that is byte-identical to (or a signed re-freeze of) `tests/golden/*`.
- **Max feedback latency:** ~90 seconds.

---

## Per-Task Verification Map

> Plan IDs are placeholders until the planner finalizes them. The mapping below is the validation contract the planner's tasks must satisfy.

| Task area | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-----------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Portfolio money props → Decimal | 1 | M5-10 / D-06 | — | money members return `Decimal`; no `float(` on money | unit | `make test-portfolio` | ✅ | ⬜ pending |
| MetricsManager coercion cleanup | 1 | M5-10 / D-06 | — | money fields Decimal; ratio math stays float at metric input | unit | `make test-portfolio` | ✅ | ⬜ pending |
| Validator Decimal cash checks | 1 | M5-10 / D-06 | — | golden-path admit/reject unchanged or re-frozen | unit | `make test-orders` | ✅ | ⬜ pending |
| Caller fan-out + mypy --strict | 1 | M5-10 / D-06 / D-13 | — | `mypy --strict` clean after retype | static | `make typecheck` | ✅ | ⬜ pending |
| Oracle regeneration + REFREEZE-M5C-DECIMAL | 1 | M5-10 / D-08 | — | `make backtest` runs; diff vs frozen attributed | integration | `make backtest` + diff `output/` vs `tests/golden/` | ✅ | ⬜ pending |
| Add pinned dev-deps + engine import smoke | 2 | M5-10 / D-10 | — | `import backtesting`/`backtrader` run on py3.13/numpy2 | smoke | `poetry run python -c "import backtesting, backtrader"` | ❌ W0 | ⬜ pending |
| Force-match engine modules (shared `ta` indicators) | 2 | M5-10 / D-01 / D-03 | — | filter-gates-both + next-bar-open replicated | integration | `poetry run python scripts/cross_validate.py` | ❌ W0 | ⬜ pending |
| Reconciliation + CROSS-VALIDATION.md + root-cause | 3 | M5-10 / D-02 / D-04 / D-05 | — | trade count + timing reconciled; divergences explained | integration | `poetry run python scripts/cross_validate.py` | ❌ W0 | ⬜ pending |
| Final oracle freeze + DoD gate | 4 | M5-10 / D-11 / D-13 | — | full DoD checklist green; final oracle frozen | integration | `make test` + `make typecheck` + double-run `make backtest` diff | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` poetry dev group gains `backtesting`, `backtrader` (and optionally `nautilus-trader`), pinned — installed before the harness modules can import.
- [ ] Engine import smoke check (esp. `backtrader` on numpy 2.x / Python 3.13) — a fast guard run before building the force-match modules; if it fails, the fork/shim fallback is selected here, not mid-harness.
- [ ] `scripts/cross_validate.py` + per-engine modules are net-new — no existing test file covers them; the committed `CROSS-VALIDATION.md` report is the durable artifact (D-10: the harness is script-only, never under `tests/`).

*Existing pytest + mypy infrastructure covers all Decimal-cleanup (Wave 1) and DoD (Wave 4) requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Re-freeze owner sign-off | M5-10 / D-08 | Golden-master discipline requires a human owner to accept each result-changing diff (Phase 6/7 law) | Review the `REFREEZE-M5C-*.md` expected-diff note; owner signs off before the new oracle is committed |
| Divergence root-cause disposition | M5-10 / D-05 | Deciding "iTrader bug" vs "legitimate reference difference" is a judgment call, not an assertion | Inspect each divergence row in `CROSS-VALIDATION.md`; confirm each is either fixed (→ re-freeze) or documented |
| Cross-validation report is committed evidence | M5-10 / D-10 | The reference-engine comparison is intentionally NOT in CI; its value is the committed report, reviewed once | Confirm `tests/golden/CROSS-VALIDATION.md` exists with reconciliation table + per-divergence notes |

---

## Validation Sign-Off

- [ ] All tasks have an automated verify command or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (engine deps + import smoke)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes task IDs)

**Approval:** pending
