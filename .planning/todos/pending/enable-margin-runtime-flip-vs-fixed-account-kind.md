---
id: enable-margin-runtime-flip-vs-fixed-account-kind
title: "enable_margin stays runtime-mutable after account KIND is fixed at construction"
status: pending
severity: high
source: 11.1-REVIEW.md (CR-02)
created: 2026-07-22
resolves_by: Phase 11.2
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

## Decision (2026-07-23)

**Option 1 — reject the flip.** Drop `enable_margin` from the reachable routable key set in
`ConfigRouter`, and raise in `Portfolio.update_config` when an incoming config would change it.
Operators recreate the portfolio instead. Queued for **Phase 11.2**.

### Rationale

The framing above understates the defect: the account leaf is not the only collaborator that
reads this flag once and keeps it. `enable_margin` is read at **construction** by five:

1. `AdmissionManager._enable_margin` — the leverage gate and the reservation math (`compose.py:318`);
2. `EnhancedOrderValidator.enable_margin` (`order_manager.py:126`), used by the cash-vs-cost check at `:528`;
3. `ManagedStrategies.enable_margin` — the SHORT-01 / D-07 short-selling gate;
4. the account leaf KIND (new in 11.1 — the mismatch this todo was opened for);
5. `Portfolio.process_transaction` at fill time (`portfolio.py:448`).

`ConfigRouter._apply_portfolio` calls only `portfolio.update_config`. So a runtime flip
**already desynchronizes four of the five** — and that is true *today*, before 11.1 touched
anything. The account-leaf mismatch is the newest and loudest symptom of a pre-existing defect,
not the whole of it.

That is what settles the choice between the three options. Option 2 (re-mint the leaf) and
option 3 (validate at apply time, then still apply) both leave the flag genuinely mutable, which
means propagating the change to all five collaborators — three of which have no
re-configuration path at all. Rejecting the flip is far smaller and matches the fail-loud
posture of the rest of the phase.

Recorded in full, with the other three 11.1 review decisions, under `## Resolution (2026-07-23)`
in `.planning/phases/11.1-account-provisioning-mandatory-account-identity/11.1-REVIEW.md`.
