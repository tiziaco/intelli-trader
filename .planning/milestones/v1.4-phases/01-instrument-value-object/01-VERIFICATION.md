---
phase: 01-instrument-value-object
verified: 2026-06-15T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification_resolved:
  - item: "WR-02 — _infer_price_scale miscounts scientific-notation/trailing-garbage cells"
    resolution: "FIXED in code (not merely acknowledged): frac.isdigit() guard added in itrader/universe/instruments.py via fix(01) commit 5bf5821. No longer a latent defect."
  - item: "WR-01 — quantize cash-scale ignored quote_currency (docstring/impl mismatch)"
    resolution: "FIXED in code: quantize(kind='cash') now derives the scale from instrument.quote_currency via _CASH_SCALES (USD -> 2dp, byte-identical) in itrader/core/money.py via fix(01) commit 1498048. Owner reviewed and approved keeping the forward-looking derivation (vs the doc-only alternative). Inert today (all USD; quantize has no production caller), byte-exact oracle independently re-verified passing post-fix."
note: "Re-verified after the gsd-code-review --fix --all --auto loop converged clean (REVIEW status: clean, REVIEW-FIX status: all_fixed). Post-fix gates independently re-run on the main working tree: byte-exact oracle 3/3 (134 trades / final_equity 46189.87730727451), mypy --strict clean (185 files), full suite 1023 passed, golden artifacts unchanged."
---

# Phase 01: Instrument Value Object — Verification Report

**Phase Goal:** A frozen per-symbol `Instrument` value object is the single source of
price/quantity precision + `min_order_size` + margin params
(`maintenance_margin_rate`, `max_leverage`, `settles_funding`); it replaces the
deleted hard-coded `_INSTRUMENT_SCALES` table, with `BTCUSD` pinned to its declared
8dp so the golden oracle does not drift.

