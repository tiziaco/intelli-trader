# Venue / Account / Bundle Redesign — Requirements

**Status:** input document for a not-yet-scoped redesign. Not a plan, not a design.
**Scope:** `itrader/venues/`, `itrader/connectors/`, `itrader/storage/`,
`itrader/portfolio_handler/account/`, `portfolio_factory.py`, `trading_system/compose.py`,
`build_live_system`, and the portfolio↔account link — most probably all of:
- `trading_system/compose.py`
- `trading_system/backtest_trading_system.py`
- `trading_system/live_trading_system.py`
- `trading_system/venue_spec.py`
- `trading_system/session_initializer.py`
- `portfolio_handler/portfolio_factory.py`
- `connectors/provider.py`
- `connectors/base.py`
- `venues/lifecycle.py`
- `venues/feed_binder.py`
- `venues/paper_plugin.py`
- `venues/okx_plugin.py`
- `venues/assemble.py`
- `venues/bundle.py`
- `venues/bundles.py`
- `venues/registry.py`
- `storage/venue_store.py`, `storage/venue_account_store.py`,
  `storage/portfolio_definition_store.py`

**Provenance:** the four Criticals in
`.planning/phases/11.2-account-provisioning-bootstrap-review-closures/11.2-REVIEW.md`,
plus findings from the 2026-07-28 comment-reduction campaign, plus the owner's target
shape (§2) recorded 2026-07-29. Every claim below marked *(verified)* was re-checked
against HEAD on 2026-07-28 or 2026-07-29; claims marked *(from review, unverified)* are
inherited and must be confirmed before they drive a decision.

The owner's stated intent, which frames everything here: **`build_live_system`, the
initialisation logic, and the lazy imports all disappear.** §2 states positively what
replaces them. This document does not argue with either; it records what must not be lost.

> ## The must-have
>
> **Fewer moving parts. The refactor should delete more source than it adds.**
>
> This outranks every other goal in this document. A redesign that satisfies §2's target
> shape, preserves §4's constraints, closes §5's failure modes — and arrives at more code
> than it started with — has failed the thing it was for. Every new abstraction proposed
> below must be paid for by a larger deletion, or dropped.
>
> The baseline is measured, not asserted (§1.1), so the outcome is checkable rather than a
> matter of taste. **Tests are excluded from the metric** — see §1.1 for why that exclusion
> is not a loophole but a requirement.

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

### 1.1 The baseline the must-have is measured against

*(measured at HEAD, 2026-07-29, over the 27 files listed in **Scope** above)*

| metric | value |
|---|---:|
| files in scope | 27 |
| raw lines | **8,781** |
| code lines (excluding blanks, comments and module docstrings) | **3,968** |

Largest single modules: `live_trading_system.py` 1,577 · `venue_account_manager.py` 670 ·
`okx_plugin.py` 417 · `venue_uid_guard.py` 334 · `compose.py` 303.

**Tests are excluded from the metric, and this is a requirement rather than a
convenience.** §6 demands that the assembled system become constructible and testable
end-to-end offline — which means test code should *grow*. A metric that counted tests
would put the must-have in direct opposition to the one fix that addresses the root cause
of all four Criticals, and the cheapest way to satisfy it would be to skip exactly the
tests whose absence caused them. Source shrinks; tests grow.

**Where the deletions are, so the target is credible rather than aspirational.** Named
candidates, with the sizes known today:

- `build_live_system` and its initialisation logic — the largest single item, inside a
  1,577-line module; ~50 of the codebase's 116 body-imports die with it (§4.2).
- `compose.py` (303 raw / 131 code) — deleted or demoted to a mode-blind graph builder
  once the roots diverge (§2.4).
- The four assembly modules — `lifecycle.py` 79, `feed_binder.py` 66, `assemble.py` 41,
  `bundles.py` 39 code lines — consolidation candidates: 225 code lines to wire two
  venues.
- `is_venue_truth` and its scaffolding — the predicate, 3 call sites, 2 user-facing error
  messages, 12 test references (§7.1).
