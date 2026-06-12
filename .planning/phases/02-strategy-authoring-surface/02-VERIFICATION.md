---
phase: 02-strategy-authoring-surface
verified: 2026-06-12T00:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Phase 2: Strategy Authoring Surface Verification Report

**Phase Goal:** A strategy author declares params as real annotated class attributes (no frozen-config subclass, no manual field-copy), overridable at construction, with the base rejecting unknown kwargs loudly — and a re-runnable idempotent `init()` hook that later phases build on.

**Verified:** 2026-06-12T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Base `Strategy` owns engine-facing names with defaults; subclass pins intrinsic values + alpha knobs as annotated class attrs; all overridable at construction via `**kwargs` | ✓ VERIFIED | `base.py:59-69` declares all 8 engine-facing attrs; `SMA_MACD_strategy.py:28-40` pins golden defaults; construction override confirmed by live run: `SMAMACDStrategy(tickers=["BTCUSD"], timeframe="1d", short_window=30).short_window == 30` |
| 2 | Unknown kwarg raises `UnknownParamError`; missing required attr raises `MissingParamError`; enum-typed fields (timeframe str) are coerced | ✓ VERIFIED | `base.py:125-126` raises `UnknownParamError(sorted(kwargs))`; `base.py:120` raises `MissingParamError(nm)`; `base.py:122-123` coerces via `_COERCE` table; live execution confirmed all three; 6/6 `test_strategy_config.py` tests pass |
| 3 | `generate_signal` reads real typed instance attrs (`self.short_window`, `self.timeframe`); frozen-config mutation guard dropped; `reconfigure()` is the sanctioned re-config path | ✓ VERIFIED | `SMA_MACD_strategy.py:61-65` reads `self.timeframe`, `self.short_window`; no `self.config` reference in `generate_signal`; `base.py:169-178` defines `reconfigure()` re-applying, re-validating, re-running `init()`; `test_reconfigure_reapplies_and_revalidates` passes |
| 4 | `init()` is overridable, called at end of construction, idempotent (calling twice leaves identical state) | ✓ VERIFIED | `base.py:161-167` no-op hook; `base.py:83` called at construction end; `test_init_is_idempotent` passes: `before == after` after second `init()` call |
| 5 | `SMAMACDStrategy` runs byte-exact against BTCUSD oracle: 134 trades / `final_equity 46189.87730727451` | ✓ VERIFIED | `tests/golden/summary.json` pins `trade_count: 134`, `final_equity: 46189.87730727451`; `pytest tests/integration/test_backtest_oracle.py` → 3 passed; two consecutive oracle runs produce identical value |
| 6 | e2e 58/58 green | ✓ VERIFIED | `pytest tests/e2e/ -x` → 58 passed |
| 7 | `mypy --strict itrader/` clean | ✓ VERIFIED | `mypy --strict itrader/` → "Success: no issues found in 172 source files" |
| 8 | Pydantic strategy-config layer (`itrader/config/strategy.py`, `BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig`) fully deleted with no dead dual-path | ✓ VERIFIED | `itrader/config/strategy.py` does not exist; zero `BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig` references anywhere in `itrader/`, `tests/`, or `scripts/`; `itrader/config/__init__.py` has no `BaseStrategyConfig` entry |
| 9 | Full 853-test suite green (no `filterwarnings=["error"]` failures, all markers declared) | ✓ VERIFIED | `make test` → 853 passed in 10.36s |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/exceptions/strategy.py` | `UnknownParamError` + `MissingParamError` subclassing `ValidationError` | ✓ VERIFIED | File exists, 4-space, module docstring, both errors subclass `ValidationError`, construct under engine call-shapes |
| `itrader/core/exceptions/__init__.py` | Barrel re-export of both strategy exceptions | ✓ VERIFIED | `from .strategy import (UnknownParamError, MissingParamError)` at line 39-42; both in `__all__` |
| `itrader/strategy_handler/base.py` | `Strategy` ABC with class-attr surface, `_apply_params` engine, `init`/`validate`/`reconfigure` hooks | ✓ VERIFIED | All 4 methods present; class-attr surface complete with bare-annotation required fields and defaulted knobs; `_MISSING` sentinel + `_COERCE` table present |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | Class-attr `SMAMACDStrategy` with golden defaults + `validate()` short<long + no-op `init()` | ✓ VERIFIED | Golden defaults verbatim (`short_window=50`, `long_window=100`, `fast_window=6`, `slow_window=12`, `signal_window=3`, `max_window=100`, `warmup=100`, `FractionOfCash(Decimal("0.95"))`); `validate()` raises on `short >= long`; no `SMA_MACDConfig` |
| `itrader/strategy_handler/signal_record.py` | `SignalRecord.config` typed `dict[str, Any]` | ✓ VERIFIED | `config: dict[str, Any]` at line 84; no `BaseStrategyConfig` import |
| `scripts/run_backtest.py` | Oracle generator constructing `SMAMACDStrategy` via kwargs | ✓ VERIFIED | `SMAMACDStrategy(timeframe=TIMEFRAME, tickers=[TICKER], sizing_policy=FractionOfCash(Decimal("0.95")), ...)` at lines 80-86; no `SMA_MACDConfig` import |
| `tests/unit/strategy/test_strategy_config.py` | Class-attr-surface unit tests (unknown/missing/override/coerce/no-coerce) | ✓ VERIFIED | 6 tests covering all surface behaviors; imports `UnknownParamError`; all 6 pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/strategy_handler/base.py` | `itrader.core.exceptions.strategy.UnknownParamError` | raise on unknown kwarg | ✓ WIRED | `base.py:10` imports; `base.py:126` raises `UnknownParamError(sorted(kwargs))` |
| `itrader/strategy_handler/base.py` | `itrader.outils.time_parser.to_timedelta` | enum→timedelta resolution for `self.timeframe` | ✓ WIRED | `base.py:14` imports; `base.py:150` calls `to_timedelta(self._timeframe.value)` |
| `itrader/strategy_handler/strategies_handler.py` | `strategy.to_dict()` | `SignalRecord` config snapshot capture (D-04) | ✓ WIRED | `strategies_handler.py:126` passes `config=strategy.to_dict()`; zero `config=strategy.config` references |
| `itrader/core/exceptions/__init__.py` | `itrader/core/exceptions/strategy.py` | `from .strategy import` | ✓ WIRED | barrel re-exports both errors; `from itrader.core.exceptions import UnknownParamError, MissingParamError` succeeds |

