---
phase: 7
slug: live-dynamic-universe-hardening
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-06
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> See `07-RESEARCH.md` → "Validation Architecture" for the finding-by-finding validation design.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/universe tests/unit/strategy -q` |
| **Full suite command** | `poetry run pytest tests` |
| **Oracle gate** | `poetry run pytest tests/integration/test_backtest_oracle.py` (byte-exact 134 / `46189.87730727451`) |
| **Type gate** | `poetry run mypy itrader` (`--strict`) |
| **Estimated runtime** | ~8–20 seconds (unit); full suite longer |

> **Test gotcha (repo memory):** `make test` exports `ITRADER_DISABLE_LOGS=true` and aborts in
> worktrees on missing `.env` — use `poetry run pytest tests` as the gate.

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched domain(s).
- **After every plan wave:** Run the full suite command.
- **Oracle-inertness (recurring milestone gate):** After any wave that adds live routing, run the
  oracle gate + confirm no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB).
- **Before `/gsd:verify-work`:** Full suite + oracle + `mypy --strict` all green.
- **Max feedback latency:** ~20 seconds (unit); oracle on wave boundaries.

---

## Per-Task Verification Map

*(Populated during planning — one row per task, mapped to WR-01/02/04/05/06 + operator-seam
requirements. See `07-RESEARCH.md` Validation Architecture for the per-finding coverage design.)*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|--------|
| 07-01-1 | 01 | 1 | WR-02/WR-06/OP-SEAM | T-07-01-DROP | Readiness enum + EventType members | unit | `poetry run python -c "from itrader.core.enums import Readiness, EventType"` | ⬜ pending |
| 07-01-2 | 01 | 1 | WR-02/OP-SEAM | T-07-01-LEAK | 4 event structs + factories | unit | `poetry run pytest tests/unit/events/test_universe_events.py -q` | ⬜ pending |
| 07-01-3 | 01 | 1 | WR-06 | T-07-01-DROP | explicit-empty routes (no NotImplementedError) | unit | `poetry run pytest tests/unit/events/test_universe_events.py -q` | ⬜ pending |
| 07-02-1 | 02 | 2 | WR-01/WR-02 | T-07-02-DESYNC | RED readiness/keep-until-flat tests | unit | `poetry run pytest tests/unit/universe/test_universe_readiness.py -q` | ⬜ pending |
| 07-02-2 | 02 | 2 | WR-01/WR-02 | T-07-02-ORACLE | TrackedInstrument + _entries + READY default | unit | `poetry run pytest tests/unit/universe/test_universe_readiness.py -q` | ⬜ pending |
| 07-03-1 | 03 | 2 | WR-02 | T-07-03-FLOOD | absorb_warmup non-emitting ring/L | unit | `poetry run pytest tests/unit/price/test_absorb_warmup.py -q` | ⬜ pending |
| 07-03-2 | 03 | 2 | WR-02 | T-07-03-LEAK/RACE | spawn_warmup → BarsLoaded/BarsLoadFailed (scrubbed) | unit | `poetry run pytest tests/unit/price/test_spawn_warmup.py -q` | ⬜ pending |
| 07-04-1 | 04 | 3 | WR-02 | T-07-04-ORACLE | readiness gate O(1) None-guarded | unit+integration | `poetry run pytest tests/unit/strategy/test_strategies_live_membership.py tests/integration/test_backtest_oracle.py -q` | ⬜ pending |
| 07-04-2 | 04 | 3 | WR-02 | — | on_bars_loaded warm concerned, no signals | unit | `poetry run pytest tests/unit/strategy/test_strategies_live_membership.py -q` | ⬜ pending |
| 07-04-3 | 04 | 3 | OP-SEAM | T-07-04-FANOUT | on_strategy_command mutate + emit UNIVERSE_POLL | unit | `poetry run pytest tests/unit/strategy/test_strategies_live_membership.py -q` | ⬜ pending |
| 07-05-1 | 05 | 3 | WR-05/WR-06 | T-07-05-FREEZE/COUPLE | on_poll dedicated route + freeze gate | unit | `poetry run pytest tests/unit/universe/test_universe_poll.py -q` | ⬜ pending |
| 07-05-2 | 05 | 3 | WR-04 | T-07-05-PRECISION | precision resolver seam + on_poll resolve | unit | `poetry run pytest tests/unit/universe/test_universe_poll.py -q` | ⬜ pending |
| 07-08-1 | 08 | 3 | WR-02 (D-01 PRIMARY gate) | T-07-08-UNWARMED/ORACLE | admission readiness gate: non-READY symbol rejected AT ADMISSION even bypassing the strategy loop; oracle-inert | unit+integration | `poetry run pytest tests/unit/order/test_admission_readiness_gate.py tests/integration/test_backtest_oracle.py -q` | ⬜ pending |
| 07-06-1 | 06 | 4 | WR-02 | T-07-06-ORDER/BATCH | async add-branch + warmup consumers + isolation | unit | `poetry run pytest tests/unit/universe/test_universe_warmup_consumers.py -q` | ⬜ pending |
| 07-06-2 | 06 | 4 | WR-01 | T-07-06-DROP | discard_instrument teardown (2 points) | integration | `poetry run pytest tests/integration/test_universe_remove_policy.py -q` | ⬜ pending |
| 07-06-3 | 06 | 4 | OP-SEAM | — | strategy-derived selection source | unit | `poetry run pytest tests/unit/universe -q` | ⬜ pending |
| 07-07-1 | 07 | 5 | OP-SEAM | T-07-07-INJECT/SPOOF-ORDER | add_event allowlist fail-closed | unit | `poetry run pytest tests/unit/trading_system/test_add_event_admission_guard.py -q` | ⬜ pending |
| 07-07-2 | 07 | 5 | WR-04/WR-06/OP-SEAM | T-07-07-CLOCK | live route wiring + poll-event swap + seams | unit | `poetry run pytest tests/unit/trading_system tests/unit/universe -q` | ⬜ pending |
| 07-07-3 | 07 | 5 | (milestone gate) | T-07-07-ORACLE | oracle byte-exact + inertness + W1/W2 (checkpoint) | integration | `poetry run pytest tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py -q` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*(Confirmed at plan time. Expected new stub files for the readiness gate, the two warmup events, the
`StrategyCommandEvent`, the `UNIVERSE_POLL` route, and the allowlist inversion.)*

- [ ] `tests/unit/universe/` — readiness-gate + TrackedInstrument + keep-until-flat stubs (WR-01/WR-02)
- [ ] Warmup async-fetch → `BarsLoaded`/`BarsLoadFailed` → warm + ready-flip stubs (WR-02 / D-03/D-04)
- [ ] `add_event` allowlist fail-closed test (D-10; update existing `test_add_event_admission_guard.py`)
- [ ] `UNIVERSE_POLL` route + HALT/pause gating stubs (WR-05/WR-06)
- [ ] Oracle-inertness regression assertion (backtest member always READY; no live routing on golden path)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live OKX async warmup end-to-end | WR-02 | Requires live/sandbox connector + network; unit tests use fakes | Drive add_ticker on a live-sandbox session; confirm PENDING→READY→subscribe ordering |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s (unit)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
