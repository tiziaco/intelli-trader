# Venue / Account / Composition Redesign — Execution Log

**Purpose:** what execution learned that the plan could not know in advance. The plan
(`VENUE-ACCOUNT-REDESIGN-PLAN.md`) remains the authority on sequencing, gating and the
settled decisions ED-1..ED-11 — nothing here overrides it. This file records amendments,
findings and carried-forward dependencies so a later session (or a different agent) does
not re-derive them.

**Status:** Stages 0–6 complete and committed. Next: Stage 7. **All four Criticals are
fixed and the suite carries ZERO xfails.**

| stage | commits | gate state at commit |
|---|---|---|
| 0 | `3a2c7692` | 3028 pass / 6 skip / 4 xfail · baseline 27 / 9,243 / 3,886 |
| 1 | `6d3596dc`, `8497434e` | 3028 pass / 6 skip / 4 xfail · successor +30 |
| 2 | `00afc644` | 3069 pass / 6 skip / 4 xfail · successor +207 |
| 3 | `44d40f71`, `ebf28c7f` | 3053 pass / 6 skip / **3 xfail** · successor **+4** |
| 4 | `1badab20`, `f75df648` | 3043 pass / 6 skip / **2 xfail** · successor **+60** |
| 5 | `0a02be39` | 3039 pass / 6 skip / **1 xfail** · successor **−34** |
| 6 | `4adeed3f`, `a6f013f4`, `b0450fc1` | 3057 pass / 6 skip / **0 xfail** · successor **+983** |

CR ledger: **all four fixed** — CR-03 (Stage 3), CR-04 (Stage 4), CR-02 (Stage 5), CR-01
(Stage 6). `tests/integration/test_live_composition_offline.py` carries no `xfail` at all
now, so any regression in the four invariants reddens the suite directly.

**Stage 6's +983 is the two shapes coexisting, by design** — the plan defers every deletion
to Stage 7 so this diff stays reviewable and the gates stay attributable. `build.py` (341)
+ `system.py` (469) + `exchanges/paper.py` (28) = **838 code lines** against the ~1,125
budget, replacing `live_trading_system.py`'s 788. The Stage-7 deletion pool measures
**1,270**, so the projected final delta is **−287**: the must-have passes with 287 lines of
headroom. Risk #3 did not fire.

**The per-stage successor deltas in the table above are measured against the OLD 27-file
manifest and are all understated — see §2.15.** On the corrected 31-file yardstick the
gate stands at **+118** after Stage 5, and `--gate` fails today, as it should. Stage 6
onward reports the corrected number.

**The deletion gate moved the WRONG WAY in Stage 4 (+4 → +60).** The absorption itself
shrank (four modules, 530 code lines → `accounts.py` 485 = −45), but modules that are
themselves scheduled for deletion grew by +89: `live_trading_system.py` 751→785,
`bootstrap.py` 121→156, `paper_plugin.py` 63→76, `feed_binder.py` 66→73. Roughly 1,310
code lines still stand against the Stage-6 replacements, so the must-have remains
reachable — but plan risk #3's "stop and report if the sign trends positive" now has a
live precedent one stage early. Watch it at Stage 5, not only at Stage 6.

---

## 1. Amendments to the plan

### 1.1 Appendix omission — one more Stage-3 disposition

`tests/unit/execution/test_supervisor_catchall.py` is NOT in the Test Disposition Table but
its section (2) drove `VenueAccount._stream_account` / `_stream_positions`, which the stage
deletes. Disposed by the table's own rule (mechanism has no successor → DELETE that
section; the `OkxExchange` / provider sections KEEP). Already applied.

### 1.2 ED-10 landed in Stage 3, not Stage 6

Deleting `account/venue.py` left `OkxVenuePlugin.new_account` with nothing to mint.
`build_compute_account(...)` therefore landed in its ED-10 home
(`portfolio_handler/account/simulated.py`) during Stage 3, and both venue arms delegate to
it. **Stage 6 must not re-create it** — only re-point `portfolio_factory.py` at it as
planned.

