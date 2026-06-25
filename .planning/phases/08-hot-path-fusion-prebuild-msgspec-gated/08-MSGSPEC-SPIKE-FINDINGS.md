# Phase 8 — msgspec.Struct Spike Findings (Req 6, DECISION-GATED)

**Date:** 2026-06-25
**Spike branch:** `spike/msgspec-events` (off `v1.5/phase-8-hot-path-improvments`) — **discarded**; only this doc kept.
**Resolves:** 08-SPEC.md Requirement 6 — "msgspec.Struct migration — DECISION-GATED".
**msgspec:** 0.21.1 (already present, dev-only transitive via nautilus-trader; no `pyproject.toml` change for the spike).

## TL;DR — DECISION: **DEFER**

| Gate | Threshold | Measured (position-averaged A/B) | Verdict |
|------|-----------|----------------------------------|---------|
| **W1 wall-clock (THE gate)** | **≥ 5%** | **+3.82% faster** | ❌ below → **DEFER** |
| W2 @ 50 symbols (corroboration only) | — | +6.72% faster | ✅ but not the gate metric |

The msgspec conversion is **correct, mypy-clean, and a genuine, consistently-measurable win** — but on the
W1 workload (4 symbols / 6 portfolios) it lands at **3.82%**, short of the **≥5% W1** bar that Req 6 requires
to fold the migration into Phase 8. Per the SPEC's keep-only-measured / gate-(b) discipline → **DEFER to a
follow-up phase.** `pyproject.toml` runtime deps stay unchanged; msgspec stays dev-only.

The win is real and **scales with symbol count** (6.72% at 50 symbols), so the deferred migration is a strong
follow-up candidate — see Recommendation.

---

## What was converted

Entire `Event` hierarchy + the `Bar` value object → `msgspec.Struct(frozen=True, kw_only=True, gc=False)`:

- `itrader/core/bar.py` — `Bar`
- `itrader/events_handler/events/base.py` — `Event` (base)
- `.../events/market.py` — `TimeEvent`, `BarEvent`, `PortfolioUpdateEvent`, `ScreenerEvent`
- `.../events/signal.py` — `SignalEvent`
- `.../events/order.py` — `OrderEvent`
- `.../events/fill.py` — `FillEvent`
- `.../events/error.py` — `ErrorEvent`, `PortfolioErrorEvent`

(msgspec forbids mixing Struct and non-Struct in one inheritance chain — once `Event` is a Struct all
subclasses must be, so all events convert together. This was the maximal-signal scope for the A/B.)

### Migration map applied
- **Type tag:** `type: EventType = field(default=EventType.X, init=False)` → `type: ClassVar[EventType] = EventType.X`.
  `EventHandler._dispatch` reads `event.type` via `self.routes[event.type]` — works unchanged (a ClassVar
  read resolves to the class constant). Dispatch verified live (oracle green).
- **event_id factory:** `field(default_factory=uuid_compat.uuid7)` → `msgspec.field(default_factory=uuid_compat.uuid7)`.
- **`dataclasses.replace` → `msgspec.structs.replace`** at `execution_handler/matching_engine.py:166` (the
  resting-order MODIFY path; `_resting` holds `OrderEvent`s). Engine-side fix landed.
- **`reporting/frames.py:75` `dataclasses.asdict`** — target is `PortfolioSnapshot` (NOT a migrated type),
  off the hot path. **Left untouched** (correctly out of scope).

### The `created_at` / frozen wrinkle — **frozen was KEPT, not dropped**
Base `Event.__post_init__` defaults `created_at` to `time` via `object.__setattr__` on a frozen instance.
Empirically (msgspec 0.21.1 / Py 3.13.1) a **frozen `msgspec.Struct` honours `object.__setattr__` inside
`__post_init__`** — so the idiom ports verbatim and **`frozen=True` was retained** for the spike (more
representative than dropping it; construction speed, the thing measured, is frozen-independent anyway).
No other subclass has a `__post_init__` normalizer (the SPEC's "e.g. OrderEvent" note was conservative —
OrderEvent has none). **Production migration needs no special frozen handling.**

