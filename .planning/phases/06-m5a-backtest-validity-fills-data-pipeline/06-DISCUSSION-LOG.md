# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-06
**Phase:** 6-m5a-backtest-validity-fills-data-pipeline
**Areas discussed:** Bar-timing & fill convention, Fill realism & fee/slippage policy, Bar struct & data-pipeline shape, Oracle discipline while results change, Strategy data-access contract, Market-order resting mechanics, Test coverage boundary, Equity-marking convention

---

## Bar-timing & fill convention

| Option | Description | Selected |
|--------|-------------|----------|
| Next-bar-open | Decide on close of bar N, fill at open of bar N+1 — backtesting.py/backtrader default | ✓ |
| Same-bar-close, documented | Keep current behavior, document + assert it | |
| Configurable, next-open default | Execution-timing switch on the exchange | |

**User's choice:** Next-bar-open
**Notes:** Chosen for like-for-like Phase 8 cross-validation.

| Option | Description | Selected |
|--------|-------------|----------|
| Completed bars only | Forming higher-TF bar invisible; label/closed='left', exclusive upper bound | ✓ |
| Include the forming bar | Partial bar aggregated up to T as last row | |

**User's choice:** Completed bars only
**Notes:** User asked for a concrete example (weekly-on-daily walkthrough) and how Nautilus handles it (on_bar fires only at close) before locking.

| Option | Description | Selected |
|--------|-------------|----------|
| Hard limit bound + gap-aware | Limits at limit-or-better, no slippage; stops market-like on trigger with gap risk | ✓ |
| Strict price-touch only | Both fill exactly at trigger price, ignoring gaps | |

**User's choice:** Hard limit bound + gap-aware
**Notes:** User asked whether this is the industry standard — confirmed via real exchange semantics (limit = contractual bound, stop = trigger) and all three reference engines.

| Option | Description | Selected |
|--------|-------------|----------|
| Keep open-time, document it | Binance kline/CCXT convention; zero churn | ✓ |
| Switch to close-time stamping | Nautilus convention; shifts every oracle timestamp | |

**User's choice:** Keep open-time stamping
**Notes:** User probed the industry standard ("BOST" = bar-open timestamping); confirmed open-time dominates kline-style data while Nautilus uses close-time; both look-ahead-safe once documented.

---

## Fill realism & fee/slippage policy

| Option | Description | Selected |
|--------|-------------|----------|
| Remove scaffolding | Full-quantity fills documented contract; partial plumbing deleted | ✓ |
| Volume-capped fills | Cap at fraction of bar volume; remainder rests | |

**User's choice:** Remove scaffolding

| Option | Description | Selected |
|--------|-------------|----------|
| Keep zero fees/slippage | Oracle stays pure engine-correctness reference | ✓ |
| Realistic fees (0.1% taker) | Representative numbers, fee path in oracle | |
| Two reference runs | Zero-cost + with-costs oracles | |

**User's choice:** Keep zero fees/slippage

| Option | Description | Selected |
|--------|-------------|----------|
| Route to M5b risk layer | Margin/solvency = admission-time risk check (Phase 7) | ✓ |
| Fix here as fill realism | Minimal margin model this phase | |
| Keep blessed through Phase 8 | Accept negative-equity shorts in final oracle | |

**User's choice:** Route DEF-01-C to M5b risk layer

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal event + derived column | FillEvent = price + commission; M5b reporting derives slippage column | ✓ |
| Also carry model slippage on the event | Extra Decimal field preserving the model component | |

**User's choice:** Minimal event + derived column
**Notes:** User leaned to the industry shape, asked whether slippage could still be stored separately "like fee" — locked the fee-is-a-fact / slippage-is-a-measurement principle; derived column lands in M5b reporting. Accepted nuance: column measures gap + model slippage combined.

| Option | Description | Selected |
|--------|-------------|----------|
| Prune to zero/percent/maker_taker | Delete TieredFeeModel (never worked) | ✓ |
| Fix all four | Repair tiered ctor and keep it | |

**User's choice:** Prune to three models

| Option | Description | Selected |
|--------|-------------|----------|
| Resting limit = maker, rest = taker | Universal exchange classification | ✓ |
| You decide | Leave to research/planning | |

**User's choice:** Resting limit = maker, rest = taker

| Option | Description | Selected |
|--------|-------------|----------|
| Decimal-native now | Fee/slippage/matching retyped Decimal; float carve-out dies | ✓ |
| Keep float internals | D-22 carve-out survives into final oracle | |

**User's choice:** Decimal-native now

---

## Bar struct & data-pipeline shape

| Option | Description | Selected |
|--------|-------------|----------|
| Decimal prices | Bar OHLCV Decimal, exact at construction | ✓ |
| Float fields, convert at boundary | float64 Bar, convert where bars meet money | |

**User's choice:** Decimal prices
**Notes:** User asked the industry standard (Nautilus fixed-point, Binance string prices vs backtesting.py/backtrader float) and whether Decimal handles 0.000005-style micro-prices — yes, exactly where float fails. Companion never-round-prices rule locked. User asked whether to implement full per-instrument precision this phase — advised no; rule lands now, Instrument model deferred (M5b sizing / D-live).