### 1.3 CR-03's probe asserts the ENUMERATION SOURCE, not the adapter list

`test_cr03_...` reads `system._stream_recovery._accounts()`, not `_streaming_adapters()`.
Deliberate: the offline gate uses a **paper** account, which legitimately carries no
connector and so has no streams to recover — but the handler must still be wired to
something that reports it online. Asserting the filtered adapter list would make the probe
vacuous for paper.

### 1.4 Stage 7's measurement command gains `--gate`

`scripts/measure_redesign_baseline.py` now distinguishes reporting from gating:

```bash
# informational (any stage)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt
# the must-have, as an exit code (Stage 7)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt --gate
```

Also: `scripts/redesign_successor_manifest.txt` **already exists** and is maintained as
stages land (Stage 7 does not author it, only completes it). See §3.1 for why.

### 1.5 Coordinator surface already reduced

`ReconciliationCoordinator._exchange_for` and its `execution_handler` ctor param were
deleted in Stage 3 as dead code (the adapter now comes off `record.bundle.exchange`). Stage
6 plans no work here, but any Stage-6 rewrite of the construction site should not
re-introduce them.

### 1.6 Manager gained `online_records()`; facade holds `_venue_manager` privately

`VenueAccountManager.online_records()` is the one enumeration the safety and reconcile
planes read. Stage 4 must carry it into `venues/accounts.py`.

The facade already holds `_venue_manager` **privately** (the reconcile coordinator needs it
at `start()`). CR-01 is about the **public** operator surface (`system.venue_accounts`) plus
required constructor arguments — still Stage 6, still red.

---

### 1.7 `build_okx_exchange` was a Stage-3 deliverable that landed in Stage 4

Plan line 338 assigns the recipe to Stage 3, "consumed in Stage 4". Stage 3 delivered
`build_compute_account` but left the exchange-construction knowledge in
`OkxVenuePlugin.build_bundle`. Stage 4 created it in its ED-3 home
(`execution_handler/exchanges/okx.py`, TAB), absorbing the stream-symbol read, the
`quote = symbol.split("/")[1]` settlement derivation, the `_OKX_DEFAULT_MARKET_TYPE`
constant and the uncoerced-`account_id` refusal.

It does NOT carry the mismatched-`account_id` refusal (`okx_plugin.py:361-374`). That
scenario has no representation any more: the pool session and the recipe read the SAME
`AccountSpec`, so a bundle serving two ids cannot arise.

`fetch_venue_uid()` joined the adapter contract in the same commit (moved verbatim off
`OkxVenuePlugin`; simulated returns `None`) — the TOFU check is keyed off the adapter and
the descriptor now, never a plugin object.

### 1.8 `bring_online` connects, so the boot loop moved into `start()`

Design §4.5 puts `adapter.connect()` inside `bring_online`, before registration. The boot
loop was invoked from `build_live_system`, so leaving it there would have made
CONSTRUCTION perform venue I/O — breaking the `test_okx_arm_*` tests that build
`for_exchange("okx")` offline against dummy credentials. The whole restart sequence
therefore moved into `start()`.

It travels as one bound callable (`facade._restart_sequence`), not three loose steps:
moving only `bootstrap_session` would have run `layer_persisted_overrides` and
`rehydrate_strategies` BEFORE the portfolios existed, so portfolio config overrides would
have iterated an empty collection — a silent ordering regression.

`start()`'s per-lifecycle loop and its streaming `exchange.connect()` loop are gone (the
bring-up does both), and `_venue_lifecycles` died with `VenueLifecycle` — every reader now
reads `online_records()` live, per the CR-03 rule.

### 1.9 An identity mismatch REFUSES the bring-up

Plan line 456 asks for "identity-check mismatch ⇒ unroutable + alert", which is stronger
than design §4.4's observe-only framing. The plan wins. The guard FUNCTION is unchanged
and still never halts; the MANAGER raises on `REASON_MISMATCH_ALERTED`, so the boot
quarantines that one account and every other account stays online. Registration being the
last step is what makes the proportionate response expressible at all.

