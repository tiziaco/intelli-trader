---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
plan: 05
subsystem: events / core / execution / portfolio / strategy value objects
tags: [perf, msgspec, value-objects, byte-exact, PERF-08, Req-6]
requires:
  - "08-04 (cool re-frozen baseline; the measured second layer rides on it, D-03)"
  - "08-MSGSPEC-SPIKE-FINDINGS.md (the proven migration map + enumerated test updates)"
provides:
  - "Bar + the full Event hierarchy (10 event classes across 6 files) as msgspec.Struct(frozen, kw_only, gc=False)"
  - "5 standalone DTOs (TrailState, FillDecision, CancelDecision, Transaction, SignalRecord) as msgspec.Struct"
  - "msgspec promoted from dev-only transitive to a shipped itrader/ runtime dependency"
affects:
  - "event construction hot path (every Bar/BarEvent/SignalEvent/OrderEvent/FillEvent built per tick)"
  - "matching_engine resting-order MODIFY path (msgspec.structs.replace)"
tech-stack:
  added:
    - "msgspec ^0.21.1 (promoted to [tool.poetry.dependencies]; already locked 0.21.1, no version churn)"
  patterns:
    - "msgspec.Struct as a CONSTRUCTION CONTAINER only — never encode/decode (Decimal money stays Decimal)"
    - "type tag: field(default=EventType.X, init=False) -> type: ClassVar[EventType] = EventType.X"
    - "frozen msgspec.Struct honours object.__setattr__ inside __post_init__ (created_at default ports verbatim)"
    - "dataclasses.replace -> msgspec.structs.replace"
key-files:
  modified:
    - "pyproject.toml (msgspec runtime dep)"
    - "poetry.lock (msgspec groups dev -> main+dev)"
    - "itrader/core/bar.py"
    - "itrader/events_handler/events/base.py"
    - "itrader/events_handler/events/market.py"
    - "itrader/events_handler/events/signal.py"
    - "itrader/events_handler/events/order.py"
    - "itrader/events_handler/events/fill.py"
    - "itrader/events_handler/events/error.py"
    - "itrader/execution_handler/matching_engine.py"
    - "itrader/portfolio_handler/transaction/transaction.py"
    - "itrader/strategy_handler/signal_record.py"
    - "tests/unit/core/test_bar.py"
    - "tests/unit/events/test_event_immutability.py"
    - "tests/unit/events/test_bar_event_ohlc.py"
    - "tests/unit/order/test_order_manager.py"
    - "tests/unit/execution/test_matching_engine.py"
decisions:
  - "D-01: Position EXCLUDED — stays class Position(object) (mutable aggregate, recompute hotspot owned by Req 2)"
  - "D-02 carve-out: the 5 standalone DTOs ship under the oracle gate for a uniform value-object layer; NOT A/B-reverted for landing in noise (~1578 fires/run vs ~69k Bar volume)"
  - "msgspec is a construction container only — no encode/decode anywhere (grep-enforced); Decimal contract untouched"
metrics:
  duration: ~30 min
  completed: 2026-06-25
  tasks: 3
  files_changed: 17
---

# Phase 8 Plan 05: msgspec.Struct Migration (Req 6) Summary

Re-implemented the spike-proven msgspec.Struct migration cleanly: `Bar` + the full `Event`
hierarchy + 5 standalone value-object DTOs converted to `msgspec.Struct` as a pure construction
container (no encode/decode, Decimal money intact), with msgspec promoted to a shipped runtime
dependency — oracle byte-exact (134 / 46189.87730727451), determinism double-run identical, and
`mypy --strict` clean across 188 files.

## What shipped

### Task 1 — Bar + full Event chain + pyproject promotion (commit eeaf286)
- `Bar` (core/bar.py) and the entire `Event` chain — `base.py::Event` + `market.py`
  (TimeEvent/BarEvent/PortfolioUpdateEvent/ScreenerEvent) + `signal.py::SignalEvent` +
  `order.py::OrderEvent` + `fill.py::FillEvent` + `error.py` (ErrorEvent/PortfolioErrorEvent) —
  converted TOGETHER to `msgspec.Struct(frozen=True, kw_only=True, gc=False)` (8 files, 10 event
  classes + Bar). msgspec forbids Struct/non-Struct in one inheritance chain, so the chain
  converts atomically.
- `type` tag: `field(default=EventType.X, init=False)` -> `type: ClassVar[EventType] =
  EventType.X` (base declares `type: ClassVar[EventType]` annotation-only). `EventHandler._dispatch`
  reads `event.type` via `self.routes[event.type]` — a ClassVar read resolves to the class
  constant, verified live by the green oracle.
- `event_id`: `field(default_factory=uuid7)` -> `msgspec.field(default_factory=uuid7)`.
- `created_at` `__post_init__` `object.__setattr__` idiom ported VERBATIM (frozen Struct honours
  it on msgspec 0.21.1 / Py 3.13.1); `frozen=True` KEPT.
- `Bar.from_row` + the `Decimal(str(...))` D-14 string path unchanged.
- msgspec promoted to `[tool.poetry.dependencies]`; `poetry lock` reflected the promotion
  (groups `["dev"]` -> `["main", "dev"]`) with NO version churn — msgspec stays 0.21.1, already
  in the lock as a transitive dev dep via nautilus-trader (no new package fetched).

