# Phase 4: Composition & Config Interface - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 4-composition-config-interface
**Areas discussed:** Composition API shape & name, Uniform update_config contract, Runtime/live scope, OrderConfig + ExchangeConfig threading, W4 composition-root cleanups

---

## Composition API shape & name

| Option | Description | Selected |
|--------|-------------|----------|
| Declarative spec + factory | Frozen spec consumed by build_system(spec); serializable/web-UI/replay; matches ScenarioSpec | ✓ |
| Declarative spec, multi-exchange now | Same, but exchange as dict[str,ExchangeConfig] from day one | |
| Fluent builder | SystemBuilder().add_strategy(...).build() chain | |
| Extend TradingSystem ctor | Widen __init__ with strategies/portfolios/exchange_config | |

**User's choice:** Declarative spec + factory. Single exchange now; multi-exchange deferred to N+4.
**Notes:** User asked re user-friendliness (recommended declarative spec — serializable, web-UI-friendly), raised production multi-exchange (Alpaca+Binance / Binance+IB → deferred N+4), and confirmed this is effectively the backtest interface (shaped to carry forward to live).

### Sub-decision: class rename
| Option | Description | Selected |
|--------|-------------|----------|
| BacktestTradingSystem | Rename for symmetry with LiveTradingSystem; pure byte-exact rename | ✓ |
| Keep TradingSystem | No rename | |

### Sub-decision: spec/factory name
| Option | Description | Selected |
|--------|-------------|----------|
| SystemSpec + build_backtest_system | Spec mode-agnostic; run-mode in the factory | ✓ |
| CompositionSpec + compose_backtest | Composition framing | |
| BacktestSpec + build_backtest_system | Mode in the spec name (undercuts live reuse) | |

**User's choice:** BacktestTradingSystem + SystemSpec (mode-agnostic) + build_backtest_system.
**Notes:** User flagged the TradingSystem/LiveTradingSystem asymmetry themselves.

---

## Uniform update_config contract

| Option | Description | Selected |
|--------|-------------|----------|
| dict arg | update_config(updates: dict) — maps to queued command / web-UI JSON; nested sub-model updates | ✓ |
| **kwargs | Matches 2 of 3 existing; awkward for nested | |

### Sub-decision: error contract
| Option | Description | Selected |
|--------|-------------|----------|
| Reuse ConfigurationError | Raise existing core ConfigurationError; wrap pydantic ValidationError; extra='forbid' | ✓ |
| New ConfigUpdateError subtype | Runtime-reconfig-specific; deferred | |
| Return bool | Keep PortfolioHandler's bool | |

### Sub-decision: uniformity meaning
| Option | Description | Selected |
|--------|-------------|----------|
| Uniform contract, per-handler internals | Same signature/contract; config-model vs init()-rerun vs feed internals | ✓ |
| Config model for every handler | StrategiesHandlerConfig + FeedConfig forcing literal model_validate | |

### Sub-decision: BacktestBarFeed
| Option | Description | Selected |
|--------|-------------|----------|
| Interface-conformance, reject unsupported | Exposes signature; raises for base_timeframe (replace, not hot-swap) | ✓ |
| Fully reconfigurable base_timeframe | Wire re-resample/grid | |

**User's choice:** dict arg; reuse ConfigurationError (wrap pydantic); uniform contract / per-handler internals; BacktestBarFeed interface-conformance.
**Notes:** User asked whether to use a custom exception — answered reuse the existing ConfigurationError (structured fields map to HTTP error body; web layer catches one type).

---

## Runtime/live scope

| Option | Description | Selected |
|--------|-------------|----------|
| update_config methods only; defer transport to N+4 | Methods + atomic-swap primitive; defer TradingInterface bridge + direct-vs-queued | ✓ |
| Also wire ReconfigureEvent through the queue now | New event type + route + run-loop application point | |
| Full live path incl. TradingInterface enqueue | End-to-end web-UI → enqueue → cross-thread apply | |

**User's choice:** update_config methods only; defer transport to N+4.
**Notes:** User questioned why a reconfigure would pass through an event vs a direct API → TradingInterface → handler call. Clarified: the event path is one way to enforce between-cycles thread-safety on the live daemon thread, but the chosen atomic-swap (GIL-atomic reference assign) already makes direct calls object-safe; the direct-vs-queued transport decision belongs to N+4 (live threading model). User's direct-call instinct affirmed as a valid live shape.

---

## OrderConfig + ExchangeConfig threading

| Option | Description | Selected |
|--------|-------------|----------|
| Thin OrderConfig; estimator stays injected dep | market_execution as system default; commission_estimator injected | ✓ |
| Broader OrderConfig (fold the estimator) | Callable into the model (breaks model_validate) | |

