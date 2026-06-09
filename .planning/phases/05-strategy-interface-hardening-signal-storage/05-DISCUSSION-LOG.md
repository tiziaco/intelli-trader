# Phase 5: Strategy Interface Hardening & Signal Storage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 5-strategy-interface-hardening-signal-storage
**Areas discussed:** Config model shape & constructor contract, Per-strategy params placement, Signal storage architecture, SMA_MACD relocation, Sizing/SLTP ↔ pydantic boundary, Timeframe validation & conversion, Config snapshot storage form, SignalRecord identity, Strategy interface simplification

---

## Config Model Shape & Constructor Contract

User asked "what's a good structure / what do other frameworks do?" → researched
nautilus-trader (config object as constructor arg, `self.config`), backtrader
(`params` tuple), backtesting.py (class attrs), LEAN (external JSON params).

| Option | Description | Selected |
|--------|-------------|----------|
| Config object IS the constructor arg (nautilus pattern) | `Strategy(config: BaseStrategyConfig)`; single source of truth; per-strategy subclass | ✓ |
| Keep kwargs, validate via config internally | Smallest diff, two surfaces, snapshot needs assembly | |
| Hybrid: config base + kwargs convenience on subclasses | Clean base + ergonomic authoring, more boilerplate | |

**User's choice:** Config object + subclass (nautilus pattern).
**Notes:** Chosen because it matches the in-repo cross-val oracle (nautilus
`StrategyConfig`), fits the repo's typed/single-source ethos, answers HARD-01 +
HARD-02 in one shape, and gives the SIG-01 config snapshot for free. Resolves
the "Per-strategy params placement" area at the same time (subclass, not a
parallel `params` submodel).

---

## Signal Storage Architecture — store shape

| Option | Description | Selected |
|--------|-------------|----------|
| Lightweight in-memory store, seam-ready | Concrete store + query API, no ABC/factory yet | |
| Full pluggable seam (mirror OrderStorage) | ABC + in-memory backend + factory | ✓ |
| You decide | — | |

**User's choice:** Full pluggable seam mirroring `order_handler/storage/`.
**Notes:** Maximum consistency with the existing order-storage pattern; ready
for the v1.3 Postgres backend.

---

## Signal Storage Architecture — record shape

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated frozen SignalRecord | Purpose-built record + config snapshot; decoupled from SignalEvent | ✓ |
| Store the SignalEvent + attach config snapshot | Less duplication, couples storage to event schema | |
| You decide | — | |

**User's choice:** Dedicated frozen `SignalRecord` (Order-vs-OrderEvent analogy).

---

## Signal Storage Architecture — capture point

User clarified: leaning per-intent because signal→order→portfolio can be
related downstream. Verified against code (`Order` carries `strategy_id`/
`portfolio_id`/`ticker`/`time`, built from the signal) — natural-key join works.

| Option | Description | Selected |
|--------|-------------|----------|
| Per enqueued SignalEvent (per-portfolio) | Carries portfolio_id, N records per fan-out | |
| Per strategy intent (pre-fan-out) | No portfolio_id; matches SIG-01 field list | ✓ |
| You decide | — | |

**User's choice:** Per-intent capture.
**Notes:** Portfolio reconciliation is a downstream natural-key join
`(strategy_id, ticker, time)`. Caveat recorded: Order does not store the
signal's `event_id` today → join, not hard FK; hard FK routed to v1.3.

---

## SMA_MACD Relocation

User proposed a `strategies/` folder inside the strategy_handler folder.
Verified import sites (4 real; empty barrel; crossval mentions are comments).

| Option | Description | Selected |
|--------|-------------|----------|
| Move SMA_MACD + empty_strategy | Both into `strategies/`; consistent split | ✓ |
| Move SMA_MACD only | Smaller, less consistent | |
| You decide | — | |

**User's choice:** Move both into `itrader/strategy_handler/strategies/`.
**Notes:** Stays in production package (no inverted dependency); parallels
`my_strategies/`; 4 import updates + byte-exact re-prove.

---

## Sizing/SLTP ↔ pydantic boundary

