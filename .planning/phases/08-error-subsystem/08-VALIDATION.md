---
phase: 8
slug: error-subsystem
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source design: `08-RESEARCH.md` → `## Validation Architecture`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (strict: `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/events -q` |
| **Full suite command** | `poetry run pytest tests` |
| **Estimated runtime** | quick ~5s · full unit ~8s · +integration oracle ~a few s |

> Note: prefer `poetry run pytest tests` over `make test` as the gate — `make test` exports
> `ITRADER_DISABLE_LOGS=true` (breaks `caplog` warn-assertions) and aborts in worktrees on a
> missing `.env`. The SMA_MACD byte-exact oracle lives at `tests/integration/test_backtest_oracle.py`.

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/events -q` (plus the domain suite the task touched — `tests/unit/portfolio`, `config`, `core`, etc.)
- **After every plan wave:** Run `poetry run pytest tests`
- **Before `/gsd-verify-work`:** Full suite green AND `tests/integration/test_backtest_oracle.py` byte-exact (`134 / 46189.87730727451`) AND `tests/integration/test_okx_inertness.py` green
- **Max feedback latency:** ~10 seconds (quick), ~30 seconds (full)

---

## Per-Task Verification Map

> Populated by the planner / gsd-nyquist-auditor from each PLAN.md task. Every task with a
> runtime surface MUST map to an `<automated>` verify command or a Wave 0 test stub.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | ERR-01 | — | FailFastPolicy re-raises identically; oracle byte-exact | unit + regression | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ❌ W0 | ⬜ pending |
| 08-0X-XX | — | — | ERR-03 | — | Money/FILL route failing every event trips + halts; WR-06 swallow holds | unit (injectable `now`) | `poetry run pytest tests/unit/events -k trip -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/events/` — new test module(s) for `ErrorPolicy` (per-handler granularity, WR-06 source guard, `should_trip` windowed-count math with injectable `now`) and `ErrorHandler` (severity-mapped log, CRITICAL→alert-sink, `state.last_error` persistence, WR-06 consumer guard, backtest None-collaborator no-op).
- [ ] The ERR-03 "prove it trips" deterministic test (SETTLEMENT halt-on-first + a windowed class) — the hard acceptance criterion.
- [ ] The FILL_TRANSLATION counted-`ErrorEvent` test (off-thread okx path → counted, classified SETTLEMENT).
- [ ] Existing `tests/integration/test_backtest_oracle.py` and `tests/integration/test_okx_inertness.py` cover the invariant guards (no new file — reused as regression backstops).

*Detailed test design lives in `08-RESEARCH.md` `## Validation Architecture`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CRITICAL → real alert-sink egress (future Telegram/email) | ERR-02 | Only `LogAlertSink` ships in P8; real egress is a deferred FastAPI-milestone channel | N/A for P8 — `LogAlertSink` is asserted via caplog in automated tests |

*All in-scope P8 behaviors have automated verification; the row above is a deferred-scope note, not a P8 gap.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