- `VenueBundle.account_factory` — a field that exists to stay in sync with a method
  (§7.4).
- The two duplicate venue-truth dedup loops (§7.3), the dead `venue_accounts` container
  (§5.2), and the defensive `getattr` for an ABC-declared attribute (§7.2).

**And the honest tension, stated so the target is set with eyes open.** Three things in
this document *add* source: the queryable catalogue surface (§8.3a), per-account
credential resolution (§8.3c), and whatever declares a data provider's auth requirement
(§2.2). The extracted restart bootstrap (§3) is a move rather than an add, but it will
not be free. These are the additions the deletions above have to outweigh — and if they
cannot, that is a finding worth surfacing early rather than discovering at the end.

---

## 2. Target shape — what the redesign is aiming at

The sections after this one are constraints and defects: what must not break, and what
went wrong. This section is the only one that says where to end up. A design that
satisfies §4–§7 while ignoring §2 will be correct and still wrong.

**The framing that matters most: this is a rewiring, not a rebuild.** The review's own
diagnosis (§6) is that the collaborators are individually sound and individually
well-tested — the defects are all at the seam between them. The components below mostly
already exist. What is being redesigned is how they name each other, how they are
assembled, and which of them are duplicates. Expect most of the current code to survive
in relocated, renamed, de-duplicated form.

### 2.1 The connector is authentication and session — nothing else

A connector owns venue credentials, one authenticated client, one event loop, and the
`connect`/`disconnect` lifecycle. It has **no method to fetch data and no method to
submit or cancel an order** — those are the jobs of the objects that hold it. Whoever
needs an authenticated venue (an exchange arm, an account, a private data stream) is
handed the connector and drives its own domain calls through it.

**This is already the written contract, and it is already true of the declared surface**
*(verified)*. `connectors/base.py` states it as D-02 — the connector owns auth, the single
`ccxt.pro` client, the loop-on-a-daemon-thread, sandbox/region routing, "and NOTHING
else. It knows nothing about orders-vs-candles-vs-balances." `LiveConnector` declares
exactly seven members: `call`, `spawn`, `client`, `sandbox`, `ws_hostname`, `connect`,
`disconnect`. No order ops, no candle ops.

Two honest caveats the redesign must decide about, because today the boundary is a
convention rather than a contract:

- **`client` leaks the whole venue API** *(verified)*. The property returns the raw
  `ccxt.pro` client, which carries every fetch and trade method there is. "The connector
  has no operations" is true of the Protocol and false of what a caller can reach through
  it. Enforcing the boundary (rather than stating it) is a design decision, not a
  cleanup.
- **`OkxConnector.set_halt_signal` is beyond the Protocol** *(verified,
  `connectors/okx.py:94`)* — safety wiring living on the session object.

### 2.2 Whether a data provider needs authentication is its own declaration

**The build seam keeps offering a connector.** A data provider that requires
authentication is a normal, expected case — private channels, account-scoped streams, any
broker whose market data sits behind a key — and future providers are more likely to need
one than not. Handing an auth object to something that may need auth does not violate
§2.1; that is precisely what the connector is for.

What must change is that authentication is currently **structural rather than declared**:

- **The OKX data plugin refuses to build without an authenticated venue account**
  *(verified, `venues/okx_plugin.py:403-411`)*: it reads `spec.account_id`, and a `None`
  raises `ValidationError` rather than building a public provider. Fetching OKX candles —
  public data on every exchange — is impossible today without naming a credentialed
  account.
- **`DataProviderPlugin.build_provider(ctx, spec, connectors)` takes the connector
  provider unconditionally** *(verified, `venues/bundle.py:197`)*. Acceptable as an
  *offer*; the defect is that no provider can say "I do not need this," so nothing
  distinguishes a provider that ignores the argument from one that depends on it.

*Design requirement:* each provider **declares** whether it needs an authenticated
session, and that declaration is readable from the catalogue (§8.3) without building
anything. A provider that declares no auth must be constructible with no venue account
and no credentials. A provider that declares auth may demand a connector and fail loudly
without one — that refusal is correct for *it*, and wrong as a property of the seam.

