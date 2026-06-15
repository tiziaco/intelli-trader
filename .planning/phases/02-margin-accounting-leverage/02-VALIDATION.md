---
phase: 2
slug: margin-accounting-leverage
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-15
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; markers: `unit`/`integration`/`slow`/`e2e` only — type marker folder-derived) |
| **Quick run command** | `poetry run pytest tests/unit/portfolio tests/unit/order -q` |
| **Full suite command** | `make test` |
| **Type gate** | `poetry run mypy itrader` (strict, `files=["itrader"]`) |
| **Byte-exact oracle** | `poetry run pytest tests/integration/test_backtest_oracle.py -x` → MUST stay **134 trades / final_equity 46189.87730727451** |
| **Estimated runtime** | unit suites ~5–15s; `mypy itrader` ~20–40s; integration oracle ~30–90s; e2e levered_long ~5–20s; full `make test` ~2–4 min |

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/<touched-domain> -x` + `poetry run mypy itrader` on touched files.
- **After every plan wave:** `make test-unit` + `poetry run pytest tests/integration/test_backtest_oracle.py -x` (oracle MUST hold byte-exact) + `poetry run mypy itrader`.
- **Before `/gsd:verify-work`:** Full `make test` green + `mypy itrader` clean + integration oracle byte-exact (134 / 46189.87730727451) + the parked leveraged-long e2e passing its hand-computed assertions.
- **Max feedback latency:** ~15s (unit suite per touched domain); the oracle integration run (~30–90s) and the e2e (~5–20s) are the slow gates, sampled per-wave and at the phase gate (not per task).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-00-01 | 00 | 0 | MARGIN-01/02/03, LEV-01/02 | T-02-00 / T-02-22 | Nyquist Wave 0: every downstream `-k`/`-m` target collects ≥1 (skipped) test; no unregistered marker | unit+e2e | `poetry run pytest tests/unit/order tests/unit/portfolio -k "levered_fraction or leverage_cap or over_margin or locked_margin or scale_in_margin or one_leverage or maintenance_margin or margin_ratio or max_leverage" --collect-only -q` (+ `tests/e2e/levered_long -m e2e --collect-only -q`) | ✅ (creates stubs) | ⬜ pending |
| 02-01-01 | 01 | 1 | LEV-01 | T-02-01 / T-02-02 | `SignalEvent.leverage` defaults `Decimal("1")` (string path); oracle-dark | static | `poetry run python -c "from itrader.events_handler.events.signal import SignalEvent; import dataclasses,decimal; assert dataclasses.fields(SignalEvent)"` + `poetry run mypy itrader` | ✅ | ⬜ pending |
| 02-01-02 | 01 | 1 | LEV-01 | T-02-01 / T-02-02 | `TradingRules.max_leverage` ge=1 floor enforced; default `Decimal("1")` | static | `poetry run python -c "from itrader.config.portfolio import TradingRules; TradingRules()"` + `poetry run mypy itrader` | ✅ | ⬜ pending |
| 02-02-01 | 02 | 1 | LEV-02 | T-02-03 / T-02-04 | `LeveredFraction` f>0 guard; FractionOfCash (0,1] guard untouched; `assert_never` exhaustive | static | `poetry run python -c "from itrader.core.sizing import LeveredFraction, SizingPolicy, SignalIntent"` + `poetry run mypy itrader` | ✅ | ⬜ pending |
| 02-02-02 | 02 | 1 | LEV-02 | T-02-05 / T-02-06 | Resolver sizes `notional = f × total_equity()` (D-12, never cash); no clamp here | unit | `poetry run pytest tests/unit/order/test_sizing_resolver.py -k levered_fraction -x` | ✅ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | LEV-01, LEV-02, MARGIN-01, MARGIN-02 | — | [BLOCKING] `Optional[Universe]` + enable_margin + portfolio_max_leverage threaded order-domain; `set_universe` seam; defaults byte-exact | static | `poetry run python -c "import inspect; from itrader.order_handler.admission.admission_manager import AdmissionManager; inspect.signature(AdmissionManager.__init__)"` + `poetry run mypy itrader` | ✅ | ⬜ pending |
| 02-03-02 | 03 | 2 | LEV-01, LEV-02 | T-02-08 / T-02-10 | `_effective_leverage = min(signal, instr, pf)` clamp+warn (D-05); spot forces 1 no instrument read; f>1+spot → audited REJECTED | unit | `poetry run pytest tests/unit/order/test_admission_rules.py -k "leverage_cap or leverage_forced_one or levered_fraction_gate" -x` | ✅ W0 | ⬜ pending |
| 02-03-03 | 03 | 2 | MARGIN-01, MARGIN-02 | T-02-07 / T-02-09 | Reservation branch: margin `notional/L + commission`, spot `notional + commission` (NO division, Pitfall 4); over-margin → audited REJECTED; SMA_MACD byte-exact | unit+integration | `poetry run pytest tests/unit/order/test_admission_rules.py -k "over_margin or margin_reservation" -x` + `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ W0 | ⬜ pending |
| 02-04-01 | 04 | 2 | MARGIN-01 | T-02-13 / T-02-14 | Position-keyed `locked_margin` lock/release full-precision; `available = balance − reserved − locked_margin`; empty → clean `Decimal("0")` (byte-exact) | unit | `poetry run pytest tests/unit/portfolio/test_cash_manager.py -k locked_margin -x` | ✅ W0 | ⬜ pending |
| 02-04-02 | 04 | 2 | MARGIN-01 | T-02-12 | One leverage per position (set at open, scale-in clamped, D-06); aggregate notional queryable; PositionManager cash-agnostic | unit | `poetry run pytest tests/unit/portfolio/test_position_manager.py -k "scale_in_margin or one_leverage" -x` | ✅ W0 | ⬜ pending |
| 02-04-03 | 04 | 2 | MARGIN-01 | T-02-11 / T-02-13 | Lock-and-settle: spot unchanged (`apply_fill_cash_flow(net_delta)`); margin debits commission-only + locks `notional/L`; settles+releases pro-rata; SMA_MACD byte-exact | unit+integration | `poetry run pytest tests/unit/portfolio -k "partial_close_margin or scale_in_margin or locked_margin" -x` + `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ W0 | ⬜ pending |
| 02-05-01 | 05 | 3 | MARGIN-03 | T-02-15 | `maintenance_margin` / `margin_ratio` Protocol members declared (compute-on-demand contract, D-13) | static | `poetry run python -c "from itrader.core.portfolio_read_model import PortfolioReadModel; assert hasattr(PortfolioReadModel,'maintenance_margin') and hasattr(PortfolioReadModel,'margin_ratio')"` | ✅ | ⬜ pending |
| 02-05-02 | 05 | 3 | MARGIN-03, LEV-01 | T-02-16 / T-02-17 / T-02-18 | `maintenance_margin = Σ mmr×|size|×price` (Decimal); `margin_ratio = equity/maintenance` honest when breached (no clamp, D-16); `max_leverage` rides update_config (D-15) | unit | `poetry run pytest tests/unit/portfolio/test_portfolio_handler.py -k "maintenance_margin or margin_ratio" tests/unit/portfolio/test_update_config.py -k max_leverage -x` | ✅ W0 | ⬜ pending |
| 02-06-01 | 06 | 4 | MARGIN-01/02/03, LEV-01/02 | T-02-19 / T-02-20 / T-02-21 | Parked leveraged-long e2e: hand-computed assertions (NOT a frozen golden, D-17); exercises full margin core end-to-end | e2e | `poetry run pytest tests/e2e/levered_long -m e2e -x` | ✅ W0 | ⬜ pending |
| 02-06-02 | 06 | 4 | (phase gate) | T-02-20 / T-02-21 | Phase gate: SMA_MACD byte-exact + margin-mode determinism double-run byte-identical + mypy clean + full suite green | checkpoint | `poetry run pytest tests/integration/test_backtest_oracle.py -x` + `make test` + `poetry run mypy itrader` (blocking human-verify) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is delivered by **Plan 02-00** (this is the Nyquist stub plan). It appends skipped
stub functions to the existing unit test files and creates the new e2e file so every
downstream `-k`/`-m` verify target collects ≥1 test BEFORE any RED→GREEN cycle:

- [x] `tests/unit/order/test_sizing_resolver.py` — stub `levered_fraction` (Plan 02 / LEV-02)
- [x] `tests/unit/order/test_admission_rules.py` — stubs `leverage_cap`, `leverage_forced_one`, `over_margin`, `margin_reservation`, `levered_fraction_gate` (Plan 03 / LEV-01, LEV-02, MARGIN-01, MARGIN-02)
- [x] `tests/unit/portfolio/test_cash_manager.py` — stub `locked_margin` (Plan 04 / MARGIN-01)
- [x] `tests/unit/portfolio/test_position_manager.py` — stubs `scale_in_margin`, `one_leverage`, `partial_close_margin` (Plan 04 / MARGIN-01)
- [x] `tests/unit/portfolio/test_portfolio_handler.py` — stubs `maintenance_margin`, `margin_ratio` (Plan 05 / MARGIN-03)
- [x] `tests/unit/portfolio/test_update_config.py` — stub `max_leverage` (Plan 05 / LEV-01)
- [x] `tests/e2e/levered_long/__init__.py` + `test_levered_long_scenario.py` — new file, one e2e stub `levered_long` (Plan 06)

All target unit test files already exist (verified) — Plan 02-00 appends stub functions only;
the e2e file/dir is created fresh. No `conftest.py` or framework install needed (folder-derived
markers; pytest already installed).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Phase-2 close: leveraged-long numbers hand-verified and PARKED (not frozen as a golden in P2) | MARGIN-01/02/03, LEV-01/02 (D-16/D-17) | The owner must confirm Phase 2 freezes NO new leveraged golden — the only accounting-core re-baseline is the owner-gated freeze at Phase 4/XVAL-01 | Plan 02-06 blocking `checkpoint:human-verify`: Claude runs the oracle + determinism double-run + mypy + `make test` + the parked e2e and pastes results; owner confirms the spot oracle held and the leveraged scenario stays parked |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (Wave 0 = Plan 02-00)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (every `-k`/`-m` target collects via Plan 02-00 stubs)
- [x] No watch-mode flags
- [x] Feedback latency ≤ ~15s (unit per-domain); oracle/e2e per-wave + gate
- [x] `nyquist_compliant: true` set in frontmatter
- [x] `wave_0_complete: true` set in frontmatter

**Approval:** approved (revision: Wave 0 stub plan added; per-task map populated)