The three lifecycle-level guard reasons (`GUARD_REASON_NOT_STARTED` /
`_PAPER_NO_CONNECTOR` / `_COLLABORATORS_ABSENT`) died with the states they described: the
guard now runs inside `bring_online` with required collaborators, and paper maps onto the
guard's own `REASON_NO_VENUE_IDENTITY`.

### 1.10 Two manager surfaces changed beyond the plan's list

`account_for` was DELETED (it delegated to `VenueBundles.account_for`, the manager no
longer holds a bundle memo, and its own docstring recorded it as unreached from the live
path). `assert_available` survives as the portfolio gate.

`bring_online` is now idempotent per pair — a second call returns the existing record
rather than opening a second session and double-spawning that account's streams.

### 1.11 The Stage-4 test cascade exceeded the Disposition Table

Moving the boot into `start()` reached eight files the table does not list:
`test_off_loop_halt_write`, `test_early_durable_halt_refusal`,
`test_resume_gated_on_all_streams`, `test_resume_missed_fill_catchup`,
`test_distinct_account_invariant`, `test_multi_portfolio_lifecycle`,
`test_strategy_registry_restart`, `test_strategy_external_add_lifecycle`. All were
mechanical (stub the session, then drive the production boot) through new helpers in
`tests/support/live_okx.py`, and no composition-root rewrite was required — so the
escalation rule did not fire. `test_live_system_okx_wiring.py`'s three binder tests and
three `start()`-connect tests were replaced one stage early; their invariants are re-homed
to `test_accounts.py` and to two new tests in the same file.

### 1.12 The public OKX session: a routing BASE class, not optional credentials

`build_okx_connector(spec=None)`'s `NotImplementedError` (log §2.1) is closed by splitting
`config/okx_settings.py` along the D-6 `kind` marking that was already on the fields:
`OkxRouting(BaseSettings)` holds the two `routing` fields plus `rest_hostname` /
`ws_hostname` and a `ccxt_credentials() -> {}`; `OkxSettings(OkxRouting)` adds the three
`secret` fields — **still required** — and overrides `ccxt_credentials()` with the ccxt
triple. `_build_client` splats that method and keeps every routing knob unconditional.

**The rejected alternative matters more than the chosen one.** Making the three credential
fields `Optional` would have been the obvious fix and would have silently killed a security
control: `build_okx_connector` derives its completeness gate as
`{name for name, f in credential_model.model_fields.items() if f.is_required()}`, so an
empty required-set makes `missing` permanently empty and the refusal to complete a partial
credential set from the ambient `OKX_API_*` environment becomes dead code. A public session
is a DIFFERENT settings class instead, so the gate is untouched. Verified at HEAD:
`OkxSettings` still requires `api_key` / `api_secret` / `api_passphrase`.
`test_every_credential_field_stays_required` is the tripwire on that premise, and the
connector's no-arg default stays `OkxSettings()` so a bare connector cannot drift public.

### 1.13 Public-session routing comes from the process env

`pool.public_session(venue)` takes no spec by design, so the public session's `sandbox` /
`region` resolve from `OKX_SANDBOX` / `OKX_REGION`. If an account row pins routing that
disagrees with the ambient env, orders and candles can reach different regional entities.
Flagged deliberately and NOT changed — giving public sessions a per-caller identity is
exactly what makes them shareable, and re-introducing one would undo §4.6.

### 1.14 `data_requires_auth=True` is implemented but unreachable

No catalogued venue declares it. The branch exists per the plan's text, with an explicit
refusal when the run names no account, rather than a silent fallback.

### 1.15 `route_orders_by_account` died by NAMING the compute venue's one account

The plan's premise for retiring the mode flag was factually wrong: backtest portfolios did
NOT sit under `('paper', 'default')`. That pair was only a memo key, while the leaf carried
`account_id=None`. Negative control at commit 1 (flag forced `True` on the old shape):
**every order refused, 0 trades, final equity 10,000.00** — `No exchange registered for
venue/account (paper, None)`.