Two reasons this matters beyond tidiness. It is what makes offline, credential-free
construction of the assembled system possible (§6) — the property whose absence is the
root cause of all four Criticals. And it decouples research/backtest data acquisition
from the live auth stack: needing a key to pull historical bars drags ccxt and the whole
credential path onto a code path that has no business touching either (§4.2).

**Consequence to weigh, not to assume:** `ConnectorProvider`'s justification is that the
execution and data registries are two separate builders which would otherwise each
construct their own connector for the same venue, yielding two `ccxt.pro` clients per
`(venue, account_id)` *(verified, `connectors/provider.py:5-13`)*. That justification
holds exactly in proportion to how many data providers authenticate. If most do, the
shared-session memo earns its place; if most do not, it is largely solving a problem the
coupling created. Size the shared-session machinery **after** answering the declaration
question above, not before.

### 2.3 Execution venue and data provider are independent choices

Which venue fills an order and which source supplies bars are two separate decisions.

**Half-true today.** `ExecutionVenueRegistry` and `DataProviderRegistry` are already
separate types over separate Protocols, explicitly so the two selections stay independent
*(verified, `venues/registry.py:12-14`)*. But `VenueSpec` fuses the axes back together in
one object and **derives** `data_provider` from `execution_venue` when the caller does not
override it *(verified, `trading_system/venue_spec.py:87-89,114`)*. Two independent
registries, one spec choosing for both.

### 2.4 Two composition roots — live and backtest diverge

**Settled decision (2026-07-29):** there is no shared mode-aware composition seam. The
two roots are `trading_system/backtest_trading_system.py` and
`trading_system/live_trading_system.py`, and they share only the handler graph — never a
function that branches on run mode.

`compose.py` is the current entangler: its own docstring calls it "the mode-agnostic seam
both `build_backtest_system` and `build_live_system` consume" *(verified)*. Divergence
means deleting it, or demoting it to a pure handler-graph builder with no knowledge of
modes, no `Optional` collaborators and no mode-selector arguments.

What divergence buys, stated precisely so it is not over-claimed — see §4.2 for the
import census: it removes the ~50 body-imports that die with `live_trading_system.py`,
and it lets the wiring seam's `Any`-typed collaborators become real types. It does **not**
remove the ~66 body-imports in modules both modes share. Divergence and the §4.2 package
boundary are complementary; neither substitutes for the other.

### 2.5 SQL is the restart source of truth for portfolios, orders and venues

In live mode the durable store is authoritative across a restart:

- **Venues:** connecting to a venue registers it, so a restart knows to reconnect it.
- **Portfolios:** the system re-initialises the N portfolios it was trading in the
  previous session.
- **Orders:** the order mirror is durable and reconciles against venue truth.

**The stores already exist and already carry the right reads** *(verified)*:
`storage/venue_store.py` (`upsert`, `list_enabled`, `read_all`),
`storage/venue_account_store.py` (`create`, `set_enabled`, `read_enabled_for`,
`record_venue_uid`), `storage/portfolio_definition_store.py` (`upsert`, `read_all`,
`set_enabled`, `set_deleted`, `live_portfolio_ids_for_account`).

What does **not** exist independently of the module being deleted is the *bootstrap
sequence* that reads them. That is §3, and it is the single largest at-risk asset in this
redesign.

### 2.6 A catalogue of supported venues, brokers and data providers

The system should be able to answer "what venues do I support, and what credentials does
each need?" as **data** — without opening a session, and without a web layer importing
per-venue settings models.

Half-built today: `VenuePlugin.credential_model` exists for exactly this reason — so a
future integrations page can render per-venue credential form fields off the registry
with zero hardcoding *(verified, `venues/bundle.py:127-143`)*. What is missing is the
catalogue as a first-class, queryable surface separate from the live build/session
machinery. See §8.3.

---