### `gc=False`
Applied to every Struct (`Bar` + all events are reference-cycle-free). No correctness issue; kept on for the
construction-speed measurement. (Contained containers like `BarEvent.bars` dict are independently
GC-tracked; only the struct instance is untracked — safe here.)

### Friction worth flagging for the real migration
- **`TrailType` forward-ref was a non-issue.** `OrderEvent.trail_type: "TrailType | None"` (a TYPE_CHECKING-only
  string forward-ref) did **not** need resolving — msgspec doesn't eagerly evaluate annotations for plain
  construction (we never `msgspec.encode` these). No import change required.
- **`mypy --strict` stayed clean** with `ClassVar[EventType]` tags + `msgspec.Struct` bases (188 files, 0 issues).
- **29 test failures, ALL test-mechanics, ZERO behavioral** (see Gate A). Each has a known one-line fix; the
  real migration must update these tests:
  - frozen tests asserting `pytest.raises(dataclasses.FrozenInstanceError)` → msgspec raises `AttributeError`
    (still frozen, different exception type) — `tests/unit/core/test_bar.py`, `tests/unit/events/test_event_immutability.py`,
    `tests/unit/events/test_bar_event_ohlc.py`.
  - `test_type_is_real_field_with_correct_member` asserts `"type" in Event.__slots__` — `type` is now a
    ClassVar by design; the assertion checks a dataclass impl detail.
  - `tests/unit/order/test_order_manager.py` (×3) test helpers call `dataclasses.replace(fill_event, …)` →
    need `msgspec.structs.replace`.

---

## Gate A — correctness (byte-exact first)

| Check | Result |
|-------|--------|
| `tests/integration/test_backtest_oracle.py` | **3 passed** — byte-exact |
| Oracle trade count / final equity | **134 trades / `46189.87730727451`** (unchanged) |
| Determinism double-run | **identical** — `test_oracle_behavioral_identity` asserts a fresh run == golden artifacts (trades, equity grid, summary) with **zero tolerance**; green. (Diff touches object construction only — no RNG seed / clock / ordering change.) |
| `mypy --strict` (`itrader`) | **Success: no issues found in 188 source files** |
| Full suite (`poetry run pytest tests`) | **1266 passed, 29 failed** — all 29 are test-mechanics friction (enumerated above), **no engine/numeric regression** |

Gate A: **PASS** (semantically). The 29 failures are assertions about the *old dataclass mechanics*
(exception identity, field-vs-ClassVar, `replace` API), not behavior.

---

## Gate B — same-machine A/B (thermal-aware)

**Method (per `v15-perf-gateb-thermal-drift` lesson):** box verified cool (`pmset -g therm`: no thermal/perf
warnings, before and during). BASE (`v1.5/phase-8-hot-path-improvments`, dataclass) vs OPT
(`spike/msgspec-events`, msgspec) alternated in a **position-balanced 8-run sequence**
(`OPT BASE BASE OPT OPT BASE BASE OPT`) so each variant has mean run-position 4.5 — cancels monotonic
thermal drift and within-pair position bias. Fresh interpreter per run (editable `.venv` picks up the
checked-out source). One discarded warmup. **Wall-clocks are higher in absolute terms than the 19.6s frozen
W1 baseline** (warmer session) — irrelevant: only the same-session OPT-vs-BASE delta is trusted, never the
frozen-baseline compare.

### W1 (`run_w1_benchmark`, 4 sym / 6 pf / 2-month 5m) — THE GATE

| run | variant | wall_clock_s |
|-----|---------|--------------|
| 1 | OPT  | 24.893 |
| 2 | BASE | 26.552 |
| 3 | BASE | 25.886 |
| 4 | OPT  | 25.153 |
| 5 | OPT  | 25.034 |
| 6 | BASE | 25.955 |
| 7 | BASE | 26.449 |
| 8 | OPT  | 25.760 |