What made uniform routing byte-exact is the compute authority NAMING the compute venue's
one account when a portfolio names none. `ExecutionHandler.portfolio_read_model` became
REQUIRED and `_resolve_account_id`'s default-constant branch was deleted, so the selector is
dead at every layer rather than relocated. Visible consequence: a backtest
`Portfolio.account_id` is now `'default'`, not `None`. Both oracles stay byte-exact
(134 / `46189.87730727451`).

### 1.16 The MPORT-07 fence inside `AccountFactory` — and why only ONE test guards it

`AccountFactory.account_for` has **two separate return statements**. The validator arm calls
`validate(...)` then builds with `account_id` VERBATIM; the `DEFAULT_ACCOUNT_ID` naming is
written INSIDE the validator-less return. Resolving the default once above the branch —
the obvious tidy-up — silently coerces an unnamed LIVE portfolio onto the default account:
a cross-account misroute with every lookup above it still reading correct.

**`tests/unit/test_account_identity_coercion_gate.py` does NOT catch that.** It scans
`portfolio_factory.py` only in its POSITIVE half (a pinned per-file count), and a relocated
coercion keeps the count at 1. Independently reproduced: applying the tidy-up reddens
`test_a_validator_that_accepts_an_unnamed_account_still_builds_an_unnamed_leaf` while the
static gate stays GREEN. That behavioural test is the only tripwire — do not delete it, and
do not "simplify" the two returns into one.

### 1.17 WR-07 closed by a DIFFERENT mechanism than the plan specified — see §2.16

The plan's step 1 ("`build_live_system` REFUSES to build without a SQL spine") was attempted
and abandoned on evidence. What landed instead: durability follows the SPINE rather than an
environment string, so the WR-07 configuration — a real spine whose portfolio durability is
silently off — is unreachable from the new root; and the spineless arm survives with a loud
`NOT DURABLE` warning naming exactly what is lost. This satisfies `11.2-REVIEW.md`'s own
wording ("gate on the presence of the spine, or log loudly"). The hard refusal remains
available as a ~5-line change once §2.16 is resolved.

## 2. Carried-forward dependencies

### 2.1 Stage 5 — OKX public sessions need a credential-free client arm (BLOCKING)

`ConnectorPool.public_session(venue)` is implemented and unit-tested, but
`build_okx_connector(spec=None)` **raises `NotImplementedError`**:
`OkxConnector._build_client` reads all three `OKX_API_*` fields unconditionally, so there is
no credential-free construction to return.

The refusal is deliberate — silently returning an authenticated session under a public name
would recreate, invisibly, the borrowed credentialed session that public sessions exist to
remove. Stage 5 (data adapter over its own public session, CR-02) therefore needs a public
arm in the client build. Tested refusal:
`tests/unit/connectors/test_okx_connector_recipe.py::test_a_public_session_is_refused_loudly_rather_than_returned_authenticated`.

### 2.2 Stage 5 candidate — `catch_up_missed_fills` is not on the adapter contract

`StreamRecoveryHandler.on_reconnect` calls `catch_up_missed_fills()` on every
connector-bearing adapter, but the method is not declared on `AbstractExchange`. It fails
safe today (a missing method lands in the stay-paused + CRITICAL-alert arm), yet the resume
contract is duck-typed rather than declared — the same gap D-5 just closed for
`set_halt_signal`. Worth folding into Stage 5's D-5-style pass.

### 2.3 Stage 6 — `('paper', 'default')` is registered unconditionally

`compose_engine` registers the compute venue's baseline exchange under
`(paper, 'default')` on **every** arm, independent of any durable `venue_accounts` row. On
the live arm that means the default paper account is order-routable with no provisioned row.

Not one of the four Criticals and not in the plan's scope, but Stage 6 rewrites both roots,
so it is a decision point rather than something to preserve by accident. The offline gate
asserts around it (object distinctness), documented in the test.

