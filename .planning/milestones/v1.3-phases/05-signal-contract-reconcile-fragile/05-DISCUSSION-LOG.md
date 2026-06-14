# Phase 5: Signal Contract & Reconcile (FRAGILE) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 5-signal-contract-reconcile-fragile
**Areas discussed:** Authoring API shape, Re-baseline posture, Reconcile streamline depth, Entry-price validation, SIG-03 snapshot-threading mechanics, Limit/stop sizing basis, Cross-val scenario design, SignalRecord audit capture

---

## Authoring API shape (SIG-01/SIG-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Opt 1 — inferred limit=/stop= | `buy(limit=X)`/`buy(stop=X)`; type inferred from kwarg (backtesting.py style) | |
| Opt 2 — explicit order_type+entry_price | `buy(order_type=LIMIT, entry_price=X)`; 1:1 with SignalEvent/Order, backtrader/ccxt style | |
| Opt 3 — distinct factories + retire attr | `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop`; retire per-instance `Strategy.order_type` (nautilus/Lean style) | ✓ |

**User's choice:** Opt 3 + hardcode MARKET in plain `buy()`/`sell()` + retire the `Strategy.order_type` attr.
**Notes:** Owner weighed opt 2 vs opt 3 and asked what's cleanest / what frameworks do. Framework
survey: broker APIs (ccxt/IB) + backtrader use explicit type; nautilus/Lean use distinct factories;
backtesting.py uses inferred kwargs. Chose opt 3 for symmetry with the existing
`Order.new_market/limit/stop_order` factories + illegal-states-unrepresentable (collapses Area 4).
Confirmed plain `buy()` hardcodes MARKET rather than reading `self.order_type` → the attr is retired.
Clarified the distinction: `SignalIntent.order_type` (the per-intent field) is ADDED, not retired;
only the strategy-wide default attribute is removed. The order handler always knows the type because
it rides intent→event→order and admission already dispatches on it.

---

## Re-baseline posture (SIG/RECON, owner-gated)

| Option | Description | Selected |
|--------|-------------|----------|
| Opt 1 — byte-exact anchor + one x-val limit-entry golden | Keep SMAMACD oracle byte-exact; add ONE cross-validated limit-entry scenario | ✓ |
| Opt 2 — migrate reference, re-baseline | Change SMAMACD to limit/stop; re-baseline existing golden to a new number | |
| Opt 3 — byte-exact only (plain e2e) | Keep oracle byte-exact; prove limit/stop via e2e only, no cross-validated golden | |

**User's choice:** Opt 1 — byte-exact anchor + one cross-validated limit-entry golden.
**Notes:** Owner weighed opt 1 vs opt 3. Analysis: the resting limit/stop MATCHING path is already
externally validated via SMAMACD's SL/TP brackets, so opt 3 was more defensible than it first looked;
but the genuinely-new entry-fill→bracket sequence isn't pinned by today's all-market oracle, this is
THE phase whose discipline is external cross-validation, and N+2 builds on this surface. Chose opt 1
scoped to ONE limit-entry scenario (v1.0 harness already exists → low marginal cost), fallback to
opt 3 if the harness is painful to extend.

---

## Reconcile streamline depth (RECON-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Opt 1 — clarity cleanup, flow-preserving | Named helpers (`_classify`/`_release_reservation`) + arms; try/finally byte-identical | ✓ |
| Opt 2 — explicit state-machine restructure | Transition table; still must keep try/finally | |
| Opt 3 — doc-only / near-no-touch | Comments only, no structural change | |

**User's choice:** Opt 1 — clarity cleanup, flow-preserving.
**Notes:** Owner asked which is most architecturally correct / most reliable. Analysis (after reading
on_fill:86-234): the hard part is irreducible exception-safe resource release (release-once-on-terminal-
even-if-body-raises, WR-03/WR-04/T-05-17), NOT a transition table. A naive table-driven `apply();release()`
reintroduces the WR-04 bug (release skipped on a raise), so opt 2-done-right ≈ opt 1 + a table — cosmetic
win, more churn on FRAGILE byte-exact code. Opt 1 captures the "release-once-obvious" win via a named
helper while leaving the exception-safety skeleton untouched.

