---
phase: 1
slug: perf-tooling-baseline
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/integration/test_backtest_oracle.py -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | oracle ~tens of seconds; full suite longer; a perf run ~240s |

---

## Sampling Rate

- **After every task commit:** Run the byte-exact oracle (`poetry run pytest tests/integration/test_backtest_oracle.py -q`) — gate (a) must stay green (134 trades / final_equity 46189.87730727451).
- **After every plan wave:** Run `make test`.
- **Before `/gsd:verify-work`:** Full suite + oracle must be green; `make perf-baseline` then `make perf-w1` must run clean and print a delta.
- **Max feedback latency:** oracle run (~tens of seconds); the `make -n perf-*` dry-runs are instant.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| P01-T1 runner flags + D-07 window | 01-01 | 1 | TOOL-02 / D-06 / D-07 | T-01-01 | N/A (tooling-only) | cli/smoke | `poetry run python -m perf.runners.run_w1_benchmark --help \| grep -E -- '--json\|--check\|--baseline-out'` ; `poetry run python -m perf.runners.run_w2_sweep --help \| grep -- '--json'` ; `grep -c '"2026-04-23"' perf/runners/run_w1_benchmark.py` ; `grep -c '"46189.87730727451"' perf/runners/run_w1_benchmark.py` | ✅ runners exist | ⬜ pending |
| P01-T2 Makefile targets + .gitignore | 01-01 | 1 | TOOL-01 / TOOL-02 | T-01-01 | N/A (tooling-only) | smoke (make -n) | `make -n perf-w1 && make -n perf-w2 && make -n perf-baseline && make -n perf-profile` ; `make -n perf-w1 \| grep -vq scalene` ; `make -n perf-profile \| grep -q 'scalene run'` ; `make -n perf-profile \| grep -q 'scalene view --html'` ; `git check-ignore scalene-profile.html` ; `! git check-ignore perf/results/W1-BASELINE.json` | ✅ Makefile/.gitignore exist | ⬜ pending |
| P01-T3 Scalene profile (manual) | 01-01 | 1 | TOOL-02 | T-01-02 | N/A | manual/human-verify | `make perf-profile` → `scalene-profile.html` renders per-line profile; gitignored; `make -n perf-w1` carries no scalene | ❌ deliverable | ⬜ pending |
| P02-T1 freeze baseline JSON | 01-02 | 2 | TOOL-04 / D-01 | T-01-03 | N/A (tooling-only) | cli/smoke | `make perf-baseline` then `python -c "import json;d=json.load(open('perf/results/W1-BASELINE.json'));assert d['metric']['wall_clock_s']>0 and d['window']['start_date']=='2026-04-23' and d['oracle_provenance']['final_equity']=='46189.87730727451' and isinstance(d['oracle_provenance']['final_equity'],str) and d['frozen_at']"` ; `! git check-ignore perf/results/W1-BASELINE.json` ; gate (a) green | ❌ deliverable | ⬜ pending |
| P02-T2 soft-guard proof | 01-02 | 2 | TOOL-04 / D-02 / D-04 | T-01-03 | N/A (tooling-only) | smoke (pos+neg) | `make perf-w1` prints Δ + exits 0 (within noise) ; baseline wall_clock_s lowered ~20% → `make perf-w1` exits non-zero + prints `PERF REGRESSION` ; `git checkout -- perf/results/W1-BASELINE.json` → `git diff --quiet perf/results/W1-BASELINE.json` ; gate (a) green | ❌ deliverable | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing infrastructure covers all phase requirements (pytest + the byte-exact oracle already exist; both runners + the Makefile + .gitignore already exist as the brownfield-extension targets). No new framework install. The new tooling surface is verified by `make -n` dry-runs, `--help` greps, JSON-field asserts, and the injected-slowdown negative test — appropriate for a measurement harness; no new pytest file required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Scalene `perf-profile` writes a gitignored HTML and never wraps the timed run | TOOL-02 | Profiling artifact is human-inspected; profiler-free benchmark is the gated path; the run is slow (~2-5× overhead) | Run `make perf-profile`; confirm `scalene-profile.html` written, gitignored, renders a per-line profile over itrader/+perf/ (not a Thread.run bucket); confirm `make -n perf-w1` (timed) carries no profiler (01-01 Task 3 checkpoint) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every code/config/freeze task carries an automated cli/smoke verify + the per-commit oracle)
- [x] Wave 0 covers all MISSING references (none — brownfield extension; oracle + runners + Makefile pre-exist)
- [x] No watch-mode flags
- [x] Feedback latency acceptable (oracle ~tens of seconds; make -n instant)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner, 2026-06-23)