User asked "what would be most correct for future-proofing the entire system?"
→ explained the correct end-state is a serializable discriminated union (needed
at v1.3 for SQL round-trip); `arbitrary_types_allowed` is an interim escape hatch.

| Option | Description | Selected |
|--------|-------------|----------|
| Interim dataclasses now + route unification to v1.3 | arbitrary_types_allowed; roadmap item for discriminated union | ✓ |
| Migrate to discriminated union now | Correct end-state, but cross-cutting byte-exact-path rewrite in a hardening phase | |
| pydantic.dataclasses middle path now | Near-drop-in, still mutates core/sizing.py on the byte-exact path | |

**User's choice:** Interim dataclasses now + route to v1.3.
**Notes:** Sequenced answer — name the correct end-state, route it; do the
minimal oracle-safe step now. v1.1 SIG-02 only needs in-memory queryability.

---

## Timeframe validation & conversion

User asked for the state-of-the-art option; dislikes `to_timedelta` (gaps).
Read `to_timedelta` (d/h/m/w fixed; rejects month) + `_aligned` (weekly fires
every midnight — M2-deferred anchoring caveat). SOTA = nautilus `BarSpecification`
`(step, aggregation)` value object.

| Option | Description | Selected |
|--------|-------------|----------|
| Constrained Timeframe enum now + route bar-spec redesign | Typed boundary, to_timedelta unchanged in base | ✓ |
| Build the structured bar-spec value object now | SOTA end-state, cross-cutting time-core refactor, high oracle risk | |
| Minimal free-string validation only | Smallest, no typing, least future-proofing | |

**User's choice:** Constrained `Timeframe` enum now + route the structured
bar-spec value object to a roadmap item.

---

## Config snapshot storage form

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen config object by reference | Lossless, cheap, serialize at the edge | ✓ |
| Serialized dict at capture time | Eager serialization, pays the round-trip cost now | |
| You decide | — | |

**User's choice:** Store the frozen config object by reference.

---

## SignalRecord identity

| Option | Description | Selected |
|--------|-------------|----------|
| UUIDv7 SignalId | New core/ids.py type + idgen method; enables v1.3 FK | ✓ |
| No id for v1.1 | Keyed only by natural key; v1.3 retrofit needed | |
| You decide | — | |

**User's choice:** UUIDv7 `SignalId` (mirrors StrategyId/OrderId).

---

## Strategy Interface Simplification

User flagged error-prone boilerplate (`__str__`/`__repr__`, `len(bars) <
max_window` guard, `last_time = bars.index[-1]`). Asked what nautilus + LEAN do
→ both make warmup a framework concern (nautilus auto-updates indicators +
`.initialized`; LEAN `SetWarmUp`/`IsWarmingUp`).

| Option | Description | Selected |
|--------|-------------|----------|
| Fold in the safe simplifications | base __str__/__repr__ + framework-enforced warmup guard; route declared-indicator framework | ✓ |
| Only the trivial cleanup | Just base __str__/__repr__ | |
| Keep Phase 5 narrow, route all of it | Config + storage + relocation only | |

**User's choice:** Fold in the safe simplifications (oracle-dark, CLAR-02);
route the declared-indicator framework to a roadmap item.

---

## Claude's Discretion

- Exact `BaseStrategyConfig` field set/shape and validator wiring.
- How `max_window` is exposed on the config/strategy (param-derived).
- Precise `SignalRecord` field set and `SignalStore` ABC method surface.
- Where the `Timeframe` enum lives + the exact supported vocabulary list.
- Whether/where the `last_time`/window helper lands.
- Whether the e2e test strategies migrate to the new config base in this phase
  or as a Phase-6 follow-up.

## Deferred Ideas

- Serializable discriminated-union sizing/SLTP vocabulary → v1.3 (Persistence).
- Structured `(step, unit)` bar-spec value object → roadmap (pairs with
  M2 weekly/DST anchoring + multi-asset trading calendars).
- Declared-indicator framework (auto-derived warmup, stateful indicators) →
  roadmap.
- Hard signal→order FK (Order stores SignalId) → v1.3.