### 2.4 Stage 6 — WR-03 is observable through the built system

`add_portfolio` on a SQL spine refuses an unprovisioned account with `IntegrityError` from
the composite FK, **not** `VenueAccountNotProvisionedError`: the durable insert runs before
the authority validates. `test_a_portfolio_naming_an_unprovisioned_account_is_refused` is
deliberately type-open (asserts "raises, and no portfolio/row survives") and must be
**tightened to the typed error** when Stage 6 closes WR-03.

### 2.5 Behaviour change to be deliberate about

The startup venue reconcile now runs for every account the manager reports ONLINE,
including one no portfolio holds (it was portfolio-driven, and inert, before). This is
consistent with the reconcile being store-intent-vs-venue and account-scoped, but it means
the `orders` table must exist for any online account —
`tests/integration/test_live_system_okx_wiring.py` provisions it explicitly for this reason.

---

### 2.6 Stage 5 — the data arm still borrows an account session (transitional shims)

`FeedConnectionBinder.data_provider` and `PoolBackedConnectors` were added in Stage 4 so
the exec and data arms keep sharing one session while the binder lives; without them the
data arm would open a SECOND `ccxt.pro` client per account. Both die with
`venues/feed_binder.py` in Stage 5, along with `manager.rebind_feed` / `feed_provider` /
`_streaming_available` and the `facade._feed_binder` reads in `start()` and
`_initialize_live_session`.

`venues/paper_plugin.py::paper_exchange_recipe` is the matching transitional seam on the
execution side — ED-3 replaces its BODY with `build_paper_exchange` in
`execution_handler/exchanges/paper.py` at Stage 6 **without touching the manager**, because
the recipe mapping is a constructor argument.

### 2.7 Stage 5 — the feed provider is halt-wired in `start()`, deliberately

Wiring it inside the binder instead would make the CR-02 xfail start PASSING, and
`strict=True` turns that into a loud suite failure. Stage 5 must move that wiring into the
data-adapter build in the SAME commit that un-xfails CR-02.

### 2.8 Stage 6 — `_restart_sequence` is where the boot ordering now lives

It is a bound closure on the facade, and it is the single home of the
bring-up → rehydrate → layer-overrides order. `build.py` should INLINE it as design §4.9
steps 7–8 rather than re-create the closure. `_bootstrap_session()` is the seam the
offline and OKX tests drive.

### 2.9 A live PAPER system now imports ccxt

`build_live_system` imports `build_okx_connector` in its body to populate the connector
recipe mapping, so building a live paper/binance system pulls `ccxt.pro` (verified:
`LiveTradingSystem.for_exchange('binance')` leaves `'ccxt' in sys.modules` True).

Design-consequent rather than a defect — §3.2's boundary is BACKTEST-vs-live, nothing on
the backtest path imports `trading_system/live/`, and G3 is green. It does mean ED-8's
inertness-probe rewrite should keep asserting the backtest boundary rather than the
absence of ccxt after a live build.

### 2.10 `measure_redesign_baseline.py` cannot run without `--manifest`

Its `BASELINE_MANIFEST` names five now-deleted files and errors out. Pre-existing since
Stage 3 (`account/venue.py`). Only the `--manifest` form matters (the frozen
`BASELINE_TOTALS` are the yardstick), but Stage 7 should either prune the default manifest
or teach it to tolerate historical paths — the `--gate` must-have runs through it.

### 2.11 Stage 7 — `_OKX_DEFAULT_MARKET_TYPE` now has two homes

It moved to `execution_handler/exchanges/okx.py`, beside the recipe that applies it.
`venues/okx_plugin.py`'s copy still exists and dies with that module in Stage 7.

### 2.12 Stage 6 — `start()` now opens a data session, so offline tests need the stub

The data adapter is built at composition (I/O-free) but its session opens in `start()`.
That made three integration tests perform REAL network connects until
`tests/support/live_okx.py::stub_data_session` was added. **Stage 6 must keep that helper
applied wherever `start()` runs offline** — the failure mode is a slow, flaky, network-
dependent test rather than a red one, so it will not announce itself.