## 3. The restart bootstrap — a contract that lives inside the module being deleted

The reads that implement §2.5 — `venue_store.read_all()`, the
`read_enabled_for` → `bring_online` loop, `definition_store.read_all()`, and
`rehydrate_portfolios` — all execute inside `build_live_system` *(verified:
`live_trading_system.py:995`, `:1336`, `:1345-1361`)*. Delete that function without first
extracting this section and live restart silently becomes a zero-portfolio, zero-venue
cold boot.

### 3.1 The ordering is load-bearing

The current sequence, in order *(verified, `live_trading_system.py:1310-1361`)*:

1. **Probe** that the `portfolios` table exists. Absent means first start or an un-run
   Alembic chain — a warning, **not** a fault. The probe is deliberately narrow (table
   existence only) so a genuine store fault still propagates loud rather than degrading
   into a silent zero-portfolio boot.
2. **`assert_distinct_accounts(persisted=definition_store.read_all())` — first**, so an
   account collision is refused *before* any account object exists.
3. **Venue assembly:** for each `venue_manager.read_enabled_for(exchange)` row,
   `bring_online(row)`; record the lifecycle under the row's account id verbatim. Then
   `rebind_feed()` **once**, after the loop — a boot with zero streaming accounts leaves
   the feed unbound and must log that cause.
4. **Then** `rehydrate_portfolios(store=definition_store, ...)`, recreating portfolios
   with their **persisted ids** so portfolio-scoped child tables and strategy
   subscriptions reattach to portfolios that still exist.

### 3.2 Step 3 before step 4 is a hard dependency, not a style choice

The live account authority gates on ACCT-03: `VenueValidatedComputeAuthority.account_for`
calls `manager.assert_available(venue_name, account_id)` and raises
`VenueAccountNotProvisionedError` unless the pair is provisioned **and** enabled **and**
brought online *(verified, `portfolio_factory.py:134-141`)*. Rehydrate before assembly
and **every live portfolio refuses to materialize**.

*Design requirement:* whatever replaces this sequence must make the dependency explicit —
portfolios cannot be materialized before their venue accounts are online — rather than
leaving it as an ordering that happens to be right in one function body.

### 3.3 Failure isolation is per entry, and that is deliberate

The restart config-layering pass degrades clean at **per-row granularity** *(verified,
`live_trading_system.py:975-1028`)*: the order-config load, each venue row, and each
portfolio's stored config are separately guarded, so one poisoned `config_json` degrades
only that venue or that portfolio instead of aborting boot. The acquisition (`read_all`)
carries its own guard; the per-entry push carries another.

*Design requirement:* preserve the granularity, not merely the guard. A single
try/except around the whole bootstrap satisfies "it degrades clean" and loses the
property that matters.

### 3.4 The collaborator that is `Optional` and late-assigned

`PortfolioHandler.definition_store` is initialised to `None`, then lazily imported and
assigned inside `__init__` when a `sql_engine` is present, and every use site is guarded
`if self.definition_store is not None` *(verified,
`portfolio_handler/portfolio_handler.py:75-80, 249-251, 367-368, 402-417`)*.

This is the `None`-then-assign shape the owner has ruled against elsewhere, and it exists
here for the GATE-01 reason in §4.2. With two roots (§2.4), the live handler can hold a
real store at construction and the backtest handler can be a type that has none.

---

## 4. Hard constraints — these survive any redesign

**4.1 The backtest oracle stays byte-exact.** 134 trades, `final_equity
46189.87730727451`, 3076 equity points. This is the program-level definition of done, not
a nice-to-have.

Both construction arms are now locked *(verified)*:
- `tests/integration/test_backtest_oracle.py` — the legacy arm
- `tests/integration/test_backtest_oracle_factory_arm.py` — the factory /
  `compose_engine` arm (added 2026-07-28, commit `1ed32e1e`)

Before that second gate existed, a change confined to the factory path passed every test
while proving nothing. **If the redesign introduces a third construction path, it needs
its own oracle assertion on day one** — the existing two will not see it. Note that §2.4
(two roots) guarantees the backtest root changes shape; whichever arm survives must carry
an oracle assertion from its first commit, not after it works.