---

### Data-Flow Trace (Level 4)

Strategy construction is value-initialization, not dynamic data rendering — no fetch/DB query path applies. The `to_dict()` snapshot reads live instance attrs (verified: `strategy_id`, `order_type.value`, `sizing_policy repr()`, etc.); `generate_signal` reads real `self.short_window` / `self.timeframe` instance attrs on every call. Data is FLOWING — no static/disconnected path.

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `base.py::to_dict()` | `self.order_type`, `self.sizing_policy`, etc. | instance attrs set by `_apply_params` | Yes | ✓ FLOWING |
| `SMA_MACD_strategy.py::generate_signal` | `self.short_window`, `self.timeframe`, `self.long_window` | instance attrs set by `_apply_params`; `self.timeframe` resolved via `to_timedelta` | Yes | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `UnknownParamError` raised on unknown kwarg | `python -c "from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy; SMAMACDStrategy(tickers=['BTCUSD'], timeframe='1d', typo=1)"` | `UnknownParamError` raised | ✓ PASS |
| `MissingParamError` raised on missing required | `python -c "from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy; EmptyStrategy(timeframe='1d', tickers=['X'])"` | `MissingParamError` raised (sizing_policy) | ✓ PASS |
| `timeframe="1d"` resolves to `timedelta` on instance | `strategy.timeframe` is `timedelta(days=1)` | Confirmed via live run | ✓ PASS |
| `init()` idempotent | `to_dict()` before and after second `init()` call equal | Confirmed by `test_init_is_idempotent` | ✓ PASS |
| BTCUSD oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -x` | 3 passed — 134 trades / `final_equity 46189.87730727451` | ✓ PASS |
| e2e suite 58/58 | `pytest tests/e2e/ -x` | 58 passed | ✓ PASS |
| mypy --strict clean | `mypy --strict itrader/` | 172 source files, no issues | ✓ PASS |
| Full suite | `pytest tests/` | 853 passed | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| STRAT-01 | 02-01, 02-02, 02-03 | Class-attribute strategy authoring surface replacing frozen pydantic config + manual field-copy; `**kwargs` engine; `UnknownParamError`/`MissingParamError`; byte-exact oracle | ✓ SATISFIED | All observable truths verified; `REQUIREMENTS.md` line 140 marks status `Complete`; all three plan waves delivered and gated green |

---

### Anti-Patterns Found

No TBD/FIXME/XXX debt markers found in any phase-modified file. The REVIEW.md warnings (WR-01 through WR-04) are all oracle-dark — assessed below against stated success criteria.

| File | Warning | Severity | Against SC? |
|------|---------|----------|------------|
| `base.py:117-124` | WR-01: shared mutable class-attr default aliased across instances | Info | No blocker — no mutable list/dict/set defaults exist in `SMAMACDStrategy` or the base's non-required knobs on the golden path. The structural hazard is real for future strategy authors but does not affect any stated SC or the oracle path. |
| `base.py:180-207` | WR-02: `to_dict()` omits `timeframe`, `tickers`, and subclass knobs | Info | No blocker — Plan 02-02 must_have truth explicitly specifies "keeping the exact 10-key set byte-identical (D-03)" — the implementation delivers exactly that. The WR-02 observation is about future snapshot fidelity (relevant to IND-01/COMP-02 phases), not a Phase 2 gap. |
| `SMA_MACD_strategy.py:52-95` | WR-03: sub-warmup `generate_signal` raises `IndexError` instead of returning `None` | Info | No blocker — the D-15 warmup short-circuit in `StrategiesHandler` guards the golden path; SC4 (byte-exact oracle) is met. The fragility affects a future strategy author who sets `warmup=0` with sparse data, but is not a Phase 2 SC violation. |
| `base.py:113-118` | WR-04: partial `reconfigure()` omission freezes the last value, not the class default | Info | No blocker — this is the documented intentional behavior (RESEARCH Open Question 1). SC3 ("sanctioned-`reconfigure()`-only discipline replaces the dropped frozen-config mutation guard") is met. The asymmetry is a documentation gap, not a missing contract. |

No anti-pattern in the reviewed files constitutes a blocker. Zero debt markers.

---

### Human Verification Required

None. All success criteria are mechanically verifiable:

- Byte-exact oracle (134 trades / `46189.87730727451`): verified by running the integration test suite.
- `mypy --strict`: verified by running mypy.
- e2e 58/58: verified by running the e2e suite.
- Behavioral rejection (UnknownParamError/MissingParamError): verified by live execution.
- Config layer deletion: verified by filesystem + grep.

No visual, real-time, or external-service behavior is involved in this phase.

---

### Gaps Summary

No gaps. All 9 must-haves are VERIFIED. The four REVIEW.md warnings (WR-01 through WR-04) are all oracle-dark and do not contradict any stated success criterion:

- WR-01 (mutable default aliasing): no mutable defaults on the golden path; future authoring guidance concern.
- WR-02 (to_dict() scope): the stated D-03 truth is "10-key byte-identical shape" — delivered exactly.
- WR-03 (sub-warmup IndexError): D-15 framework warmup short-circuit guards all production call paths; the oracle gate is green.
- WR-04 (reconfigure omission semantics): intentional per RESEARCH Open Question 1; SC3 reconfigure discipline is satisfied.

These warnings are appropriate follow-up hygiene for Phase 3 (IND-01 auto-warmup, where `warmup` semantics are re-derived) and Phase 4 (COMP-02 `update_config`, where snapshot fidelity becomes load-bearing).

---

_Verified: 2026-06-12T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