---

## Entry-price validation (SIG-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Opt 1 — accept, defer venue-reject to N+4 | No new validation; marketable limit fills at open (already coded, oracle-consistent) | ✓ |
| Opt 2 — reject wrong-side stop now | Binance-realistic "would trigger immediately"; diverges from oracles | |

**User's choice:** Opt 1 — accept, defer Binance-style venue rejection to N+4.
**Notes:** Owner asked what's most realistic / what pros do. Found `MatchingEngine._evaluate:166-180`
already fills marketable limits at the bar open with price improvement (limit-or-better). Realism splits:
marketable LIMIT is universally accepted (real venues + all backtest frameworks); wrong-side STOP is
often rejected by real crypto venues (Binance -2010) but accepted by backtesting.py/backtrader. For a
backtest engine cross-validated against those oracles, opt 1 is both oracle-consistent and already
implemented; venue-realistic stop rejection is a per-venue LIVE concern → N+4.

---

## SIG-03 snapshot-threading mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Thread the Position object | Capture `Optional[Position]` once at top of process_signal; pass into all 3 sites | ✓ |
| Thread a lightweight value | Just net_quantity; risks a refetch if a site needs more | |

**User's choice:** Thread the Position object.
**Notes:** Byte-exact because nothing mutates the position between the three `get_position()` sites
(404/484/583); the line-208 reserve touches cash, no fill yet. Captured before the step-0 direction gate.

---

## Limit/stop sizing basis

| Option | Description | Selected |
|--------|-------------|----------|
| signal_event.price, no new logic | Conservative-correct; accept gap-stop under-reservation as a blessed class | ✓ |
| add a buffer / refetch market price | Extra logic; would diverge from byte-exact | |

**User's choice:** signal_event.price, no new logic, accept + document the gap edge.
**Notes:** Already the basis (sizing ~565, reserve 206). Limit-or-better → sizing/reserving at the limit
is a safe ≤ quantity. BUY-stop gap-up fill above trigger = same blessed class as MARKET sized-on-close /
filled-next-bar-open.

---

## Cross-val scenario design

| Option | Description | Selected |
|--------|-------------|----------|
| Crafted minimal strategy | Dead-simple deterministic limit-entry on BTCUSD golden; isolates the mechanic | ✓ |
| Reuse SMAMACD + limit offset | Entangles limit mechanic with declared-indicator MACD (hard to replicate across 3 engines) | |

**User's choice:** Crafted minimal deterministic limit-entry strategy on the same BTCUSD golden data.
**Notes:** Must fill on a later bar, exercise entry-fill→bracket, and include a marketable-limit case to
pin open-vs-limit fill price. Reuses the v1.0 cross-val harness.

---

## SignalRecord audit capture

| Option | Description | Selected |
|--------|-------------|----------|
| Add order_type + entry_price | Audit read-model faithfully records limit/stop decisions | ✓ |
| Leave SignalRecord unchanged | Lighter, but audit trail misrepresents new decisions | |

**User's choice:** Add `order_type` + `entry_price` to SignalRecord.
**Notes:** Oracle-dark sink (does not affect fills) → low-risk schema add on the in-memory backtest store.

---

## Claude's Discretion

- Exact factory signatures + shared `_intent(...)` private helper across the 6 buy/sell methods.
- Exact home/names of `_classify` / `_release_reservation` / per-status arm helpers.
- The crafted cross-val strategy's exact offset %, cadence N, SL/TP %.
- `SignalRecord` field names/types for `order_type`/`entry_price`.

## Deferred Ideas

- N+4: per-venue "stop would trigger immediately" rejection (Binance -2010 class) + trailing native-vs-synthetic seam.
- Future signal-contract phase: per-signal `market_execution` fill-timing override.
- N+2 (margin/shorts/trailing) builds on this completed SIG surface; the limit-entry golden becomes its anchor.