### 2.13 Stage 6 — three facade callbacks are production-dead

`_request_connector_halt`, `_on_venue_stream_down`, `_on_venue_stream_up` have no
production caller left (the manager and the data recipe both use the bus-bound `emit_*`
partials, which put the same CONTROL events). They survive only because three tests drive
them. `live/system.py` should NOT re-create them.

### 2.14 `is_streaming_healthy` is still duck-typed on adapters

Same gap class as `catch_up_missed_fills` (closed in Stage 5), called from the same
`StreamRecoveryHandler` method over the same connector-filtered adapters, and left
undeclared only because §2.2 named one method. Declare it on `AbstractExchange` in the next
contract pass.

### 2.15 The measurement asymmetry — SETTLED after Stage 5 (owner decision)

**The reported −34 was wrong; the honest like-for-like number is +118.** The deletion gate
was measuring an inconsistent file set: code relocated into
`portfolio_handler/account/simulated.py` counted (it is in the manifest), but code
relocated into `execution_handler/exchanges/{base,okx,simulated}.py` and
`price_handler/providers/okx_provider.py` did not — no host was in either manifest, while
the modules they replaced (`account/venue.py`, `feed_binder.py`, the plugin `build_*`
methods) all WERE among the baseline 27. Lines were counted leaving and not counted
arriving. Same false-green class as §3.1, one level up: §3.1 is "relocation drops lines
from the measured set", this was "the measured set never included the destinations".

Measured at the frozen commit `3a2c7692` versus HEAD, with the gate script's own counting
rule:

| set | baseline | HEAD | delta |
|---|---|---|---|
| the 27-file manifest | 3,886 | 3,852 | −34 |
| the 4 recipe hosts (uncounted) | 1,182 | 1,334 | +152 |
| **like-for-like, 31 files** | **5,068** | **5,186** | **+118** |
| whole `itrader/` tree, 263 files | 22,297 | 22,475 | +178 |

The whole-tree row is the cross-check that involves no set-selection judgment at all; it
agrees in sign. Every commit on this branch is a redesign stage, so all of it is redesign
growth.

**Settled (owner, option 1 of three):** extend BOTH sides to the 31-file set.
`EXTENDED_BASELINE_TOTALS = (31, 11684, 5068)` is pinned in
`scripts/measure_redesign_baseline.py` beside a `RECIPE_HOSTS` tuple, and the successor
manifest lists the four hosts. `BASELINE_TOTALS` is untouched — it remains the historical
record of what the requirements' Scope block measured, not the gate's comparand.

Three behaviours now hold, each verified:
- the successor run reports **31 files / 11,945 raw / 5,186 code / delta +118**;
- `--gate` **exits 1** today (`GATE FAILED: 5186 >= 5068`), which is correct — the must-have
  is genuinely unmet at Stage 5;
- a manifest that OMITS a recipe host is **refused** rather than measured, because an
  extended baseline against a 27-file successor set is the same asymmetry sign-flipped.

The default (no-`--manifest`) historical run no longer hard-errors on the six baseline paths
the redesign has deleted — it reports them and counts them as zero. That closes the old
§2.10. An absent path in a SUPPLIED manifest is still a hard error, since there it means a
typo or a stale entry.

**Reachability:** 1,303 code lines are slated for deletion in Stages 6–7
(`live_trading_system.py` alone is 791). The gate passes if the Stage-6 replacements
(`build.py` / `system.py` / `graph.py` / `exchanges/paper.py`) come in under ~1,185 lines.
Real target, not a comfortable margin — plan risk #3's stop-and-report now has a number
attached to it.

### 2.16 OPEN — the replay/parity harness blocks WR-07's hard refusal (owner decision)

`build_paper_replay_system` — which drives the **DoD parity gate** — plus
`remove_policy_harness` and ~7 `for_exchange("binance")`-style tests all build a live system
with NO spine. Requiring one forces `environment='live'`, which switches the parity run onto
SQL order/signal/portfolio-state storage. That experiment was run and failed three ways:

