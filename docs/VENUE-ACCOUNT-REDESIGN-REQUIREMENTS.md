# Venue / Account / Bundle Redesign — Requirements

**Status:** input document for a not-yet-scoped redesign. Not a plan, not a design.
**Scope:** `itrader/venues/`, `itrader/portfolio_handler/account/`, `portfolio_factory.py`,
`trading_system/compose.py`, `build_live_system`, and the portfolio↔account link.
**Provenance:** the four Criticals in
`.planning/phases/11.2-account-provisioning-bootstrap-review-closures/11.2-REVIEW.md`,
plus findings from the 2026-07-28 comment-reduction campaign. Every claim below marked
*(verified)* was re-checked against HEAD on 2026-07-28; claims marked *(from review,
unverified)* are inherited and must be confirmed before they drive a decision.

The owner's stated intent, which frames everything here: **`build_live_system`, the
initialisation logic, and the lazy imports all disappear.** This document does not argue
with that. It records what must not be lost when they do.

---

## 1. Why this is being redone

The current composition layer is ~611 lines across 10 modules to wire **two** venues, one
of which (`paper`) is the in-process default *(verified)*:

| module | code lines |
|---|---:|
| `trading_system/compose.py` | 131 |
| `portfolio_handler/portfolio_factory.py` | 90 |
| `venues/lifecycle.py` | 79 |
| `venues/feed_binder.py` | 66 |
| `venues/paper_plugin.py` | 63 |
| `venues/assemble.py` | 41 |
| `venues/bundle.py` (the Protocols) | 41 |
| `venues/bundles.py` | 39 |
| `trading_system/venue_spec.py` | 32 |
| `venues/registry.py` | 29 |

A plugin architecture with two plugins is a plugin architecture with one plugin and a
fallback. That is the core over-engineering claim, and it is measurable rather than
aesthetic.

**A useful secondary signal:** the comment campaign measured prose-to-code ratios per
module. `bundle.py` needed 3.39 lines of explanation per line of code, `venue_spec.py`
2.69, `bundles.py` 2.49, `assemble.py` 1.98. Protocols and ABCs legitimately run high —
there the contract *is* the deliverable — but a non-Protocol module that takes two to
three lines of prose per line of code is usually a module not earning its place. Worth
re-measuring after the redesign as a cheap check on whether the new shape is simpler or
just differently arranged.

---

## 2. Hard constraints — these survive any redesign

**2.1 The backtest oracle stays byte-exact.** 134 trades, `final_equity
46189.87730727451`, 3076 equity points. This is the program-level definition of done, not
a nice-to-have.

Both construction arms are now locked *(verified)*:
- `tests/integration/test_backtest_oracle.py` — the legacy arm
- `tests/integration/test_backtest_oracle_factory_arm.py` — the factory /
  `compose_engine` arm (added 2026-07-28, commit `1ed32e1e`)

Before that second gate existed, a change confined to the factory path passed every test
while proving nothing. **If the redesign introduces a third construction path, it needs
its own oracle assertion on day one** — the existing two will not see it.

Related trap, worth stating because it already cost time: `test_results_persist.py`
mentions both `build_backtest_system` and the golden final-equity constant, but its
byte-exact test builds via the *legacy* arm and its factory tests use a short 2018→2021
window. It is **not** factory-arm oracle coverage. Two symbols in one file is not a gate.

**2.2 Import inertness (GATE-01) is preserved — but as a package boundary, not as import
placement.** `import itrader` must pull no ccxt, no sqlalchemy, no asyncio stack;
`tests/integration/test_okx_inertness.py` proves it.

The lazy imports currently carry that guarantee, and they are going away. The structural
replacement is a subpackage boundary the backtest path never imports, with the existing
inertness test enforcing it. Then every import sits at the top of its file where it
belongs, and the property is enforced by the module graph rather than by remembering
where to indent an import. **The lazy imports are a workaround for a boundary that was
never drawn — draw the boundary and they become unnecessary rather than merely
unwanted.**

**2.3 Money stays `Decimal` end-to-end.** `float()` only at serialization/logging edges.

**2.4 Determinism.** One seeded `random.Random` built at wiring from `config.rng_seed`,
carried on the engine context, reaching the exchange. Exactly one per run. Never seeded
per-call.