| Option | Description | Selected |
|--------|-------------|----------|
| Current bar only: dict[str, Bar] | Event carries one immutable Bar per ticker | ✓ |
| Bar + recent window on the event | Event also carries pandas windows | |

**User's choice:** Current bar only

| Option | Description | Selected |
|--------|-------------|----------|
| Full seams, backtest impls only | All three Protocols now; CSV store + feed implemented; dormant code quarantined | ✓ |
| Backtest path only, defer seams | Fix bugs inside slimmed PriceHandler | |
| Full split + delete dormant code | Delete SqlHandler/CCXT/streaming outright | |

**User's choice:** Full seams, backtest impls only

| Option | Description | Selected |
|--------|-------------|----------|
| float64 pandas windows | Indicators on float; Decimal Bar only touches money | ✓ |
| Decimal-typed windows | Object-dtype frames, ~100x slower rolling math | |

**User's choice:** float64 pandas windows

| Option | Description | Selected |
|--------|-------------|----------|
| Delete PriceHandler | Consumers wire Store/Feed directly | ✓ |
| Keep as thin facade | PriceHandler delegates internally | |

**User's choice:** Delete PriceHandler

| Option | Description | Selected |
|--------|-------------|----------|
| Feed method, fixed + tested | Megaframe = BarFeed query; FR8 bugs fixed; multi-symbol fixture | ✓ |
| Quarantine with screener code | Defer fix to D-screener | |

**User's choice:** Feed method, fixed + tested

---

## Oracle discipline while results change

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid: inert-proven vs explained re-freeze | Structural work holds current oracle byte-exact; validity fixes re-freeze with documented diffs | ✓ |
| Suspend numerics, re-freeze at phase end | Numeric asserts off for the phase | |
| Re-freeze on every diff | No inert/changing classification | |

**User's choice:** Hybrid
**Notes:** User asked for a concrete example — the $0.001-refactor-bug vs next-open-diff walkthrough (134 trades / $53,229.685 baseline) clarified the choice.

| Option | Description | Selected |
|--------|-------------|----------|
| Structural first, validity last | Inert workstreams prove byte-exactness before any result-changing fix | ✓ |
| Planner discretion entirely | Interleave if dependencies favor it | |

**User's choice:** Structural first, validity last

| Option | Description | Selected |
|--------|-------------|----------|
| Blocking owner sign-off each | User reviews each expected-diff note before re-freeze commits | ✓ |
| Document now, review at phase end | Batch review at verification | |

**User's choice:** Blocking owner sign-off per re-freeze

---

## Strategy data-access contract (follow-up round)

| Option | Description | Selected |
|--------|-------------|----------|
| Push: handler feeds windows | StrategiesHandler queries Feed, hands window + Bar to calculate_signal | ✓ |
| Guarded pull portal now | Time-scoped Feed handle (Zipline/Nautilus shape) | |

**User's choice:** Push
**Notes:** User asked how other frameworks do it — surveyed backtesting.py (truncated views), backtrader (relative indexing), Zipline/Lean (time-scoped portals), Nautilus (append-only cache); locked the "strategies never choose the as-of time" invariant; pull portal deferred as a later Feed layer.

## Market-order resting mechanics (follow-up round)

| Option | Description | Selected |
|--------|-------------|----------|
| Unified book in MatchingEngine | Market orders rest with trigger "fill at next open" | ✓ |
| Separate pending queue in exchange | Second resting-state home | |

**User's choice:** Unified book

## Test coverage boundary (follow-up round)

| Option | Description | Selected |
|--------|-------------|----------|
| Test-with-code | Every new component ships with unit tests this phase | ✓ |
| Mandated tests only | Only look-ahead regression + oracle gates now | |

**User's choice:** Test-with-code

## Equity-marking convention (follow-up round)

| Option | Description | Selected |
|--------|-------------|----------|
| Confirm: close-marked | Equity at T = cash + positions at T's close; documented + asserted | ✓ |
| You decide | Leave to research/planning | |

**User's choice:** Close-marked

---

## Claude's Discretion

- Exact price_handler package layout, Protocol names, Bar module location
- Precompute timeframe derivation + frame keying/slicing mechanics
- MatchingEngine market-order trigger implementation + bracket sequencing + last-bar edge
- Fate of PriceHandler symbol methods (minimal relocation pending M5b universe stub)
- OrderEvent.price documentation for market orders (reservation interplay)
- core/money quantization details for the execution retype under never-round-prices
- Workstream inert/result-changing classification + commit sequencing
- Expected-diff note format for re-freeze sign-offs

## Deferred Ideas

- DEF-01-C margin/liquidation model → Phase 7 (M5b) risk layer
- Slippage attribution column in trade log → M5b reporting (#38)
- Instrument metadata model (tick/step size, precision, filters) → M5b sizing / D-live
- Guarded pull portal on the Feed → M5b+ when a strategy needs it
- Volume-based partial fills / liquidity model → out of program scope
- SQL store backend, CCXT/OANDA rework, live streaming → D-sql / D-oanda / D-live
- Ingestion pipeline as a real CLI → persistence milestone (stub only this phase)
