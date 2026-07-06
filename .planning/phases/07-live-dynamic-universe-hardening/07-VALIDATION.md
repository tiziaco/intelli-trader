---
phase: 7
slug: live-dynamic-universe-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | WR-02 | — | — | unit | `poetry run pytest tests/unit/universe -q` | ❌ W0 | ⬜ pending |

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