**2.5 Queue-only cross-domain writes; read-models for reads.** Handlers emit events, never
call across domains. Read-only cross-domain access goes through an injected read-model
(`PortfolioReadModel`, the bar feed). The single-writer contract — all state mutation on
the engine thread — is what makes the absence of a portfolio-collection lock correct.

---

## 3. Failure modes the new design must make structurally impossible

Each of these is a real defect found in the current wiring. They are stated as properties
to design against, not as patches to apply — the code they live in is being deleted.

**3.1 A collaborator that is built but not reachable.** *(CR-01)*
`VenueAccountManager` is constructed as a local inside `build_live_system` and never
attached to the facade *(verified: no `venue_accounts` property exists on
`LiveTradingSystem`)*. The phase's headline deliverable — runtime account provisioning
without a restart — therefore has no entry point at all, and the typed refusal message
tells operators to call an attribute that does not exist.

*Design requirement:* a collaborator that is not reachable should not be constructible, or
its unreachability should be a startup error rather than a silent success.

**3.2 A set derived from a container nothing writes.** *(CR-03)*
`venue_accounts: Dict[str, Any] = {}` is declared in `build_live_system` and written by no
code path *(verified: three occurrences — the declaration, two comments, and
`lambda: list(venue_accounts.values())`)*. That callable always returns `[]`, so
`StreamRecoveryHandler.on_reconnect`'s `account.snapshot()` loop is a no-op in production.
After a venue stream reconnects, the engine resumes submission against a venue cache last
refreshed before the outage — violating the handler's own documented contract, *"don't
trade when you can't see the venue … never resume blind."*

The failure is silent: no log, no halt, no status flag. And the bring-up loop right beside
it *does* populate its sibling map (`venue_lifecycles`), so the omission looks like
symmetry.

*Design requirement:* a live collection must be **derived from the authoritative source at
use time**, never mirrored into a container that a separate code path is responsible for
keeping in sync. The comment above the current lambda already says this — *"a build-time
capture goes stale the moment an account is re-attached"* — which makes this a case of the
rationale surviving while the mechanism was lost.

**3.3 Something routable before it is connected and halt-wired.** *(CR-04)*
`bring_online` publishes an account's exchange into the order-routing registry before the
session is connected or its halt signals are wired *(from review, unverified)*.

*Design requirement:* registration into a routing surface is the **last** step of bring-up,
after every safety wire is armed. An order must not be routable to a venue that cannot
halt.

**3.4 A resource built, then abandoned without teardown.** *(CR-02)*
The feed re-borrow path builds a provider that is never subscribed, never halt-wired and
never stream-state-wired, and abandons the previous provider without stopping it — blinding
the live feed and disarming the data arm's halt path *(from review, unverified)*.

*Design requirement:* ownership of every started resource is explicit, and replacement is a
transfer with teardown, not an overwrite.

---

## 4. The root cause — and the one thing a redesign does not automatically fix

The review's own diagnosis is that the new collaborators are individually sound:

> `VenueAccountManager`, `FeedConnectionBinder`, `PortfolioDefinitionStore`, the two-flag
> lifecycle and the migration are individually correct and individually well-tested. **The
> defects are all at the wiring seam between those new collaborators and the running live
> system** — precisely the place the phase's own test strategy does not reach, because
> every new unit and integration test constructs the collaborators directly rather than
> through `build_live_system`.

One root cause, four Criticals. **A redesign changes the design; it does not change the
test strategy.** Rebuild the same subsystem with tests that hand-construct collaborators
and the same class of hole reappears, however clean the new shape looks.

This is the same false-green pattern found independently three times in the same codebase:

| defect | proven on | production reality |
|---|---|---|
| `TradingRules.liquidation_fee_rate` | a hand-built `Instrument` | no builder ever sets it — every live liquidation prices its penalty at zero |
| `venue_accounts` reconnect refresh | an injected `lambda: [_FakeAccount(...)]` (8 of 8 tests) | the real callable returns `[]` |
| CR-01…CR-04 generally | directly-constructed collaborators | the assembled system is never built in a test |

The shared question that catches all three: **"does a production builder ever produce the
value this test is asserting on?"**