Related trap, worth stating because it already cost time: `test_results_persist.py`
mentions both `build_backtest_system` and the golden final-equity constant, but its
byte-exact test builds via the *legacy* arm and its factory tests use a short 2018→2021
window. It is **not** factory-arm oracle coverage. Two symbols in one file is not a gate.

**4.2 Import inertness (GATE-01) is preserved — but as a package boundary, not as import
placement.** `import itrader` must pull no ccxt, no sqlalchemy, no asyncio stack;
`tests/integration/test_okx_inertness.py` proves it.

The lazy imports currently carry that guarantee, and they are going away. The structural
replacement is a subpackage boundary the backtest path never imports, with the existing
inertness test enforcing it. Then every import sits at the top of its file where it
belongs, and the property is enforced by the module graph rather than by remembering
where to indent an import. **The lazy imports are a workaround for a boundary that was
never drawn — draw the boundary and they become unnecessary rather than merely
unwanted.**

**The census, so the job is not under-scoped** *(verified 2026-07-29, AST count of
function-body imports across `itrader/`)*: **116 body-imports in 26 files.**

| location | count | removed by root divergence (§2.4)? |
|---|---:|---|
| `trading_system/live_trading_system.py` | 50 | yes — the module goes |
| `venues/okx_plugin.py`, `price_handler/providers/okx_provider.py`, `execution_handler/exchanges/okx.py`, `portfolio_handler/account/venue.py` | 18 | yes, if OKX lands behind the boundary |
| the four `*/storage/storage_factory.py` | 14 | **no** — both modes import them |
| `venues/paper_plugin.py`, `venues/venue_account_manager.py`, `venues/venue_uid_guard.py` | 10 | **no** — backtest uses paper |
| `portfolio_handler/{portfolio_handler,validators}.py`, `portfolio_handler/{position,transaction,metrics}/*_manager.py`, `core/sizing.py`, `config/itrader_config.py` | ~12 | **no** — shared core domain |
| remainder | ~12 | case by case |

So root divergence removes roughly 43%. The rest sit in modules **both** modes import and
move only if the boundary is drawn — or if they turn out not to be inertness workarounds
at all.

**They are not all the same thing, and the design must classify before it deletes.**
Three distinct reasons a body-import exists here, with three different fixes:

- **GATE-01 inertness** — e.g. the four `storage_factory.py` files keeping SQL off the
  backtest graph. Fixed by the package boundary.
- **Circular-import avoidance** — suspected for `portfolio_handler/validators.py` and the
  three `portfolio_handler/*/manager.py` modules *(unverified — confirm before acting)*.
  This is a layering defect wearing an import trick; a boundary does not touch it,
  correct layering does.
- **Genuinely optional dependency** — legitimate; keep.

*Design requirement:* "remove all the lazy imports" reads as one job and is at least
three. Classify all 116 before treating any of them as uniform.

**The `Any`-typing consequence is the sharper prize.** Because naming the real types would
drag the venue substrate onto the backtest import graph, the wiring seam types its
collaborators as `Any`: `PortfolioFactory.authority` / `.sql_engine`,
`ComputeAccountAuthority.venue_bundles` *(verified,
`portfolio_factory.py:36-40, 152-181`)*, `VenueAccountConfig.connectors` / `.spec` /
`.state_storage` and every `VenuePlugin`/`DataProviderPlugin` build argument *(verified,
`venues/bundle.py:65-67, 145-147, 197`)*. Fifty-six files carry `TYPE_CHECKING` blocks
*(verified)*.

That means the inertness workaround **silently disables `mypy --strict` at exactly the
wiring seam where all four Criticals live** — the same seam §6 shows the tests do not
reach. Restoring real types there is a checkable, gate-able outcome of the redesign, not
a stylistic preference.

**4.3 Money stays `Decimal` end-to-end.** `float()` only at serialization/logging edges.

