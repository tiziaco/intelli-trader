# Phase 2: M2a — Identity, Money & Determinism - Research

**Researched:** 2026-06-04
**Domain:** Brownfield structural refactor — Python 3.13 identity (UUIDv7), money (Decimal), typing (`mypy --strict`, frozen DTOs, ABC/Protocol), determinism (injected clock + seeded RNG)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

> The WHAT is fully locked. This phase resolves only the HOW. The decisions D-01…D-15 are LOCKED — do not re-litigate.

### Locked Decisions

**Money: Decimal precision & quantization (M2-02, #17)**
- **D-01:** Hybrid precision policy. Carry a **28-digit default Decimal context** through all intermediate money math; **quantize only at money boundaries** (cash ledger, reported PnL, persistence/serialization) to **per-instrument scale**.
- **D-02:** Quantization scale = **per-instrument, via a lookup with a default + override**. BTC price/quantity → **8 dp**; USD cash/PnL/commission → **2 dp**. Only BTCUSD is traded; ship a default + a single BTCUSD entry. General per-cryptocurrency registry is deferred.
- **D-03:** Rounding mode = **`ROUND_HALF_UP`** at quantization boundaries.
- **D-04:** float→Decimal boundary = **the money-path entry only**, via **`Decimal(str(x))`** (avoids float-repr artifacts), at fill/execution price, position mark-to-market, and the `OrderManager` sizing seam (M1 D-09). **Indicator/analytics path stays float by design** (SMA/MACD on `ta`/`pandas-ta`, plots, statistics on float64). The defect fixed is the **same-value float↔Decimal round-trip** (`portfolio.cash += float(...)`), not "a float exists somewhere." No money value round-trips back to float.

**Typing: mypy --strict scope (M2-03, #8)**
- **D-05:** In-scope strict + documented excludes. Strict-clean everything on/around the backtest path + shared core (events, enums, exceptions, config, portfolio, order, execution, strategy, csv price feed, reporting). Deferred subsystems get explicit `[[tool.mypy.overrides]]` excludes, each commented with its deferral tag: `live_trading_system`, `trading_interface` (D-live); `sql_handler` (D-sql); `CCXT`/OANDA/`BINANCE_Live` (D-oanda/D-live); `screeners_handler` (D-screener). "mypy --strict clean" = clean over the **in-scope package**.
- **D-06:** Add a **`make typecheck` gate now** + mypy config in `pyproject.toml`, wired into the test/make workflow, so M3/M4/M5 cannot silently regress strictness.

**Typing: ABC vs Protocol for the 8 dead `__metaclass__` bases (M2-04, #20)**
- **D-07:** Per-#20 mix, not uniform.
  - **Protocol** (pluggable swap-a-fake structural seams, no shared impl): `AbstractExchange` (execution `exchanges/base`), `AbstractPositionSizer` (position_sizer/base), `AbstractPriceHandler` (price/base).
  - **ABC** (subclasses inherit real shared code/lifecycle): `AbstractExecutionHandler`, `AbstractStatistics`, `Strategy` base, `Universe`, `Screener`.
- **D-08:** Convert all 8 now (SC3) + minimal conformance; defer deep rework. Fix missing/mismatched signatures just enough to conform + pass mypy (e.g. `SimulatedExchange.configure`, `PriceHandler` signature drift). Deeper rework stays in owning milestone: `calculate_signal` contract → M5b #24; universe collapse → M5b #33; reporting split → M5b #38; screener wiring → D-screener. The screener base is converted (cheap) despite the module being mypy-excluded.

**Determinism: clock & RNG (M2-05, #5, PERF2)**
- **D-09:** Injected clock returns **simulation (bar/event) time** in backtest; live returns wall clock. Domain timestamps become deterministic & bar-derived. **Perf-telemetry `datetime.now()` legitimately stays wall-clock** (e.g. backtest run-duration in `backtest_trading_system.py`).
- **D-10:** M2a builds the mechanism + replaces **engine-path sites only**. **Defer** order-audit (`order.py`) & transaction-timestamp determinism to M2b (its SC2). Leave live-mode (D-live) status/uptime `datetime.now()` sites alone.
- **D-11:** RNG = config seed behind an injected `random.Random` (documented default seed), injected into the components that use `random` (`SimulatedExchange` failure-sim, fixed/linear slippage models). **Forbid module-level `random.*` in the engine.** No oracle impact (M1 oracle runs failure-sim off, zero slippage).

**Identity: UUIDv7 migration (M2-01, #10)**
- **D-12:** Distinct `NewType` alias per entity: `OrderId`, `PortfolioId`, `PositionId`, `TransactionId`, `StrategyId`, `ScreenerId` — each `NewType` over `uuid.UUID`.
- **D-13:** Drop the type-in-id encoding. Type was encoded in the integer prefix (1=Transaction…6=Screener); **nothing decodes it today** (verified). No discriminator field added.
- **D-14:** Native UUID end-to-end. `id` fields typed `UUID` (not `str`/`int`), the flat order index is `Dict[UUID, Order]`, storage keys are native `UUID`; tighten the loose `Union[str, int]` keying in `in_memory_storage.py` to `UUID`.

**Golden-master / oracle handling this phase**
- **D-15:** Behavioral-exact + bounded transitional numerical tolerance. The behavioral oracle (trade timing + sides + sequence) stays asserted **EXACTLY** throughout M2a. The run-path integration test's **numerical** assertion gets a **documented bounded tolerance** for the duration of M2a. The tolerance is **removed and the numerical oracle re-frozen EXACT at M2b** (Phase 3 SC4). NOT a third re-baseline point.

### Claude's Discretion
- **idgen facade shape:** keep a thin `idgen` facade whose methods return UUIDv7 to minimize churn at the ~7 call sites; per-type generator methods collapse to a single `uuid7()` implementation. (Entity `event_id` redesign stays M3 #11.)
- **Flat O(1) order index (PERF2):** the `Dict[UUID, Order]` index design/placement in storage.
- **`frozen=True`/`slots=True` rollout:** which hot-path DTOs/events get frozen+slots this phase (note `SignalEvent.verified` mutation at `event.py:235` is a known immutability blocker — coordinate with M3, do not pre-judge #11).
- **Transitional numerical-tolerance magnitude:** set empirically from observed M2a drift.
- Exact `[[tool.mypy.overrides]]` module list and `make typecheck` invocation details.
- Per-base Protocol-vs-ABC edge calls within the D-07 policy.

### Deferred Ideas (OUT OF SCOPE)
- General per-cryptocurrency precision registry (18-dp tokens) — only BTCUSD traded.
- **Order-audit & transaction-timestamp determinism** → M2b (Phase 3) SC2. M2a builds the clock mechanism; M2b applies it to order/transaction timestamps.
- `calculate_signal` contract enforcement → M5b #24.
- Universe collapse to a documented stub → M5b #33. M2a only converts `Universe` base + minimal conformance.
- Reporting computation/presentation split + `print_summary` fix → M5b #38. M2a only converts `AbstractStatistics` to a real ABC.
- Screener wiring → D-screener. M2a converts the base (cheap, SC3) but the module stays mypy-excluded and dormant.
- Cash-through-`CashManager` (no `portfolio.cash += float(...)` bypass) + DEF-01-A commission reconciliation + atomic transactions → M4 (#22, #16, #23). M2a types money fields Decimal; M4 fixes cash-flow routing.
- Event immutability + `event_id` + linkage IDs + dispatch registry → M3 (#11, #1, #2). M2a touches only the six entity IDs.
- mypy --strict over deferred subsystems (live/SQL/screener/OANDA) — excluded now.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M2-01 | Single UUIDv7 scheme via `uuid-utils` replaces the integer `id_generator`; IDs stored as native UUID, type not encoded *(#10 Critical)* | §UUIDv7 Migration — `uuid_utils.compat.uuid7()` returns stdlib `uuid.UUID`; facade swap at `id_generator.py`; D-13 prefix-decode verified absent; `Union[str,int]`→`UUID` tightening |
| M2-02 | Money is `Decimal` end-to-end with no `float` round-trips + centralized quantization policy *(#17)* | §Decimal End-to-End — 28-digit context / quantize-at-boundary pattern; `Decimal(str(x))`; `ROUND_HALF_UP`; per-instrument quantization module; the `cash += float(...)` round-trip at `transaction_manager.py:229` |
| M2-03 | `mypy --strict` clean; hot-path DTOs/events `frozen=True`/`slots=True`; `NewType` ID aliases *(#8)* | §mypy --strict + §Frozen/Slots — `[tool.mypy]` strict config, per-module overrides, `make typecheck`; `NewType` over `uuid.UUID`; SignalEvent.verified blocker |
| M2-04 | The eight Py2 `__metaclass__` bases become real ABCs/Protocols, fixing non-conforming subclasses *(#20)* | §ABC vs Protocol — exact base inventory + DRIFT NOTE; `SimulatedExchange` missing `configure`/`is_connected`/`validate_symbol` confirmed |
| M2-05 | Backtests deterministic — RNG seeded behind injected `Random`, clock injected, flat global order index by id *(#5, PERF2)* | §Determinism + §Flat Order Index — injected `Clock`/`Random`; engine-path `datetime.now()`/`random.*` site map; `Dict[UUID, Order]` index |
</phase_requirements>

## Summary

This is a brownfield structural-foundations refactor with a fully-locked design. Research focused on
the **HOW** and on **verifying the CONTEXT.md code references against the live tree**. All four axes
are low-risk because the M1 oracle (D-12) deliberately excluded integer-ID *values* and wall-clock
timestamps from the captured baseline, so UUIDv7 + injected clock are oracle-safe by construction;
only the float→Decimal shift can move numbers (hence D-15's bounded transitional tolerance).

The single most important technical finding: **`uuid_utils.uuid7()` returns a custom `uuid_utils.UUID`
type, NOT a stdlib `uuid.UUID`**, but `uuid_utils.compat` ships a drop-in module whose functions return
**stdlib `uuid.UUID` instances**. Because D-14 mandates native `uuid.UUID` end-to-end and D-12 mandates
`NewType` aliases *over `uuid.UUID`*, the facade must call **`uuid_utils.compat.uuid7()`** — not the
top-level `uuid_utils.uuid7()`. Using the top-level function would force the codebase to type fields as
the custom type or convert at every boundary, contradicting D-14 and complicating mypy.

Two pieces of drift were found between CONTEXT.md and the tree (both flagged below): (1) the "8 dead
`__metaclass__` bases" is a **curated in-scope subset** — the tree actually has **11 classes across
9 files** using the dead Py2 pattern (two extra: `trading_system/simulation/base.py` and the two
classes in `portfolio_handler/base.py`); and `Strategy`/`Screener` do NOT use `__metaclass__` at all
(`Strategy` is a bare `class Strategy(object)`, `Screener` has one `@abstractmethod` with a
self-less signature). (2) The run-path integration test currently asserts `check_exact=True` on **all**
columns including numeric — D-15 requires splitting trade-identity (exact) from numeric (tolerance).

**Primary recommendation:** Use `uuid_utils.compat.uuid7()` behind the existing `idgen` facade;
build a single `core/money.py` quantization module (28-digit context + per-instrument `quantize` with
`ROUND_HALF_UP`); add `[tool.mypy]` strict + per-module `[[tool.mypy.overrides]]` excludes and a
`make typecheck` target; convert the dead bases to real ABC/Protocol with minimal conformance fixes;
inject a `Clock` and seeded `random.Random` on the engine path only. Apply `frozen=True`/`slots=True`
to genuinely-immutable hot-path event DTOs **except** `SignalEvent` (the `verified` mutation is M3's).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ID generation | Shared core (`outils/id_generator.py` facade) | — | Single singleton `idgen`; all entities import it |
| ID type aliases (`NewType`) | Shared core (`core/` — new module) | All handlers | `OrderId`/`PortfolioId`/… imported across domains; belongs with enums/exceptions |
| Money quantization policy | Shared core (`core/money.py` — new) | Portfolio, execution, order | Centralized per-instrument scale + rounding; consumed at money boundaries |
| Decimal money fields | Domain entities (transaction, position, portfolio, order, fill) | — | Each entity owns its money state; quantize at its boundary |
| Injected `Clock` | Engine/orchestration (`trading_system/`) | Order, portfolio, execution | Clock constructed at run wiring, passed down; bar-time source in backtest |
| Injected seeded `Random` | Execution (`SimulatedExchange`, slippage models) | Config (seed source) | Only execution-layer components use `random` on the engine path |
| Flat `Dict[UUID, Order]` index | Order storage (`in_memory_storage.py`) | — | Storage owns the order mirror; index is a storage concern (PERF2) |
| ABC/Protocol bases | Each owning domain's `base.py` | — | Convert in place; subclasses live in the same domain |
| mypy config + gate | Build config (`pyproject.toml`, `Makefile`) | — | Cross-cutting CI gate |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uuid-utils` | **0.16.0** (latest) | Rust-backed UUIDv7 generation via `uuid_utils.compat.uuid7()` returning stdlib `uuid.UUID` | Locked decision (REFACTOR-BRIEF / D-12); Rust-backed, faster than stdlib; `compat` gives native `uuid.UUID` |
| `mypy` | **2.1.0** (latest) | `--strict` static type checking (the M2-03 gate) | Reference type checker; `[tool.mypy]` + per-module overrides are the idiomatic strict-with-exclusions pattern |
| `decimal` (stdlib) | Python 3.13 | `Decimal`, `getcontext`, `localcontext`, `ROUND_HALF_UP`, `.quantize()` | stdlib; D-01…D-04 require no third-party money lib |
| `random.Random` (stdlib) | Python 3.13 | Seeded RNG instance injected into execution components | stdlib; D-11 requires an *instance* (not module-level) |
| `abc` / `typing.Protocol` (stdlib) | Python 3.13 | Real ABCs (`ABC`/`abstractmethod`) + structural `Protocol`s | D-07/D-08; replaces the dead Py2 `__metaclass__ = ABCMeta` |
| `typing.NewType` (stdlib) | Python 3.13 | `OrderId = NewType("OrderId", uuid.UUID)` etc. | D-12; gives mypy cross-entity id mix-up detection at zero runtime cost |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas.testing.assert_frame_equal` | 2.3.x (installed) | `rtol`/`atol` numeric tolerance on the oracle test (D-15) | Already used in `test_backtest_oracle.py` — extend with tolerance on numeric columns |
| `dataclasses` (stdlib) | Python 3.13 | `@dataclass(frozen=True, slots=True)` on hot-path event DTOs | M2-03 frozen/slots rollout |

**`uuid_utils.compat` is required, not optional.** `uuid_utils.uuid7()` (top-level) returns the
custom `uuid_utils.UUID`. `uuid_utils.compat.uuid7()` returns stdlib `uuid.UUID`. D-14 mandates native
`uuid.UUID` typing and D-12 aliases over `uuid.UUID`, so the facade MUST use the compat module. `[CITED: github.com/aminalaee/uuid-utils README]`

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `uuid_utils.compat.uuid7()` | top-level `uuid_utils.uuid7()` + convert at boundaries | Custom type complicates `Dict[UUID, Order]` + `NewType`; contradicts D-14. Rejected. |
| stdlib `decimal` | third-party money lib (`py-moneyed`) | Out of scope; D-01…D-04 specify a stdlib-context approach. Rejected. |
| `NewType` over `uuid.UUID` | subclassing `uuid.UUID` | Subclass adds runtime cost + serialization complexity; `NewType` is zero-cost and the D-12 choice. |

**Installation:**
```bash
poetry add uuid-utils@^0.16.0
poetry add --group dev mypy@^2.1.0
```
(Neither `uuid_utils` nor `mypy` is currently installed — verified `ModuleNotFoundError` for both.)

**Version verification:** `pip index versions uuid-utils` → 0.16.0 latest [VERIFIED: PyPI]; `pip index versions mypy` → 2.1.0 latest [VERIFIED: PyPI]. Note mypy 2.x is newer than common training-data knowledge (mypy 1.x era) — pin to `^2.1.0` and validate the strict-config syntax against the installed version.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `uuid-utils` | PyPI | ~3 yrs (since 0.1.0) | high (Rust-backed, widely used) | github.com/aminalaee/uuid-utils | unavailable | Approved — locked decision, verified on PyPI, authoritative GitHub README confirms API |
| `mypy` | PyPI | 10+ yrs | very high | github.com/python/mypy | unavailable | Approved — reference type checker |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was not run in this session (network/tooling). Both packages are nonetheless high-confidence: `uuid-utils` is the explicitly locked program decision (REFACTOR-BRIEF) authored by a known maintainer (aminalaee, also of Starlette/SQLAdmin); `mypy` is the canonical type checker. Both verified present on PyPI via `pip index versions`. The planner may still gate the `poetry add uuid-utils` step behind a `checkpoint:human-verify` if desired, but the package is the program's own locked choice.*

## Architecture Patterns

### System Architecture Diagram (M2a foundations layered onto the existing engine)

```
                          ┌──────────────────────────────────────────┐
   run wiring             │  Clock (backtest: bar/event time)         │  ← injected at construction
   (trading_system)  ───► │  random.Random(seed from ConfigProvider)  │  ← injected at construction
                          └────────────┬───────────────┬─────────────┘
                                       │               │
   idgen facade  ──► uuid_utils.compat.uuid7() ──► stdlib uuid.UUID
        │                                              │
        ▼                                              ▼
   Entity construction (Order/Transaction/Position/Portfolio/Strategy/Screener)
   id: UUID  (NewType alias)        time: <- Clock          money fields: Decimal
        │                                                          │
        ▼                                                          ▼
   in_memory_storage  ──► Dict[UUID, Order] flat index      core/money.py
   (keys: native UUID)        (PERF2, O(1) lookup)          quantize(value, instrument)
        │                                                   28-digit ctx → ROUND_HALF_UP @ boundary
        ▼                                                          │
   money boundaries (cash ledger / reported PnL / serialize) ◄─────┘
        │
        ▼
   run-path integration test:  trade-identity columns EXACT  +  numeric columns rtol/atol (D-15)
```

### Recommended additions (new files)
```
itrader/core/
├── ids.py            # NewType aliases: OrderId, PortfolioId, PositionId, TransactionId, StrategyId, ScreenerId (over uuid.UUID)
├── money.py          # 28-digit context helpers + quantize(value, instrument) with ROUND_HALF_UP; per-instrument scale lookup (default + BTCUSD)
└── clock.py          # Clock protocol/ABC + BacktestClock (bar-time) + WallClock (live)
```
(Place under `core/` — matches the "shared core" tier where enums/exceptions already live; **spaces indentation** in `core/` per CONVENTIONS.)

### Pattern 1: idgen facade swap (D-12/D-14, minimal churn)
**What:** Keep the `idgen` singleton + its method names; replace the integer body with `uuid_utils.compat.uuid7()`.
**When to use:** All ~7 call sites stay byte-identical (`idgen.generate_order_id()` etc.), only the return type changes from `int` to `uuid.UUID`.
```python
# itrader/outils/id_generator.py  — Source: github.com/aminalaee/uuid-utils README (compat module) [CITED]
import uuid
import uuid_utils.compat as uuid_compat  # compat → returns stdlib uuid.UUID

class IDGenerator:
    """Single UUIDv7 scheme (D-12/D-13/D-14). Type is no longer encoded in the value."""
    def _uuid7(self) -> uuid.UUID:
        return uuid_compat.uuid7()  # stdlib uuid.UUID, time-ordered/monotonic

    def generate_order_id(self) -> uuid.UUID: return self._uuid7()
    def generate_portfolio_id(self) -> uuid.UUID: return self._uuid7()
    def generate_position_id(self) -> uuid.UUID: return self._uuid7()
    def generate_transaction_id(self) -> uuid.UUID: return self._uuid7()
    def generate_strategy_id(self) -> uuid.UUID: return self._uuid7()
    def generate_screener_id(self) -> uuid.UUID: return self._uuid7()
```
Note: the per-type integer counters + `threading.Lock` + `_last_timestamp` cache are deleted (uuid7
carries its own monotonicity). The 6 distinct method names are kept so the call sites don't churn, but
they may be typed with the matching `NewType` alias for stricter mypy (e.g. `-> OrderId`).

### Pattern 2: NewType aliases over stdlib UUID (D-12)
```python
# itrader/core/ids.py
import uuid
from typing import NewType

OrderId       = NewType("OrderId", uuid.UUID)
PortfolioId   = NewType("PortfolioId", uuid.UUID)
PositionId    = NewType("PositionId", uuid.UUID)
TransactionId = NewType("TransactionId", uuid.UUID)
StrategyId    = NewType("StrategyId", uuid.UUID)
ScreenerId    = NewType("ScreenerId", uuid.UUID)
```
`NewType` is zero runtime cost; mypy flags passing a `PortfolioId` where an `OrderId` is expected. Use
the aliases on entity `id` fields and exception signatures.

### Pattern 3: Decimal — 28-digit working context + quantize-only-at-boundary (D-01…D-04)
```python
# itrader/core/money.py — idiomatic stdlib pattern
from decimal import Decimal, ROUND_HALF_UP, getcontext

# D-01: Python's default context is already 28 significant digits — carry it through
# intermediate math; do NOT quantize intermediates.

# D-02: per-instrument SCALE (decimal places), default + override
_DEFAULT_SCALES = {"price": Decimal("0.01"), "quantity": Decimal("0.00000001"), "cash": Decimal("0.01")}
_INSTRUMENT_SCALES = {
    "BTCUSD": {"price": Decimal("0.00000001"),    # 8 dp
               "quantity": Decimal("0.00000001"),  # 8 dp
               "cash": Decimal("0.01")},           # USD 2 dp
}

def to_money(x) -> Decimal:
    """D-04 entry: float→Decimal via str() to avoid float-repr artifacts."""
    return Decimal(str(x))

def quantize(value: Decimal, instrument: str, kind: str) -> Decimal:
    """D-03: ROUND_HALF_UP at money boundaries only."""
    scale = _INSTRUMENT_SCALES.get(instrument, _DEFAULT_SCALES).get(kind, _DEFAULT_SCALES[kind])
    return value.quantize(scale, rounding=ROUND_HALF_UP)
```
**Critical:** quantize only at the *boundary* (cash ledger write, reported PnL, serialization), never on
every intermediate multiply — that is what keeps drift vs the M1 float oracle minimal (D-01 rationale).
The codebase **already has the correct entry pattern** at `transaction_manager.py:_calculate_transaction_cost`
(`Decimal(str(transaction.price))` etc.) — the defect is the **`self.portfolio.cash += float(transaction_cost)`
round-trip at `transaction_manager.py:229`**: M2a types `portfolio.cash` (and the chain) as `Decimal` and
removes the `float()` cast; M4 routes it through `CashManager` (do NOT pull forward).

### Pattern 4: ABC vs Protocol conversion (D-07/D-08)
```python
# ABC (shared impl + lifecycle): execution_handler/base.py
from abc import ABC, abstractmethod
class AbstractExecutionHandler(ABC):       # was: class AbstractExecutionHandler(object): __metaclass__ = ABCMeta
    @abstractmethod
    def on_order(self, event: "OrderEvent") -> None: ...

# Protocol (structural seam, swap-a-fake): execution_handler/exchanges/base.py
from typing import Protocol, runtime_checkable
@runtime_checkable
class AbstractExchange(Protocol):
    def on_order(self, event: "OrderEvent") -> None: ...
    def configure(self, config: dict) -> bool: ...   # SimulatedExchange MUST implement this now
    # ...
```
Use `ABC` + `@abstractmethod` where subclasses inherit real shared code (`AbstractExecutionHandler`,
`AbstractStatistics`, `Strategy`, `Universe`, `Screener`); use `Protocol` for pluggable structural seams
(`AbstractExchange` exec, `AbstractPositionSizer`, `AbstractPriceHandler`). Replacing the dead Py2
`__metaclass__ = ABCMeta` with a real ABC will **start enforcing** abstract methods — this surfaces the
`SimulatedExchange` conformance gap (Pitfall 3).

### Pattern 5: Injected Clock (D-09/D-10)
```python
# itrader/core/clock.py
from typing import Protocol
from datetime import datetime
class Clock(Protocol):
    def now(self) -> datetime: ...

class BacktestClock:
    """Returns simulation/bar time; updated each BAR/PING by the engine."""
    def __init__(self) -> None: self._t: datetime | None = None
    def set_time(self, t: datetime) -> None: self._t = t
    def now(self) -> datetime:
        assert self._t is not None, "BacktestClock not advanced"
        return self._t

class WallClock:
    def now(self) -> datetime: return datetime.now()
```
M2a builds this and replaces engine-path `datetime.now()`; **order-audit (`order.py`) and
transaction-timestamp determinism are explicitly M2b** (D-10) — wire the mechanism but do not convert
those sites this phase. `order_validator.py:287` already uses `signal.time.time()` — mirror that
event-time pattern.

### Pattern 6: Injected seeded Random (D-11)
```python
# SimulatedExchange / slippage models accept a Random instance
import random
class FixedSlippageModel:
    def __init__(self, slippage_pct: float = 0.01, random_variation: bool = True,
                 rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()  # engine wiring passes a seeded instance
    def _variation(self) -> float:
        return self._rng.uniform(-self.slippage_pct, self.slippage_pct) / 100.0
```
Seed source = `ConfigProvider` (documented default seed). **Forbid module-level `random.*`** — replace
every `random.random()/uniform()/choice()` with `self._rng.*`. No oracle impact (M1 runs failure-sim
off, zero slippage) but locks future determinism per #5/PERF2.

### Pattern 7: Flat O(1) order index (PERF2, D-14)
**What:** Add a flat `Dict[UUID, Order]` alongside the existing nested `Dict[portfolio][order]` dicts in
`InMemoryOrderStorage`, keyed by native `uuid.UUID`; keep nested dicts for portfolio-scoped queries.
**When:** lookup/removal by id (currently O(n) cross-portfolio scans in `_remove_order_search_all`,
`get_order_by_id` without portfolio_id). Tighten the `Union[str, int]` param types to `UUID`.
> Note: the **full** O(1) flat-index rework for nested-scan removal is **M4-06 (PERF3)** — M2a adds the
> flat index + UUID keying; the deeper nested-scan elimination is M4's. Coordinate scope with the planner.

### Anti-Patterns to Avoid
- **Calling top-level `uuid_utils.uuid7()`** — returns the custom type; breaks D-14 native-UUID typing. Use `uuid_utils.compat`.
- **Quantizing intermediate Decimal math** — inflates drift vs the M1 oracle; quantize only at boundaries (D-01).
- **`Decimal(float_value)`** — captures float-repr artifacts (`Decimal(0.1)` → `0.1000000000000000055…`). Always `Decimal(str(x))` (D-04).
- **Freezing `SignalEvent`** — `verified` is mutated at `event.py:235`; freezing it pre-judges M3 #11. Leave mutable.
- **Module-level `random.*` in engine code** (D-11 forbids).
- **Pulling forward `portfolio.cash += ...` cash routing** (M4 #22) or **order/txn timestamp determinism** (M2b) — type the fields/build the mechanism only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-ordered unique IDs | Custom timestamp+counter scheme (the current `IDGenerator`) | `uuid_utils.compat.uuid7()` | Rust-backed, monotonic, collision-safe, native `uuid.UUID`; the current scheme is the overflow-prone defect being removed |
| Money rounding | Ad-hoc `round(x, 2)` on floats | `Decimal.quantize(scale, ROUND_HALF_UP)` | float `round()` is banker's-rounding + binary-repr lossy; D-03 requires HALF_UP on Decimal |
| float→Decimal conversion | `Decimal(x)` on a float | `Decimal(str(x))` | Direct `Decimal(float)` captures binary artifacts |
| Numeric DataFrame diff | byte-compare or manual loops | `pandas.testing.assert_frame_equal(..., rtol=, atol=)` | Column-level failure messages; tolerance built in (D-15) |
| Abstract-method enforcement | Manual `raise NotImplementedError` in bodies | `abc.ABC` + `@abstractmethod` or `typing.Protocol` | The dead `__metaclass__` pattern enforces nothing on Py3; real ABCs fail at instantiation (#20) |
| ID-type confusion detection | Runtime asserts | `typing.NewType` + `mypy --strict` | Zero-cost static detection (D-12) |

**Key insight:** Every "Don't Build" here is literally a defect the M1 review flagged (#10 custom IDs,
#17 float money, #20 dead ABCs, #5 unseeded RNG). The phase is replacing hand-rolled foundations with
stdlib/blessed equivalents — resist re-implementing.

## Runtime State Inventory

> This is a structural code refactor with no external datastore migration. The id-scheme change is a
> code/type change, not a stored-data migration (backtest uses in-memory storage; no Postgres yet).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — backtest path uses `InMemoryOrderStorage` (no DB persistence; D-sql deferred). IDs are generated fresh per run; no historical UUIDs to migrate. | none |
| Live service config | **None** — live mode (D-live) is out of scope; no running service holds the integer-id scheme. | none |
| OS-registered state | **None** — no cron/scheduler/daemon references the id scheme. | none |
| Secrets/env vars | **None** — no secret or env var encodes ids or the RNG seed today; the seed source is `ConfigProvider`/YAML (new config key, not a rename). | add a documented default-seed config key (D-11) |
| Build artifacts | **`uuid-utils` + `mypy` not yet installed** — `poetry add` updates `pyproject.toml` + `poetry.lock`; `.venv` must be re-synced. | `poetry add` (both); `poetry install` |

**Canonical question — after every file is updated, what runtime systems still hold the old integer
id scheme?** Answer: **nothing.** The integer scheme exists only in code (`id_generator.py` + entity
fields); there is no persisted store, no live service, no OS registration. The golden oracle (D-12)
deliberately excludes id *values*, so the frozen `test/golden/` files contain no integer ids to drift.

## Common Pitfalls

### Pitfall 1: Using top-level `uuid_utils.uuid7()` (custom type leak)
**What goes wrong:** Fields end up typed as `uuid_utils.UUID`; `Dict[uuid.UUID, Order]` keys and `NewType` aliases over `uuid.UUID` mismatch; mypy strict errors proliferate; serialization differs.
**Why it happens:** The top-level module is the "obvious" import and most examples show it.
**How to avoid:** `import uuid_utils.compat as uuid_compat` and call `uuid_compat.uuid7()` — returns stdlib `uuid.UUID`. Verify in a smoke test: `assert type(idgen.generate_order_id()) is uuid.UUID`.
**Warning signs:** mypy `Argument has incompatible type "uuid_utils.UUID"; expected "uuid.UUID"`.

### Pitfall 2: `Decimal` warnings tripping `filterwarnings = ["error"]`
**What goes wrong:** Decimal context overflow/rounding can raise signals; if surfaced as Python warnings, the strict pytest config (`filterwarnings = ["error"]`) fails the suite.
**Why it happens:** `pyproject.toml:69` sets `error` first (then ignores UserWarning + DeprecationWarning, and `--disable-warnings` is in addopts). A *new* warning category (e.g. from a Decimal trap or uuid-utils) is NOT ignored and will error.
**How to avoid:** Keep Decimal math inside the default 28-digit context (no traps enabled); add a targeted `filterwarnings` ignore (with a comment + deferral tag) only if a specific, identified warning appears — never blanket-ignore. Run the suite after the Decimal conversion to surface any.
**Warning signs:** `pytest` failing with `DecimalException` or a new `Warning` subclass.

### Pitfall 3: Real ABC enforcement surfaces `SimulatedExchange` non-conformance (the #20 payoff)
**What goes wrong:** `AbstractExchange` (execution `exchanges/base.py`) declares `@abstractmethod configure`, `is_connected`, `validate_symbol` — but **`SimulatedExchange` does not implement `configure`, `is_connected`, or `validate_symbol`** (verified by grep: it has `execute_order/on_market_data/on_order/connect/disconnect/health_check/validate_order` only). The dead `__metaclass__` pattern lets it instantiate today; a real ABC/Protocol will fail instantiation or mypy.
**Why it happens:** Py2 `__metaclass__ = ABCMeta` is a no-op on Python 3, so enforcement was never active (#20).
**How to avoid (D-08 minimal conformance):** Implement the missing methods on `SimulatedExchange` "just enough" to conform + pass mypy — e.g. `configure(config) -> bool`, `is_connected() -> bool` (return `self._connected`), `validate_symbol(symbol) -> bool`. Do NOT do deeper rework. Audit each base's subclasses similarly before flipping the metaclass.
**Warning signs:** `TypeError: Can't instantiate abstract class SimulatedExchange with abstract methods configure, is_connected, validate_symbol` at construction, or mypy "Cannot instantiate abstract class".

### Pitfall 4: Freezing `SignalEvent` breaks the `verified` mutation
**What goes wrong:** Applying `@dataclass(frozen=True)` to `SignalEvent` raises `FrozenInstanceError` when `event.py:235`'s `verified: bool` field is set after construction (the order validator flips it).
**Why it happens:** `verified` is a mutable flag on a hot-path event; it's a known immutability blocker.
**How to avoid:** Do NOT freeze `SignalEvent` this phase. Freeze only events with no post-construction mutation. The full event-immutability + `event_id` redesign (#11) is M3 — coordinate, do not pre-judge.
**Warning signs:** `dataclasses.FrozenInstanceError: cannot assign to field 'verified'`.

### Pitfall 5: Quantizing intermediate math inflates oracle drift
**What goes wrong:** Quantizing every multiply/add (instead of only at boundaries) compounds rounding and pushes numeric drift past the D-15 transitional tolerance, failing the run-path test for the wrong reason.
**Why it happens:** Over-eager "round everything" instinct.
**How to avoid (D-01):** Carry full 28-digit precision through intermediates; `quantize()` only at the cash ledger / reported-PnL / serialization boundary.
**Warning signs:** Numeric oracle drift much larger than sub-cent.

### Pitfall 6: mypy 2.x config-syntax surprises
**What goes wrong:** Training-data mypy knowledge is 1.x-era; 2.1.0 may have changed defaults or option names, and `--strict-config`-style invalid options would error.
**Why it happens:** mypy 2.x is newer than common knowledge (verified 2.1.0 latest on PyPI).
**How to avoid:** After `poetry add mypy`, run `poetry run mypy --help` / validate the `[tool.mypy]` block against the installed version; introduce strict via `strict = true` then layer `[[tool.mypy.overrides]]` `module = [...]` `ignore_errors = true` for deferred subsystems.
**Warning signs:** mypy erroring on its own config keys.

## Code Examples

### mypy strict config + deferred-module excludes (D-05/D-06)
```toml
# pyproject.toml — Source: mypy docs config-file pattern [CITED: mypy.readthedocs.io/en/stable/config_file.html]
[tool.mypy]
python_version = "3.13"
strict = true
warn_unused_ignores = true
warn_redundant_casts = true
files = ["itrader"]

# Deferred subsystems — excluded now (D-05); each tagged with its deferral.
[[tool.mypy.overrides]]
module = [
    "itrader.trading_system.live_trading_system",   # D-live
    "itrader.trading_system.trading_interface",     # D-live
    "itrader.price_handler.sql_handler",            # D-sql
    "itrader.price_handler.exchange.CCXT",          # D-oanda
    "itrader.price_handler.exchange.OANDA",         # D-oanda
    "itrader.price_handler.live_streaming.BINANCE_Live",  # D-live
    "itrader.screeners_handler.*",                  # D-screener
]
ignore_errors = true

# Third-party libs without stubs (if any surface)
[[tool.mypy.overrides]]
module = ["ta.*", "pandas_ta.*", "ccxt.*"]
ignore_missing_imports = true
```
```makefile
# Makefile (D-06)
typecheck:
	poetry run mypy itrader
```
> Validate the exact `module` paths and the `strict`/override keys against installed mypy 2.1.0 — the
> module list above is the D-05 intent; confirm each path resolves.

### D-15 oracle test: split exact identity from tolerant numerics
```python
# test_backtest_oracle.py — extend the existing exact assert
# Behavioral identity columns (entry_date, exit_date, side) — EXACT (D-15):
pdt.assert_frame_equal(
    fresh_trades_sorted[_TRADE_KEY_COLUMNS],
    golden_trades_sorted[_TRADE_KEY_COLUMNS],
    check_exact=True,
)
# Numeric columns — bounded transitional tolerance for M2a (D-15), removed at M2b:
_NUMERIC_COLS = [c for c in fresh_trades_sorted.columns if c not in _TRADE_KEY_COLUMNS]
pdt.assert_frame_equal(
    fresh_trades_sorted[_NUMERIC_COLS],
    golden_trades_sorted[_NUMERIC_COLS],
    check_exact=False, rtol=1e-9, atol=1e-2,   # tune empirically; sub-cent quantization drift OK, dollar-level bugs caught
)
```
> **Tolerance magnitude (Claude's discretion / D-15):** start with `atol=1e-2` (one cent) on USD money
> columns and `rtol=1e-9` on relative drift, then **tighten empirically** from the observed M2a drift —
> tight enough to catch dollar-level money bugs, loose enough for sub-cent quantization. Document the
> chosen value inline with a `# D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)` comment.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `__metaclass__ = ABCMeta` (Py2) | `class X(ABC)` + `@abstractmethod`, or `typing.Protocol` | Python 3.0 (2008) / `Protocol` PEP 544 (Py 3.8) | The dead pattern enforces nothing; real ABCs are the fix (#20) |
| Custom timestamp+counter int IDs | UUIDv7 (time-ordered) | RFC 9562 (2024) standardized UUIDv7 | Sortable + collision-safe without a custom scheme (#10) |
| float for money | `Decimal` end-to-end | long-standing financial best practice | float money is a correctness defect (#17) |
| mypy 1.x | mypy **2.1.0** | 2.0 released after training cutoff | Validate strict config keys against installed version |

**Deprecated/outdated:**
- The integer `IDGenerator` (timestamp+counter+type-prefix) — replaced wholesale by uuid7.
- `__metaclass__ = ABCMeta` in all 9 base files — Python-2-only, no effect on Py3.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | mypy 2.1.0 strict config uses `strict = true` + `[[tool.mypy.overrides]]` with `ignore_errors`/`module` (same as 1.x) | mypy config example | LOW — config schema is stable; planner must validate against installed 2.1.0 |
| A2 | `uuid_utils.UUID` (custom) is hashable/sortable | UUIDv7 §alternatives | LOW — we recommend `compat` (stdlib UUID) anyway, so this is moot for the chosen path |
| A3 | The D-15 tolerance `atol=1e-2`/`rtol=1e-9` is a reasonable starting point | Code Examples | LOW — explicitly to be tuned empirically per D-15 (Claude's discretion) |
| A4 | slopcheck verdicts (not run) would be OK for both packages | Package Legitimacy Audit | LOW — both are locked/canonical and PyPI-verified |

**If this table is empty:** N/A — four low-risk assumptions, all flagged for the planner to confirm at build time.

## Open Questions (RESOLVED)

_Q1 resolved: convert the 8 bases named in D-07 as the contract; the 2 extra dead bases are flagged as COVERAGE-INDEX deltas (handled in the ABC plan), not silently scoped in. Q2 and Q3 are Claude's Discretion per CONTEXT.md (per-event freeze audit; Order stays a mutable entity)._

1. **Exact set of bases to convert (CONTEXT.md "8" vs tree "11 classes / 9 files").**
   - What we know: CONTEXT.md D-07 names 8 (3 Protocol + 5 ABC). The tree has the dead `__metaclass__` pattern in **9 files / 11 classes** — extras: `trading_system/simulation/base.py::SimulationEngine`, and `portfolio_handler/base.py` has **two** classes (`AbstractPortfolioHandler` + `AbstractPortfolio`). Also `Strategy` (`strategy_handler/base.py`) has **no** metaclass at all (bare `class Strategy(object)`), and `Screener` has one `@abstractmethod` with a self-less signature but no metaclass.
   - What's unclear: Whether D-07's "8" intends to convert ONLY the named 8 (leaving `simulation/base.py` and `portfolio_handler/base.py` dead) or whether those were omitted from the list. D-08 says "convert all 8 now (SC3)."
   - Recommendation: Convert the **8 named in D-07** as the contract; **flag** the 2 extra dead bases (`SimulationEngine`, `AbstractPortfolioHandler`/`AbstractPortfolio`) to the planner/owner as a COVERAGE-INDEX §E delta candidate — do NOT silently expand scope. `Strategy` becomes a real ABC (D-07 lists it as ABC); `Screener`'s self-less `@abstractmethod screen_market(prices, event)` signature must be fixed to conform.

2. **`frozen=True`/`slots=True` precise event list.**
   - What we know: `event.py` has ~9 `@dataclass` events; `SignalEvent` must stay mutable (`verified` at :235).
   - What's unclear: Which of the remaining events (PingEvent, BarEvent, OrderEvent, FillEvent, ScreenerEvent, etc.) are mutated post-construction.
   - Recommendation: Audit each event for post-construction attribute assignment before freezing; freeze only the genuinely-immutable ones; defer anything ambiguous to M3 (#11). This is Claude's discretion per CONTEXT.md.

3. **`Order` entity: frozen or not?**
   - What we know: `Order` (`order.py:40`) is a mutable `@dataclass` whose lifecycle fields (`updated_at`, `filled_at`, `status`, `state_changes`) are mutated in-place; it is an *entity*, not an immutable event DTO.
   - Recommendation: Do **not** freeze `Order` — it is a mutable entity by design (the hot-path "DTOs/events" in M2-03 refers to events/result-objects, not stateful entities). Type its `id` field as `UUID`/`OrderId` and money fields as `Decimal`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uuid-utils` | M2-01 (UUIDv7) | ✗ | — (0.16.0 on PyPI) | none — `poetry add` required (locked dep) |
| `mypy` | M2-03 (strict gate) | ✗ | — (2.1.0 on PyPI) | none — `poetry add --group dev` required |
| Python 3.13 | all | ✓ | 3.13.x (`.venv`) | — |
| Poetry | install | ✓ | in-project `.venv` | — |
| `pandas` (testing) | M2a oracle test (D-15) | ✓ | 2.3.x | — |

**Missing dependencies with no fallback:**
- `uuid-utils` and `mypy` — must be installed (`poetry add`). Both verified present on PyPI. This is the first install step of the phase.

**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov, pytest-html, pytest-watch) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (strict markers/config; `filterwarnings=["error", ignore UserWarning, ignore DeprecationWarning]`; `--disable-warnings`) |
| Quick run command | `poetry run pytest test/test_order_handler test/test_portfolio_handler -q` |
| Full suite command | `make test` (`poetry run pytest`) |
| Type gate (new, D-06) | `make typecheck` → `poetry run mypy itrader` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M2-01 | `idgen.generate_*_id()` returns a stdlib `uuid.UUID` (UUIDv7); ids unique + time-ordered | unit | `poetry run pytest test/test_outils/test_id_generator.py -x` | ❌ Wave 0 (new) |
| M2-01 | Storage keys + flat index are native `UUID`; lookup/removal by UUID works | unit | `poetry run pytest test/test_order_handler/test_order_storage.py -x` | ✅ exists (extend) |
| M2-02 | `core.money.quantize` HALF_UP per-instrument; `to_money` uses `str()`; no float round-trip in cash path | unit | `poetry run pytest test/test_core/test_money.py -x` | ❌ Wave 0 (new) |
| M2-02 | Transaction/portfolio money fields are `Decimal`; `cash += float(...)` removed | unit | `poetry run pytest test/test_portfolio_handler -k decimal -x` | ❌ Wave 0 (new) |
| M2-03 | `mypy --strict` clean over in-scope package | type | `make typecheck` | ❌ Wave 0 (config new) |
| M2-04 | Each converted base is a real ABC/Protocol; `SimulatedExchange` conforms (configure/is_connected/validate_symbol) | unit | `poetry run pytest test/test_execution_handler/test_exchanges -x` | ✅ exists (extend) |
| M2-05 | Injected `Clock` returns bar time; engine-path `datetime.now()` removed; seeded `Random` injected | unit | `poetry run pytest test/test_core/test_clock.py test/test_execution_handler -k rng -x` | ❌ Wave 0 (new) |
| M2a (oracle) | Behavioral identity EXACT + numeric within D-15 tolerance | integration/slow | `poetry run pytest test/test_integration/test_backtest_oracle.py -x` | ✅ exists (MODIFY for D-15 tolerance) |

### Sampling Rate
- **Per task commit:** the relevant quick unit command above for the touched area.
- **Per wave merge:** `make test` + `make typecheck`.
- **Phase gate:** `make test` green, `make typecheck` clean, and `test_backtest_oracle.py` green with the D-15 tolerance (behavioral EXACT, numeric within bound) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `test/test_outils/test_id_generator.py` — covers M2-01 (uuid7 type, uniqueness, ordering)
- [ ] `test/test_core/test_money.py` — covers M2-02 (quantize HALF_UP, per-instrument scale, `to_money`)
- [ ] `test/test_core/test_clock.py` — covers M2-05 (Clock returns bar time; advance contract)
- [ ] `pyproject.toml` `[tool.mypy]` + `[[tool.mypy.overrides]]` — M2-03 gate config (none today)
- [ ] `Makefile` `typecheck` target — M2-03/D-06 (none today)
- [ ] `conftest.py` `DIR_MARKERS` — add `"test_outils": "unit"`, `"test_core": "unit"` mappings if new dirs are created (otherwise new tests won't get the marker auto-applied; `--strict-markers` is active)
- [ ] **MODIFY** `test/test_integration/test_backtest_oracle.py` — split identity-exact from numeric-tolerant (D-15)
- [ ] Install: `poetry add uuid-utils@^0.16.0` and `poetry add --group dev mypy@^2.1.0`

## Project Constraints (from CLAUDE.md)
- **Queue-only cross-domain communication** — handlers never call other handlers; emit events. (Unaffected by M2a but must not be violated.)
- **Indentation:** tabs in handler modules; **spaces** in `config/` and newer modules — **match the file you edit**. New `core/` files (`ids.py`, `money.py`, `clock.py`) use **spaces** (consistent with `config/` + `core/exceptions/`).
- **Import side effects:** `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons on import — the `idgen` swap stays inside this singleton; do not change the import-time contract.
- **Test strictness:** `filterwarnings=["error"]` + `--strict-markers` + `--strict-config` — any new warning fails the suite; every marker must be declared; new test dirs need a `DIR_MARKERS` entry or an explicit marker.
- **Decimal money, single UUIDv7 scheme, determinism** — program-level locked decisions this phase implements.
- **New issues found during execution → COVERAGE-INDEX §E delta log with owner approval** — never silently fold into the running phase (relevant to the 2 extra dead bases in Open Question 1).

## Security Domain

> `security_enforcement` is not set in `.planning/config.json`. This is a backtest-only structural
> refactor (no auth, no network input on the engine path, no user-facing surface — live/SQL/adapters
> are all deferred). The only input is a committed golden CSV. No new attack surface is introduced.
> ASVS categories (auth/session/access-control/crypto) are **not applicable** to this phase.
> V5 Input Validation: the CSV/config parse path is unchanged by M2a; `Decimal(str(x))` conversion is
> the only new value-handling and is internal. No security controls required for M2a.

## Sources

### Primary (HIGH confidence)
- `github.com/aminalaee/uuid-utils` README — `uuid7()` return type, `uuid_utils.compat` returns stdlib `uuid.UUID`, function inventory [CITED]
- PyPI `pip index versions uuid-utils` → 0.16.0 latest [VERIFIED: PyPI]
- PyPI `pip index versions mypy` → 2.1.0 latest [VERIFIED: PyPI]
- Live codebase grep/read (all line refs below verified against the tree on 2026-06-04):
  - `itrader/outils/id_generator.py` (integer scheme + 6 generators) [VERIFIED: codebase]
  - `idgen` call sites: `order.py:50`, `screeners/base.py:24`, `transaction.py:90`, `position.py:38`, `portfolio.py:44`, `portfolio_handler.py:269`, `strategy_handler/base.py:18` [VERIFIED: codebase]
  - D-13 prefix-decode: `* 10**19` appears ONLY in `id_generator.py:58` — no decode site [VERIFIED: codebase]
  - `transaction_manager.py:229` `self.portfolio.cash += float(transaction_cost)` round-trip; `_calculate_transaction_cost` already uses `Decimal(str(...))` [VERIFIED: codebase]
  - `in_memory_storage.py` keys by `str(order.id)`, `Union[str, int]` params throughout [VERIFIED: codebase]
  - Dead `__metaclass__ = ABCMeta` bases: reporting/base, price_handler/base, price_handler/exchange/base, trading_system/simulation/base, portfolio_handler/base (×2), execution_handler/base, execution_handler/exchanges/base, universe/universe, position_sizer/base [VERIFIED: codebase]
  - `SimulatedExchange` missing `configure`/`is_connected`/`validate_symbol` vs `AbstractExchange` abstract methods [VERIFIED: codebase]
  - `SignalEvent.verified` at `event.py:235` (frozen blocker) [VERIFIED: codebase]
  - engine-path `random.*`: `fixed_slippage_model.py:61`, `linear_slippage_model.py:63`, `simulated.py:142,150,181` [VERIFIED: codebase]
  - `test_backtest_oracle.py` currently `check_exact=True` on all columns [VERIFIED: codebase]

### Secondary (MEDIUM confidence)
- mypy config-file pattern (`[tool.mypy]` strict + `[[tool.mypy.overrides]]`) — stable across recent versions; validate keys against installed 2.1.0 [CITED: mypy.readthedocs.io/en/stable/config_file.html]

### Tertiary (LOW confidence)
- D-15 tolerance starting magnitude (`atol=1e-2`/`rtol=1e-9`) — to be tuned empirically (explicitly Claude's-discretion per CONTEXT.md)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — both deps verified on PyPI; uuid-utils API confirmed via authoritative GitHub README; `compat` finding is decisive and well-sourced.
- Architecture: HIGH — all integration points read directly from the tree; CONTEXT.md refs verified.
- Pitfalls: HIGH — Pitfall 3 (SimulatedExchange non-conformance) and Pitfall 4 (SignalEvent.verified) confirmed by direct grep; not theoretical.
- Drift findings: HIGH — the "8 vs 11" base-count and the oracle-test `check_exact=True` drift are grep-confirmed; flagged for planner decision, not silently resolved.

**Research date:** 2026-06-04
**Valid until:** 2026-07-04 (stable stdlib + locked decisions; uuid-utils/mypy versions may bump — re-verify before install)
