# Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-07
**Phase:** 7-m5b-sizing-policy-metrics-universe-coverage
**Areas discussed:** Sizing policy design, Risk admission rules, Reporting & metrics, Universe stub & coverage, SL/TP policy (user-raised)

---

## Sizing policy design

| Option | Description | Selected |
|--------|-------------|----------|
| Typed policy + engine resolver | Frozen SizingPolicy on signal, one resolver in order layer (LEAN shape) | ✓ |
| Sizer objects in order layer | backtrader-style per-strategy Sizer registry | |
| Keep dict, just wire it | Minimal: read strategy_setting in _resolve_signal_quantity | |

**User's choice:** Typed policy + engine resolver
**Notes:** User liked option 1 but also option 2's flexibility; asked for institutional standards. Walked through LEAN Insight→PortfolioConstruction, Nautilus, Zipline, FIX/OMS desks — concluded the institutional hybrid is typed data + engine-owned pluggable resolver; registry can layer on later behind the same seam.

| Option | Description | Selected |
|--------|-------------|----------|
| Fraction + fixed | Smallest provable vocabulary | |
| Fraction + fixed + risk-% | Adds Van Tharp RiskPercent, oracle-dark | ✓ |
| Full DynamicSizer semantics | Also port slot-splitting allocation | |

**User's choice:** Fraction + fixed + risk-%

| Option | Description | Selected |
|--------|-------------|----------|
| Declare 0.95 — inert | Golden declares today's hardcode; refactor byte-exact gated | ✓ |
| Declare 0.80 — re-freeze | Adopt documented default, burn a re-freeze | |
| Two-step | Inert first, decide config later | |

**User's choice:** Declare 0.95 — inert

| Option | Description | Selected |
|--------|-------------|----------|
| Delete all three | position_sizer/, risk_manager/, sltp_models/ die; rewritten clean in order_handler/ | ✓ |
| Re-home into order_handler | git mv + refactor in place | |
| Keep sltp_models, delete rest | Keep dead indicator helpers for future | |

**User's choice:** Delete all three, new files in order_handler/
**Notes:** User asked for the concrete post-deletion structure (what survives in strategy_handler, where policy types/resolver live) before confirming.

| Option | Description | Selected |
|--------|-------------|----------|
| No — full precision, defer | Keep never-round quantities; Instrument model later | |
| Optional policy param, off for golden | step_size: Decimal \| None, ROUND_DOWN, None for golden | ✓ |
| Yes — round to 8dp now | Global crypto quantum, forces re-freeze | |

**User's choice:** Optional step_size param, off for golden

| Option | Description | Selected |
|--------|-------------|----------|
| Reject loudly, audited | Typed failure → audited REJECTED with policy-violation reason | ✓ |
| Fallback to FractionOfCash | Silent fallback on missing stop | |
| Raise at construction | Static validation only | |

**User's choice:** Reject loudly, audited

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — exit_fraction, default 1.0 | Declarative partial exits, golden inert, remainder rule | ✓ |
| Full-close only, defer | Partials only via explicit quantity | |

**User's choice:** exit_fraction, default 1.0
**Notes:** User asked twice whether partial exits already work — confirmed the explicit-quantity path (order_manager.py:583, TradingInterface) exists and survives unchanged; the question was only about unsized signal exits. User then asked if policy-driven partials are simple — yes (~20 lines + remainder rule + bracket caveat) — and chose to include them.

---

## Risk admission rules

| Option | Description | Selected |
|--------|-------------|----------|
| Per-strategy direction | TradingDirection enum enforced at admission; LONG_SHORT reserved until margin milestone; result-changing re-freeze | ✓ |
| Margin reservation, no liquidation | Phase 5 reservation API for shorts; doesn't fix DEF-01-C | |
| Keep shorts, document — inert | DEF-01-C stays a documented hole | |