**4.4 Determinism.** One seeded `random.Random` built at wiring from `config.rng_seed`,
carried on the engine context, reaching the exchange. Exactly one per run. Never seeded
per-call.

**4.5 Queue-only cross-domain writes; read-models for reads.** Handlers emit events, never
call across domains. Read-only cross-domain access goes through an injected read-model
(`PortfolioReadModel`, the bar feed). The single-writer contract — all state mutation on
the engine thread — is what makes the absence of a portfolio-collection lock correct.

---

## 5. Failure modes the new design must make structurally impossible

Each of these is a real defect found in the current wiring. They are stated as properties
to design against, not as patches to apply — the code they live in is being deleted.

**5.1 A collaborator that is built but not reachable.** *(CR-01)*
`VenueAccountManager` is constructed as a local inside `build_live_system` and never
attached to the facade *(verified: no `venue_accounts` property exists on
`LiveTradingSystem`)*. The phase's headline deliverable — runtime account provisioning
without a restart — therefore has no entry point at all, and the typed refusal message
tells operators to call an attribute that does not exist.

*Design requirement:* a collaborator that is not reachable should not be constructible, or
its unreachability should be a startup error rather than a silent success.

**5.2 A set derived from a container nothing writes.** *(CR-03)*
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

**5.3 Something routable before it is connected and halt-wired.** *(CR-04)*
`bring_online` publishes an account's exchange into the order-routing registry before the
session is connected or its halt signals are wired *(from review, unverified)*.

*Design requirement:* registration into a routing surface is the **last** step of bring-up,
after every safety wire is armed. An order must not be routable to a venue that cannot
halt.

**5.4 A resource built, then abandoned without teardown.** *(CR-02)*
The feed re-borrow path builds a provider that is never subscribed, never halt-wired and
never stream-state-wired, and abandons the previous provider without stopping it — blinding
the live feed and disarming the data arm's halt path *(from review, unverified)*.

*Design requirement:* ownership of every started resource is explicit, and replacement is a
transfer with teardown, not an overwrite.

---

## 6. The root cause — and the one thing a redesign does not automatically fix

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

Note the interaction with §4.2: the `Any` typing means the type checker is blind at this
same seam. Tests that do not reach it plus types that do not describe it is why four
Criticals could all live in one function.

---

## 7. Specific things to collapse

**7.1 `is_venue_truth` is a type test wearing a property.** *(verified)*
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

**7.2 A defensive `getattr` for a property the ABC defines.** *(verified)*
`portfolio.py` reads `getattr(account, "is_venue_truth", False)` — for an attribute the
`Account` ABC declares. Code that does not trust its own type contract is a scar; something
upstream was handing that seam objects that were not `Account`s. Find what, before
redesigning around it.

**7.3 Two near-duplicate "enumerate venue-truth accounts, dedup by identity" loops**
*(verified)* — one in `StreamRecoveryHandler._distinct`, one inline in
`ReconciliationCoordinator.run_startup_reconcile` (the latter an O(n²) list-of-`id()`
membership test). One derivation, one home.

**7.4 `VenueBundle.account_factory` duplicates `VenuePlugin.new_account`.** *(verified)*
The bundle carries a `Callable[..., Account]` field whose only job is to delegate straight
to the plugin's own `new_account` method — the docstring says the field exists so the two
"can never mint different accounts" *(`venues/bundle.py:95-99, 149-170`)*. A field that
exists to stay in sync with a method is a duplicate defended by a comment. If the bundle
carries the plugin, the field is unnecessary.

---

## 8. Construction doctrine — when is a factory warranted

This section exists because the owner's question — "I introduced a `PortfolioFactory`; do
I need one for venues, accounts and connectors too?" — currently has no principled answer
in this codebase. There are **five different names for "an object that constructs
another object"**, with no stated rule separating them.

### 8.1 The inventory *(verified)*