*Design requirement:* whatever replaces `build_live_system` must be **constructible
end-to-end in a test without credentials, from day one** — not as a later hardening pass.
If the assembled system cannot be built offline, the wiring cannot be tested, and this
section will be rewritten verbatim after the next review.

---

## 5. Specific things to collapse

**5.1 `is_venue_truth` is a type test wearing a property.** *(verified)*
Its only job is to let a caller ask "are you really a `VenueAccount`?" before calling a
method that does not exist on the alternative — **`snapshot()` and `start_streaming()` are
not on the `Account` ABC**, only on `VenueAccount`. The predicate exists to protect callers
from an `AttributeError`, not because behaviour differs.

Its docstring is honest about the intent: key the reconcile on account *kind* rather than
on `exchange == 'okx'`. That was a genuine improvement — but it replaced a string type-test
with a boolean type-test instead of removing the type-test.

The polymorphic version deletes it: put `snapshot()` on the ABC, make it a no-op on compute
leaves, and both guard sites plus the predicate disappear.

Cost of having kept it: 3 call sites, **2 user-facing error messages** in
`core/exceptions/portfolio.py` (so it is now operator vocabulary, not just plumbing), and
12 test references.

**5.2 A defensive `getattr` for a property the ABC defines.** *(verified)*
`portfolio.py` reads `getattr(account, "is_venue_truth", False)` — for an attribute the
`Account` ABC declares. Code that does not trust its own type contract is a scar; something
upstream was handing that seam objects that were not `Account`s. Find what, before
redesigning around it.

**5.3 Two near-duplicate "enumerate venue-truth accounts, dedup by identity" loops**
*(verified)* — one in `StreamRecoveryHandler._distinct`, one inline in
`ReconciliationCoordinator.run_startup_reconcile` (the latter an O(n²) list-of-`id()`
membership test). One derivation, one home.

---

## 6. Settle these before designing

**6.1 Is `is_venue_truth` currently `False` everywhere in live?** The review claims live
portfolios sit on compute leaves, which would make the venue reconcile, the drift halt and
the resume snapshot **all** inert today *(from review, unverified — my own check is
ambiguous: `OkxVenuePlugin.build_bundle` does construct a real `VenueAccount` via
`account_factory`, and `ComputeAccountAuthority` is documented as the backtest/in-memory
arm)*.

This is the highest-value unknown in this document. If the venue-truth layer is already
inert, there is less working behaviour to preserve than assumed — which makes the redesign
cheaper and changes what needs migrating.

**6.2 What is the actual venue count the design must serve?** Two today. If the honest
answer for the next year is "OKX plus paper", the plugin indirection is not paying for
itself and the design should be sized for two with a clear seam for a third — not for N.

**6.3 What replaces `compose_engine` for the backtest path?** It is shared by both modes.
The backtest arm is oracle-locked and must stay byte-exact; the live arm is being deleted.
Decide whether they diverge or stay unified **before** touching either.

**6.4 Does the reconnect-resume failure path need escalation?** Currently a reconnect that
cannot refresh venue truth stays paused and retries on the next stream-up, with only an
`error` log. An account that never successfully snapshots leaves the engine paused
indefinitely with no alert. Designed behaviour, or a missing failure counter?

---

## 7. Notes on reading the source material

**`CR-NN` is a per-review counter, not a global registry.** `11.2-CONTEXT.md` warns about
this in bold — *"Different ID namespace"* — because phase 11's review and phase 11.2's
review both define `CR-02`/`CR-03`. Plans in the 11.2 phase directory cite `CR-01` twice
and `CR-02` six times, but those may be closing *phase 11's* findings. **`CR-03` and
`CR-04` of `11.2-REVIEW.md` are cited by no plan at all** *(verified)*, and the review was
committed after the plans, so its findings are open by construction.

The same hazard applies to `D-NN` (per-phase counter, ~60 unrelated definitions of `D-04`)
and `T-NN` (per-plan threat counter). `FL-NN` and `GATE-NN` are genuine global registries.

**Related:** `.planning/todos/pending/comment-campaign-code-defects.md` (items 1 and 9 are
the two false-green defects above; items 5–7 are OKX-exchange cleanups in the same
subsystem), `.planning/todos/pending/comment-campaign-untested-safety-claims.md` (46
behavioural claims in this area defended by prose alone).
