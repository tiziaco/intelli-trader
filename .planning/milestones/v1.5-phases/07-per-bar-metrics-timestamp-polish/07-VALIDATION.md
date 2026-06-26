---
phase: 7
slug: per-bar-metrics-timestamp-polish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-25
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Byte-exact perf phase: every change must hold the SMA_MACD oracle (134 trades /
> `final_equity 46189.87730727451`). The hard correctness lock is Gate (a).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` (any unexpected warning fails) |
| **Quick run command** | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py tests/unit/portfolio/test_state_storage.py tests/unit/outils/ -x` |
| **Full suite command** | `poetry run pytest tests` (use this, not `make test`, as gate — `make test` exports `ITRADER_DISABLE_LOGS=true` which fails caplog warn-assertion tests; see memory `make-test-env-disables-logs`) |
| **Estimated runtime** | ~60–120 seconds (full unit+integration); oracle ~30s |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest <touched test file> -x` (quick).
- **After every plan wave:** Run `poetry run pytest tests` (full unit+integration).
- **Before `/gsd:verify-work`:** Full suite green + oracle byte-exact + `mypy --strict` clean.
- **Max feedback latency:** ~120 seconds.

---

## Per-Task Verification Map

> Final Task IDs assigned by the planner. This map is requirement-anchored; the planner
> wires each row to a concrete task ID in PLAN.md.

| Item | Req | Wave | Behavior | Threat Ref | Test Type | Automated Command | File Exists | Status |
|------|-----|------|----------|------------|-----------|-------------------|-------------|--------|
| D-01 | PERF-07 | — | `_aligned` output byte-unchanged for sampled `(ts,tf)`; memo bounded | — | unit | `poetry run pytest tests/unit/outils/test_time_parser.py -x` | ❌ W0 (new file) | ⬜ pending |
| D-01 | PERF-07 | — | `_aligned.cache_info().currsize` stays ≤ maxsize over a run | — | unit | `poetry run pytest tests/unit/outils/test_time_parser.py -k bounded -x` | ❌ W0 (new file) | ⬜ pending |
| D-02 | PERF-07 | — | per-bar `record_snapshot` debug log removed; snapshot fields intact | — | unit | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py -x` | ✅ | ⬜ pending |
| D-03 | PERF-07 | — | `get_snapshots()` value-identical pre/post deque; last-N retention on >10k-bar run | — | unit | `poetry run pytest tests/unit/portfolio/test_state_storage.py -x` | ✅ (update T4; add T5) | ⬜ pending |
| D-03 | PERF-07 | — | per-tick path makes no full-list copy (trim removed) | — | unit | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py -x` | ✅ (keep green) | ⬜ pending |
| D-04 | PERF-07 | — | metrics recompute-stable; cache attrs gone (`not hasattr`) | — | unit | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py -x` | ✅ (delete/rewrite 3 tests) | ⬜ pending |
| Gate (a) | PERF-07 | — | oracle byte-exact 134 / `46189.87730727451` | — | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| Gate (a) | PERF-07 | — | `mypy --strict` clean | — | static | `make typecheck` | ✅ | ⬜ pending |
| Gate (a) | PERF-07 | — | determinism double-run byte-identical | — | integration | (oracle re-run; planner pins command) | ✅ | ⬜ pending |
| Gate (b) | PERF-07 | — | W1 measurable win + four hotspots gone in re-profile | — | manual/perf | `make perf-profile` → `make perf-view` → `make perf-w1` → (cool) `make perf-baseline` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/outils/test_time_parser.py` — **new file**: `_aligned` equivalence (sampled `(ts,tf)` byte-unchanged) + bounded-memo + `cache_info().currsize ≤ maxsize`. Confirm/create `tests/unit/outils/` dir (source dir is `itrader/outils/`; `tests/unit/` exists but `outils/` subdir may need creating).
- [ ] Update `tests/unit/portfolio/test_state_storage.py::test_get_snapshots_returns_live_container_no_copy` from identity (`is`) to value-equality (`==`) — D-03 makes `get_snapshots()` return `list(deque)` (a copy).
- [ ] Add `test_state_storage.py` last-N retention test on a `> max_snapshots` (>10000-bar) run.
- [ ] Delete/rewrite the three breaking metrics-cache tests in `test_metrics_manager.py`: `test_performance_metrics_caching`, `test_metrics_cache_invalidation`, and the `cache_duration_minutes == 5` assertion (D-04 removes the cache). Add a recompute-stability + `not hasattr(self, "_metrics_cache")` test.
- [ ] Framework install: **none** — pytest is present.

> **CRITICAL (research Gap C/D fallout):** under `filterwarnings=["error"]` + `--strict-config`, the four
> pre-existing cache/identity tests fail HARD once D-03/D-04 land. They MUST be updated in the same plan
> that removes the cache/changes the container — not deferred.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gate (b) W1 wall-clock win + hotspot elimination | PERF-07 | Thermally sensitive; frozen-baseline Δ% is unreliable on a throttled box (memory `v15-perf-gateb-thermal-drift`) | (1) `make perf-profile` then `make perf-view` — confirm the four hotspots (`_aligned`, debug-log eager args, trim copy, cache clear) are gone from the Scalene CPU share. (2) `make perf-w1` same-machine A/B (pre vs post) for attribution. (3) On a **verified-cool** machine only: `make perf-baseline` to re-freeze `perf/results/W1-BASELINE.json`. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the new `test_time_parser.py` + the four breaking-test updates)
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