| called | example | what it actually is |
|---|---|---|
| `Factory`, holds deps | `PortfolioFactory.materialize` | a builder holding real collaborators, with a non-trivial mapping (definition → runtime graph) |
| `Factory`, static switch | `OrderStorageFactory`, `PortfolioStateStorageFactory`, `SignalStorageFactory`, `StrategyRegistryStorageFactory` | an environment-string `if`, no state, could be a function |
| `Authority` | `ComputeAccountAuthority`, `VenueValidatedComputeAuthority` | a factory that does not say factory — the injected arm that *is* the mode difference |
| `Plugin` | `VenuePlugin.build_bundle`, `DataProviderPlugin.build_provider`, `ConnectorPlugin.build` | a per-venue factory, selected by name |
| `*_factory` callable field | `VenueBundle.account_factory` | a duplicate of a Protocol method (§7.4) |

Five names, and a reader cannot predict from any of them whether the thing holds state,
selects an implementation, or merely calls a constructor.

### 8.2 `ConnectorProvider` is three responsibilities in one class *(verified)*

`connectors/provider.py` fuses:

1. **the catalogue** — `dict[str, ConnectorPlugin]`, name → build recipe;
2. **the factory** — `self._plugins[venue].build(spec)`;
3. **the session pool** — the `(venue, account_id)` memo, `close_all()` teardown, and the
   session-identity conflict guard that refuses a re-ask whose `secret_ref` / `sandbox` /
   `region` disagree with the memoized session (`provider.py:113-140`).

Only (3) has a hard reason to be a stateful object: it owns live sessions and their
lifetime. (1) is data. (2) is one method call. That split is the worked example the
doctrine should be derived from.

### 8.3 The catalogue — mostly built, and the gap is not where it looks

**The credential-declaration mechanism the owner wants already exists and already works
the way he describes it.** A per-venue Pydantic settings class declares what that venue
needs, and the plugin exposes the class *(verified)*:

- `config/okx_settings.py::OkxSettings(BaseSettings)` — `api_key` / `api_secret` /
  `api_passphrase` as `SecretStr`, plus `sandbox` and `region`, each bound to a
  `validation_alias`, with a required passphrase that fails loud rather than shipping a
  half-authenticated client.
- `OkxVenuePlugin.credential_model` returns that class *(a `@property` with a lazy import
  — the module's AST inertness gate rejects a plain `credential_model = OkxSettings`
  attribute)*.
- `PaperVenuePlugin.credential_model` returns `None` — "a paper account has no
  credentials to collect." **The owner's paper exception is the implemented behaviour, not
  a change to make.**

**`None` is already semantic, not merely absent.** `venue_uid_guard.py:221-243` branches
on `credential_model is None` to distinguish a credential-less venue's legitimate missing
venue-UID (`REASON_NO_VENUE_IDENTITY`, a clean no-op) from a *credentialed* venue that
returned `None` because its endpoint broke or a field was renamed
(`REASON_UID_UNAVAILABLE_CREDENTIALED`). Reshaping this triple — model / `None` / raised —
silently reclassifies a venue degradation as a paper no-op. Any redesign of the catalogue
must carry that distinction forward.

*So the design requirement is not "build the mechanism." It is three narrower things:*

**(a) Make it queryable without constructing anything.** Answering "what venues exist and
what does each need?" still requires reaching a plugin instance through the live build
path. The catalogue should be readable as data: venue names, credential model,
capabilities (execution / private data / public data), and the §2.2 auth declaration.

