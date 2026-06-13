---
phase: 05
slug: signal-contract-reconcile-fragile
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-13
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; markers: unit/integration/slow/e2e) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit/strategy tests/unit/order -q` |
| **Full suite command** | `make test` |
| **Byte-exact canary** | `poetry run pytest tests/integration/test_backtest_oracle.py` → 134 / `46189.87730727451` |
| **Type gate** | `poetry run mypy --strict` (over `itrader`) |
| **Worktree note** | prepend `PYTHONPATH="$PWD"` if pytest/mypy don't see worktree edits (editable-install shadowing, MEMORY) |

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/strategy tests/unit/order -q` + `poetry run mypy --strict`
- **After every plan wave:** `make test` + the byte-exact canary (`tests/integration/test_backtest_oracle.py`) + `tests/e2e -m e2e` (58/58)
- **Before `/gsd:verify-work`:** Full suite green; oracle byte-exact; mypy --strict clean; determinism double-run identical; NEW limit golden owner-signed + cross-validated
- **Max feedback latency:** touched-domain quick loop is seconds; full suite under a couple of minutes

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | SIG-01/02 | T-05-02 / T-05-04 | SignalIntent/SignalRecord carry order_type+entry_price; money via to_money (no Decimal(float)) | unit + mypy | `poetry run mypy --strict itrader/core/sizing.py itrader/strategy_handler/signal_record.py` | ✅ (mypy) | ⬜ pending |
| 05-01-02 | 01 | 1 | SIG-01/02 | T-05-01 / T-05-04 | 6 factories; price required+kw-only (illegal combos unrepresentable); buy()/sell() MARKET byte-exact | unit | `poetry run pytest tests/unit/strategy/test_signal_factories.py -x` | ❌ W0 (new) | ⬜ pending |
| 05-01-03 | 01 | 1 | SIG-01/02 | T-05-03 | Fan-out reads intent.order_type; MARKET keeps to_money(bar.close) (oracle byte-exact) | integration + e2e | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m e2e -q` | ✅ | ⬜ pending |
| 05-02-01 | 02 | 1 | SIG-03 | T-05-05 / T-05-08 | Order.action+_PendingBracket.action are Side; literal sites narrowed; W4-04 doc updated | unit + mypy | `poetry run mypy --strict && poetry run pytest tests/unit/order -x` | ✅ | ⬜ pending |
| 05-02-02 | 02 | 1 | SIG-03 | T-05-06 / T-05-07 | Single threaded Position snapshot; oracle byte-exact under single-writer contract | integration + e2e | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m e2e -q` | ✅ | ⬜ pending |
| 05-03-01 | 03 | 1 | RECON-01 | T-05-09 / T-05-10 | body-raise-still-releases (WR-04); unknown-status-holds reservation; 3 terminal releases | unit | `poetry run pytest tests/unit/order/test_reconcile_manager.py -x` | ✅/❌ W0 (extend) | ⬜ pending |
| 05-03-02 | 03 | 1 | RECON-01 | T-05-11 / T-05-12 | Extract-method on_fill; try/finally byte-identical; oracle byte-exact | unit + integration + e2e | `poetry run pytest tests/unit/order/test_reconcile_manager.py tests/integration/test_backtest_oracle.py tests/e2e -m e2e -q` | ✅ | ⬜ pending |
| 05-04-01 | 04 | 2 | SIG-01/02 | T-05-15 | Crafted buy_limit strategy on BTCUSD; e2e leaf; no engine import under tests/ | e2e | `poetry run pytest tests/e2e/matching/entries/limit_entry_crossval -m e2e -q` | ❌ W0 (new) | ⬜ pending |
| 05-04-02 | 04 | 2 | SIG-01/02/RECON-01 | T-05-15 / T-05-16 | LIMIT runners (backtesting.py+backtrader) SCRIPT-ONLY; three-engine reconcile report | script | `poetry run python scripts/cross_validate_limit.py` | ❌ W0 (new) | ⬜ pending |
| 05-04-03 | 04 | 2 | SIG-01/02/RECON-01 | T-05-13 / T-05-14 / T-05-17 | Owner sign-off freezes the golden; existing oracle unchanged; determinism double-run | manual + integration | `poetry run pytest tests/e2e/matching/entries/limit_entry_crossval -m e2e && poetry run pytest tests/integration/test_backtest_oracle.py` | ❌ (golden frozen post sign-off) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity check:** No 3 consecutive tasks lack an `<automated>` verify — every task above has an automated command (05-04-03's freeze is gated by a human checkpoint but still ends in an automated leaf assertion).

---

## Wave 0 Requirements

- [ ] `tests/unit/strategy/test_signal_factories.py` — buy_limit/buy_stop/sell_limit/sell_stop produce the right SignalIntent (order_type, entry_price, sl/tp/exit_fraction); price required+kw-only; buy()/sell() stay MARKET-only (Plan 01 Task 2).
- [ ] `tests/unit/order/test_reconcile_manager.py` — confirm/extend coverage for body-raise-still-releases (WR-04) + unknown-status-holds-reservation + the three terminal releases, GREEN against current code BEFORE the RECON-01 refactor (Plan 03 Task 1).
- [ ] `scripts/crossval/limit_entry_strategy.py` + the LIMIT runners (`backtesting_py_limit_run.py`, `backtrader_limit_run.py`) + `scripts/cross_validate_limit.py` + the `tests/e2e/matching/entries/limit_entry_crossval/` leaf — the D-07 cross-val deliverable (Plan 04 Tasks 1-2).
- [ ] mypy is already the strict type gate (no install) — the SIG-03 `Side` retype must be mypy-clean.

*The byte-exact integration oracle and the e2e suite (58/58) already exist and cover the byte-exact discipline.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Freeze the NEW LIMIT golden master | SIG-01/02/RECON-01 (D-07) | Owner-gated re-baseline — a result-changing golden may freeze ONLY after explicit owner sign-off with full attribution (STATE Milestone Gate) | Read `tests/golden/CROSS-VALIDATION-LIMIT.md`; confirm the cross-val verdict + the D-07 scenario properties (later-bar fill, entry-fill→bracket, marketable-limit-at-open); confirm the existing oracle is still 134/46189.87730727451; sign off with attribution; the executor then freezes the golden and the e2e leaf goes green. (Plan 04 Task 3 — `checkpoint:human-verify`, `autonomous: false`.) |

*Everything else has automated verification (the freeze itself ends in an automated e2e-leaf assertion).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (factory test, reconcile branch test, cross-val deliverable)
- [x] No watch-mode flags
- [x] Feedback latency acceptable (touched-domain quick loop = seconds)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
