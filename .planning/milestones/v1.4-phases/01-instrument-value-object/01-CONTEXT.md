# Phase 1: Instrument Value Object - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Land a frozen, per-symbol `Instrument` value object as the single source of price
precision, quantity precision, `min_order_size`, and the margin/funding params
(`maintenance_margin_rate`, `max_leverage`, `settles_funding`) that the later
margin/leverage/short/liquidation phases consume. It replaces the hard-coded
`_INSTRUMENT_SCALES` table in `core/money.py`.

**Byte-exact gate (this phase re-baselines NOTHING):** the SMA_MACD spot oracle
(134 trades / `final_equity 46189.87730727451`) must hold byte-for-byte. `BTCUSD`
always takes the **declared 8dp** branch — inference must never touch it.

In scope: `Instrument` value object, symbol→`Instrument` resolution via the
universe, the `quantize()` rewire, declared→inferred→default precision ladder,
`ExchangeLimits` demotion to venue fallback. Margin *accounting*, shorts,
liquidation, leverage, trailing stops are LATER phases — Phase 1 only lands the
fields they will read.
</domain>

<decisions>
## Implementation Decisions

### `min_order_size` ownership (INST-01 / INST-03)
- **D-01:** `Instrument` is the source of truth for `min_order_size`;
  `ExchangeLimits.min_order_size` is demoted to a **venue-level fallback for
  undeclared symbols** (follows the authoritative REQUIREMENTS over the older
  design note, which had kept it in `ExchangeLimits`).
- **D-01a (byte-exact tactic):** `BTCUSD` leaves `min_order_size` **undeclared**
  on its `Instrument` so `SimulatedExchange` resolution falls through
  `Instrument(None) → ExchangeLimits(0.001)` — the value it reads today
  (`config.limits.min_order_size`) — keeping the oracle byte-exact. `SimulatedExchange`
  currently reads `self.config.limits.min_order_size`; it must be taught the
  Instrument-first → ExchangeLimits-fallback resolution order.

### Behavioral gate — `quantize()` rewire (INST-01)
- **D-02:** **Rewire `quantize()` now** to resolve precision from the `Instrument`
  (Instrument-driven), and **delete `_INSTRUMENT_SCALES`**. INST-01 is fully met,
  no dead value object is left behind.
- **D-02a:** Blast radius is low because `core/money.py::quantize()` is **only
  called from tests today** (production money boundaries round via inline
  `.quantize(Decimal('0.01'))` in `cash_manager` etc.). So the rewire updates test
  call sites + deletes the table; the production rounding path is unaffected. The
  byte-exact gate holds because `BTCUSD`'s declared-8dp scales are byte-identical
  to the deleted table entry.

