# Phase 6: Order Matching Scenarios - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 6-Order Matching Scenarios
**Areas discussed:** Test-strategy & price control, MODIFY/CANCEL injection, Golden artifact scope, Granularity & verify-batching, Sequencing / cost isolation / bracket SLTP

---

## Test-strategy & price control

### Strategy shape
| Option | Description | Selected |
|--------|-------------|----------|
| One generic scripted-emitter | Single parametrized strategy emitting a configured intent on configured bars | ✓ |
| Bespoke per-scenario strategies | ~10+ near-identical classes | |
| A few family strategies | One per order-type family | |

**User's choice:** One generic scripted-emitter.

### Entry price control (LIMIT/STOP entry)
| Option | Description | Selected |
|--------|-------------|----------|
| Contrived-bar authoring | Entry rests at decision-bar close; author following bars for touch/gap/never-fill; no contract change | ✓ |
| Add explicit entry-price to the intent | Decouple resting price from decision-bar close | |

**User's choice:** Contrived-bar authoring.
**Notes:** User correctly observed SL/TP are already explicit on the intent, narrowing the question to the LIMIT/STOP ENTRY price only. Also noted the oracle uses only MARKET orders, so an optional entry-price field would be oracle-inert — but agreed the cleaner framing is scope (coverage phase tests what ships; adding the field is a new production capability). Confirmed it IS a real missing production feature → noted as deferred.

### order_type scope (confirmed constraint)
**Notes:** `SignalEvent.order_type = strategy.order_type` — one order_type per strategy instance; intent doesn't carry it. Emitter mirrors production; bracket children typed by the assembler.

### Firing key
| Option | Description | Selected |
|--------|-------------|----------|
| Completed-bar count | `len(bars) == fire_on_bar` (canary pattern) | |
| Explicit bar date/timestamp | `bars.index[-1] == "YYYY-MM-DD"` | ✓ |
| You decide | Delegate to planning | |

**User's choice:** Date-keying.
**Notes:** Asked for an example; agreed date-keying is more self-documenting against bars.csv and sidesteps the len(bars)/max_window/warmup gotcha.

---

## MODIFY/CANCEL injection (MATCH-07)

### Mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| Scenario-level scheduled action calling the real API | Harness plays operator, calls real OrderHandler.modify_order/cancel_order | ✓ |
| Test strategy with order-handler back-reference | Strategy calls modify/cancel | |
| Direct OrderEvent(MODIFY/CANCEL) queue injection | Pre-built event onto queue | |

**User's choice:** Option A (harness plays operator, real API).
**Notes:** User asked what the cleanest thing was and whether a component was missing. Established: OCO sibling-cancel is engine-driven (MATCH-04, no injection); orphaned-children cleanup is order-handler-driven; the external operator modify/cancel API is the only one with no backtest caller — by design (pure-alpha D-12; amendment is an operator concern, live's TradingInterface). Seam = oracle-inert `on_tick` hook + `ScenarioSpec.actions`. Order resolved by predicate via existing query API.

### Order reference resolution
| Option | Description | Selected |
|--------|-------------|----------|
| Predicate query via existing API | ticker+status resolved at action bar via get_active_orders/get_orders_by_ticker | ✓ |
| Capture order_id at creation | Observe creation, thread the id | |
| Stable label/handle on the order | Add a label field (contract change) | |

**User's choice:** Predicate query via existing API.
**Notes:** Also explored (educational): peer frameworks (backtrader/nautilus/backtesting.py) DO let strategies manage orders directly; iTrader's pure-alpha stance is a deliberate advantage for a correctness-first deterministic engine, a limitation only for order-centric strategy styles.

---

## Golden artifact scope

### Artifact approach
| Option | Description | Selected |
|--------|-------------|----------|
| New optional golden artifact: orders snapshot | Final order-mirror, deterministic business columns, logical roles, UUIDs excluded | ✓ |
| Extend summary.json with order-outcome counts | Coarse counts | |
| Inline per-folder test assertions | Bespoke Python asserts | |

**User's choice:** New optional orders-snapshot artifact.

### Snapshot scope
| Option | Description | Selected |
|--------|-------------|----------|
| Opt-in, like equity.csv | Freeze only where order state is the assertion | ✓ |
| Uniform — freeze for all | Every scenario | |
| You decide | Delegate | |

**User's choice:** Opt-in.

### MATCH-08 run-end assertion
| Option | Description | Selected |
|--------|-------------|----------|
| Assert as-is: order stays ACTIVE | Accept current no-disposition behavior | ✓ |
| Wire run-end expiry so it asserts EXPIRED | Behavior change | |

**User's choice:** Assert as-is.
**Notes:** Confirmed no run-end order disposition exists; `expire_order()`/EXPIRED are unwired on the backtest path → deferred idea.

---

## Granularity & verify-batching

### Granularity
| Option | Description | Selected |
|--------|-------------|----------|
| One folder per distinct fill-shape | ~12-15 leaves; MATCH-02/03/06 split by shape | ✓ |
| One folder per requirement | 8 folders | |
| You decide | Delegate | |

**User's choice:** One folder per distinct fill-shape.

### Verify-batching
| Option | Description | Selected |
|--------|-------------|----------|
| Interleaved per batch | Verify+freeze each batch before next | |
| Batched-at-end (generate all, then ~4 grouped verify sittings) | Parallel generation decoupled from review | ✓ |
| All-at-end single pass | One 15-at-once pass | |

**User's choice:** Batched-at-end with ~4 grouped sittings by cluster.
**Notes:** User asked whether they could verify all at the end; clarified generation vs hand-verification, and that grouping into ~4 cluster sittings honors "not 12-at-once" while decoupling generation from review.

---

## Sequencing / cost isolation / bracket SLTP

### Foundational plan structure
| Option | Description | Selected |
|--------|-------------|----------|
| Infra + one proof scenario, then parallel wave | Build/commit shared infra AND dogfood MATCH-01 before fan-out | ✓ |
| Infra only, then parallel wave | All scenarios in the wave | |

**User's choice:** Infra + one proof scenario first.

### Exchange cost isolation
| Option | Description | Selected |
|--------|-------------|----------|
| Zero-fee / zero-slippage, isolate matching | exchange=None for all scenarios | ✓ |
| Include some cost in matching scenarios | Thread fees/slippage now | |

**User's choice:** Zero-fee / zero-slippage.

### Bracket SLTP declaration
| Option | Description | Selected |
|--------|-------------|----------|
| Explicit Decimal levels | intent.stop_loss/take_profit (D-13 primary) | ✓ |
| Percent-based sltp_policy | PercentFromDecision/PercentFromFill | |

**User's choice:** Explicit Decimal levels.

---

## Claude's Discretion

- Exact orders-snapshot column set + ENTRY/SL/TP role-derivation rule.
- `on_tick` hook signature and `ScenarioSpec.actions` shape.
- Deterministic sort key for snapshot rows.
- Contrived `bars.csv` authoring per scenario.
- Exact `tests/e2e/matching/` sub-dir names/depth.
- Whether MODIFY needs separate re-price vs re-size leaves.

## Deferred Ideas

- Explicit per-intent limit/stop ENTRY price (and per-intent order_type) on the signal contract — real missing production feature, owner-gated.
- Run-end resting-order disposition / time-in-force (expire_order unwired) — result-changing, owner-gated.
- Strategy-driven order management (order-centric styles) — deliberately unsupported by pure-alpha; context only.
