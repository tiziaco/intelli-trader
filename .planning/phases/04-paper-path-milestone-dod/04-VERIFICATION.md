---
phase: 04-paper-path-milestone-dod
verified: 2026-07-02T12:57:59Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
---

# Phase 4: Paper Path (milestone DoD) Verification Report

**Phase Goal:** Paper Path (milestone DoD) — reuse `SimulatedExchange` as-is as the paper exchange;
runnable worker + lifecycle; paper-parity gate = paper ≡ a fresh backtest on the same data, exact
frame-equality. (Revised 2026-07-02: parity re-anchored to a fresh backtest rather than the frozen
`46189…` artifact; `SimulatedExchange` reused rather than a new `PaperExchange` with `apply_costs`;
Postgres command/status channel deferred to Phase 5.)

**Verified:** 2026-07-02T12:57:59Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The paper exchange is the reused `SimulatedExchange` — no new adapter class, no `apply_costs` extraction, exchange stays account-free (revised PAPER-01/02) | ✓ VERIFIED | `grep -n "class PaperExchange\|apply_costs\|def _emit_fill" itrader/trading_system/live_trading_system.py` → no matches. `git diff main --stat -- itrader/execution_handler/exchanges/simulated.py` → empty (file never touched by any Phase-4 commit; `git blame`/`git log` confirm last change predates this phase). |
| 2 | `LiveTradingSystem` runs the paper path end-to-end (live feed → strategy → order → fill → Portfolio) with the determinism seams threaded through (PAPER-03) | ✓ VERIFIED | `poetry run python scripts/run_live_paper.py --mode replay` exits 0, prints `trades: 134, final equity: 46189.87730727451` — matches the oracle transitively (D-01 transitive property). `run_paper_replay()` present in `live_trading_system.py`, drives `replay_bar → process_events → record_metrics` per the backtest per-tick discipline. |
| 3 | A runnable worker entrypoint with start/stop/status lifecycle exists (revised RUN-01: worker + lifecycle only, channel deferred) | ✓ VERIFIED | `scripts/run_live_paper.py` exists, runs `--mode replay` offline (verified above) and exposes `--mode okx` for the manual smoke via `start()/stop()/get_status()`. `grep -n "LISTEN\|NOTIFY\|fastapi\|FastAPI\|uvicorn" scripts/run_live_paper.py` → no matches (channel/FastAPI correctly deferred to Phase 5). |
| 4 | The paper-parity gate (DoD): paper ≡ a fresh backtest on the same data, exact frame-equality, no tolerance, NOT pinned to the frozen artifact (revised PAPER-04) | ✓ VERIFIED | `poetry run pytest tests/integration/test_paper_parity.py -v` → 1 passed. Read the test source: it builds `BacktestTradingSystem` AND `LiveTradingSystem(exchange='paper').run_paper_replay()` in the same test, tz-normalizes to UTC, and calls `pdt.assert_frame_equal(..., check_exact=True, check_like=True)` twice (trades + equity) plus a non-empty-trades guard (`assert len(paper_trades) > 0`). `grep -n "46189\|tests/golden\|golden_dir" tests/integration/test_paper_parity.py` → no matches (not pinned to the frozen artifact). |
| 5 | The recurring milestone gate holds: backtest oracle stays byte-exact, replay/live machinery is inert on the backtest hot path (D-12) | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -v` → 3 passed (134 / `46189.87730727451`, `check_exact=True`). `git diff --exit-code tests/integration/test_backtest_oracle.py` → exit 0 (unchanged). `poetry run pytest tests/integration/test_okx_inertness.py -v` → 1 passed; the `_FORBIDDEN` tuple includes `itrader.price_handler.providers.replay_provider` (read the source — confirmed present with a D-12 comment). |
| 6 | Lifecycle/command-surface coverage (COV-01): `start()`/`stop()`/`get_status()` on `exchange='paper'` — clean startup, graceful stop (thread joins), status reporting (D-10) | ✓ VERIFIED | `poetry run pytest tests/integration/test_live_paper_lifecycle.py -v` → 3 passed (`test_clean_startup_reports_running`, `test_graceful_stop_joins_thread`, `test_status_before_start_reports_stopped`). Read the test source: asserts `start()` True, polls for RUNNING status, asserts post-`stop()` `is_running() is False` and `get_status()['thread_alive'] is False`, and a second `stop()` is a safe no-op. Runs on `exchange='paper'` only (no OKX network in CI). |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/price_handler/providers/replay_provider.py` | `ReplayDataProvider`: offline drop-in for `OkxDataProvider` on `set_bar_sink`/`fetch_ohlcv_backfill`, plus `replay_bar`/`iter_closed_bars` | ✓ VERIFIED | Exists, 167 lines, substantive. `ClosedBar` imported (not redefined) from `okx_provider.py`. Every OHLCV cell crosses `to_money(str(cell))`. `ts` built from the tz-aware index (`int(row.Index.value // 1_000_000)`). No `aiohttp`/`ccxt`/connector imports. `mypy --strict` clean. |
| `tests/unit/price/test_replay_provider.py` | Offline unit coverage (COV-01 fixture) | ✓ VERIFIED | 5 tests, all pass (`poetry run pytest tests/unit/price/test_replay_provider.py`); full `tests/unit/price` (61 tests) green, no collection regression. |
| `itrader/trading_system/live_trading_system.py` (paper arm + `run_paper_replay`) | paper venue arm + synchronous driver | ✓ VERIFIED | `LiveTradingSystem(exchange='paper')` wires `ReplayDataProvider` lazily; `run_paper_replay()` present and drives the golden dataset E2E (134 trades / 3076 equity points). Lazy import confirmed via the inertness probe (subprocess-isolated). `mypy --strict` clean. |
| `scripts/run_live_paper.py` | standalone worker bootstrap with `--mode replay`/`--mode okx` | ✓ VERIFIED | Runs, exits 0, produces non-zero trade count + final equity. No channel/FastAPI tokens. Uses `BTCUSD` (not `BTC/USDT`) for the replay ticker. |
| `tests/integration/test_live_paper_lifecycle.py` | FL-13 lifecycle coverage | ✓ VERIFIED | 3 tests, all pass. `exchange='paper'` only — no OKX network on CI path. |
| `tests/integration/test_paper_parity.py` | DoD parity gate | ✓ VERIFIED | 1 test, passes. `assert_frame_equal` called exactly twice with `check_exact=True`. |
| `tests/integration/test_okx_inertness.py` | inertness gate extended to forbid `replay_provider` | ✓ VERIFIED | `_FORBIDDEN` tuple includes `"itrader.price_handler.providers.replay_provider"` with a D-12 comment; test passes. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `replay_provider.py` | `okx_provider.py::ClosedBar` | import the TypedDict | ✓ WIRED | `from itrader.price_handler.providers.okx_provider import ClosedBar`; no local redefinition (`grep -c "class ClosedBar"` → 0). |
| `replay_provider.py` | `core/money.py::to_money` | Decimal edge on every cell | ✓ WIRED | `to_money(str(row.open/high/low/close/volume))` on every yielded bar. |
| `live_trading_system.py` | `replay_provider.py::ReplayDataProvider` | lazy import inside `elif exchange=='paper'` | ✓ WIRED | Import only inside the paper arm (confirmed by the passing inertness probe running in a fresh subprocess). |
| `run_paper_replay` | `backtest_runner.py`-style per-tick discipline | mirrors `record_metrics`/`process_events`/`expire_all_resting` | ✓ WIRED | Smoke run + parity test both confirm bit-identical behavior end-to-end. |
| `scripts/run_live_paper.py` | `LiveTradingSystem.run_paper_replay` | offline replay driver | ✓ WIRED | `--mode replay` calls `run_paper_replay()`, prints result. |
| `tests/integration/test_live_paper_lifecycle.py` | `start/stop/get_status` | lifecycle assertions | ✓ WIRED | 3 passing tests exercise the full command surface. |
| `tests/integration/test_paper_parity.py` | `LiveTradingSystem.run_paper_replay` + `BacktestTradingSystem` | fresh-backtest comparand (D-01 option b) | ✓ WIRED | Both systems constructed and run in the same test; frames diffed exactly. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Paper-parity DoD gate passes | `poetry run pytest tests/integration/test_paper_parity.py -v` | 1 passed | ✓ PASS |
| Parity test not pinned to frozen artifact | `grep -n "46189\|tests/golden\|golden_dir" tests/integration/test_paper_parity.py` | no matches | ✓ PASS |
| OKX inertness gate (extended) | `poetry run pytest tests/integration/test_okx_inertness.py -v` | 1 passed | ✓ PASS |
| SMA_MACD oracle untouched, byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -v` + `git diff --exit-code tests/integration/test_backtest_oracle.py` | 3 passed; diff empty | ✓ PASS |
| `SimulatedExchange` untouched by this phase | `git diff main --stat -- itrader/execution_handler/exchanges/simulated.py` | empty | ✓ PASS |
| ReplayDataProvider import-light (no network/async/connector) | `grep -n "aiohttp\|ccxt\|connectors" itrader/price_handler/providers/replay_provider.py` | no matches | ✓ PASS |
| Worker runs offline, non-zero trades | `poetry run python scripts/run_live_paper.py --mode replay` | exit 0, `trades: 134, final equity: 46189.87730727451` | ✓ PASS |
| Lifecycle coverage (start/stop/status) | `poetry run pytest tests/integration/test_live_paper_lifecycle.py -v` | 3 passed | ✓ PASS |
| mypy --strict clean on new/modified files | `poetry run mypy itrader/price_handler/providers/replay_provider.py itrader/trading_system/live_trading_system.py` | Success: no issues found | ✓ PASS |
| No regression in the broader integration suite | `poetry run pytest tests/integration -q` | 105 passed, 1 skipped (OKX creds absent, expected) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| PAPER-01 | 04-02 | Paper exchange implements `AbstractExchange` — revised to "reuse `SimulatedExchange` as-is" (D-04) | ✓ SATISFIED (per revised intent) | `SimulatedExchange` fetched from `execution_handler.exchanges['simulated']`, no new adapter class. REQUIREMENTS.md text is stale (still describes the pre-revision "reused pure `MatchingEngine`" framing) — see Known Drift below. |
| PAPER-02 | 04-02 | Shared `apply_costs` helper — dissolved/satisfied-by-reuse (D-05) | ✓ SATISFIED (per revised intent, dissolved) | One fill-pricing impl (`SimulatedExchange._emit_fill`, untouched). REQUIREMENTS.md text is stale (still describes the dropped `apply_costs` extraction) — see Known Drift below. |
| PAPER-03 | 04-01, 04-02 | `LiveTradingSystem` wired E2E on the paper path with determinism seams | ✓ SATISFIED | `run_paper_replay()` E2E confirmed (134 trades / 3076 equity points). |
| PAPER-04 | 04-04 | Paper-parity gate (DoD) — revised to "paper ≡ fresh backtest, exact" (D-01) | ✓ SATISFIED (per revised intent) | `test_paper_parity.py` passes, not pinned to frozen artifact. REQUIREMENTS.md text is stale (still describes "byte-exact vs the oracle 46189…") — see Known Drift below. |
| RUN-01 | 04-03 | Runtime topology decided + runnable worker — revised to defer the Postgres channel to Phase 5 (D-08) | ✓ SATISFIED (per revised intent) | `scripts/run_live_paper.py` + lifecycle exist; no channel/FastAPI code present. REQUIREMENTS.md text is stale (still describes "Postgres LISTEN/NOTIFY as the default command/status channel" as in-scope for Phase 4) — see Known Drift below. |
| COV-01 | 04-01, 04-03, 04-04 | FL-13 coverage: parity gate (anchor E2E) + lifecycle tests + synthetic replay fixture | ✓ SATISFIED | `test_replay_provider.py` (5 tests), `test_live_paper_lifecycle.py` (3 tests), `test_paper_parity.py` (1 test) all pass; real-connector coverage correctly deferred to Phase 5 (manual/opt-in `test_okx_smoke.py`, skipped without credentials). |

**No orphaned requirements** — all 6 IDs declared across the phase's 4 plans (`04-01`: PAPER-03, COV-01; `04-02`: PAPER-01, PAPER-02, PAPER-03; `04-03`: RUN-01, COV-01; `04-04`: PAPER-04, COV-01) match exactly the 6 IDs REQUIREMENTS.md maps to Phase 4 (PAPER-01..04, RUN-01, COV-01).

### Known Non-Blocking Drift (flagged, not a goal miss)

ROADMAP.md (`.planning/ROADMAP.md` Phase 4 section) has already been updated with a `> Revised 2026-07-02` note
and revised success criteria reflecting D-01/D-04/D-05/D-08. **REQUIREMENTS.md has NOT been updated** — it still
carries the pre-revision wording for PAPER-01 ("reused pure `MatchingEngine`"), PAPER-02 ("apply_costs helper"),
PAPER-04 ("byte-exact... 46189.87730727451... LX-11"), and RUN-01 ("Postgres LISTEN/NOTIFY as the default...
channel [decided/architected for Phases 2-5]" — implying in-scope now). All four executor SUMMARYs independently
flagged this same drift as a documentation follow-up, not a code defect. The delivered behavior matches the
REVISED intent from `04-CONTEXT.md` (D-01/D-04/D-05/D-08), confirmed by direct code inspection and test
execution above — this is prose staleness in REQUIREMENTS.md, not a functional gap. **Recommended follow-up:**
update REQUIREMENTS.md's PAPER-01/02/04 and RUN-01 bullets to match the ROADMAP.md revision note (a `[x]`
checkbox text edit, no code change).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/trading_system/live_trading_system.py` | 427 | `TODO: Add more specific event type handling...` | ℹ️ Info | Pre-existing (git blame: commit `fa884192b`, 2025-06-16) — predates this phase by over a year, not introduced by Phase 4, unreferenced-marker gate does not apply retroactively to code this phase did not author. |

No debt markers (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER) were introduced by any file created or modified in this
phase (`replay_provider.py`, `live_trading_system.py`'s new paper arm, `scripts/run_live_paper.py`,
`test_paper_parity.py`, `test_okx_inertness.py`'s extension, `test_live_paper_lifecycle.py`,
`test_replay_provider.py`).

### Human Verification Required

None. All must-haves are verifiable via automated grep/test/mypy checks; no visual, real-time, or external-service
behavior is in scope for this phase's DoD gate (the OKX live smoke is explicitly out-of-CI/manual by design, D-11,
and is not part of the phase's pass/fail criteria).

### Gaps Summary

No gaps. All 6 observable truths verified against actual running tests and direct code inspection (not SUMMARY.md
claims alone — every SUMMARY.md numeric claim, e.g. "134 trades / 46189.87730727451", was independently
reproduced by re-running the worker script and the test suite in this verification session). The only drift found
is a documentation-only staleness in REQUIREMENTS.md, explicitly called out as non-blocking in the phase's own
plan `<success_criteria>` sections and independently confirmed here — not a goal miss.

---

*Verified: 2026-07-02T12:57:59Z*
*Verifier: Claude (gsd-verifier)*
