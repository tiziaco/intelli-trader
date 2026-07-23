---
id: account-reservation-ledger-narrow-port
title: "SimulatedCashAccount takes the whole PortfolioStateStorage but uses nine of its methods — narrow it to a ReservationLedger port"
status: pending
severity: medium
source: 2026-07-23 design discussion following 11.1-REVIEW.md WR-04
created: 2026-07-23
resolves_by: Phase 12
---

# The simulated account depends on a portfolio-wide store to use nine methods

`SimulatedCashAccount` receives the whole `PortfolioStateStorage` — a ~25-method
portfolio-wide interface — and calls exactly **nine** of them, in three clusters:

- **reservations** — `get_reserved_cash`, `add_reservation`, `pop_reservation`;
- **margin locks** — `get_locked_margin`, `get_locked_margin_for`, `add_locked_margin`,
  `pop_locked_margin`;
- **cash-operation audit trail** — `add_cash_operation`, `get_cash_operations`.

It touches none of positions, transactions, snapshots or config. `VenueAccount` carries no
seam at all — so this is a **simulated-leaf-only** dependency on a portfolio-wide store.

## The atomicity constraint underneath is real and must be preserved

`CachedSqlPortfolioStateStorage` spans a fill's position write and its cash-scalar durable
write in **one transaction**: a crash between them can never leave the durable position one
fill ahead of the durable cash.

So the answer is emphatically **not** "give the account its own store". That is literally the
current bug. An omitted `state_storage` makes the leaf build its own private in-memory backend,
while the restart path `state_storage.rehydrate(account)` runs against the **portfolio's**
store — so every reservation written to the private one is silently lost.

## The answer is a narrow port onto the same instance

A `ReservationLedger` Protocol of those nine methods, which `PortfolioStateStorage` already
satisfies structurally. **Same object, same transaction boundary, narrower door.** Nothing about
persistence or ordering changes; only the declared type narrows.

## Why this is Phase 12 work, not a quick fix

Two structural facts:

**(a) Three of four collaborators still reach the seam through the portfolio.**
`PositionManager` (`position_manager.py:63`) and `TransactionManager`
(`transaction_manager.py:45`) still take `portfolio` and reach the seam via
`getattr(portfolio, "state_storage", None)` — and `position_manager.py:80` writes it **back**
onto the portfolio. 11.1's D-01 removed the back-reference from `Account` *only*.

**(b) The portfolio adopts its storage from the account it was handed.** Because the account is
constructed *before* the portfolio, `Portfolio._init_managers` reads its seam back off its own
leaf (`portfolio.py:205`). That inversion is the direct cause of WR-04.

A narrow port plus a constructor reordering makes **WR-04 stop existing** rather than being
guarded — and Phase 12's stated goal is already "every collaborator a required constructor
argument".

## The 11.2 fix is a down-payment, not throwaway work

The WR-04 required-kwarg fix queued for Phase 11.2 (make `state_storage` a required keyword on
the simulated leaves, delete the in-memory fallback, fail loud in `PaperVenuePlugin.new_account`)
is a **down-payment on this shape**: the port would be a required constructor argument
regardless. Nothing done for WR-04 in 11.2 has to be undone here — only the declared type of the
argument changes.

Related Phase 12 item out of the same review:
`.planning/todos/pending/venue-bundle-memo-check-then-set-race.md`.
