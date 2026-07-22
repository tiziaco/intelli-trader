---
id: enable-margin-runtime-flip-vs-fixed-account-kind
title: "enable_margin stays runtime-mutable after account KIND is fixed at construction"
status: pending
severity: high
source: 11.1-REVIEW.md (CR-02)
created: 2026-07-22
---

# `enable_margin` can flip after the account KIND is already chosen

Phase 11.1 (D-02/D-03) made `VenuePlugin.new_account` the sole account factory:
`PortfolioHandler.add_portfolio` selects the cash-vs-margin leaf **once**, at construction,
and the selection branch was deleted from `Portfolio`.

But `Portfolio.process_transaction` still branches on
`self.config.trading_rules.enable_margin` at fill time, and that field remains routable via
`ConfigRouter._apply_portfolio` and is applied by `_layer_persisted_overrides` **after**
`rehydrate_portfolios` has already minted the account.

Flip `enable_margin` to true on a portfolio whose account was built as cash, and
`_require_margin_account` raises on every subsequent fill. Live runs publish-and-continue
(documented, intentional — see CONVENTIONS.md), so the error is swallowed and **fills
silently never settle**.

The phase removed the runtime selection branch without adding the compensating invariant.

## Needs a decision before fixing

Three defensible resolutions — pick one deliberately, do not let a fixer choose:

1. Make `enable_margin` immutable after construction (reject the override at the router).
2. Rebuild/swap the account leaf when the flag flips (who owns that lifecycle?).
3. Validate at apply time and refuse the override with a loud error rather than deferring
   the failure to the next fill.

Option 1 is the most consistent with the phase's "collaborators are built once and
injected" direction, but it changes the config-router contract, which is out of scope
for 11.1.