- **OPT mean = 25.210s** (4 runs) · **BASE mean = 26.211s** (4 runs)
- **Δ = +3.82% faster (OPT)** · clean separation: **max OPT 25.760 < min BASE 25.886** (every OPT run beats
  every BASE run — consistent signal, not noise).
- **3.82% < 5% → gate not met.**

### W2 @ 50 symbols (`run_w2_sweep`, scaling axis — corroboration)

| run | variant | wall_clock_s @ 50 |
|-----|---------|-------------------|
| 1 | OPT  | 5.732 |
| 2 | BASE | 6.147 |
| 3 | BASE | 5.847 |
| 4 | OPT  | 5.622 |
| 5 | OPT  | 5.591 |
| 6 | BASE | 5.907 |
| 7 | BASE | 6.221 |
| 8 | OPT  | 5.557 |

- **OPT mean = 5.626s** · **BASE mean = 6.031s**
- **Δ = +6.72% faster (OPT)** · again all OPT < all BASE (max OPT 5.732 < min BASE 5.847).
- The construction win **amplifies with symbol count** (more `Bar`/`BarEvent` built per tick) — 3.82% at
  4 symbols → 6.72% at 50.

### Scalene corroboration (single profile on OPT, mechanism check)

| | BASE (committed `scalene-w1.json`) | OPT (msgspec) |
|---|---|---|
| `<exec@dataclasses.py:498>` construction CPU share | **13.32%** | **6.31%** |
| `msgspec` CPU share | — | **0.00%** |

Construction frame **roughly halved** (−7.0 pp). msgspec's per-object construction is compiled C →
invisible to Scalene's Python-line attribution (the per-field `object.__setattr__` Python loop is *gone* —
which is exactly why it's faster). Residual 6.31% = the **other** hot-path dataclasses NOT in scope (Position,
TrailState/FillDecision/CancelDecision, transactions, signal_record). This explains the modest W1 wall-clock
delta: events+Bar are ~half the dataclass-construction cost, and that cost is itself diluted by
non-construction work (position math, csv load, logging). A ~7pp CPU reduction → ~3.8% wall-clock is
consistent. (Scalene perturbs absolute shares — e.g. `logger.py` inflated — but the BASE→OPT directional
drop is the signal.)

---

## Decision (SPEC Req 6 gate)

> "ships in Phase 8 IFF it clears **≥5% W1 wall-clock** AND msgspec is promoted to a runtime dependency."

W1 = **+3.82% < 5%** → **DEFER.** No msgspec on the shipped runtime path; `pyproject.toml` runtime deps
unchanged. Spike code discarded; this doc is the recorded delta + recommendation.

## Recommendation for the follow-up

**Worth doing as a dedicated phase**, for these reasons:
1. The win is **real, consistent, and directionally confirmed** by Scalene (construction frame halved) — not
   run-to-run noise (perfect OPT/BASE separation on both W1 and W2).
2. It **scales with symbol count** (3.82% → 6.72% from 4 → 50 symbols). If the production/target universe is
   larger than W1's 4 symbols, msgspec clears 5% comfortably. The W1 gate is conservative *for this specific
   small workload*.
3. **Friction is low:** frozen ports cleanly (no created_at rework), mypy-strict stays clean, only one engine
   call (`matching_engine.py` replace) + ~29 test assertions need updating — all mechanical, all enumerated.
4. **Bigger prize if combined:** converting the *other* hot-path dataclasses (Position, transactions, the
   matching-engine decision structs) in the same migration would attack the residual 6.31% construction frame
   too — the events+Bar slice alone only reaches half of the 13.3% pool.

**Suggested trigger:** fold msgspec in when either (a) a future phase already touches the event/Bar layer, or
(b) the target universe grows past ~10 symbols (where the W1-equivalent crosses 5%), and do it as a
*whole-hot-path* dataclass→Struct migration (events + Bar + Position + matching structs) to capture the full
~13% rather than the ~7% this spike isolated. Promote msgspec to a runtime dep at that point.

---

*Spike executed 2026-06-25. Code on `spike/msgspec-events` discarded after measurement; this findings doc is
the only artifact retained.*