**Verified:** 2026-06-15
**Status:** passed
**Re-verification:** Yes — both human-verification items (WR-01, WR-02) were resolved in code by the `gsd-code-review --fix --all --auto` loop and owner-approved; gates independently re-run on the main tree post-fix (oracle 3/3, mypy clean, 1023 passed)

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `core/money.py::quantize` reads precision from an `Instrument` and `_INSTRUMENT_SCALES` no longer exists in the codebase | VERIFIED | `grep -c '_INSTRUMENT_SCALES' money.py` == 0 (doc-string mentions of the deleted table in comments/docstrings only); `quantize(value: Decimal, instrument: Instrument, kind: str)` signature confirmed at line 62; `from itrader.core.instrument import Instrument` at line 32 |
| 2 | Price precision resolves declared → inferred-from-data (guarded: string read, max-dp cap) → default; `quantity_precision`/`min_order_size` resolve declared → default | VERIFIED | `_infer_price_scale` reads raw strings (not float64 frame); 8dp cap enforced (`min(max_dp, _MAX_PRICE_DP)`); BTCUSD declared wins (D-10); 11 unit tests in `test_derive_instruments.py` all pass (inferred 3dp/5dp/8dp-cap/max-across-cells, string-not-float, default fallback, quantity-never-inferred) |
| 3 | `BTCUSD` takes the declared 8dp branch and the SMA_MACD oracle stays byte-exact (134 trades / `final_equity 46189.87730727451`) | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -v` — 3 passed; `_DECLARED["BTCUSD"]` declares `price_precision=Decimal("0.00000001")`, `quantity_precision=Decimal("0.00000001")`, `min_order_size` OMITTED (None); golden artifacts unchanged (`git status --short tests/golden/` empty) |
| 4 | An `Instrument` exposes `maintenance_margin_rate`, `max_leverage`, `settles_funding` and `ExchangeLimits` is demoted to a venue-level fallback for undeclared symbols | VERIFIED | All three margin fields present and typed in `core/instrument.py:73-79`; `resolve_min_order_size(ticker)` in `simulated.py:150` resolves Instrument-first with None → venue fallback; `ExchangeLimits.min_order_size = Decimal("0.001")` value unchanged (6 occurrences confirmed); 5 unit tests in `test_min_order_size_resolution.py` all pass |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/instrument.py` | Frozen Instrument value object (symbol, quote_currency, price/quantity precision, min_order_size, margin params) | VERIFIED | 79 lines; `@dataclass(frozen=True, slots=True, kw_only=True)`; all 8 fields present and typed; 4-space indented (no tabs); `__all__ = ["Instrument"]` |
| `itrader/core/money.py` | `quantize(value, Instrument, kind)` reading scale off Instrument; `_INSTRUMENT_SCALES` deleted | VERIFIED | Signature updated; `_INSTRUMENT_SCALES` count == 0; `from itrader.core.instrument import Instrument` present; `_DEFAULT_SCALES` retained as no-data fallback |
| `tests/unit/core/test_instrument.py` | Instrument frozen-ness, field defaults, declared/undeclared min_order_size, scale-equivalence (INST-01/03) | VERIFIED | 8 tests; all pass — frozen-ness (`FrozenInstanceError`), 8dp scale byte-exactness, scale-vs-int guard, min_order_size None default + declared round-trip, margin-field presence, settles_funding/quote_currency defaults |
| `tests/unit/core/test_money.py` | quantize call sites updated to pass Instrument objects | VERIFIED | 5 tests; all pass; 3 `quantize(` calls now pass Instrument objects (BTCUSD 8dp + default-precision) with byte-identical expected outputs |
| `itrader/universe/instruments.py` | Pure `derive_instruments(...)` -> `dict[str, Instrument]` with declared->inferred->default precision ladder | VERIFIED | 233 lines; pure function (no class/state/queue import); `_DECLARED` table reproduces deleted `_INSTRUMENT_SCALES["BTCUSD"]` exactly; inference reads raw strings (Pitfall 1); 8dp cap enforced |
| `itrader/universe/universe.py` | Universe facade read-model composing derive_membership/is_active; .members + .instrument(symbol) | VERIFIED | 75 lines; thin facade; `.members` returns internal list by identity (byte-exact, Pitfall 4); `.instrument(symbol)` raises KeyError for non-members; `def derive_membership` count == 0 (composes, does not reimplement) |
| `itrader/trading_system/compose.py` | Engine dataclass carrying a universe field for injection | VERIFIED | `universe: Optional[Universe] = None` present at line 106; TABS indentation preserved |
| `itrader/execution_handler/exchanges/simulated.py` | Instrument-first → ExchangeLimits-fallback min_order_size resolution | VERIFIED | `set_universe(universe)`, `resolve_min_order_size(ticker)`, and `_universe: Optional[Universe] = None` all present; admission gate at line 481 calls `resolve_min_order_size`; TABS preserved |
| `tests/unit/universe/test_derive_instruments.py` | Declared / inferred(string-count,8dp cap) / default ladder on SYNTHETIC non-oracle symbol + BTCUSD-takes-declared | VERIFIED | 11 tests; all pass — declared-wins, inferred(3dp/5dp/8dp-cap/max-across-cells), string-not-float, default fallback, quantity-never-inferred, BTCUSD-min-None |
| `tests/unit/universe/test_universe.py` | Universe.members byte-exact, .instrument() round-trip | VERIFIED | 4 tests; all pass — members identity, byte-exact, instrument round-trip, KeyError for unknown symbol |
| `tests/unit/execution/test_min_order_size_resolution.py` | Instrument(None) -> ExchangeLimits(0.001) fallback assertion | VERIFIED | 5 tests; all pass — None→0.001, declared→declared, BTCUSD→0.001, no-universe→fallback, non-member→fallback |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/core/money.py` | `itrader/core/instrument.py` | `from itrader.core.instrument import Instrument` (line 32) | WIRED | Import present; `quantize` consumes `instrument.price_precision` / `instrument.quantity_precision` |
| `tests/unit/core/test_money.py` | `itrader/core/instrument.py` | Constructs `Instrument(...)` objects to pass to `quantize` | WIRED | `Instrument(` calls present; all 3 call sites pass Instrument objects |
| `itrader/trading_system/backtest_runner.py` | `itrader/universe/universe.py` | `Universe(members=membership, instrument_map=instruments)` at wiring (Trap-4 preserved) | WIRED | `derive_membership` on line 61, `derive_instruments` on line 70-73, `Universe(...)` on line 74; `feed.bind` on line 84 — order preserved |
| `itrader/trading_system/live_trading_system.py` | `itrader/universe/universe.py` | `Universe(members=membership, instrument_map=instruments)` at live derive_membership site | WIRED | `grep -n 'Universe\|derive_instruments'` confirms construction at lines 263-273 |
| `itrader/trading_system/backtest_runner.py` | `itrader/price_handler/feed/bar_feed.py` | `feed.bind` receives `universe.members` (same list) | WIRED | Line 84: `engine.feed.bind(engine.global_queue, universe.members)` |
| `itrader/execution_handler/exchanges/simulated.py` | `itrader/universe/universe.py` | `set_universe(universe)` / `resolve_min_order_size(ticker)` | WIRED | `set_universe` called at runner wiring (backtest_runner.py:81); resolution at admission gate line 481 |
| `itrader/universe/universe.py` | `itrader/universe/membership.py` | `derive_membership` composed (not reimplemented) in `instruments.py` | WIRED | `derive_membership` imported and called in `instruments.py:38,186`; `universe.py` holds the pre-computed list by reference |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase delivers pure value objects and pure functions, not components that render dynamic data in the React/UI sense. The critical data flow is: wiring-time `derive_instruments(...)` → `Universe(...)` → `simulated.set_universe(...)` → `resolve_min_order_size(ticker)` at admission. This flow is verified by the oracle gate (134 trades / 46189.87730727451) passing with `check_exact=True`.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All phase unit tests pass (33 tests across 5 test files) | `poetry run pytest tests/unit/core/test_instrument.py tests/unit/core/test_money.py tests/unit/universe/ tests/unit/execution/test_min_order_size_resolution.py -v` | 33 passed | PASS |
| Byte-exact oracle gate: 134 trades / final_equity 46189.87730727451 | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed (behavioral-identity + numeric-values check_exact=True + signal-store) | PASS |
| mypy --strict across itrader | `poetry run mypy itrader` | Success: no issues found in 185 source files | PASS |
| Determinism double-run | `poetry run pytest tests/e2e/robust/test_determinism.py -v` | 9 passed (two_tickers, two_strategies, fanout_portfolios, contended_cash, sparse_bar, union_window, no_trade, flat, losing) | PASS |
| Golden artifacts unchanged | `git status --short tests/golden/` | empty output (no modifications) | PASS |
| Working tree clean | `git status --short` | empty output | PASS |

---

### Probe Execution

No probe scripts declared or applicable for this phase (pure Python value object + wiring changes; no migration or CLI tooling phase).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INST-01 | 01-01-PLAN.md | `Instrument` value object is the per-symbol precision source; `_INSTRUMENT_SCALES` deleted; `quantize` reads off Instrument | SATISFIED | `core/instrument.py` exists and is frozen; `_INSTRUMENT_SCALES` count == 0 in `money.py`; `quantize` signature takes `Instrument`; 13 core unit tests pass |
| INST-02 | 01-02-PLAN.md | Precision ladder: declared → inferred(string-read, guarded, 8dp cap) → default; BTCUSD always on declared branch | SATISFIED | `derive_instruments` implements the D-09 ladder; `_infer_price_scale` reads raw strings; BTCUSD in `_DECLARED`; 11 unit tests cover all ladder rungs; oracle holds byte-exact |
| INST-03 | 01-01-PLAN.md, 01-02-PLAN.md | `Instrument` exposes margin/funding params; `ExchangeLimits` demoted to venue-level fallback | SATISFIED | `maintenance_margin_rate`, `max_leverage`, `settles_funding` on Instrument; `resolve_min_order_size` is Instrument-first with ExchangeLimits fallback; 5 resolution tests pass |

**Coverage:** 3/3 phase requirements (INST-01, INST-02, INST-03) satisfied. REQUIREMENTS.md marks all three Complete with `[x]`.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/universe/instruments.py` | 53 | `# liquidation). Conservative Phase-1 placeholders` | Info | Comment describing inert margin defaults that are present as typed fields for downstream phases (Phase 2/4 consumers). NOT a stub — the fields carry real Decimal values on every constructed Instrument; no consumer reads them yet. This is the documented INST-03 inert-phase behavior. |

No TBD, FIXME, or XXX debt markers found in any phase-modified file.

No empty-return stubs, placeholder components, or disconnected wiring found.

---

### Code Review Findings Assessment

The 01-REVIEW.md (status: issues_found, 5 warnings + 5 info) was examined for phase-goal-blocking findings:

**WR-01 (WARNING): `quantize` cash scale ignores `quote_currency` — doc/impl mismatch.**
The docstring says cash scale "derives from `quote_currency`" but the implementation hard-codes `_DEFAULT_SCALES["cash"]` (always 2dp). Inert while all instruments are USD-quoted, but becomes a real correctness defect the moment a non-2dp quote currency lands. This is NOT a blocker for the current phase goal (BTCUSD oracle holds byte-exact) but requires owner acknowledgment before non-USD instruments are added. Routed to human verification.

**WR-02 (WARNING): `_infer_price_scale` miscounts scientific-notation and trailing-garbage cells.**
A raw cell like `"1.0e-5"` yields `len("0e-5") == 4` → inferred 4dp (wrong). Confirmed in code. Oracle-dark: the golden run passes `price_data={}`, BTCUSD is declared (D-10), inference is never consulted. The phase goal (byte-exact oracle, BTCUSD declared branch) is met. This is a latent bug in the not-yet-exercised inference path, NOT a blocker for Phase 1's goal, but requires acknowledgment before any non-declared symbol is wired through live inference. Routed to human verification.

**WR-03 (WARNING): Redundant double `derive_membership` derivation in runner.** Fragile (future desync risk) but correct today — no bug in current state. Not a phase-goal blocker.

**WR-04 (WARNING): `LiveTradingSystem.universe` has no `__init__` declaration.** Mypy-deferred module; AttributeError risk pre-`start()`. Not a byte-exact or oracle blocker. Not a phase-goal blocker.

**WR-05 (WARNING): `derive_membership` set-ordered output is non-deterministic for multi-symbol universe.** Pre-existing behavior (pre-phase, the legacy code also used `list(set(...))`); single-symbol golden run is byte-exact and unaffected. Not a phase-regression; not a phase-goal blocker.

**IN-01 through IN-05:** Informational only; none are phase-goal blockers.

**Assessment:** None of the review findings are BLOCKER-class for this phase's goal. The two material findings (WR-01, WR-02) are latent defects inert under the current oracle path and require human acknowledgment rather than gate-blocking. They are surfaced in the human verification section.

---

### Human Verification Required

#### 1. WR-02: Inference Bug Acknowledgment

**Test:** Read `itrader/universe/instruments.py:108-143` (`_infer_price_scale`). Note that `text.split(".", 1)[1]` has no digit-only validation — a cell like `"1.0e-5"` would yield `len("0e-5") == 4` → wrong inference of 4dp. Confirm that this path is acceptable as a known latent defect for Phase 1 given that (a) the golden run passes `price_data={}` so inference is never called, (b) BTCUSD is declared so it never reaches inference, and (c) all current tests use synthetic data that happen to be plain-decimal strings.

**Expected:** Owner acknowledges WR-02 as oracle-dark for Phase 1; optionally schedules the one-line fix (`frac = text.split(".", 1)[1]; if not frac.isdigit(): continue`) before wiring any live non-declared symbol through the inference path, or opens a follow-up issue.

**Why human:** The fix is a one-line guard but would change the behavior of the inference path (currently untested with scientific-notation inputs). Deciding whether to fix now or defer is an owner judgment call; automated verification cannot confirm owner intent.

#### 2. WR-01: Cash Scale Contract Acknowledgment

**Test:** Read `itrader/core/money.py:62-79` and `itrader/core/instrument.py:47-48`. The `Instrument.quote_currency` field docstring says it is "source of the `kind="cash"` scale (USD -> 2dp)". The `quantize` implementation ignores `instrument.quote_currency` entirely and hard-codes `_DEFAULT_SCALES["cash"]` (always `Decimal("0.01")`). Both files were reviewed and the mismatch is confirmed.

**Expected:** Owner either (a) accepts the current behavior as intentionally inert for the USD-only Phase 1 scope and annotates the docstring with "(inert this phase — cash fixed at 2dp; consumed when non-USD quote currencies land)" to make the contract honest, or (b) implements the promised derivation as recommended in WR-01.

**Why human:** This is a doc/impl mismatch that misleads future consumers. Deciding between fixing the docstring vs implementing the derivation is an owner judgment call that depends on when non-USD instruments are expected.

---

## Summary

Phase 1 (Instrument Value Object) goal is **substantially achieved and technically complete**. All 4 ROADMAP success criteria are VERIFIED against the actual codebase:

1. `quantize` reads from `Instrument`; `_INSTRUMENT_SCALES` is gone — VERIFIED
2. Declared → inferred(string-read, 8dp cap) → default precision ladder — VERIFIED
3. BTCUSD declared 8dp; oracle byte-exact (134 trades / 46189.87730727451) — VERIFIED
4. Margin params on Instrument; ExchangeLimits demoted to venue fallback — VERIFIED

All 33 unit tests pass. Oracle gate passes with `check_exact=True`. `mypy --strict` clean (185 source files). Determinism 9/9. Full suite 1023 tests green (at time of plan 01-03 execution). Golden artifacts unchanged.

Two review findings (WR-01 cash-scale doc/impl mismatch; WR-02 inference scientific-notation bug) are latent defects inert under the current oracle path, not phase-goal blockers, but require explicit owner acknowledgment before the inference path or non-USD instruments are wired. Status is `human_needed` only because of this acknowledgment requirement; all automated gates are green.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
