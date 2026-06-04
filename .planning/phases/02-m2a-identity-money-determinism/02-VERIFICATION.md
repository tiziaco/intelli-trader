---
phase: 02-m2a-identity-money-determinism
verified: 2026-06-04T22:32:00Z
status: gaps_found
score: 3/4 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Backtests are deterministic — RNG seeded behind an injected Random, clock injected (no local datetime.now()), flat global order index by id"
    status: partial
    reason: |
      Multiple sub-criteria of SC#4 are not met:
      (a) BacktestClock has zero domain consumers — self.clock is constructed and set_time() is
          called every ping, but clock.now() is invoked nowhere in the codebase outside clock.py
          itself. Every domain consumer of 'now' (order.py audit timestamps, transaction_manager
          correlation_id/context timestamps, cash_manager _create_operation, portfolio.set_state,
          position_manager holding-period end_time, metrics_manager) still calls datetime.now()
          directly. The clock is inert wiring.
      (b) BacktestClock.now() guards with a bare `assert self._t is not None` (clock.py:45),
          which is stripped under `python -O` — the determinism guard silently vanishes under
          a standard interpreter flag. The test_core/test_clock.py expects AssertionError which
          is only valid when assert statements are not optimized away.
      Note: The M2a plan (02-06) explicitly scopes the clock to "build the mechanism; M2b wires
      it into order/transaction timestamps" (D-09/D-10). Whether (a) satisfies M2a is a judgment
      call requiring the owner's explicit acceptance — the plan text says "M2a wires the clock
      onto the backtest engine path" and "the claim is not realized; the seam is dead wiring"
      (per 02-REVIEW.md CR-01). Item (b) is a code defect regardless of scope.
      (c) The `_calculate_transaction_cost` method (transaction_manager.py:253-255) runs
          Decimal(str(transaction.price/quantity/commission)) on values that are already Decimal
          (Transaction.__post_init__ normalizes via to_money). The validation code at line 162
          even states "no Decimal(str(...)) round-trip needed" but the execution code does it
          anyway — a comment/code mismatch flagged in WR-03.
    artifacts:
      - path: "itrader/core/clock.py"
        issue: "BacktestClock.now() uses `assert` (stripped under python -O); no domain consumer reads clock.now() — the seam is inert"
      - path: "itrader/portfolio_handler/transaction_manager.py"
        issue: "Lines 253-255: Decimal(str(transaction.price/quantity/commission)) on already-Decimal values — redundant round-trips that defeat the M2a money policy"
    missing:
      - "Replace `assert self._t is not None` in BacktestClock.now() with an explicit `raise RuntimeError(...)` that survives python -O"
      - "Update test_core/test_clock.py::test_backtest_clock_now_before_advance_raises to expect RuntimeError instead of AssertionError"
      - "Drop the Decimal(str(...)) wrappers at transaction_manager.py:253-255 since the fields are already Decimal end-to-end"
      - "Decision required from owner: is the clock being 'constructed + advanced but no domain consumer reads it' acceptable for M2a (matching the D-09/D-10 recorded deferral), or does the plan text 'wires the clock onto the backtest engine path' require at least one live consumer? The 02-REVIEW.md CR-01 says the docstring guarantee is false. Minimally, the docstring/comment in backtest_trading_system.py:46-51 must be corrected to accurately state that no domain consumer reads clock.now() yet."
---

# Phase 2: M2a — Identity, Money & Determinism — Verification Report

**Phase Goal:** Replace the overflow-prone integer ID scheme with UUIDv7, make money Decimal
end-to-end, achieve `mypy --strict` cleanliness with frozen/typed DTOs and real ABCs, and make
runs deterministic via seeded RNG and an injected clock.