### Sub-decision: supported symbols
| Option | Description | Selected |
|--------|-------------|----------|
| SystemSpec drives symbols at construction | Spec tickers → config.limits.supported_symbols; kill hardcoded BTCUSD + conftest loop | ✓ |
| Keep additive register_symbol seam | Lowest risk; keeps post-construction step + hardcoded BTCUSD | |

**User's choice:** Thin OrderConfig (market_execution default; estimator stays injected); SystemSpec drives symbols at construction (kill hardcoded BTCUSD).
**Notes:** User observed execution should depend on the strategy/signal — clarified that per-intent order_type/entry-price is owner-gated Phase 5 (SIG-01/02), distinct from market_execution (fill-timing). Per-signal market_execution captured as a deferred idea. User explicitly disliked the hardcoded register_symbol — wants symbols registered from the SystemSpec (= chosen option).

---

## W4 composition-root cleanups

### W4-06 (rng_seed / 2nd SystemConfig)
| Option | Description | Selected |
|--------|-------------|----------|
| Keep run-wide; source from singleton, don't dup | rng_seed in SystemConfig.performance; read the config singleton | ✓ |
| Keep run-wide; thread SystemConfig via composition | Explicit injection of the mostly-future config | |
| Move rng_seed into ExchangeConfig | Consumer-owns-it; mis-models determinism | |

**Notes:** User questioned why SystemConfig exists when only rng_seed is used — confirmed ~95% is future-live scaffolding; pruning SystemConfig deferred to N+4. rng_seed kept run-wide per D-11.

### W4-05 (BarFeed ABC home)
| Option | Description | Selected |
|--------|-------------|----------|
| Keep in price_handler/feed/ | Price-domain abstraction; no cross-domain pull | ✓ |
| Move BarFeed ABC to core/ | Consistency with PortfolioReadModel | |

### W4-02/03/07 (root decomposition)
| Option | Description | Selected |
|--------|-------------|----------|
| Extract now; design-for-live, defer live refactor | compose_engine + BacktestRunner + reporting; don't touch LiveTradingSystem | ✓ |
| Full extraction incl. refactoring LiveTradingSystem now | Touches live unverified by byte-exact suite | |
| Minimal cleanup only | Keep root largely intact | |

**Notes:** User wants backtest_trading_system.py cleaned (does too many things) and shared with live. Clarified the clean seam (compose_engine wiring) vs the mode-specific run driver (sync for-loop vs daemon thread); defer the live refactor (no byte-exact coverage) to a fast-follow.

### Construction pattern (curiosity → decision)
| Option | Description | Selected |
|--------|-------------|----------|
| Factory builds, class is a thin holder | build_backtest_system → compose_engine + runner → thin holder | ✓ |
| Class takes the spec, delegates internally | __init__(spec) calls compose_engine | |
| Leave to the planner | | |

**Notes:** User asked whether TradingSystem.__init__ is gone or replaced by SystemSpec — clarified: partially replaced + slimmed (params→spec, wiring→compose_engine, thin shell). Chose the factory/thin-holder pattern.

### Commission estimator seam
| Option | Description | Selected |
|--------|-------------|----------|
| CommissionEstimator Protocol in core/ | Typed read-model seam mirroring PortfolioReadModel; byte-exact | ✓ |
| Named factory function only | Untyped Callable, out of __init__ | |
| Leave exact shape to planner | | |

**Notes:** User disliked the inline _estimate_commission closure in __init__ and asked for the cleanest/architecturally-correct option even if more refactoring/risky. Answered: promote to a typed CommissionEstimator Protocol read-model seam (mirrors the codebase's PortfolioReadModel) — and it happens to be byte-exact-safe (structure/typing change, fees pinned 0 in golden). Preserve late binding (adapter holds exchange ref, reads fee_model in __call__).

---

## Claude's Discretion

- Exact SystemSpec field names / where portfolio↔strategy subscription is declared (spec vs factory).
- Internal deep-merge + atomic-swap mechanics per handler.
- compose_engine signature/return; how BacktestRunner receives the engine.
- Module home for the FeeModelCommissionEstimator adapter.
- How csv_paths/symbol derivation is surfaced (spec field vs factory derivation).

## Deferred Ideas

- Live runtime-config transport (TradingInterface bridge + direct-vs-queued ReconfigureEvent) → N+4.
- LiveTradingSystem adopts compose_engine → immediate fast-follow (out of byte-exact gate).
- Multi-exchange composition (dict[str, ExchangeConfig], venue-named) → N+4.
- Per-signal market_execution (fill-timing) override → future signal-contract phase (beyond SIG-02).
- Prune SystemConfig to live-essentials → N+4.
- ConfigUpdateError(ConfigurationError) subtype → only if runtime-reconfig needs a distinct HTTP code.