**User's choice:** Per-strategy direction
**Notes:** User confirmed the engine currently allows (accidental) shorts — golden has 2 blessed SHORT trades. Asked whether margin is simple: walked through reservation-only (simple but doesn't fix DEF-01-C, result-changing anyway) vs full maintenance+liquidation (new BAR-path mechanic, not simple) → margin deferred to its own milestone. User asked how a future long+short strategy would declare itself → per-strategy TradingDirection enum, enforcement at admission, LONG_SHORT rejected at registration until margin exists.

| Option | Description | Selected |
|--------|-------------|----------|
| False — reject increases | SMA_MACD keeps declared False, now enforced; result change folds into re-freeze | ✓ |
| True — preserve blessed behavior | Enshrine accidental micro-increases | |
| Don't enforce — document only | Flag stays dormant | |

**User's choice:** False — reject increases
**Notes:** User asked how per-strategy increase permissions work and confirmed strategies keep emitting duplicate signals (portfolio-blind by design) — filtering is the admission gate's job per portfolio.

| Option | Description | Selected |
|--------|-------------|----------|
| Two named re-freezes | Direction first, increases second, each owner-gated | ✓ |
| One combined re-freeze | Single diff note covering both | |
| Planner decides | Sequencing discretion | |

**User's choice:** Two named re-freezes

| Option | Description | Selected |
|--------|-------------|----------|
| Return-typed intent | generate_signal -> SignalIntent \| None; handler owns events/fan-out | ✓ |
| Keep emit-style, declare done | ABC signature enforcement is enough | |

**User's choice:** Return-typed intent
**Notes:** User asked whether to rename calculate_signal. Presented generate_signal / on_bars / keep — chose **generate_signal**.

---

## Reporting & metrics

| Option | Description | Selected |
|--------|-------------|----------|
| Pure functions on run artifacts | Metrics consume equity+trades frames; no handler imports; SQL dies | ✓ |
| Fix StatisticsReporting in place | Keep facade, fix math | |

**User's choice:** Pure functions on run artifacts

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — into summary.json | Frozen metrics reference for Phase 8 | ✓ |
| Separate frozen metrics.json | Sibling artifact | |
| Compute on demand, don't freeze | No oracle coupling | |

**User's choice:** Metrics freeze into summary.json

| Option | Description | Selected |
|--------|-------------|----------|
| Fix minimal set, optional module | Equity/drawdown/P-L charts, smoke-tested | ✓ |
| Delete charts entirely | Plots die like EngineLogger | |
| Quarantine as-is | D-sql treatment | |

**User's choice:** Fix minimal set

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — column in trades.csv | Slippage attribution frozen, rides re-freezes | ✓ |
| Reporting-computed only | Not regression-locked | |

**User's choice:** Slippage column in trades.csv

| Option | Description | Selected |
|--------|-------------|----------|
| Implement rolling Sharpe | One pure function, unit-tested | ✓ |
| Delete the stub | Resolve by removal | |

**User's choice:** Implement rolling Sharpe

| Option | Description | Selected |
|--------|-------------|----------|
| Industry-standard, rf=0, 365d | Definitions matched to Phase 8 reference engines | ✓ |
| Keep current formulas, fix crashes only | Continuity with old outputs | |

**User's choice:** Industry-standard definitions

---

## Universe stub & coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Into the BarFeed | Feed owns BarEvent factory; universe = membership stub; ABC deleted | ✓ |
| Keep in the universe stub | Stub keeps event production | |
| Into the trading-system loop | Loops build events inline | |

**User's choice:** Into the BarFeed
**Notes:** User asked how professional frameworks do it (LEAN/Nautilus/Zipline/backtrader survey: data events always come from the feed/data engine; universe = membership only, and only exists when membership is time-varying). User asked whether multi-strategy runs survive the collapse — yes, unaffected; only time-varying mid-run membership is deferred. User asked whether keeping event production in the universe would ease future expansion — concluded the opposite: purity (membership-only) is what makes the future rebalance milestone cheap; StaticUniverse/get_assets ABC cited as the cautionary tale of speculative seams.

| Option | Description | Selected |
|--------|-------------|----------|
| Targeted gap-fill, hand-verified fixtures | Requirement-keyed; synthetic frames with hand-computable expectations | ✓ |
| Coverage-threshold push | Percent gate | |
| Golden-characterization only | Frozen artifacts as sole regression | |

**User's choice:** Targeted gap-fill

---

## SL/TP policy (user-raised area)

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit levels + typed SLTPPolicy | Levels primary; PercentFromFill/PercentFromDecision declarative alternative; explicit wins | ✓ |
| Explicit levels only | Industry-baseline, defer policies | |
| Full policy vocabulary now | Also AtrMultiple + trailing | |

**User's choice:** Explicit levels + typed SLTPPolicy
**Notes:** User raised the area at the wrap-up gate ("where does SL/TP calculation happen now?"). Walked through the current flow (strategy levels → bracket declaration → exchange OCO; sltp_models orphaned) and the decision-anchored vs fill-anchored distinction under next-bar-open fills. User asked whether the hybrid is industry standard — yes: explicit absolute prices universal; fill-anchored relative rules = IB attached orders/pegged orders/trailing order params; policy-object packaging is the LEAN-flavored variant consistent with SizingPolicy.

---

## Claude's Discretion

- Exact module/file shapes for SizingPolicy, SLTPPolicy, SignalIntent, TradingDirection in order_handler/ (import direction so strategy_handler avoids circularity)
- direction/allow_increase/max_positions as policy fields vs sibling strategy fields; multi-ticker max_positions semantics
- FractionOfCash semantics under allow_increase=True (oracle-dark)
- Fill-time bracket mechanics for PercentFromFill (validated modify vs deferred child pricing)
- cash<30 floor dies with RiskManager (inert); no min-notional this phase
- summary.json metrics schema; trades.csv slippage column naming; expected-diff note format
- Sequencing: inert work first, then the two result-changing admission rules (Phase 6 D-22 discipline)

## Deferred Ideas

- Margin + liquidation milestone (LONG_SHORT unlocks with it)
- Resolver registry for custom sizing code
- Trailing stops + AtrMultiple SLTP kinds
- Full Instrument metadata model → D-live
- Real time-aware Universe (LEAN UniverseSelectionModel) → with D-screener rebalance loop
- Multi-strategy oracle validation
- Declarative scale-out policies beyond exit_fraction
- Stats persistence (SQL) → D-sql