1. the portfolio-state tables (`equity_snapshots`, `cash_operations`, …) register on the
   metadata only WHEN a portfolio is created, so a `provision_schema` before boot never
   creates them — a chicken-and-egg the flow does not currently support;
2. with them pre-registered, the run dies on `sqlite3.OperationalError: database is locked`
   **within a single process** (order store versus portfolio-state store);
3. the durable rows were observed carrying FLOAT money (`amount: -9500.0`).

Point 3 is **reported but NOT independently verified** — a grep of
`portfolio_handler/storage/` and `storage/` for `float(` returns nothing, so if it is real
the coercion is elsewhere (a JSON column round-trip is the obvious suspect). Money is
Decimal end-to-end by locked decision, so **confirm or dismiss this before migrating the
harness**, and treat it as a correctness question in its own right rather than a detail of
the migration.

Sequencing: migrating the replay/parity harness off the live durable arm is its own piece of
work — it needs a schema-provisioning story for the handler-owned tables and a look at the
SQLite write-lock contention. Plan risk #2 requires the parity gate stay byte-exact, so
forcing it through as part of Stage 6 would have been a large unplanned behavioural change
on the one gate that certifies the DoD.

### 2.17 Stage 7 — the deletion list, and what must move first

Zero production references remain to any of these; only Stage-7-disposed tests and docstring
prose still name them. **Pool = 1,270 code lines.**

`trading_system/live_trading_system.py` (788), `venues/okx_plugin.py` (177),
`venues/paper_plugin.py` (71), `connectors/provider.py` (56), `venues/bundle.py` (41),
`venues/bundles.py` (39), `trading_system/compose.py` (37),
`trading_system/venue_spec.py` (32), `venues/registry.py` (29).

**ED-5 must run FIRST:** `COMPUTE_VENUE` / `DEFAULT_ACCOUNT_ID` are still imported from
`venues/registry.py` by `execution_handler.py:18`, `portfolio_factory.py:47` and
`admission_manager.py:35`. Re-home into `execution_handler/execution_handler.py`, then
`git rm`.

Also in Stage 7:
- Delete/re-point `tests/unit/connectors/test_provider.py`,
  `tests/unit/venues/test_{venue_bundles,registry,okx_plugin,paper_plugin}.py`,
  `tests/unit/trading_system/test_venue_spec.py`,
  `tests/integration/test_compose_wiring.py`, and `tests/support/venue_wiring.py` (which
  still builds `VenueBundles` / `ConnectorProvider` / `PaperVenuePlugin`).
- `tests/unit/test_account_identity_coercion_gate.py` must drop its two
  `live_trading_system.py` entries (the `_LIVE_ROOTS` tuple and the positive-half count)
  when that file dies.
- Remove `"itrader.trading_system.live_trading_system"` from `pyproject.toml`'s
  `ignore_errors` list (`:104`) with the file.
- `_LIVE_QUEUE_TIMEOUT` / `_LIVE_MAX_IDLE_TIME` now live in `live/build.py`; the old copies
  die with the old root.
- `order_handler/admission/admission_manager.py:101` still has
  `account_for(...) or DEFAULT_ACCOUNT_ID`. Left deliberately in Stage 6: it is a fee-model
  lookup with an in-source rationale explicitly forbidding unification with the routing
  path, and removing a defensive default on a money-adjacent path is a decision, not a
  sweep. Decide it explicitly.
- Pre-existing: `tests/integration/test_live_system_okx_wiring.py` has an unused
  `import pytest`.

### 2.18 `trading_system/live/__init__.py` is deliberately import-LIGHT

It re-exports `bootstrap` only. Adding `build` / `system` to the barrel makes importing ANY
live submodule pull ccxt and reddens the inertness probe — hit during Stage 6 commit 2. Keep
it that way, or rewrite the probe.

### 2.19 The §7.5 rehydrate-ordering gate asserts the ORDERING, not a runtime tripwire