**(b) Decide whether one model serves both purposes.** `OkxSettings` mixes two kinds of
field: real secrets (`api_key`, `api_secret`, `api_passphrase` — `SecretStr`) and
**session routing** (`sandbox`, `region` — non-secret, and exactly two of the three
`_SESSION_IDENTITY_FIELDS` the connector memo's conflict guard keys on, `provider.py:44`).
A UI rendering "the credentials for this venue" would render routing controls too, and a
catalogue exposing the model exposes both. One model with the two kinds marked, or two
models? Decide explicitly — this is the one place the current design has genuinely not
chosen.

**(c) Close the per-venue → per-account gap, which is the real open half.** Declaring
*which* credentials a venue needs is solved. Resolving *which credentials this account
uses* is not. The source already records the hazard: `populate_by_name` was added to
`OkxSettings` specifically because per-account credentials (MPORT-06) must be constructed
from a resolved mapping rather than the ambient process environment — otherwise two
`account_id`s connect with **identical keys** *(verified, `config/okx_settings.py:62-72`,
the D-12 caveat)*. Today the field names bind to bare `OKX_API_*` environment variables,
so the default construction path is process-global by design. A catalogue of N venues
each claiming bare unprefixed env names compounds this.

That gap is the one that produces a wrong-account live order, so it outranks the UI
surface in (a).

### 8.4 The rule to settle — open

A candidate rule, offered as a starting point rather than a decision:

- **Does it need held state or injected collaborators to build correctly?** → an object.
  (`PortfolioFactory` qualifies: it holds an authority, an environment and a SQL engine,
  and does a real mapping. So would a connector *session pool*.)
- **Does it select between implementations by a key?** → a registry or catalogue, and
  the selection should be data, not a class.
  (The three `*StorageFactory` classes and the plugin lookup are this.)
- **Does it only call a constructor with rearranged arguments?** → delete it and call the
  constructor.
  (`VenueBundle.account_factory` is this.)

*Open questions for the design session:*
- Adopt this rule, amend it, or replace it — but state one, and name every constructing
  object in the new design against it.
- Pick **one** vocabulary. Five names for one role is the measurable symptom; unifying
  them is a stated goal of this redesign.
- Does `Authority` survive as a distinct concept (a *validating* factory), or is it a
  factory whose injected policy differs?

---

## 9. Settle these before designing

**9.1 Is `is_venue_truth` currently `False` everywhere in live?** The review claims live
portfolios sit on compute leaves, which would make the venue reconcile, the drift halt and
the resume snapshot **all** inert today *(from review, unverified — my own check is
ambiguous: `OkxVenuePlugin.build_bundle` does construct a real `VenueAccount` via
`account_factory`, and `ComputeAccountAuthority` is documented as the backtest/in-memory
arm)*.

This is the highest-value unknown in this document. If the venue-truth layer is already
inert, there is less working behaviour to preserve than assumed — which makes the redesign
cheaper and changes what needs migrating.

Sharpened 2026-07-29: `VenueValidatedComputeAuthority.account_for` **always** builds a
compute leaf, never a `VenueAccount` — because `VenueAccount.balance` raises until the
first venue snapshot while `Portfolio.__init__` reads balance at construction, so the
venue-truth swap is deferred (COMP-07) *(verified, `portfolio_factory.py:107-141`)*. That
is strong evidence for the review's claim. What remains unverified is whether anything
later performs the swap.

**9.2 What is the actual venue count the design must serve?** Two today. If the honest
answer for the next year is "OKX plus paper", the plugin indirection is not paying for
itself and the design should be sized for two with a clear seam for a third — not for N.
Note this interacts with §8.3: a *catalogue* of supported venues is worth building even at
N=2, because its consumer is a UI, not the engine.

**9.3 What replaces `compose_engine` for the backtest path? — SETTLED.** The roots
diverge; see §2.4. `compose.py` is deleted or demoted to a mode-blind handler-graph
builder. The remaining work is deciding exactly which graph construction is genuinely
common and giving it a home that neither root has to branch inside.

**9.4 Does the reconnect-resume failure path need escalation?** Currently a reconnect that
cannot refresh venue truth stays paused and retries on the next stream-up, with only an
`error` log. An account that never successfully snapshots leaves the engine paused
indefinitely with no alert. Designed behaviour, or a missing failure counter?

**9.5 How much of the connector boundary is enforced vs. conventional?** §2.1: `client`
hands out the full venue API. Decide whether the redesign narrows that surface (a typed
per-domain view over the session) or keeps the raw client and enforces the boundary by
review. Not settling this means "the connector has no operations" stays a comment.

---

## 10. Notes on reading the source material

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
