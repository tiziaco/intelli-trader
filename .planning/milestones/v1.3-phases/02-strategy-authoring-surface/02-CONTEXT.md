# Phase 2: Strategy Authoring Surface - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

**STRAT-01 — the class-attribute strategy authoring surface.** Replace the frozen-pydantic-config
+ manual-field-copy authoring pattern with **real annotated class-attribute declarations**:
engine-facing names with defaults on the base `Strategy`, alpha knobs as annotated class attrs on
the subclass, **all overridable at construction via `**kwargs`**, with the base **rejecting unknown
kwargs loudly** (`UnknownParamError`) and rejecting missing-required. Ship a **re-runnable
idempotent `init()` lifecycle hook** (the seam Phase 3 IND-01 auto-warmup and Phase 4 COMP-02
`update_config` build on) and a **strategy-level `reconfigure(**kwargs)`** method that replaces the
dropped frozen-config mutation guard (D-03). `generate_signal` still reads real typed instance
attrs (`self.short_window`) — the pure-alpha **D-12** contract is preserved.

**Byte-exact phase.** The reference `SMAMACDStrategy` runs through the new surface byte-exact against
the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`); e2e 58/58; `mypy --strict` clean
(declared params are real annotated attrs mypy sees directly).

**Explicitly NOT in this phase (drawn from the converged design note, kept separate):**
- **IND-01 (Phase 3)** — declared-indicator framework, lazy per-tick recompute, auto-derived
  `warmup`/`max_window`, free-function `crossover`/`crossunder`. In Phase 2 `init()` is an
  empty/no-op overridable hook; SMA_MACD keeps inline indicators in `generate_signal` and
  **hand-set** `max_window`/`warmup` class attrs.
- **COMP-02 (Phase 4)** — handler-level uniform `update_config` on `StrategiesHandler` (and every
  other handler), applied between event cycles / thread-safe. Phase 2 ships only the per-strategy
  `reconfigure` method that COMP-02 will call.
- **SIG-01/02/03 (Phase 5)** — signal-contract completion (per-intent entry price / order_type,
  `Side`-typed action). Untouched here.

</domain>

<decisions>
## Implementation Decisions

### Config-layer fate & blast radius
- **D-01:** **Full delete** of the config layer. Remove `config/strategy.py` (`BaseStrategyConfig`),
  `SMA_MACDConfig` (in `strategies/SMA_MACD_strategy.py`), and `EmptyStrategyConfig` (in
  `strategies/empty_strategy.py`). The class-attribute surface fully replaces them — no dead
  dual-path. Drop the `config/__init__.py` re-export of `BaseStrategyConfig`.
- **D-02:** The base `__init__` signature changes from `(name, config)` to a class-attribute +
  `**kwargs` surface. This is an **all-or-broken** change: every construction site migrates this
  phase (see D-05).
- **D-03:** `to_dict()` and `__str__`/`__repr__` read **real instance attributes**
  (`self.timeframe`, `self.sizing_policy`, `self.order_type`, …) directly — drop all `self.config`
  references. Keep the serialized **shape byte-identical** where it is observed downstream (signal
  store snapshot, any e2e snapshot). `name` and `strategy_id` derivation: Claude's discretion — a
  sensible default `name` (e.g. class name or a `name` class attr) is fine; `strategy_id` still
  minted per construction by `idgen` as today.
- **D-04:** `SignalRecord.config: BaseStrategyConfig` → a **plain params snapshot dict** captured
  from the strategy's declared attrs at decision time (e.g. `strategy.to_dict()` /
  `params_snapshot()`). The `config.model_dump()` read-edge callers become dict accessors. Preserves
  SIG-02 queryability without pydantic. `signal_record.py` field retyped; `test_signal_store.py`
  (`record.config is strategy.config` + `model_dump()`) updated to assert the dict shape.
- **D-05:** **Migrate ALL construction sites this phase, byte-exact** — `SMAMACDStrategy` +
  `EmptyStrategy` (in-scope, mypy-strict), the e2e fixtures `tests/e2e/strategies/scripted_emitter.py`
  + `tests/e2e/strategies/single_market_buy.py`, all unit/integration tests that construct a strategy
  (`tests/unit/strategy/test_strategy.py`, `test_strategy_config.py`, `test_signal_store.py`;
  `tests/integration/test_backtest_smoke.py`, `test_universe_spans.py`, `test_reservation_inertness.py`,
  `test_backtest_oracle.py`), `scripts/run_backtest.py`, and any cross-val script that constructs an
  iTrader strategy. It is a mechanical authoring swap — e2e 58/58 + oracle stay byte-exact. **No
  compatibility shim** (would leave the dual-path the design note wants gone).
  - Note: `test_strategy_config.py` largely tests `BaseStrategyConfig` behavior that is going away —
    rewrite it to test the new class-attribute surface (kwargs override, reject-unknown, required
    detection, coercion) rather than deleting coverage.

### Validation mechanism & cross-field rules
- **D-06:** **Pure-python introspection** — no pydantic. The base inspects its own + subclass
  `__annotations__`/class attrs, applies `**kwargs` overrides, coerces the known enum fields,
  raises `UnknownParamError` on unknown kwargs and on missing-required. Keeps mypy seeing real
  annotated attrs (the design note's mypy-strict requirement; rejects backtrader's synthesized
  `self.p.x`).
- **D-07:** **Bare annotation = required.** A name present in `__annotations__` with **no class-attr
  value** is required (must arrive via `**kwargs` or be pinned by a subclass) — `timeframe`,
  `tickers`, `sizing_policy` on the base. Missing → raise loudly. Subclass alpha knobs carry literal
  defaults (`short_window: int = 50`) and are optional.
- **D-08:** **Enum coercion on the known engine fields**, driven off their annotations:
  `timeframe` str→`Timeframe`, `order_type` str→`OrderType`, `direction` str→`TradingDirection`.
  Subclass int/Decimal knobs are not coerced.
- **D-09:** **Drop** the pydantic `Field(gt=0)` constraints and the `@model_validator` cross-field
  rule, but provide an **optional overridable `validate()` hook** (run after kwargs apply + coerce).
  `SMAMACDStrategy` keeps its `short_window < long_window` assert (HARD-02 loud-rejection behavior)
  **via that hook**, so its current construction-time rejection is preserved.

### init() lifecycle hook (Phase 2 scope)
- **D-10:** Phase 2 introduces `init()` as an **overridable lifecycle hook called at the end of
  construction** (after kwargs applied + validated), **structured to be re-runnable/idempotent** —
  the seam Phase 3 (auto-warmup re-derivation) and Phase 4 (`update_config`) consume. SMA_MACD's
  `init()` is **empty/no-op** for now; indicators stay inline in `generate_signal` and
  `max_window`/`warmup` stay **hand-set class attrs** until Phase 3.
- **D-11:** **Build the re-runnable seam + a light idempotency test** — call `init()` twice and
  assert identical resulting state. Do NOT build the full reconfig pipeline beyond the per-strategy
  method (D-12); just prove the seam is sound so Phase 3/4 can lean on it.

### Reconfigure surface (Phase 2 vs Phase 4 boundary)
- **D-12:** **Ship a strategy-level `reconfigure(**kwargs)` (a.k.a. `update_params`) now:**
  re-apply + coerce kwargs → re-validate (`validate()` hook) → re-run `init()`. This **is** the
  sanctioned-reconfigure discipline that replaces the dropped frozen guard, and it is the unit the
  handler-level COMP-02 `update_config` (Phase 4) will call between event cycles. **Single-strategy
  scope only** — no handler/queue wiring this phase.
- **D-13:** **No runtime mutation guard.** Do not add a `__setattr__` guard against direct
  `self.x = ...` mutation. Rely on the documented "reconfigure via the sanctioned method only"
  discipline (RESEARCH Pitfall 2) + the `reconfigure` method as the blessed path. Mutability is what
  ENABLES runtime reconfig; a hard guard would fight that and add machinery the design note moved
  away from.

### Claude's Discretion
- `name` / `strategy_id` derivation details (D-03) — default `name` source and whether a `name`
  class attr is introduced.
- Exact indicator-handle / snapshot-dict key shape for `to_dict()`/`params_snapshot()` (D-04),
  subject to keeping observed serialized shapes byte-identical.
- Precise `validate()` hook signature/placement (D-09) and how the SMA_MACD `short<long` assert is
  expressed within it.
- Internal structure of the introspection/coercion engine (D-06) as long as it stays mypy-strict
  and byte-exact.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Converged design (authoritative for this phase)
- `.planning/notes/strategy-authoring-surface-999.5c.md` — the `/gsd:explore` converged design for
  STRAT-01 (+ IND-01 refinements). §"Param surface (STRAT-01)" is THE design for this phase;
  §"Runtime reconfiguration constraint" governs D-10/D-12; §"Parked for spec-time" lists what is
  deliberately left to planning. **Read first.**

### Phase source / requirements
- `.planning/REQUIREMENTS.md` — **STRAT-01** (the authoritative requirement, §"Indicator Framework &
  Strategy Authoring"); sequencing rationale (STRAT-01 before COMP-02; IND-01 between).
- `.planning/ROADMAP.md` §"Phase 2: Strategy Authoring Surface" — goal + 4 success criteria (the
  pass/fail contract). Also §"Phase 3" (IND-01) and §"Phase 4" (COMP-02) for the explicit
  out-of-scope boundary.

### Code to migrate / touch (the blast radius — D-05)
- `itrader/strategy_handler/base.py` — the `Strategy` ABC; new class-attribute surface lands here.
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` — reference strategy + `SMA_MACDConfig`
  (to delete); in-scope, mypy-strict, byte-exact gate.
