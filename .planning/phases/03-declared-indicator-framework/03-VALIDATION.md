---
phase: 3
slug: declared-indicator-framework
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-12
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `03-RESEARCH.md` §Validation Architecture. This is a **byte-exact** phase —
> the load-bearing gate is the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`,
> EXACT, no tolerance). No SMA_MACD unit test guards the MACD value, so the oracle is
> non-optional.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/strategy -x` |
| **Full suite command** | `make test` |
| **Estimated runtime** | quick ~1-2s · full suite (incl. oracle + e2e) ~3-5 min |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/strategy -x` (sub-second indicator/primitive units)
- **After every plan wave:** Run `make test-e2e` + `poetry run pytest tests/integration/test_backtest_oracle.py`
- **Before `/gsd:verify-work`:** `make test` green + `poetry run mypy itrader` clean
- **Max feedback latency:** ~5s for the unit slice; the oracle/e2e run is a per-wave gate

---

## Per-Task Verification Map

> Task IDs are forward references (plans not yet authored). Mapped by requirement +
> byte-exact verification protocol (RESEARCH §Byte-Exact Verification Protocol).

| Item | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| primitives crossover/crossunder/is_above/is_below + scalar broadcast (D-02) | IND-01 | — | N/A | unit | `poetry run pytest tests/unit/strategy/test_primitives.py -x` | ❌ W0 | ⬜ pending |
| EMA/RSI adapters + `min_period(w)→w`; assert SMA/MACDHist min_period (50/100/15) (D-07/D-08) | IND-01 | — | N/A | unit | `poetry run pytest tests/unit/strategy/test_indicators.py -x` | ❌ W0 | ⬜ pending |
| `warmup == max_window == 100` after `init()` (auto-derived) | IND-01 | — | N/A | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -k warmup -x` | ❌ W0 | ⬜ pending |
| SMA_MACD `generate_signal(ticker)` returns BUY on bullish crossover; None on short frame | IND-01 | — | N/A | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -x` | ✅ (signature migration) | ⬜ pending |
| BTCUSD oracle byte-exact (134 trades / 46189.87730727451) — **the gate** | IND-01 | — | N/A | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ existing | ⬜ pending |
| e2e leaves byte-exact (all green; baseline count — Open Q1) | IND-01 | — | N/A | e2e | `make test-e2e` | ✅ existing | ⬜ pending |
| determinism double-run byte-identical | IND-01 | — | N/A | integration | run oracle twice, diff | ✅ via oracle harness | ⬜ pending |
| `mypy --strict` clean (typed adapter symbols + handle wrapper) | IND-01 | — | N/A | static | `poetry run mypy itrader` | ✅ existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/strategy/test_primitives.py` — crossover/crossunder/is_above/is_below + scalar broadcast (D-02)
- [ ] `tests/unit/strategy/test_indicators.py` — EMA/RSI adapters + `min_period`; assert SMA/MACDHist `min_period` (50/100/15)
- [ ] New assertion in `tests/unit/strategy/test_strategy.py`: `strategy.warmup == strategy.max_window == 100` post-`init()`
- [ ] Migrate `test_strategy.py` direct `generate_signal(ticker, bars)` call sites to the no-`bars` shape (through the `evaluate` seam or set `self.bars`/`self.now` manually)

*Framework install: none — `ta` 0.11.0 / `pandas` 2.3.3 already present.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Eager-vs-lazy MACD reorder is value-identical (Pitfall 2) | IND-01 | No unit test guards the MACD value; proven by code review + the oracle | Confirm via `tests/integration/test_backtest_oracle.py` passing EXACT |
| SMA per-indicator slice (`bars[start_dt:]`) preserved (Pitfall 1) | IND-01 | The byte-exact landmine — verified only by the oracle, not a dedicated unit | Oracle must show 134 trades / 46189.87730727451; a 1-2 trade delta is the tell-tale of an ULP boundary flip |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test_primitives.py, test_indicators.py, warmup assertion)
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s (unit slice)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