Design §7.5 wanted the live validator to consult the manager's ONLINE RECORDS, so
rehydrate-before-bring-up fails loudly at the first portfolio. But Stage 4 deliberately
scoped `assert_available` to EXISTS+ENABLED — requiring "brought online" would crash an okx
boot on a validly-provisioned FOREIGN-venue portfolio. Code wins, so
`tests/unit/trading_system/test_bootstrap_ordering.py` asserts the ordering itself on the
production `bootstrap_session` / `_restart_sequence`, and documents that the ordering has no
runtime tripwire of its own — which is precisely why it needs a static gate.

## 3. Process findings (things that bit, so they do not bite again)

### 3.1 The baseline manifest under-reports mid-refactor — a false-green

Code RELOCATED into a new module leaves the baseline manifest without being deleted. At
Stage 1 that silently dropped the measured total to 9,079 / 3,782, which reads as ~100 lines
of progress toward the must-have bought entirely by a move.

Mitigations, all in place: `BASELINE_TOTALS` pins `(27, 9243, 3886)` as a historical fact;
the default manifest says loudly when it stops reproducing them; the successor manifest is
maintained as stages land so the sign is observable throughout (plan risk #3 wants a
trending-positive Stage 6 caught *before* Stage 7).

### 3.2 Scripted replacements must assert, and indentation is per file

Four `str.replace` edits against `portfolio_handler.py` silently no-op'd because they were
written with tabs and the file is 4-space. `str.replace` does not error on a miss. Every
scripted edit should assert the pattern was found and is unambiguous. Measure the file
(`grep -c $'^\t' <file>`); never infer from a sibling.

### 3.3 A broad regex on production code caused ~31 spurious failures

`re.sub(r"\n\s*execution_handler=[^,\n]*,", "", s)` intended for the coordinator also
stripped the argument from `ConfigRouter` and `layer_persisted_overrides`. Scope such edits
to one known call site, or assert the match count.

### 3.4 `git checkout <file>` reverts the whole file, not one hunk

Used to undo a temporary negative-control edit in `okx_plugin.py`, it also discarded two
real, uncommitted changes in the same file. Prefer a targeted inverse edit while a stage is
mid-flight and uncommitted.

### 3.5 Grep BOTH trees for every moved or deleted name

`test_config_restart_layering.py` imported `_layer_persisted_overrides` by name and broke
collection after the Stage-1 move; the initial sweep had covered `itrader/` only.

### 3.6 A green suite did not catch a real wiring defect

The spec→adapter gap in §1.1 of the Stage-3b commit (`quote`/`market_type`/`symbol`
computed but never passed to `OkxExchange`) passed the full suite, mypy and both oracles. It
lived in the gap between "the adapter derives correctly" (unit-tested) and "the plugin wires
it" (untested). A subagent review found it. Where a stage adds constructor parameters,
assert at the CONSTRUCTION SITE that they are threaded, and verify the new test is
load-bearing by reverting the fix.

---

## 4. Verification commands (the gate battery, as run)

```bash
# G1/G2/G3/G4 — oracles (both arms), inertness, offline composition
poetry run pytest tests/integration/test_backtest_oracle.py \
                 tests/integration/test_backtest_oracle_factory_arm.py \
                 tests/integration/test_okx_inertness.py \
                 tests/integration/test_live_composition_offline.py -q
# G5
poetry run mypy
# G6  (never `make test` — it exports ITRADER_DISABLE_LOGS and aborts in worktrees)
poetry run pytest tests -q
# measurement (informational until Stage 7)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt
```

### 3.7 A passing STATIC gate can be blind to the very relocation it exists to prevent

`test_account_identity_coercion_gate.py` pins per-file coercion COUNTS in its positive half.
A coercion moved WITHIN a counted file keeps the count identical, so the gate stays green
through exactly the change it was written to stop (§1.16). Static counts prove absence
across a tree; they do not prove a surviving use is still in the safe position. Where the
position is what matters, the guard has to be behavioural.