### Registry seam — the Universe is the home (INST-03; supersedes "InstrumentRegistry")
- **D-03:** **No separate `InstrumentRegistry` subsystem, and no state in
  `money.py`.** A standalone registry would be a parallel source of truth for the
  same symbol set the universe already owns (D-20/D-21: *"the multi-strategy union
  IS the membership"*). The **universe is the single home** for symbol→`Instrument`
  resolution.
- **D-04:** The `Instrument` **type** lives in `core/instrument.py` (frozen value
  object, mirrors `core/bar.py::Bar`, depends on nothing inside `itrader`).
- **D-05:** `core/money.py::quantize()` stays a **pure, stateless function taking
  an `Instrument`** (`quantize(value, instrument, kind)`) — it reads the scale off
  the Instrument it is handed, never looks anything up. money.py owns zero domain
  state. (`Instrument` is an intra-`core` import — allowed.)
- **D-06:** Introduce a **`Universe` class** as the cohesive, injectable read-model
  (object-shaped, matching `PortfolioReadModel` / `BacktestBarFeed`; aligns with the
  D-20 `UniverseSelectionModel` growth target). It is the per-tick poll-able seam:
  `.members`, `.instrument(symbol) -> Instrument`, optionally `.is_active(symbol, asof)`.
- **D-07 (composition, NOT rewrite):** `Universe` is a **thin façade that composes
  the existing pure functions** — `derive_membership` and `is_active` stay as pure
  helpers (they carry locked decisions M5-08/D-20/D-03) and the class **delegates**
  to them. `.members` returns the **same `list[str]`** today's wiring consumes, so
  `feed.bind` → ping-grid → precompute (Trap-4 ordering in `backtest_runner.py`) is
  untouched and byte-exact. A new pure `derive_instruments(...)` sibling builds the
  symbol→`Instrument` map. **Scope discipline:** build the façade + instrument map
  only — NOT the full dynamic `UniverseSelectionModel`.
- **D-08:** The `Universe` instance is **constructed once at wiring** (in
  `backtest_runner.py` / the live runner, where `derive_membership` runs today) from
  strategies + screeners + declared instrument config + price data, then **injected
  as a read-model** into the components that round / (later) margin.

### Inference guard & defaults (INST-02)
- **D-09:** Price-precision ladder is **declared → inferred (guarded) → default**:
  - *inferred:* read the CSV price column as a **string**, count decimal places,
    **capped at 8dp** (crypto max, DOGE-safe; fixes the catastrophic flat-`0.01`
    default for real symbols).
  - *default:* keep `_DEFAULT_SCALES` price = `0.01` as the final fallback **only
    when there is no data**.
- **D-10:** `quantity_precision` and `min_order_size` are **declared-or-default**
  (not inferable from OHLCV). `BTCUSD` always takes the **declared 8dp** branch for
  price (inference would yield ~2–4dp and drift the golden master).

### Claude's Discretion
- Exact `derive_instruments(...)` signature/placement within `itrader/universe/`,
  and whether `is_active`/spans fold into the `Universe` class now or stay
  standalone (cheap-to-fold → fold; otherwise defer) — planner's call, kept
  byte-exact.
- Precise resolution-order plumbing in `SimulatedExchange` for the
  Instrument→ExchangeLimits `min_order_size` fallback.
- The exact `kind → precision-field` mapping inside `quantize` (price/quantity/cash;
  cash from `quote_currency`, default `"USD"` → 2dp).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone discipline
- `.planning/REQUIREMENTS.md` — INST-01/02/03 (the locked Phase 1 requirements);
  also the milestone owner-gated/byte-exact discipline.
- `.planning/ROADMAP.md` — v1.4 Phase 1 entry + the "byte-exact phase" milestone gate.
- `.planning/STATE.md` — "Milestone Gate (v1.4)" → the **Byte-exact phase (Phase 1)**
  block: oracle 134 trades / `46189.87730727451`, BTCUSD-always-declared-8dp gate.

### Design source
- `.planning/notes/margin-leverage-shorts-999.4.md` §6 (item 1 — `Instrument`
  value object design: fields, layered precision, ExchangeLimits reconciliation,
  behavioral gate) and §4 (spot-margin vs perp field comparison).

### Code to change / mirror
- `itrader/core/money.py` — `quantize()` (rewire to take `Instrument`),
  `_INSTRUMENT_SCALES` / `_DEFAULT_SCALES` (delete the per-instrument table; keep
  the default fallback). NOTE: `quantize()` is currently only called from tests.
- `itrader/core/bar.py` — shape reference for the new frozen `core/instrument.py`.
- `itrader/universe/membership.py` — `derive_membership` / `is_active` (the pure
  helpers the new `Universe` class composes; locked decisions M5-08/D-20/D-21/D-03).
- `itrader/trading_system/backtest_runner.py` — the wiring point (membership derive
  → `feed.bind` → ping-grid → precompute; **Trap-4 ordering** must stay intact);
  also `live_trading_system.py` for the live wiring path.
- `itrader/config/exchange.py` — `ExchangeLimits` (`min_order_size`, demoted to
  venue fallback).
- `itrader/execution_handler/exchanges/simulated.py` — reads
  `config.limits.min_order_size` today (`self._min_order_size`); must learn
  Instrument-first → ExchangeLimits-fallback resolution.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/bar.py::Bar` — the frozen value-object template `core/instrument.py` mirrors.
- `itrader/universe/derive_membership` + `is_active` — pure functions the `Universe`
  façade composes (do NOT reimplement their logic).
- `PortfolioReadModel` / `BacktestBarFeed` — the injected read-model seam pattern the
  `Universe` class follows.

### Established Patterns
- **core depends on nothing inside itrader** — `Instrument` lives in `core/`;
  `quantize` imports it intra-core; the registry/resolution lives OUTSIDE core (in
  `universe/`), keeping money.py pure and stateless.
- **Derive-once-at-wiring purity** — membership (and now the instrument map) is
  derived data built at wiring, never event plumbing.
- **Trap-4 ordering** in `backtest_runner.py` (membership derive → feed.bind →
  ping-grid → precompute) is ordering-sensitive — preserve it.

### Integration Points
- Wiring (`backtest_runner.py` / `live_trading_system.py`): construct the `Universe`
  read-model where `derive_membership` runs today; inject it.
- `SimulatedExchange`: min_order_size resolution.
- `core/money.py::quantize` callers (tests today; margin/position code in later phases).

</code_context>

<specifics>
## Specific Ideas

- The user explicitly rejected putting an instrument registry inside `money.py`
  ("money.py's job is the rounding mechanism, not domain state") and rejected a
  standalone `InstrumentRegistry` in favor of upgrading the **existing universe**
  — and chose to introduce a proper **`Universe` class** as the read-model, built
  by **composition** over the existing pure functions (not a rewrite of them).

</specifics>

<deferred>
## Deferred Ideas

- **Full dynamic `UniverseSelectionModel`** (per-tick add/remove membership, the
  D-20 growth target) — the `Universe` class lands as a façade now; the dynamic
  selection model is its own future milestone. Phase 1 builds façade + instrument
  map only.
- **Margin / leverage accounting, shorts, borrow carry, liquidation, trailing
  stops** — Phases 2–5; Phase 1 only lands the `Instrument` fields they read.
- **`settles_funding`** lands as an inert field now (Phase B / perp realism, deferred
  per REQUIREMENTS Future Requirements).

None outside phase scope were raised.

</deferred>

---

*Phase: 1-Instrument Value Object*
*Context gathered: 2026-06-15*