- `itrader/strategy_handler/strategies/empty_strategy.py` — `EmptyStrategy` + `EmptyStrategyConfig`
  (to delete).
- `itrader/config/strategy.py` — `BaseStrategyConfig` (to delete); + `config/__init__.py` re-export.
- `itrader/strategy_handler/strategies_handler.py` — reads `strategy.timeframe/tickers/max_window/
  warmup/order_type/sizing_policy/direction/...` and captures `config=strategy.config` at line ~126
  (D-04 snapshot change lands here); `add_strategy` LONG_ONLY guard stays.
- `itrader/strategy_handler/signal_record.py` — `SignalRecord.config: BaseStrategyConfig` field
  (D-04 retype to snapshot dict).
- `tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/strategies/single_market_buy.py` — e2e
  fixtures to migrate (byte-exact, e2e 58/58).
- `tests/unit/strategy/test_strategy.py`, `test_strategy_config.py`, `test_signal_store.py` — unit
  tests to migrate/rewrite.
- `tests/integration/test_backtest_smoke.py`, `test_universe_spans.py`,
  `test_reservation_inertness.py`, `test_backtest_oracle.py` — integration construction sites.
- `scripts/run_backtest.py` (lines ~48/77/84) — the oracle generator; `scripts/crossval/*` strategy
  builders if they construct iTrader strategies.

