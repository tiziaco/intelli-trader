# Phase 2: M2a — Identity, Money & Determinism - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-04
**Phase:** 2-m2a-identity-money-determinism
**Areas discussed:** Money precision policy, mypy --strict scope, Oracle during Decimal shift, Determinism scope, UUIDv7 migration, ABC vs Protocol

---

## Money precision policy

### Q1 — Decimal precision model
| Option | Description | Selected |
|--------|-------------|----------|
| High-precision context, quantize at edges | 28-digit context, full precision in math, quantize only at display/persistence | |
| Per-instrument quantization at boundaries | Quantize at every money boundary to instrument scale (BTC 8dp / USD 2dp) | |
| You decide | Claude picks per research | |
| **Hybrid (resolved in discussion)** | 28-digit working context + per-instrument quantization at money boundaries | ✓ |

**User's choice:** Hybrid (initially leaned to option 2 / per-instrument).
**Notes:** User worried 28 digits was "too much" and that small-value cryptos need high precision.
Clarified that **context precision** (significant figures, Python default 28) is a *separate knob*
from **quantization scale** (decimal places per instrument). The two combine — keep 28-digit context
AND quantize at boundaries (exactly #17's recommendation). Small-value-token precision is a
quantization-scale concern, deferred since only BTCUSD is traded.

### Q2 — Rounding mode
| Option | Description | Selected |
|--------|-------------|----------|
| ROUND_HALF_UP | Matches #17; conventional financial rounding | ✓ |
| ROUND_HALF_EVEN (banker's) | Python default; reduces cumulative bias | |
| You decide | — | |

**User's choice:** ROUND_HALF_UP.

### Q3 — float→Decimal boundary
| Option | Description | Selected |
|--------|-------------|----------|
| At data ingest via str() | Convert whole CSV/frame at the feed | |
| At event/DTO construction | Convert when building fills/transactions | |
| You decide | — | |
| **Money-path entry only (resolved in discussion)** | Decimal(str(x)) at fill/valuation/sizing; indicator path stays float | ✓ |

**User's choice:** Money-path entry only.
**Notes:** User asked "weren't we supposed to get rid of float completely?" Clarified that
"Decimal end-to-end" is a **money** rule, not an "eliminate all floats" rule (#17 carve-out: float
OK for derived analytics). Indicator path (SMA/MACD on ta/pandas-ta) must stay float; the defect is
the same-value float↔Decimal round-trip, not float's existence. User accepted the distinction.
Also confirmed: OK with the **numerical** oracle drifting this phase (behavioral stays exact).

---

## mypy --strict scope

### Q1 — Scope width
| Option | Description | Selected |
|--------|-------------|----------|
| In-scope strict + documented excludes | Strict backtest+core; exclude deferred live/SQL/screener/OANDA via overrides | ✓ |
| Whole package, no excludes | Type even deferred/out-of-scope code now | |
| You decide | — | |

### Q2 — Enforcement
| Option | Description | Selected |
|--------|-------------|----------|
| Add a mypy gate now | `make typecheck` + config wired into workflow | ✓ |
| Reach clean, gate later | Achieve clean but no enforcing target yet | |
| You decide | — | |

**User's choice:** In-scope strict + documented excludes; add the gate now.

---

## Oracle during Decimal shift

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded transitional tolerance | Keep numerical assertion with a tolerance; remove + re-freeze exact at M2b | ✓ |
| Skip numerical until M2b | xfail/skip numerical for the phase | |
| Re-freeze exact at end of M2a | Adds a third sanctioned re-baseline point | |

**User's choice:** Bounded transitional tolerance.
**Notes:** Behavioral oracle asserted exactly throughout. Tolerance magnitude set empirically during
planning. Honors PROJECT.md's two-point exact-baseline rule (after M2, after M5).

---

## Determinism scope

### Q1 — Backtest clock semantics
| Option | Description | Selected |
|--------|-------------|----------|
| Simulation time = current bar/event time | Clock returns bar time in backtest; perf-timing stays wall-clock | ✓ |
| Fixed injected timestamp / monotonic counter | Synthetic value disconnected from market time | |
| You decide | — | |

### Q2 — Replacement breadth
| Option | Description | Selected |
|--------|-------------|----------|
| Clock mechanism + engine-path sites; defer order/txn audit to M2b | M2a builds mechanism; M2b owns audit/txn timestamp determinism (its SC2) | ✓ |
| All domain timestamps now | Pull M2b SC2 forward | |
| You decide | — | |

### Q3 — RNG seeding
| Option | Description | Selected |
|--------|-------------|----------|
| Config seed behind an injected Random | Seeded random.Random injected into SimulatedExchange + slippage models | ✓ |
| Module-level random.seed() at run start | Global mutable state (the anti-pattern #5 warns against) | |
| You decide | — | |

**User's choice:** Simulation time; mechanism + engine-path (defer audit/txn to M2b); config seed + injected Random.

---

## UUIDv7 migration

### Q1 — NewType alias granularity
| Option | Description | Selected |
|--------|-------------|----------|
| Distinct alias per entity | OrderId/PortfolioId/PositionId/TransactionId/StrategyId/ScreenerId over UUID | ✓ |
| Single EntityId alias | One alias for all (loses cross-entity safety) | |
| You decide | — | |

### Q2 — Type discriminator
| Option | Description | Selected |
|--------|-------------|----------|
| Drop it — type implicit in entity/field | No discriminator; table IS type when Postgres lands | ✓ |
| Add explicit entity-type enum field | Keep a discriminator on each entity | |
| You decide | — | |

### Q3 — Storage representation
| Option | Description | Selected |
|--------|-------------|----------|
| Native UUID end-to-end | UUID fields, Dict[UUID, Order] index, native keys | ✓ |
| Stringified UUID keys | Keep str(order_id) keying | |
| You decide | — | |

**User's choice:** Distinct per-entity aliases; drop the type discriminator; native UUID end-to-end.
**Notes:** Scout confirmed nothing decodes the integer type-prefix today, so dropping it is safe.
event_id redesign stays M3 (#11) — M2a touches only the six entity IDs.

---

## ABC vs Protocol

### Q1 — Default policy
| Option | Description | Selected |
|--------|-------------|----------|
| Per-#20 mix | Protocol for swap-a-fake seams; ABC where shared behavior is inherited | ✓ |
| Uniform real ABC for all 8 | Convert every base to ABC | |
| You decide | — | |

### Q2 — Conversion depth
| Option | Description | Selected |
|--------|-------------|----------|
| Convert all 8 + minimal conformance; defer deep rework | Satisfy SC3 now; deeper module rework stays in owning milestone | ✓ |
| Convert + fully fix each subclass now | Pull later-milestone rework forward | |
| You decide | — | |

**User's choice:** Per-#20 mix; convert all 8 + minimal conformance, defer deep rework.
**Notes:** User asked for a refresher on ABC vs Protocol and whether mixing both is common in Python
frameworks. Confirmed it's idiomatic (stdlib `collections.abc` + `typing` Protocols, Django,
FastAPI/Starlette). Protocol → AbstractExchange, AbstractPositionSizer, AbstractPriceHandler;
ABC → AbstractExecutionHandler, AbstractStatistics, Strategy, Universe, Screener.

---

## Claude's Discretion

- idgen facade shape (keep thin facade returning uuid7()).
- Flat O(1) `Dict[UUID, Order]` index design/placement (PERF2).
- Which hot-path DTOs/events get `frozen=True`/`slots=True` (mind `SignalEvent.verified` mutation; don't pre-judge M3 #11).
- Transitional numerical-tolerance magnitude (empirical).
- Exact `[[tool.mypy.overrides]]` module list + `make typecheck` invocation.
- Per-base Protocol-vs-ABC edge calls within the D-07 policy.

## Deferred Ideas

- General per-cryptocurrency precision registry (small-value tokens) — only BTCUSD traded.
- Order-audit & transaction-timestamp determinism → M2b SC2.
- calculate_signal contract enforcement → M5b #24.
- Universe collapse → M5b #33.
- Reporting computation/presentation split + print_summary → M5b #38.
- Screener wiring → deferred D-screener.
- Cash-through-CashManager + DEF-01-A reconciliation + atomic transactions → M4 (#22, #16, #23).
- Event immutability + event_id + linkage IDs + dispatch registry → M3 (#11, #1, #2).
- mypy --strict over deferred subsystems → excluded until a later milestone reworks them.