**Verified:** 2026-06-04T22:32:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | A single UUIDv7 scheme via `uuid-utils` replaces the integer `id_generator`; IDs stored as native UUIDs with type no longer encoded in the value (Critical #10) | ✓ VERIFIED | `itrader/outils/id_generator.py` uses `uuid_utils.compat.uuid7()` returning `uuid.UUID`; the integer prefix+timestamp+counter scheme is gone; six NewType aliases in `core/ids.py`; `in_memory_storage` uses flat `Dict[UUID, Order]` index |
| 2  | Money is `Decimal` end-to-end (prices, quantities, cash, commissions, PnL) with no float round-trips and a centralized quantization policy | ⚠ PARTIAL | Core path is Decimal: `core/money.py` provides `to_money`/`quantize`; Transaction fields are Decimal via `__post_init__`; Position properties return Decimal; cash ledger is Decimal. Three active concerns: (A) CR-03 — `portfolio.cash += transaction_cost` routes through `cash_manager.deposit/withdraw` which quantizes every amount to 2dp via `_validate_and_convert_amount`, silently losing sub-cent precision on every BTC transaction; also exposes latent crash from balance-gate checks inside the setter. (B) WR-01/WR-02 — `position_manager._should_close_position` casts Decimal tolerance to float for comparison (`float(self.tolerance)`) and `_validate_position_consistency` compares against float literal `1e-6`. (C) WR-05 — `order_manager._resolve_signal_quantity` does `float(portfolio.cash)` and `float(open_position.net_quantity)` for sizing, re-introducing float at the signal boundary. These are M2 SC#2 correctness issues, not future-milestone deferrals. |
| 3  | `mypy --strict` is clean across the (in-scope) package; hot-path DTOs/events are `frozen=True`/`slots=True` with NewType ID aliases; the Py2 `__metaclass__` bases are real ABCs/Protocols with non-conforming subclasses fixed | ✓ VERIFIED (scoped) | `make typecheck` exits 0 ("Success: no issues found in 157 source files"). Frozen events: PingEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent all `@dataclass(frozen=True, slots=True)`; SignalEvent correctly left mutable (verified: FrozenInstanceError raised on PingEvent mutation; SignalEvent allows mutation). All 11 dead `__metaclass__` bases converted — one remaining outlier (`price_handler/exchange/base.py`) is the D-oanda CCXT/OANDA data-provider base explicitly called out in 02-05-SUMMARY as out-of-scope. Scope-down was owner-approved (Option 2 in 02-07 gate). Stale `int` annotations on `OrderEvent.order_id/parent_order_id/portfolio_id`, `FillEvent.portfolio_id/order_id`, `SignalEvent.portfolio_id` (IN-02) and `MatchingEngine._resting: Dict[int, OrderEvent]` (IN-03) are active type lie annotations — they do not break mypy because the fields are duck-typed at runtime, but they undermine the ID migration. |
| 4  | Backtests are deterministic — RNG seeded behind an injected Random, clock injected (no local `datetime.now()`), flat global order index by id | ✗ PARTIAL | RNG: VERIFIED — `execution_handler.py` constructs `random.Random(rng_seed)` from config (default 42) and injects it into SimulatedExchange + slippage models; no bare `random.random/uniform/choice` remains in the 3 engine files. Clock: PARTIAL with two distinct defects — (1) BacktestClock is constructed and set_time() is called each ping but `clock.now()` has zero consumers in the codebase; every domain timestamp source still calls `datetime.now()` directly (CR-01); (2) BacktestClock.now() uses a bare `assert` that python -O strips, making the not-advanced guard inert under optimization (CR-02). Flat order index: VERIFIED — InMemoryOrderStorage uses `Dict[UUID, Order]`. |

**Score:** 2/4 truths fully VERIFIED (SC#1 verified, SC#3 verified-scoped). SC#2 and SC#4 are partial with active code defects.

---

### Assessment of Scope Nuances

**SC#4 Clock — D-09/D-10 Deferral:**

The 02-06 plan objective says "M2a builds + advances the mechanism here; M2b wires it into
order/transaction timestamps" (D-10 scope note), and the plan's acceptance criteria only requires
"backtest_trading_system.py constructs a BacktestClock and calls set_time in the run loop."
By this narrow reading, the construction-and-advance mechanism is present and M2a's stated
deliverable is technically met.

However, the phase-level SC#4 states "clock injected (no local datetime.now())" which is
observably false: there are 25+ `datetime.now()` calls in domain modules that remain on
wall-clock. The 02-REVIEW.md CR-01 characterizes the clock as "dead wiring" and specifically
says the docstring guarantee "any engine-path consumer of 'now' reads deterministic time" is
not true. More critically, the defect in CR-02 (bare `assert` stripped by python -O) is a
code quality issue independent of scope — the test_core/test_clock.py currently expects
`AssertionError` which only works when asserts are not disabled.

**Verdict:** The deferral of order/transaction timestamps to M2b is a recorded and acceptable
scope split. The requirement that the clock mechanism be "constructed and advanced" is met.
However, the bare `assert` guard (CR-02) and the false docstring claims (CR-01) are real defects
that must be fixed regardless of deferral scope. The overall SC#4 truth is therefore PARTIAL, not
FAILED — the RNG wiring is solid, the flat index is solid, the clock mechanism exists, but the
guard implementation is defective.

**SC#2 Decimal — CR-03:**

The `portfolio.cash += transaction_cost` path (transaction_manager.py:236) triggers the cash
setter in portfolio.py, which calls `cash_manager.deposit/withdraw`. These methods call
`_validate_and_convert_amount` which quantizes every amount to 2dp. This means a Decimal
transaction cost of `Decimal('5228.454321')` becomes `Decimal('5228.45')` at the ledger — losing
`Decimal('0.004321')` per transaction, accumulating across hundreds of trades. The review
confirmed that a sub-cent amount (e.g. `Decimal('0.00042350727777')`) raises
`InvalidTransactionError` from inside the setter — a latent crash not visible in the test suite
because current tests use round transaction amounts. This is a genuine precision defect on the
cash accounting path that SC#2 ("no float round-trips and a centralized quantization policy")
claims to fix. The cash route `portfolio.cash += float_value → Decimal` round-trip is gone, but
a new Decimal→2dp quantization loss is introduced via the setter routing. SC#2 is PARTIAL.

**SC#3 mypy scoped clean:**

The `make typecheck` gate is clean (0 errors / 157 files) with documented `ignore_errors`
overrides for out-of-scope modules (`my_strategies/*`, `legacy_config`, `postgresql_storage`,
`reporting.statistics`, `reporting.engine_logger`, `reporting.plots`, D-live, D-sql, D-screener).
The scope-down was explicitly owner-approved at the 02-07 gate. The stale `int` annotations on
event ID fields (IN-02/IN-03) are technically carried through mypy because those fields are
duck-typed at runtime and the current code produces no mypy error. They are documentation debt
rather than typecheck failures.

**Judgment:** SC#3 VERIFIED-scoped. The scope narrowing is legitimate and documented.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/ids.py` | NewType UUID aliases (M2-01) | ✓ VERIFIED | Six `NewType("X", uuid.UUID)` aliases |
| `itrader/core/money.py` | `to_money` / `quantize` centralized policy (M2-02) | ✓ VERIFIED | String-entry Decimal, per-instrument scales, ROUND_HALF_UP |
| `itrader/core/clock.py` | Injectable Clock Protocol + BacktestClock + WallClock (M2-05) | ✓ VERIFIED | Present and substantive; `BacktestClock.now()` has assert defect (CR-02) |
| `itrader/outils/id_generator.py` | UUIDv7 via uuid_utils.compat (M2-01) | ✓ VERIFIED | `uuid_utils.compat.uuid7()` → `uuid.UUID`; integer scheme deleted |
| `itrader/events_handler/event.py` | frozen=True/slots=True on immutable events (M2-03) | ✓ VERIFIED | PingEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent all frozen; SignalEvent mutable |
| `itrader/execution_handler/slippage_model/fixed_slippage_model.py` | injected `random.Random`; no bare random.* (M2-05) | ✓ VERIFIED | `self._rng` injected; `self._rng.uniform(...)` used |
| `itrader/execution_handler/slippage_model/linear_slippage_model.py` | injected `random.Random`; no bare random.* (M2-05) | ✓ VERIFIED | `self._rng` injected; `self._rng.uniform(...)` used |
| `itrader/execution_handler/exchanges/simulated.py` | injected `random.Random`; no bare random.* (M2-05) | ✓ VERIFIED | `self._rng` injected; all 4 engine-sim sites use `self._rng.*` |
| `itrader/execution_handler/execution_handler.py` | constructs `random.Random(seed)` and injects (M2-05) | ✓ VERIFIED | `random.Random(self._rng_seed)` constructed and passed to SimulatedExchange |
| `itrader/config/system/config.py` | documented `rng_seed` config key (M2-05) | ✓ VERIFIED | `rng_seed: int = 42` in `PerformanceSettings` |
| `itrader/trading_system/backtest_trading_system.py` | BacktestClock constructed + set_time called each ping (M2-05) | ✓ VERIFIED | `self.clock = BacktestClock()` at :53; `self.clock.set_time(ping_event.time)` at :117 |
| `pyproject.toml` | `[tool.mypy]` strict + overrides + `make typecheck` gate (M2-03) | ✓ VERIFIED | `strict = true`; three `[[tool.mypy.overrides]]` sections with documented deferrals |
| `Makefile` | `typecheck:` target (M2-03) | ✓ VERIFIED | Target present, runs `poetry run mypy itrader` |
| `test/test_integration/test_backtest_oracle.py` | D-15 identity-EXACT + numeric-TOLERANT split (M2-03) | ✓ VERIFIED | `_TRADE_KEY_COLUMNS check_exact=True`; numeric columns `check_exact=False, rtol=_D15_RTOL, atol=_D15_ATOL`; each tolerance commented with D-15/M2b note |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `execution_handler.py` | `SimulatedExchange + slippage models` | inject `random.Random(seed)` | ✓ WIRED | `simulated = SimulatedExchange(self.global_queue, rng=self._rng)` at :110; exchange passes `self._rng` to slippage model at :513,519 |
| `backtest_trading_system.py` | `core.clock.BacktestClock` | construct + set_time on each ping | ✓ WIRED (mechanism only) | BacktestClock constructed at :53; `self.clock.set_time(ping_event.time)` at :117 — no domain consumer reads clock.now() yet (D-09/D-10 deferral) |
| `transaction_manager._execute_transaction` | `portfolio.cash setter` | `self.portfolio.cash += transaction_cost` | ⚠ PARTIAL | Cash value reaches the ledger as Decimal but routes through `deposit/withdraw` which quantizes to 2dp, losing sub-cent precision (CR-03) |
| `test_backtest_oracle.py` | behavioral identity columns | `assert_frame_equal check_exact=True on _TRADE_KEY_COLUMNS` | ✓ WIRED | `check_exact=True` on identity columns; numeric tolerance on rest |

---

### Data-Flow Trace (Level 4)

| Component | Variable | Source | Real Data | Status |
|-----------|----------|--------|-----------|--------|
| `transaction.price/quantity/commission` | Decimal money | `Transaction.__post_init__` via `to_money()` | Yes | ✓ FLOWING — string-entry Decimal at construction boundary |
| `portfolio.cash` (ledger) | `Decimal` | `cash_manager._balance` | Yes | ⚠ STATIC quantization — values lose sub-cent precision at each deposit/withdraw via `_validate_and_convert_amount` quantizing to `0.01` |
| `BacktestClock._t` | `datetime` | `set_time(ping_event.time)` called each bar | Sim time set | ⚠ HOLLOW_PROP — set every bar but never read by any consumer |
| `idgen.generate_*_id()` | `uuid.UUID` (UUIDv7) | `uuid_utils.compat.uuid7()` | Yes | ✓ FLOWING — real UUIDv7 |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite green | `poetry run pytest -q` | 299 passed in 10.85s | ✓ PASS |
| mypy --strict clean | `make typecheck` | "Success: no issues found in 157 source files" | ✓ PASS |
| Oracle test passes | `poetry run pytest test/test_integration/test_backtest_oracle.py -x` | 1 passed in 4.35s | ✓ PASS |
| UUID generation returns stdlib UUID | `uuid_utils.compat.uuid7()` returns `uuid.UUID` | `isinstance(u, uuid.UUID) == True` | ✓ PASS |
| Frozen events raise FrozenInstanceError | Assign to `PingEvent.time` post-construction | `FrozenInstanceError` raised | ✓ PASS |
| SignalEvent stays mutable | Check `SignalEvent.__dataclass_params__.frozen` | `False` | ✓ PASS |
| No bare module-level random.* in engine files | grep on 3 engine files | No results | ✓ PASS |
| Sub-cent Decimal deposit raises | `CashManager.deposit(Decimal('0.00042...'))` | `InvalidTransactionError` — confirms CR-03 | ✗ FAIL (latent) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| M2-01 | 02-03 | UUIDv7 single scheme | ✓ SATISFIED | IDGenerator uses uuid_utils.compat; NewType aliases in core/ids.py |
| M2-02 | 02-04 | Decimal money end-to-end | ⚠ PARTIAL | Decimal on the critical path; CR-03 precision loss at cash ledger boundary; WR-01/WR-02 float comparisons in position_manager; WR-05 float sizing in order_manager |
| M2-03 | 02-07 | mypy --strict clean + frozen events + NewType aliases | ✓ SATISFIED (scoped) | 0 errors / 157 files; PingEvent/BarEvent/PortfolioUpdateEvent/ScreenerEvent frozen; scope-down owner-approved |
| M2-04 | 02-05 | Real ABCs/Protocols (11 dead metaclass bases) | ✓ SATISFIED | 11 bases converted; one remaining outlier (price_handler/exchange/base.py) is D-oanda explicitly documented as out-of-scope |
| M2-05 | 02-06 | Determinism: seeded RNG + injected clock + flat order index | ⚠ PARTIAL | RNG seeded and injected: verified. Flat order index: verified. Clock mechanism: exists but (1) no domain consumer reads clock.now() — the "no local datetime.now()" claim is not realized in domain code; (2) assert guard is stripped by python -O (CR-02) |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/core/clock.py` | 45 | `assert self._t is not None` — stripped under `python -O` | 🛑 Blocker | Determinism guard silently vanishes; `now()` returns `None` under optimization; test_clock.py expects `AssertionError` which is only raised when assertions are not disabled |
| `itrader/portfolio_handler/transaction_manager.py` | 253-255 | `Decimal(str(transaction.price/quantity/commission))` on already-Decimal fields | ⚠ Warning | Contradicts the comment at line 162 ("no Decimal(str(...)) round-trip needed"); defeats the M2a money policy intent; WR-03 from code review |
| `itrader/portfolio_handler/transaction_manager.py` | 236 | `self.portfolio.cash += transaction_cost` routes through setter that quantizes to 2dp and runs balance gates | ⚠ Warning | Sub-cent Decimal precision silently lost per transaction; latent crash when balance gates fire unexpectedly from inside the setter — CR-03 |
| `itrader/portfolio_handler/position_manager.py` | 184 | `abs(position.net_quantity) <= float(self.tolerance)` — Decimal compared via float cast | ⚠ Warning | Reintroduces float imprecision in position-closure decision; defeats M2a Decimal intent — WR-01 |
| `itrader/portfolio_handler/position_manager.py` | 208 | `abs(position.net_quantity) > 1e-6` — float literal compared against Decimal | ⚠ Warning | Same class of float/Decimal seam as WR-01 — WR-02 |
| `itrader/order_handler/order_manager.py` | 274,279 | `float(open_position.net_quantity)` / `float(portfolio.cash)` for sizing | ⚠ Warning | Re-introduces float at the signal boundary; sized exit may not exactly net position to zero — WR-05 |
| `itrader/events_handler/event.py` | 235,302,305,306,383,384 | `portfolio_id: int`, `order_id: Optional[int]`, `parent_order_id: Optional[int]` | ℹ Info | Stale int annotations on ID fields that now hold UUIDs at runtime; lie annotations; IN-02/IN-03 |
| `itrader/portfolio_handler/portfolio.py` | 1 | `import numpy as np` — unused import | ℹ Info | Unused; IN-05 |
| `itrader/trading_system/backtest_trading_system.py` | 125 | `print("Backtest duration:", duration)` | ℹ Info | Should use structured logger; IN-04 |

---

### Gaps Summary

Two overlapping gaps block a clean SC verdict:

**Gap 1 (BLOCKER — CR-02): BacktestClock.now() assert guard is stripped under python -O.**

`itrader/core/clock.py:45` uses `assert self._t is not None, "BacktestClock not advanced"`. The
`assert` statement is silently removed by CPython under the `-O` optimization flag. Under
optimization, `now()` returns `None` (the un-advanced sentinel) instead of raising, silently
corrupting any future consumer with a `None` timestamp. The existing test
`test_backtest_clock_now_before_advance_raises` expects `AssertionError`, which only holds when
assertions are enabled. This is a straightforward one-line fix: replace the assert with an explicit
`if ... raise RuntimeError(...)`.

**Gap 2 (WARNING — CR-01 + SC#4 partial): BacktestClock has no domain consumers.**

`self.clock.set_time()` is called every ping, but `clock.now()` is called nowhere in the
codebase. The plan-level deferral of order/transaction timestamps to M2b (D-09/D-10) is recorded
and accepted. However, the backtest_trading_system.py docstring at line 46-51 makes a false
guarantee ("any engine-path consumer of 'now' reads deterministic time") when no consumer
actually reads the clock. The docstring/comment must be corrected to accurately state the
current state: the clock mechanism is built and advanced, and M2b will wire domain consumers to
it. This is a documentation fix, not a code change.

**Gap 3 (WARNING — CR-03): Cash setter precision loss on transaction path.**

`transaction_manager._execute_transaction` does `self.portfolio.cash += transaction_cost` where
`transaction_cost` is a full-precision Decimal. The `cash` setter routes through
`cash_manager.deposit/withdraw`, which calls `_validate_and_convert_amount`, which quantizes to
2dp. Sub-cent BTC transaction costs raise `InvalidTransactionError` (confirmed by live test). On
the golden dataset with `settings/` overrides of `failure_simulation.enabled=false` and zero
slippage, the oracle test still passes because the current backtest configuration avoids the
failing edge cases. But the precision loss is real and accumulates across a multi-year run. This
overlaps with SC#2 ("no float round-trips and a centralized quantization policy") — the route IS
Decimal but loses precision at the cash ledger boundary.

**Relationship to later phases:** Gap 3 (CR-03) is partially addressed by M4-01 ("Every trade
routes cash through CashManager — no `portfolio.cash += float(...)` setter bypass") in Phase 5.
However, M4-01 is targeted at `float` bypass; the current issue is that the Decimal route
through the setter still quantizes. The M4 fix will need to also resolve the precision loss, not
just the float bypass. Gaps 1 and 2 are not addressed in any later phase roadmap entry.

---

_Verified: 2026-06-04T22:32:00Z_
_Verifier: Claude (gsd-verifier)_
