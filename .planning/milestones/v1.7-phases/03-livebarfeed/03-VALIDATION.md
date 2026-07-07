---
phase: 3
slug: livebarfeed
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-01
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (+ pytest-asyncio ^1.4.0, `asyncio_mode="auto"`) |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Quick run command** | `poetry run pytest tests/unit/price/test_live_bar_feed.py -x -q` |
| **Full suite command** | `make test` (main checkout) / `poetry run pytest tests` (worktree — make test aborts on missing `.env`) |
| **Estimated runtime** | quick < 5s; full suite ~ existing (oracle test is the long pole) |

---

## Sampling Rate

- **After every task commit:** the plan's quick run command (per-task `<automated>` verify)
- **After every plan wave:** `poetry run pytest tests` (or `make test` in main checkout)
- **Before `/gsd:verify-work`:** full suite green + oracle byte-exact + inertness probe green
- **Max feedback latency:** < 5s per task (offline synthetic ClosedBar); full suite dominated by the oracle run

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 03-01 | 1 | FEED-01, D-12 | T-03-01-TAMPER | Routing keys sourced from trusted provider config, not the venue row | unit | `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -x -q` | ✅ (extend) | ⬜ pending |
| 03-01-T2 | 03-01 | 1 | FEED-03 | T-03-01-SC | Offline fixtures — no socket, no new deps | unit | `poetry run pytest tests/unit/price -q` | ❌ W0 | ⬜ pending |
| 03-02-T1 | 03-02 | 2 | FEED-01, FEED-02 | T-03-02-LOOKAHEAD, T-03-02-MEM | tz-aware venue-open time; bounded deque; window rule-4 cutoff | unit | `poetry run pytest tests/unit/price/test_live_bar_feed.py -x -q` | ❌ W0 | ⬜ pending |
| 03-02-T2 | 03-02 | 2 | FEED-02, FEED-04 | T-03-02-REPLAY, T-03-02-RACE, T-03-02-SILENTDROP | Monotonic guard (stale/dup/revision/gap), single-writer, logged drops | unit | `poetry run pytest tests/unit/price/test_live_bar_feed.py -x -q` | ❌ W0 | ⬜ pending |
| 03-03-T1 | 03-03 | 3 | FEED-03, FEED-04 (reconnect) | T-03-03-STARVE, T-03-03-DOUBLEDELIVER, T-03-03-PARITYDRIFT | One-by-one replay (no bulk path); boundary-gated reconnect; indicators warm | integration | `poetry run pytest tests/integration/test_live_bar_feed_warmup.py -x -q` | ❌ W0 | ⬜ pending |
| 03-04-T1 | 03-04 | 4 | FEED-05, D-13 | T-03-04-INERT, T-03-04-STARVE, T-03-04-RACE | Lazy import; D-13 capacity=100; warmup before start_stream | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x -q` | ✅ (extend) | ⬜ pending |
| 03-04-T2 | 03-04 | 4 | FEED-05, GATE | T-03-04-INERT, T-03-04-DORMANT | Inertness probe forbids live_bar_feed; oracle byte-exact; route order preserved | integration | `poetry run pytest tests/integration/test_live_bar_feed_route_order.py tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py -x -q` | ❌ W0 (+ ✅ oracle) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Coverage check:** FEED-01 (03-01/03-02), FEED-02 (03-02), FEED-03 (03-01/03-03), FEED-04 (03-02
guard + 03-03 reconnect), FEED-05 (03-04). D-06 taxonomy fully covered in 03-02-T2 (in-sequence /
gap-backfill-replay / duplicate-drop / revision-forward-only / stale-reject). No 3 consecutive
tasks without an automated verify — every task has one.

**Recurring milestone gate** (03-04-T2): oracle byte-exact (134 / `46189.87730727451`,
`check_exact=True`) + extended inertness probe (`live_bar_feed` in `_FORBIDDEN`). W1/W2 unchanged by
construction (no new module on the backtest hot path — the inertness probe is the proxy).

---

## Wave 0 Requirements

- [ ] `tests/unit/price/conftest.py` — `_StubProvider` (programmable `fetch_ohlcv_backfill`) + `closed_bar` synthetic builder + sequence helper (03-01-T2). NOTE: dir is package-less (no `__init__.py`).
- [ ] `tests/unit/price/test_live_bar_feed.py` — FEED-01/02/04 offline unit matrix (03-02).
- [ ] `tests/integration/test_live_bar_feed_warmup.py` — FEED-03 warmup replay + indicator readiness + reconnect boundary (03-03).
- [ ] `tests/integration/test_live_bar_feed_route_order.py` — FEED-05 BAR-route ordering (03-04).
- [ ] Extend `tests/integration/test_okx_inertness.py` `_FORBIDDEN` with `itrader.price_handler.feed.live_bar_feed` (03-04).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | — | All Phase-3 behaviors are automated offline (synthetic `ClosedBar` sequences + golden-CSV oracle). A live OKX socket is NOT required to complete or verify Phase 3 (RESEARCH §Environment Availability). |

*Target met: all Phase-3 behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s per task
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned (populate Status column during execution)