### Conventions (must respect)
- `CLAUDE.md` — pure-alpha D-12 contract; **tabs** in `strategy_handler/` modules, **4 spaces** in
  `config/` and `tests/e2e`/`tests/conftest`-aligned files — match the file being edited, never
  normalize (mixed-indentation diff breaks a tab file).
- `.planning/codebase/CONVENTIONS.md` — money policy (`to_money` only Decimal entry), naming.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Strategy.buy()` / `Strategy.sell()` sugar** (`base.py:131-165`) — unchanged; returns
  `SignalIntent`, the pure-alpha return contract. The new surface only changes how params are
  *declared*, not how signals are *returned*.
- **`subscribe_portfolio` / fan-out** (`base.py:167-179`, handler `calculate_signals`) — unchanged;
  the handler owns stamping/policy-attachment/fan-out (the #24 boundary).
- **`core/sizing.py`** — `SizingPolicy`/`FractionOfCash`/`TradingDirection`/`SLTPPolicy` frozen
  dataclasses are the typed values declared as class attrs (`sizing_policy = FractionOfCash("0.95")`).
- **`Timeframe`/`OrderType`/`TradingDirection` enums** (`core/enums`) — the coercion targets (D-08);
  already have case-insensitive `_missing_` parsers from M2-07.

### Established Patterns
- **D-01/D-03 today:** strategy DECLARES via frozen pydantic config; base reads fields onto the
  instance; `generate_signal` reads `self.x`. STRAT-01 keeps the "engine reads declared values onto
  the instance" spirit but the declaration moves to class attributes (no config object, no copy).
- **D-15 warmup short-circuit** lives in the handler (`calculate_signals`, guards on
  `strategy.warmup`). Phase 2 keeps `warmup`/`max_window` as hand-set attrs; auto-derivation is
  Phase 3. The handler short-circuit is untouched.
- **LONG_ONLY registration guard** (`add_strategy`, `base` direction) stays — shorts are N+2.

### Integration Points
- `StrategiesHandler.calculate_signals` reads the strategy's declared attrs and snapshots
  `config` into `SignalRecord` — the one place the D-04 snapshot-dict change surfaces beyond the
  strategy/base files.
- `scripts/run_backtest.py` is the byte-exact oracle generator: its strategy construction must
  produce the identical strategy behavior post-migration.

</code_context>

<specifics>
## Specific Ideas

- The converged design note's worked example is the target authoring shape:
  ```python
  class SMAMACDStrategy(Strategy):
      sizing_policy  = FractionOfCash("0.95")   # pin intrinsic engine-facing values
      direction      = LONG_ONLY
      short_window: int = 50                     # alpha knobs (annotated)
      long_window:  int = 100
      ...
      def init(self): ...                        # empty/no-op in Phase 2
      def generate_signal(self, ticker, bars): ...

  s1 = SMAMACDStrategy(tickers=["BTCUSD"], timeframe="1d")   # deploy-time params via kwargs
  s2 = SMAMACDStrategy(tickers=["ETHUSD"], timeframe="4h", short_window=30)  # tune + redeploy
  ```
- **Reuse model = override-at-construction** (locked in the design note): the same class is
  instantiated many times with different tickers/timeframes/params; each instance is a distinct
  strategy with its own `strategy_id`. Forward-compatible with the Phase 4 composition interface.

</specifics>

<deferred>
## Deferred Ideas

- **Auto-derived `warmup`/`max_window`** from registered indicator recipes → **Phase 3 (IND-01)**.
  Phase 2 keeps them hand-set.
- **Declared-indicator framework, model-B pre-eval reads (`self.short_sma[-1]`), free-function
  `crossover`/`crossunder`** → **Phase 3 (IND-01)**.
- **Handler-level uniform `update_config` on `StrategiesHandler`** (re-validate → re-run `init()` →
  re-derive warmup), applied between event cycles / thread-safe → **Phase 4 (COMP-02)**. Phase 2
  ships only the per-strategy `reconfigure` method it will call.
- **Indicator handle type** (raw pandas Series vs thin positional-index wrapper) → Phase 3 spec-time
  decision (design note "Parked" §1).
- **SMA_MACD full migration onto the indicator framework** (boundary-semantics match for the MACD
  `>=`/`<` trigger vs a textbook `crossover`) → Phase 3 (design note "Parked" §2).
- **Indicator-based SL/TP** consuming the strategy-decoupled indicator recipe → future phase
  (percent-offset SL/TP stays).
- **Stateful/incremental indicator backends** (IND-02) → deferred per REQUIREMENTS Future (W1-05
  incremental half; byte-exactness risk).

None of the above are scope creep — they are explicit downstream-phase work the design note already
separates.

</deferred>

---

*Phase: 2-strategy-authoring-surface*
*Context gathered: 2026-06-12*
