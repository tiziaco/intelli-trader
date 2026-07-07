# Phase 1: Account Abstraction + Portfolio/Handler Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-30
**Phase:** 1-account-abstraction-portfolio-handler-refactor
**Areas discussed:** Account ABC leaf shape, reserve/release home, TradingInterface fate, LiveConnector interface scope, File placement

---

## Account ABC leaf shape

| Option | Description | Selected |
|--------|-------------|----------|
| Inheritance: Margin extends Cash | `SimulatedMarginAccount(SimulatedCashAccount)`; sim-vs-venue as sibling leaves under the ABC | ✓ |
| Single unified SimulatedAccount | One class mirroring today's CashManager 1:1; cash-vs-margin a runtime flag | |
| Siblings under shared ABC | Cash and Margin leaves with no inheritance between them | |

**User's choice:** Inheritance.
**Notes:** User asked "what's most architecturally correct AND most in line with what I already do."
Findings reconciled: today cash-vs-margin is a runtime `enable_margin` flag on one unified CashManager,
but ACCT-01 *literally commits to two leaves*, removing "single unified" from contention. Inheritance
chosen because margin is a strict superset of cash (zero duplication) and because the two axes map onto
patterns already in the codebase: sim-vs-venue = the ABC+sibling-leaf pattern (fee_model/exchanges),
cash-vs-margin = inheritance. Plan must pin whether the oracle runs spot or margin (decides which leaf
the byte-exact gate exercises).

---

## reserve/release home

| Option | Description | Selected |
|--------|-------------|----------|
| Mechanics → Account; seam stays on handler | `account.reserve(order_id, amount)`; `PortfolioReadModel.reserve(portfolio_id,…)` stays on PortfolioHandler, re-points delegation | ✓ |
| Keep reserve/release as a Portfolio/handler responsibility | Account only does raw balance math | |

**User's choice:** Mechanics → Account; seam stays on handler.
**Notes:** Resolved as "both, at the correct layer" — mechanics are CashManager methods that ride the
CashManager→SimulatedCashAccount code-motion (Account-level signature drops portfolio_id under LX-04
1:1); the portfolio_id-keyed PortfolioReadModel seam must stay on the handler (Account has no notion of
portfolio_id). Net: zero ripple into the order domain (protects success-criterion #4). Pushing the
portfolio_id-keyed method onto Account explicitly rejected (leaks portfolio identity downward).

---

## TradingInterface fate (LX-14)

| Option | Description | Selected |
|--------|-------------|----------|
| Delete + lock principle, defer surface to Phase 4 | Remove TradingInterface; lock only the "thin engine command surface" principle; method set defined in Phase 4 | ✓ |
| Delete + sketch the thin surface now | Also enumerate the intended command surface interface-only in Phase 1 | |
| Keep/slim instead of delete | Retain a slimmed boundary FastAPI calls | |

**User's choice:** "delete and let's define the principle in phase 4."
**Notes:** TradingInterface is effectively dead (only barrel export + a test docstring; not wired into
LiveTradingSystem composition) and carries a live-path float-money leak (D-09; `quantity: float`).
Deleting helps the mypy/no-float gate. FastAPI (per the application-layer plan) owns the app layer, so
the surviving command surface crystallizes in Phase 4 when there is a real live consumer — designing it
in Phase 1 would be speculative.

---

## LiveConnector interface scope

| Option | Description | Selected |
|--------|-------------|----------|
| Structural Protocol; pin VenueAccount-coupled reads, defer rest | Name arm boundaries + pin account-relevant reads now | |
| Full interface now, shaped on the spec's OKX reality | Freeze async submit→ack→fill, balances, positions, watch_ohlcv now | |
| Minimal marker only, full shape in Phase 2 | Near-empty LiveConnector + VenueAccount stub; everything else Phase 2 | ✓ |

**User's choice:** Option 3 (minimal marker), after clarification.
**Notes:** User was torn between option 1 and option 3. Resolved by the insight that VenueAccount's
stable contract comes from the **Account ABC** (already locked), not from the connector — so a thin
LiveConnector marker does NOT underdeliver ACCT-06. Connector-read signatures are genuinely
OKX-determined (Phase 2 CONN-*) and the connector→VenueAccount data flow is Phase 5 (RECON-01); pinning
them now would be the premature-interface trap. Reframed as "option 3 done right": thin
runtime_checkable Protocol marker naming the arm boundaries + Account-ABC-backed VenueAccount stub.

---

## File placement

| Option | Description | Selected |
|--------|-------------|----------|
| `portfolio_handler/account/` (peer to four managers) | Account family as a subdir; LiveConnector → new top-level `connectors/` | ✓ |
| New top-level `account_handler/` | Account as a sibling handler domain | |

**User's choice:** `portfolio_handler/account/` for the Account family; new top-level `connectors/` for LiveConnector.
**Notes:** `*_handler` means a queue-facing thin layer; Account has no queue/events (liquidation
emission stays in PortfolioHandler), so `account_handler/` would misrepresent it. Account is the fifth
peer delegate alongside cash/position/transaction/metrics; under LX-04 1:1 Account/Portfolio share
scope (not an independent domain). LiveConnector is broader than the portfolio domain (data + order
arms) → new top-level `connectors/` package (base.py now; okx.py Phase 2, paper.py Phase 4).
VenueAccount stays in `account/venue.py` (an Account leaf, not a connector).

---

## Claude's Discretion

- Mechanical code-motion, constructor-signature-ripple resolution (user_id strip), the
  `Portfolio.cash → Portfolio.account.balance` delegation wiring, `mypy --strict` cleanliness, and
  oracle re-confirmation — handled at plan/execute time (Research flag: SKIP, code-motion only).

## Deferred Ideas

- Engine command surface (concrete method set) → Phase 4.
- LiveConnector real signatures (async submit→ack→fill, watch_ohlcv, balances/positions, OKX
  confirm-flag, rate-limit accounting) → Phase 2.
- VenueAccount connector-coupled implementation (caching streams, per-symbol drift reconciliation) →
  Phase 5.
- Venue* cash/margin leaf bodies (computed-vs-cached split) → Phase 5.