### Task 2 — 5 standalone DTOs + matching_engine replace; Position excluded (commit 2500beb)
- `TrailState` (mutable, non-frozen Struct, gc=False), `FillDecision`, `CancelDecision`
  (frozen Structs) in matching_engine.py.
- `Transaction` (transaction.py, mutable Struct): `__post_init__` `to_money` re-assign ports
  directly (a mutable Struct supports `self.x = ...`). msgspec has no per-field `kw_only`, so the
  field order was adjusted — `fill_id` (no default) moved ahead of the defaulted fields so
  msgspec's "defaults come last" ordering rule holds. All construction sites use keyword args, so
  this is behavior-neutral.
- `SignalRecord` (signal_record.py, frozen Struct); `signal_id` uses `msgspec.field` default_factory.
- matching_engine.py:166 `dataclasses.replace(order, ...)` -> `msgspec.structs.replace` (the
  resting-order MODIFY path now holds Struct OrderEvents).
- `Position` STILL `class Position(object)` — exclusion held (D-01).

### Task 3 — mechanical test updates + gate (a) (commit 0648d53)
30 mechanical, zero-behavioral test updates (the spike enumerated ~29; one extra parametrized
case fell out of the same families):
- `FrozenInstanceError` -> `AttributeError`: test_bar.py (1), test_event_immutability.py (8),
  test_bar_event_ohlc.py (2).
- `test_type_is_real_field_with_correct_member`: `"type" in Event.__slots__` -> `"type" not in
  type(event).__struct_fields__` + `type(event).type is expected_type` (type is now a ClassVar
  discriminator, absent from struct fields).
- `test_fill_decision_has_no_fill_quantity`: `dataclasses.fields(FillDecision)` ->
  `FillDecision.__struct_fields__`.
- test_order_manager.py (3): `dataclasses.replace(fill_event, …)` -> `msgspec.structs.replace`.

## Gate (a) — byte-exact correctness

| Check | Result |
|-------|--------|
| `tests/integration/test_backtest_oracle.py` | 3 passed — byte-exact |
| Oracle trade count / final equity | 134 / 46189.87730727451 (unchanged) |
| Determinism double-run | identical (test_oracle_behavioral_identity green) |
| Full suite (`poetry run pytest tests`) | 1340 passed, 0 failed |
| `mypy --strict` | Success: no issues found in 188 source files |
| `grep msgspec.encode/decode itrader/` | CLEAN (construction container only) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Transaction field reorder (no per-field kw_only in msgspec)**
- **Found during:** Task 2
- **Issue:** The dataclass used `field(kw_only=True)` per-field for `fill_id`/`leverage` so the
  defaulted `position_id` could sit between them. `msgspec.field` has no `kw_only` parameter, and
  setting class-level `kw_only=True` would break the positional construction the codebase doesn't
  actually use.
- **Fix:** Moved `fill_id` (no default) ahead of the defaulted fields (`position_id`, `leverage`)
  so msgspec's "defaulted fields last" rule is satisfied without class-level kw_only. All
  construction sites (production + tests) pass these by keyword, so the reorder is behavior-neutral
  — oracle byte-exact confirms.
- **Files modified:** itrader/portfolio_handler/transaction/transaction.py
- **Commit:** 2500beb

### D-02 carve-out (documented, not a deviation)
The 5 standalone DTOs (FillDecision, CancelDecision, TrailState, Transaction, SignalRecord) fire
at ~1,578/run (~4% of the ~69k Bar volume), so their isolated A/B lands in noise. They were
converted under the SAME byte-exact oracle gate for a uniform value-object layer and are NOT
A/B-reverted for showing no isolated delta. Events + Bar are the A/B-attributed headline win
(+3.82% W1 / +6.72% W2@50 from the spike). The fresh msgspec A/B + final cool re-freeze is plan
08-06.

### Other notes
- One extra test case beyond the spike's "~29" count was updated (30 total): the same
  `FrozenInstanceError`/`__slots__`/`replace` families, just one more parametrized instance — all
  behavioral-neutral.
- Docstrings referencing `dataclasses.FrozenInstanceError`, `frozen=True, slots=True`, and
  `dataclasses.replace` were updated to the msgspec equivalents for accuracy (no logic change).

## Known Stubs
None.

## Threat Flags
None — msgspec is a construction container only (no encode/decode), so no new
deserialization-of-untrusted-input surface and no new trust boundary. T-08-09 / T-08-10 / T-08-SC
mitigations held: Decimal contract intact, ClassVar dispatch verified by the oracle, and the
runtime-dep promotion fetched no new package (locked 0.21.1).

## Commits

- eeaf286: perf(08-05) convert Bar + full Event chain to msgspec.Struct; promote msgspec to runtime dep
- 2500beb: perf(08-05) convert 5 standalone DTOs to msgspec.Struct; Position excluded (D-01)
- 0648d53: test(08-05) apply mechanical test updates for msgspec migration (zero behavioral)

## Self-Check: PASSED
- SUMMARY.md present.
- All 3 task commits found in git log (eeaf286, 2500beb, 0648d53).
- STATE.md / ROADMAP.md untouched (orchestrator owns those after the wave).
