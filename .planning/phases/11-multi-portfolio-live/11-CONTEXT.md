# Phase 11: Multi-Portfolio-Live ★ - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

> **Phase-resolution note (for the researcher/planner):** GSD `init.phase-op` returns
> `phase_found: false` for Phase 11 — the starred header (`### Phase 11 ★: Multi-Portfolio-Live`)
> breaks `roadmap.get-phase`, exactly as it did for Phase 9 and Phase 10. Ground truth was injected
> manually: phase 11, name **Multi-Portfolio-Live**, working dir
> `.planning/phases/11-multi-portfolio-live/` (created this session), requirements
> **MPORT-01..06** (+ the discovered **MPORT-07**, D-27), depends on Phase 5 + Phase 7. Ignore any
> null / `has_context:false` flags from init — they reflect the failed lookup, not this phase.
> Expect `init.plan-phase` to return `phase_req_ids: null` and `roadmap.annotate-dependencies` to
> no-op (`updated:false`) as well; inject REQ IDs by hand and write the wave list manually.

<domain>
## Phase Boundary

Let multiple portfolios trade live **independently**, each against its own venue account
(MPORT-01..06): per-`account_id` account minting via the venue plugin, a distinct-`account_id`
invariant that fails loud at composition time, per-portfolio reconciliation, and two-key
attribution (`client_order_id` for venue↔engine correlation, `portfolio_id` for attribution).
(★ feature-add — LR-03 mandate, never trim.)

**Live-only, backtest-dark.** Per-phase gates: the backtest oracle stays byte-exact
(`134 / 46189.87730727451`) and `tests/integration/test_okx_inertness.py` stays green.

**The load-bearing reframe of this phase (D-27):** the discussion found that MPORT-01..06 is
**necessary but not sufficient**. The requirements say *connectors* are keyed `(venue, account_id)`
— but the **exchange** is keyed by bare name (`ExecutionHandler.exchanges.get(event.exchange)`,
`execution_handler.py:126`) while `OkxExchange` holds exactly **one** connector
(`okx.py:101`). Two portfolios on venue `okx` with different accounts therefore both route to the
same exchange, and **account B's orders would be submitted through account A's connector** — with
per-account credentials, per-account `VenueAccount`, and the distinct-`account_id` invariant all
correct. Investigation showed **every** piece of mutable state on `OkxExchange` is already
account-scoped (connector, `VenueCorrelationIndex`, `watch_my_trades` stream handles, connection
status) and the markets/precision map lives on the **connector**, not the exchange
(`okx.py:952-955`, `:402`). So the exchange's true cardinality *already is* `(venue, account_id)`;
it has only ever been instantiated once because there has only ever been one account. D-27 makes
that dimension explicit. The decisive constraint is `watch_my_trades`: it is an authenticated
**per-account** stream, so one shared exchange cannot correctly subscribe to two accounts' fill
streams at all.

**The second reframe (D-08):** portfolios are the only major entity in the system with child state
tables but **no definition row**. Seven portfolio-scoped tables exist (`portfolio_account_state`,
`positions`, `transactions`, `cash_operations`, `cash_reservations`, `locked_margin`,
`equity_snapshots`), all keyed by `portfolio_id`, all recording what a portfolio **has** — never
what it **is**. There is no `name`, no `exchange`, no `enabled`, no `initial_cash`, and nowhere for
`account_id` to live. Live has **zero** `add_portfolio` call sites in `itrader/`. P11 adds the
missing `portfolios` definition table, paralleling `venue_store` and `strategy_registry`.

**Two defects discovered during discussion, carried into execution** (see `<code_context>` →
Discovered Defects): the non-restart-stable `portfolio_id` (F-1) and the first-mismatch `return` in
`_run_session_baseline_guard` (F-2).

**Scope explicitly carved OUT by owner decision:** the data-provider connector's account model
(D-26 — the owner intends to redesign the data-connector logic; folds into the spec §14
multi-provider feed-router deferral) and per-`account_id` pre-trade throttle keying (D-30).

</domain>

<decisions>
## Implementation Decisions

### Account identity & credentials (Area 1)

- **D-01 (Identity is the `(venue, account_id)` PAIR, not a bare `account_id`):** `account_id` is
  namespaced **per venue** — `"main"` on `okx` and `"main"` on a future venue are different accounts
  by design. This matches the `ConnectorProvider._memo` key already shipped in P5
  (`connectors/provider.py:69`, `dict[tuple[str, str], LiveConnector]`), so no new keying concept is
  introduced. **Consequence, load-bearing:** `account_id` alone can NEVER derive the venue — every
  reference to an account is inherently two columns. **Rejected:** globally-unique `account_id`
  (diverges from the shipped memo key and pushes namespacing onto operator convention like
  `"okx_main"` — convention instead of structure).

- **D-02 (Credentials: a `CredentialResolver` Protocol + the secret-ref pattern — the DB stores a
  POINTER, never a secret):** `itrader` defines the Protocol and ships an **env-backed resolver**;
  the durable record holds a `secret_ref` string pointing at wherever the secret actually lives. The
  web app later registers a Vault/AWS/GCP-backed resolver **in its own repo with its own
  dependency** — `itrader` never imports a cloud SDK. **The owner's stated target was credentials
  stored in the database** (driven by a real workflow: an integrations page in the web app where
  venues are connected by entering keys, with no `.env` involvement — *"i do not want to define
  venues keys in the .env files, that was just temporary"*). **Two blocking findings redirected it,
  and downstream agents must not re-litigate without re-reading them:** (1) `venue_store.py:40-77`
  already ships `_assert_no_secret_keys` (D-05) — a recursive any-depth denylist (`api_key`,
  `secret`, `passphrase`, `token`, `private_key`, `credential`, …) raising `ValidationError` with
  the message *"credentials are connector-owned and must never be persisted to VenueStore"*; storing
  credentials in the DB reverses a decision this milestone made deliberately. (2) The
  **milestone-wide gate** forbids any new third-party dependency across P1–P12, which blocks every
  secret-manager SDK (hvac / boto3 / google-cloud-secret-manager) **and** blocks promoting
  `cryptography` (present in `poetry.lock` only transitively via ccxt) to a direct dep for envelope
  encryption. **Why the pointer beats an encrypted blob even when a dep is allowed:** envelope
  encryption relocates the problem rather than solving it (the master key still needs a safe home —
  the secret manager you were going to run anyway), while a plaintext-or-decryptable blob puts live
  exchange keys into every `pg_dump`, read replica, and backup snapshot. This is the third instance
  of the pattern P10 D-01 (injected `strategy_catalog`) and P5 D-03 (per-venue connector plugins)
  already established: **`itrader` ships the seam, the app owns the data.** **NOTE:** the denylist is
  *exact lowercased membership* — `"credential"` is denied, `"credentials"` (plural) and
  `"secret_ref"` both pass. Name the column `secret_ref`, never `credentials`; passing by one letter
  is a bad place to be.

- **D-03 (Venue plugins expose their credential schema):** `VenuePlugin` gains a credential/settings
  model class attribute (e.g. `credential_model: type[BaseSettings] | None`, `OkxSettings` for okx,
  `None` for paper). This is what lets the future integrations page render per-venue form fields
  with **zero hardcoding**, and it is precisely LR-01's "make the engine interfacable while shipping
  no ASGI code". Nearly free — `OkxSettings` already exists. **Rejected:** letting the web app import
  the settings models directly (the venue registry stops being self-describing, so adding a venue
  means editing the web app too — reintroducing the per-venue branching P5 spent a whole phase
  deleting).

- **D-04 (Venue-UID assertion: OBSERVE-ONLY, trust-on-first-use):** After `connect()`, capture the
  venue's own account UID and compare it to the recorded value for that `(venue, account_id)`. A
  mismatch fires a **CRITICAL alert** via the existing `alert_sink` (P10 D-19's channel) and is
  surfaced in the read-model — it does **NOT** halt. Expected value is **trust-on-first-use**: the
  first connect for a `(venue, account_id)` records the UID; every later connect asserts against it.
  No operator data entry, no typo surface. **Why this is in P11 at all** (P5 deferred it to "P7 /
  P11"): per-account credentials are exactly what makes the misroute *reachable* — a mistyped
  `secret_ref` or a swapped vault entry means `account_id="acct_a"` connects with account B's keys,
  orders route to the wrong **real** account, and reconciliation succeeds cleanly against it. It is a
  silent, money-losing failure that only exists once multi-account exists. **Rejected:**
  operator-declared expected UID (one more thing to look up and mistype; a wrong expected-UID blocks
  a correctly-configured account).

- **D-05 (`venue_accounts` — a NEW FLAT table, one row per account):** Composite natural PK
  `(venue_name, account_id)` — matching D-01 and the memo key, and following the natural-key
  convention of P4 D-06 / `venue_store.venue_name` / `strategy_registry.strategy_name`. Columns:
  `secret_ref` (typed String — a pointer, rotates with credentials; **NULL for paper accounts**),
  `venue_uid` (typed, nullable — **engine-written** TOFU value, D-04), `enabled` (Boolean),
  `config_json` (JSON — **operator-authored** per-account connection config: `sandbox`, `region`,
  and whatever a future venue kind needs), `updated_at` (`UtcIsoText`). The owner specifically asked
  for `config_json` to be **separate from** the credentials-ref column; the resulting three-lifecycle
  split (pointer / engine-written / operator-authored) mirrors `venue_store` (typed `enabled` +
  `config_json`, `venue_store.py:96-99`) and P10 D-06's runtime-state-vs-authoring-params reasoning.
  `config_json` absorbs venue-kind variation so a new venue's knobs never require a migration.
  **Rejected:** nesting an `accounts` sub-map inside the existing `VenueStore.config_json` (zero
  migration, and P10 D-06 kept `tickers` in `config_json` by the same logic — but the owner
  explicitly wanted flat rows: *"i do not like this nested structure. i want a flat one, a raw for
  each account"*, which is also the correct end-state cardinality per LR-21) and a dedicated new
  column on `venue_store` (still venue-keyed, so it does not actually fix cardinality). Exact column
  types/nullability are the planner's.

### Portfolio definition & bootstrap (Area 2)

- **D-06 (`account_id` is NOT NULL on every portfolio; `venue_accounts` holds paper rows too):**
  Every portfolio names an account — no exceptions, no two classes of portfolio. Paper accounts are
  **real `venue_accounts` rows** with `venue_name='paper'` and `secret_ref` NULL (a paper account has
  no secret to point at). This resolves a conflict the discussion surfaced between an earlier
  nullable-`account_id` answer and the owner's "every portfolio must have a distinct account_id"
  ruling: enforcing distinctness *including* NULL would require Postgres `NULLS NOT DISTINCT`
  (NULLs are distinct in a unique index by default), which permits **at most one** paper portfolio
  system-wide — almost certainly not intended. NOT NULL collapses the awkwardness: **plain** (not
  partial) unique index, **unconditional** FK, one rule with no exceptions, and each paper portfolio
  naturally gets its own `SimulatedAccount`. Backtest is unaffected (in-memory storage, never touches
  these tables, oracle-dark). **Accepted cost:** creating a paper portfolio now requires an account
  row first — paper setup is no longer zero-config.

- **D-07 (`portfolios` table shape — `venue_name` replaces `exchange`, no redundant column):**
  `portfolios(portfolio_id PK, name, venue_name, account_id NOT NULL, initial_cash, enabled,
  config_json, updated_at)`, with a composite FK `(venue_name, account_id)` → `venue_accounts`,
  **unconditional** given D-06. There is **no separate `exchange` column** — the owner correctly
  identified it as redundant with the venue half of the account reference, so `Portfolio.exchange`
  (`portfolio.py:73`, feeding `exchange_for()` at `portfolio_handler.py:365-368` → admission metadata
  → every `Order`) becomes **derived from `venue_name`**. **Correction applied during discussion:**
  the owner's initial framing was that the venue could be derived from `account_id` alone; D-01 makes
  that impossible, so the reference is inherently two columns — but only *one* of them is new, and
  `exchange` is not stored twice. **Rejected:** keeping `exchange` alongside `account_id` (two sources
  of truth for a portfolio's venue that can drift).

- **D-08 (Add the missing `portfolios` definition table + rehydrate-on-boot):** Paralleling
  `venue_store` and `strategy_registry`, and following P10 D-01's ruling that **the store is the
  source of truth for instances**. See `<domain>` for the finding that motivated it. Rehydrate runs
  at boot and reconstructs portfolios with their **persisted `portfolio_id`s**. **Rejected:**
  pinnable-id-plus-params with the FastAPI app owning portfolio definitions (smaller surface and it
  matches ACCT-04's ruling that portfolio-identity mapping is an app-layer concern — but it leaves
  `itrader`'s own seven durable child tables unreadable without the app supplying the right ids) and
  minimal-`account_id`-param-only (leaves the restart gap fully open).

- **D-09 (Per-portfolio config MOVES onto the `portfolios` definition row):** `portfolios.config_json`
  becomes the single home for per-portfolio config, **migrating it off**
  `portfolio_account_state.config_json` (P9 D-25) and repointing the restart-layering path that
  currently reads `portfolio.state_storage.load_config()` (`live_trading_system.py:1262-1266`,
  `sql_storage.py:526-560`). Rationale: config belongs on a **definition** row, not a **state** row —
  it only ever lived there because no definition row existed. **RESEARCH/REGRESSION RISK the planner
  MUST cover:** this is the tested **RTCFG-03** path, and **P12's TEST-03 config-restart gate**
  verifies exactly it. The migration must move existing data, not just repoint reads. **Rejected:**
  dropping `config_json` from the new table and leaving P9's home alone (zero disruption — the safe
  option) and splitting authoring-vs-runtime across both blobs (principled, mirrors P10 D-04, but
  two config blobs for one portfolio plus a merge/precedence rule to define and test).

### Account minting & wiring (Area 3)

- **D-10 (`new_account()` as a typed `VenuePlugin` Protocol method):** Promote account construction
  from the untyped `VenueBundle.account_factory` field (`bundle.py:65`, `Callable[..., Account]`) to
  a real Protocol method beside `build_bundle`, matching spec §10b's wording
  (`new_account(portfolio_ref, config)`). **IMPORTANT CORRECTION recorded so it is not repeated:**
  this was initially justified as "killing the arg-swallowing trap structurally via `mypy --strict`".
  **That is FALSE.** `(*args: Any, **kwargs: Any)` is the universally-compatible signature in mypy and
  satisfies **any** Protocol method, and `VenuePlugin` is a **structural** `Protocol` (`bundle.py:77`)
  that plugins do not subclass — so an arm keeping `*args/**kwargs` would type-check clean under
  every option considered. The surface choice governs **where code lives**, NOT whether wrong-wiring
  is possible. The actual guard is D-11.

- **D-11 (`account_id` becomes a REQUIRED keyword ctor arg on `VenueAccount` — THE structural
  guard):** `VenueAccount(connector, *, account_id: str, ...)`, no default. Today **every**
  parameter has a default or is optional (`account/venue.py:75-82`), which is exactly why returning
  an unscoped shared singleton is expressible — and why `okx_plugin.py:101-110`'s
  `account_factory(*args, **kwargs)` can absorb a `portfolio` argument and hand back the shared
  account with **no error**. With a required arg no plugin arm can produce an unscoped account
  without naming one; the failure becomes a `TypeError` at construction. This matches the codebase's
  fail-loud posture (the deliberate `RuntimeError`-not-`assert` choice at
  `reconciliation_coordinator.py:164`). **Rejected:** a `"default"` fallback for migration smoothness
  (re-opens precisely the hole — a caller that forgets silently gets the default account).

- **D-12 (One connector per `(venue, account_id)`):** Exactly what `ConnectorProvider._memo` already
  implements (`provider.py:69-80`), so close to free. Clean isolation, no routing layer on the order
  path, and it fits D-02's per-account credential model. Spec §14 explicitly lists the alternative
  ("single-connector-multi-`account_id` optimization" — OKX master key + per-account routing on one
  session) as **deferred/not built**. **Bounded, accepted cost:** N `ccxt.pro` clients, N WS sessions,
  N rate-limit buckets. **CAVEAT the planner must handle:** the memo is `(venue, account_id)`-keyed
  but `ConnectorProvider._plugins` behind it is keyed by **venue only** and `build(spec)` receives the
  single global spec — so today two `account_id`s would build two connectors reading **identical**
  `OkxSettings()` credentials. VENUE-03 does **not** give per-account isolation for free; D-02's
  resolver is what closes it.

- **D-13 (DELETE the facade's `self._venue_account` singleton):** `live_trading_system.py:195`
  (`self._venue_account = lifecycle.bundle.account_factory()`) goes away. `Portfolio.account` is the
  designed home (Portfolio delegates to an injected `Account` leaf), and
  `_link_venue_account_to_portfolios` + its `RuntimeError(>1)` guard are deleted anyway per MPORT-01.
  Removing the field eliminates the last place a "the one venue account" assumption can hide.
  **PLANNER WARNING:** `live_trading_system.py` is under a mypy `ignore_errors` override — a leftover
  unused field or import passes **both** mypy and the suite silently, and only code review catches it.
  Sweep after deletion. **Rejected:** replacing it with a `dict[(venue, account_id) -> Account]`
  (reintroduces a second source of truth for "which account does this portfolio use" — the exact
  drift MPORT-02 exists to prevent).

### The distinct-`account_id` invariant (Area 4)

- **D-14 (Enforced BOTH in the DB and in the application):** A **plain** unique index on
  `portfolios(venue_name, account_id)` — plain, not partial, given D-06's NOT NULL — makes the
  collision structurally impossible **including for out-of-band writes** from the future integrations
  page. An application check at composition produces a readable, actionable error instead of a raw
  `IntegrityError`. Deliberate defense-in-depth, matching the justified-overlap posture
  `.planning/codebase/CONVENTIONS.md` pins for the dual-layer order validator (D-03a). **Rejected:**
  application-check-only (nothing stops a bad row being written out-of-band; the collision would then
  surface only at next boot) and DB-only (an `IntegrityError` is a poor operator-facing message for
  something this consequential).

- **D-15 (A collision REFUSES TO START — hard fail before any account is minted):** Matches MPORT-02's
  wording ("rejected", "fails loud at composition time"). There is no safe way to choose which
  colliding portfolio is legitimate, and conflated buying power across two portfolios is a
  money-losing wrong answer. **Deliberately NOT the P10 D-19 quarantine treatment** — D-19's rationale
  was that a skipped *strategy* is harmless, which is not true for a *portfolio* that may hold open
  positions. Contrast D-22, where quarantine IS correct because the accounts are isolated.

### Attribution & the `client_order_id` rename (Area 5)

- **D-16 (Rename engine symbols + normalize the response readers; wire strings stay `clOrdId`):**
  `clOrdId` appears 46 times across just **two** files (`execution_handler/exchanges/okx.py`,
  `venue_correlation.py`), most of them docstrings. Rename engine-side identifiers
  (`_orders_by_clOrdId` → `_orders_by_client_order_id`, `venue_correlation.py:141`, plus the
  docstring vocabulary). `params["clOrdId"]` (`okx.py:426`) and the response readers
  (`info.get("clOrdId") or info.get("clientOrderId")`, `venue_correlation.py:94`) keep the venue's
  spelling **verbatim** — `clOrdId` is OKX's API contract and renaming it on the wire simply breaks
  submission. Additionally, **fold the `clOrdId`/`clientOrderId`/`info`-fallback extraction behind
  one documented venue-vocabulary helper** so the wire spelling appears in exactly one place
  (`_extract_client_order_id`, `venue_correlation.py:81-94`, is already most of this) — makes adding
  a second venue with a different field name cheaper.

- **D-17 (Portfolio attribution rides the index + the durable `orders` row — do NOT change the id
  format):** MPORT-04's "every submitted order is tagged with its portfolio" is **already satisfied**:
  `SignalEvent`, `OrderEvent`, `OrderAckEvent`, `FillEvent` and `Order` all carry a typed
  `portfolio_id` today (`events/order.py:62,165`, `events/fill.py:64`, `events/signal.py:88`,
  `order_handler/order.py:57`). Attribution is derivable **three** independent ways without touching
  the id string: (1) `_client_order_id` is a **lossless deterministic bijection** of the UUIDv7 order
  id (the WR-04 contract, `okx.py:204-232` — "distinct order ids yield distinct clOrdIds, no
  truncation collision"), so `clOrdId → order_id` is pure decode; (2) `orders.portfolio_id` is
  `nullable=False` (`order_handler/storage/models.py`), so `order_id → portfolio_id` is a durable
  lookup; (3) D-15 guarantees one portfolio per `(venue, account_id)`, so even an order absent from
  the store is attributable by **which connector saw it**. **Rejected:** encoding an account/portfolio
  tag into the `clOrdId` string (breaks the WR-04 lossless-bijection contract, spends part of the
  32-char budget — currently ≤24 — needs a new encode/decode contract plus tests, and buys
  attribution three existing mechanisms already provide).

- **D-18 (Convert the bare `assert` at `okx.py:230` to a real raise):** `assert clordid.isalnum() and
  len(clordid) <= 32` is **stripped entirely under `python -O`**, so the only guard on a venue-bound
  identifier silently disappears in an optimized run. Same reasoning as the deliberate
  `RuntimeError`-over-`assert` choice at `reconciliation_coordinator.py:164`. Small, and P11 is
  already editing this function.

### Per-portfolio reconciliation (Area 6)

- **D-19 (The coordinator asks each portfolio for its OWN account):** Drop the scalar `venue_account`
  (and `connector`) ctor params from `ReconciliationCoordinator` (`:80-91`); iterate
  `get_active_portfolios()` and read `portfolio.account`. Single source of truth, consistent with
  D-13, and it makes comparing one portfolio against another's account **structurally impossible**.
  The per-account connector comes from that account rather than a separate scalar param. **Rejected:**
  injecting a `dict[(venue, account_id) -> Account]` (easier to unit-test without portfolios, but
  reintroduces the second source of truth D-13 removed).

- **D-20 (Baseline guard covers EVERY symbol the account holds a position in):** Replace the single
  global-config symbol read (`_system_config.stream.okx_stream_symbol`,
  `reconciliation_coordinator.py:194`) with iteration over `account.positions` **per portfolio**.
  This also closes a **latent gap that exists today, single-account or not**: pinning the guard to
  `okx_stream_symbol` means an unexplained residual in any *other* symbol is invisible. Naturally
  per-account once accounts are per-portfolio, and it removes a global-config read from a
  per-portfolio code path. **Rejected:** union-of-subscribed-symbols (tighter and avoids alarming on
  unrelated parked holdings — but an unexplained residual in an *unsubscribed* symbol is arguably the
  exposure you most want to know about) and keeping the single configured symbol per-account
  (carries today's blind spot forward).

- **D-21 (Evaluate ALL portfolios before acting — see F-2):** `_run_session_baseline_guard` currently
  `return`s on the **first** mismatch (`:216`). With N portfolios that stops the scan early. It must
  evaluate every portfolio and collect results before deciding.

- **D-22 (One portfolio's unexplained drift QUARANTINES that portfolio; the rest keep trading):**
  Accounts are now fully isolated — own connector, own credentials, own venue account, own exchange
  (D-27), and D-15 guarantees no sharing — so drift on account A carries **zero information** about
  account B. Today's global latched halt (`HaltReason.BASELINE_RESIDUAL`, `:215`) is over-broad. The
  drifted portfolio stops taking **new entries** with a **CRITICAL alert** via `alert_sink`; open
  positions and resting brackets run to natural exit (**reusing P10 D-07's ruling verbatim**);
  everything else keeps trading. **Mechanism is mostly assembly, not new machinery:** `SafetyController`
  already has the exact shape as global scalars (`_submission_paused` bool `:146`, `halt()` `:151`,
  `is_submission_paused()` `:265`, consumed at only two call sites — `live_trading_system.py:473`,
  `:607`), so this is a per-portfolio set beside it; the admission gate is one guard clause because
  `AdmissionManager` is already fully keyed by `portfolio_id`; the alert channel (P8) and read-model
  (RTCFG-06) already exist. **Rejected:** keeping the global halt (knowingly ships the wrong blast
  radius, and P12's TEST-04 attribution gate would surface it immediately — the retrofit reopens
  `safety_controller.py`, `admission_manager.py` and `reconciliation_coordinator.py` a second time).

- **D-23 (Quarantine clears OPERATOR-ONLY, via a CONTROL command):** Mirrors the halt posture —
  `HALTED` has no legal exit except operator `reset_halt()`, so quarantine gets the same discipline.
  An unexplained venue residual means the engine **cannot explain real exposure**; a human should look
  before that account trades again. Needs a CONTROL verb + route, which the `LiveRouteRegistrar`
  pattern already supports. **Rejected:** auto-clear on a subsequent clean reconcile (an unexplained
  residual that quietly disappears is exactly the thing you want a human to have seen) and a
  both/threshold hybrid (two paths and a tuning knob, in a phase already carrying a lot).

- **D-24 (Quarantine state surfaces in the RTCFG-06 `state.*` read-model):** A quarantined-portfolios
  list with reason and timestamp, reusing the same P9 surface P10 D-19 uses for its strategy
  quarantine list. One consistent place an operator (and later the web app) asks "what is not trading
  and why" — and D-23's release command needs something to tell the operator what to release. The
  CRITICAL alert remains the **push** notification; this is the **pull** surface.

### Test boundary & deferrals (Area 7)

- **D-25 (P11 proves the FULL lifecycle including restart; P12's TEST-04 owns the milestone gate):**
  Follows the **P10 D-22 / P9 D-23 precedent** — with no FastAPI layer (LR-01), the phase that builds
  the surface must drive the real external path or it ships **untested**. For P11 that path is:
  durable rows → **restart** → rehydrate → two portfolios trading independently against their own
  accounts, with fills routed to the correct portfolio. Deliberate overlap with P12 is the point:
  P11 must not depend on a later phase to discover it is broken. **Test venue: two paper accounts on
  the simulated venue** — two portfolios, two distinct `account_id`s on `venue_name='paper'`, each
  with its own `SimulatedAccount`, which D-06 makes a **first-class configuration rather than a test
  hack**. Deterministic, CI-safe, no credentials, and it exercises the whole path. **Why not OKX
  demo:** the EEA demo account trades only BTC/USDC and ETH/USDC (MiCA whitelist), both are pre-seeded
  non-flat, and sells are blocked by a price-floor above best-bid — an online settlement e2e cannot
  reach a fill there.

- **D-26 (DEFER the data-provider connector's account model; rename `SystemSpec.account_id`):** The
  owner intends to redesign the data-connector logic, and spec §14 already carries the
  **multi-provider feed-router** as deferred work — the data-side account model belongs with that
  redesign, not bolted onto a multi-portfolio phase. **Risk of deferring is low:** the data arm keeps
  resolving `spec.account_id or "default"` (`okx_plugin.py:138-139`) while execution goes per-account,
  costing **one extra connector** — a cost, not a defect; nothing mis-routes. **The one thing P11 does
  NOT defer is the naming ambiguity:** once execution stops reading `SystemSpec.account_id`
  (`system_spec.py:126`), that field is read **only** by the data arm while still named as the
  system-wide execution default. Rename and document it as data-provider-scoped, plus a todo pointing
  at the §14 redesign. A stale name that no longer matches what reads it is exactly the failure class
  F-1 already demonstrates in this codebase.

- **D-30 (DEFER per-`account_id` pre-trade throttle keying — P7 D-03's shaped seam stays shaped):**
  The global engine-wide cap **is** wrong in a multi-account system for the same reason the global
  halt was — account A's order rate starves account B. But unlike the halt it **fails conservatively**:
  it under-trades rather than mis-trades, costing opportunity, not correctness. Given P11's load, this
  is the right thing to cut. Todo required.

### Discovered scope beyond MPORT-01..06 (Area 11)

- **D-27 (MPORT-07, discovered: the EXCHANGE becomes per-`(venue, account_id)`):** See `<domain>` for
  the full finding and why it is architecturally correct rather than merely convenient.
  `ExecutionHandler.exchanges` keys on the **pair**; `on_order` (`execution_handler.py:123-131`)
  resolves the account from `event.portfolio_id`; `VenueBundle` carries per-account exchanges. Each
  account gets its own `VenueCorrelationIndex`, which incidentally makes that index's bare-`venue_id`
  keying (`venue_correlation.py:139-151` — five dicts keyed by venue order id) safe **by
  construction** rather than by assumption. `PortfolioReadModel` gains an `account_for(portfolio_id)`
  alongside the existing `exchange_for`. **Rejected:** one exchange per venue with the connector passed
  per call (the exchange holds connector-bound state, and `watch_my_trades` is a *private per-account*
  stream — there is no correct version of this) and encoding the account into the exchange **name**
  string (stringly-typed, and `Order.exchange` is a **persisted column**, so the composite would leak
  into durable data and every query over it). **Traceability:** record as a discovered requirement in
  the phase audit; the planner should confirm with the owner whether it also warrants an explicit
  MPORT-07 entry in `REQUIREMENTS.md` to keep the 64/64 coverage table honest.

### Decomposition & migrations (Areas 10 & 12)

- **D-28 (SEVEN waves, ONE phase — do not split):** P11 stays whole with explicit wave boundaries.
  The work is one coherent capability; splitting it would leave an intermediate state where accounts
  are per-portfolio but reconciliation still assumes one — **worse than either end**, and a state that
  must never be run live. P12 depends on P11 as a unit anyway. Wave structure and dependencies:

  | Wave | Work | Depends |
  |---|---|---|
  | **W1 Schema** | `venue_accounts` + `portfolios` tables, migrations, B2 (Uuid + FK CASCADE), portfolio-config move (D-09) | — |
  | **W2 Credentials** | `CredentialResolver` Protocol + env resolver, `credential_model` on plugins, secret-ref resolution, TOFU `venue_uid` | W1 |
  | **W3 Accounts** | `new_account()` Protocol method, required `account_id` on `VenueAccount`, per-account connectors, per-account **exchange** (D-27), delete `_link_venue_account_to_portfolios` + facade singleton | W2 |
  | **W4 Bootstrap** | portfolios rehydrate, pinnable `portfolio_id` + fix the two false comments (F-1), distinct invariant + refuse-to-start | W1, W3 |
  | **W5 Attribution** | `clOrdId` rename + response-reader helper, `assert`→raise | *independent — parallelizable* |
  | **W6 Reconcile** | per-portfolio coordinator, all-symbols baseline guard, evaluate-all (F-2), quarantine + admission gate + CONTROL release + read-model | W3, W4 |
  | **W7 Tests** | two-paper-account lifecycle + restart (D-25) | all |

- **D-29 (TWO chained Alembic revisions; refuse-if-non-empty on the B2 type change):** Revision 1
  creates `venue_accounts` **then** `portfolios` (order matters — `portfolios` FKs `venue_accounts`).
  Revision 2 does the B2 `String`→`Uuid` change **plus** the FK to `portfolios` **plus** the D-09
  config move. Separates "create new" from "modify existing", which is where the risk and the data
  guards live. Chains after the current head **`p10_strategy_portfolio_subs`**; the milestone's
  single-head + parity gate covers the full chain. For the B2 type change on a possibly-populated
  table: **refuse loudly if non-empty**, mirroring P10's own migration which opens with
  `_refuse_if_subscriptions_hold_data()` before its destructive op (and which STATE.md flags as
  assumption **A1** — unverifiable from source, worth a manual `SELECT count(*)` first). Especially
  defensible here because any existing rows point at `portfolio_id`s that F-1 has already orphaned.
  **Rejected:** one big revision (atomic, and it follows P10's precedent — but mixes creates, an
  in-place type change and a data migration under one downgrade path), three revisions (more surface
  for the parity gate, little practical gain), and an in-place `USING portfolio_id::uuid` cast
  (Postgres-specific where the store's test path runs on **SQLite** — P10 already needed
  `batch_alter_table` for exactly this reason — and it preserves rows that are orphaned anyway).

### Claude's Discretion

- Exact `CredentialResolver` Protocol shape/location and the `secret_ref` URI format (D-02).
- Exact `venue_accounts` / `portfolios` column types and nullability (D-05, D-07).
- Whether `VenuePlugin.credential_model` is a class attribute, a property, or a classmethod (D-03).
- The `VenueAccountConfig` object's shape passed to `new_account(portfolio, config)` (D-10).
- How `ExecutionHandler` composes its `(venue, account_id)` key and whether the `id()`-based alias
  dedup in `on_market_data` (`execution_handler.py:141-145`) needs adjusting (D-27).
- The quarantine read-model entry shape (D-24) and the CONTROL verb name for release (D-23).
- Where portfolio rehydrate runs relative to the existing deferred-session-wiring contracts in
  `build_live_system` (the same P10 research risk applies — see Research Items).
- Plan/commit granularity **within** each of the seven waves (D-28 fixes the waves, not the plans).

### Folded Todos

- **`.planning/todos/pending/b2-strategy-subscription-portfolio-id-uuid-column.md`** — **FULLY
  FOLDED.** Scope is **both** halves, and they are one piece of work, not two: change
  `strategy_portfolio_subscriptions.portfolio_id` from `String` to `Uuid` **and** add the FK to
  `portfolios.portfolio_id` with **`ON DELETE CASCADE`**. The owner correctly observed the table
  already exists from P10 and asked whether only the relationship was missing — investigation
  confirmed it: the `strategy_name` half **has** a real FK → `strategy_registry.strategy_name`
  (`strategy_registry_store.py:113-127`), while the `portfolio_id` half has **none**, because there
  was no `portfolios` table to reference. **The type change is a prerequisite for the FK** — the new
  `portfolios.portfolio_id` PK is `Uuid` (matching `orders.portfolio_id` `Uuid(as_uuid=True)` and
  `portfolio_account_state.portfolio_id` `sa.Uuid()`), and a `String` child column cannot FK to a
  `Uuid` parent. `strategy_portfolio_subscriptions.portfolio_id` is the **odd one out** among the
  three. **The reason P10 left it open no longer holds:** the in-code comment says `String` because
  *"`to_dict` serializes each handle via `str(pid)` and rehydrate parses it back"* — that is a
  **serialization** concern, not a storage one, and `Uuid(as_uuid=True)` does that conversion at the
  driver boundary exactly as `orders.portfolio_id` already does. **CASCADE** chosen because a
  subscription to a nonexistent portfolio has no meaning (unlike an orphaned bracket child, where
  `orders.parent_order_id` deliberately uses `SET NULL` per WR-01) and because such rows would
  otherwise quarantine loudly at every subsequent rehydrate.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **MPORT-01..06** (lines 318–338) + the milestone-wide gates.
- `.planning/ROADMAP.md` → "Phase 11 ★: Multi-Portfolio-Live" (goal + 5 success criteria,
  lines 488–500); Phase 12 (lines 503–515) for the TEST-03/TEST-04 boundary D-25 splits against.

### Design source
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` — **§10a** (cardinality
  model: strategy⇄portfolios M:N, portfolio→one Account keyed by `account_id`; the fail-loud
  not-supported case), **§10b** (per-portfolio account minting; `new_account(portfolio_ref, config)`;
  delete `_link_venue_account_to_portfolios`), **§10c** (attribution & reconciliation; the
  `client_order_id`-vs-`portfolio_id` two-key split), **§8c** (connector memoization —
  `dict[(venue, account_id), LiveConnector]`, credentials per-`account_id`), **§14** (deferred seams:
  multi-provider feed-router → D-26; single-connector-multi-`account_id` → D-12; shared-`account_id`
  risk allocator → D-15).

### Prior-phase context this phase depends on / cashes forward
- `.planning/phases/05-venue-registry-bundle/05-CONTEXT.md` — **D-07** (the three explicit P11
  deferrals: `OKX_<ACCOUNT>_*` env scheme, a real `PortfolioSpec.account_id`, per-account credential
  dispatch; plus `account_id` = a config-known **stable name** resolved pre-`connect()`), **D-03**
  (`ConnectorProvider` + the `(venue, account_id)` memo and why a memo at all), **D-04**
  (triple-deferral laziness — **planner/executor MUST NOT hoist plugin imports to module top**),
  **D-05** (`'simulated'` is deliberately NOT a registered venue), and its Deferred Ideas
  (venue-provided account-UID reconciliation → D-04 here).
- `.planning/phases/07-safety-reconciliation-stream-recovery/07-CONTEXT.md` — **D-03** (throttle caps
  are global; per-`account_id` keying is a shaped seam for P11 → deferred by D-30), **D-17**
  (`ReconciliationCoordinator` home).
- `.planning/phases/10-strategies-registry/10-CONTEXT.md` — **D-01** (injected catalog; the store is
  the source of truth for instances — the pattern D-02 and D-08 both follow), **D-06** (typed column
  vs `config_json` split → D-05), **D-07** (disable keeps positions/brackets warm → reused verbatim
  by D-22), **D-19** (per-instance quarantine + CRITICAL alert, not halt → D-22/D-24; and the
  contrast D-15 draws), **D-22** (test-the-external-path precedent → D-25).
- `.planning/phases/09-runtime-config-platform/09-CONTEXT.md` — **D-25** (`config_json` per owning
  store; the `portfolio_account_state.config_json` home D-09 migrates OFF), **D-23** (the
  no-FastAPI-driver test precedent), RTCFG-03/RTCFG-06.
- `.planning/phases/04-storage-schema-migrations-relocation-new-durable-stores/04-CONTEXT.md` —
  **D-06** (natural name PK — the basis of D-05's composite key) + the store/registrar template.
- `.planning/codebase/CONVENTIONS.md` — **D-03a** justified-overlap / defense-in-depth precedent
  (cited by D-14); the tab/space indentation hazard.

### Existing code P11 changes / extends
- `itrader/storage/venue_store.py:40-77` — `_assert_no_secret_keys` + `_SECRET_KEY_DENYLIST`
  (**exact lowercased membership**); `:96-99` the typed-`enabled`-plus-`config_json` shape D-05 copies.
- `itrader/config/okx_settings.py` — `OkxSettings` (`SecretStr` end-to-end, plain `OKX_API_*`
  `validation_alias` per D-10 of P1, region/sandbox host derivation). The `credential_model` D-03
  exposes.
- `itrader/connectors/provider.py:67-91` — `_plugins` (venue-keyed) vs `_memo`
  (`(venue, account_id)`-keyed) + `close_all()`. The D-12 caveat lives here.
- `itrader/venues/bundle.py:65` `account_factory` field, `:77` `VenuePlugin` Protocol, `:90`
  `build_bundle`; `:96` `DataProviderPlugin`.
- `itrader/venues/okx_plugin.py:85-115` — `build_bundle` (one exchange, one connector,
  `spec.account_id or "default"`) and **`:101-110` the `account_factory(*args, **kwargs)` swallowing
  arm** (the D-11 trap); `:130-145` the data arm (D-26).
- `itrader/venues/paper_plugin.py:63-69` — the real `account_factory(portfolio, initial_cash)` signature.
- `itrader/portfolio_handler/account/base.py:35` `Account` ABC (no `account_id` member);
  `account/venue.py:55,75-82` `VenueAccount.__init__` (D-11); `account/simulated.py:69,89,609,631`.
- `itrader/portfolio_handler/portfolio.py:71` — **F-1**, the fresh-UUIDv7 `portfolio_id`; `:68` the
  false restart-stability claim; `:73` `self.exchange` (D-07).
- `itrader/portfolio_handler/portfolio_handler.py:198-249` `add_portfolio`; `:365-368` `exchange_for`
  (gains `account_for`, D-27); `:918+` `rehydrate`; `:217` the `max_portfolios` limit (default 50,
  `config/portfolio.py:42`).
- `itrader/portfolio_handler/storage/models.py:78-220` — the seven portfolio-scoped child tables;
  `storage/sql_storage.py:526-560` `save_config`/`load_config` (the D-09 migration source).
- `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:80-91` ctor, `:103-148`
  `run_startup_reconcile`, **`:151-176` `_link_venue_account_to_portfolios` + the `RuntimeError(>1)`
  guard (both DELETED by MPORT-01)**, `:193-216` `_run_session_baseline_guard` (D-20/D-21/F-2),
  `:215` the `HaltReason.BASELINE_RESIDUAL` call D-22 replaces.
- `itrader/portfolio_handler/account/conformance.py:3,51` — a mypy-only mirror of the account
  assignment; nothing imports it at runtime. Check whether it survives MPORT-01.
- `itrader/execution_handler/execution_handler.py:66` `exchanges` dict, **`:123-131` `on_order`'s bare
  name lookup (D-27)**, `:136-151` `on_market_data` + the `id()` alias dedup.
- `itrader/execution_handler/exchanges/okx.py:101-145` `__init__` (one connector, one
  `VenueCorrelationIndex`, stream handles — all account-scoped), `:204-232` `_client_order_id` +
  **`:230` the bare assert (D-18)**, `:402,407` precision via the connector's client, `:425-428`
  `params["clOrdId"]` + `register_pending`, `:443,492` `register`, `:952-969` the markets-map
  fail-closed check (CF-9/D-11).
- `itrader/execution_handler/exchanges/venue_correlation.py:81-94` `_extract_client_order_id` (the
  D-16 helper), `:139-151` the five `venue_id`-keyed dicts, `:141` `_orders_by_clOrdId`.
- `itrader/order_handler/storage/models.py:61-113` — `orders` incl. `portfolio_id`
  `Uuid(as_uuid=True), nullable=False`, `venue_order_id`, the `(portfolio_id, status)` index.
- `itrader/order_handler/admission/admission_manager.py:50,177-179,321,386,416,429,444` — already
  fully per-`portfolio_id`; the D-22 gate is one guard clause here.
- `itrader/storage/strategy_registry_store.py:113-127` — `strategy_portfolio_subscriptions`
  (`strategy_name` FK present, `portfolio_id` `String` with **no** FK — the folded B2 todo).
- `itrader/strategy_handler/strategies_handler.py:524-536` — the existing signal fan-out loop over
  `subscribed_portfolios` (already multi-portfolio; P11 changes nothing here).
- `itrader/trading_system/safety/safety_controller.py:146,151,265,284` — the global scalars D-22
  extends per-portfolio; consumed at `live_trading_system.py:473,607`.
- `itrader/trading_system/live_trading_system.py:195` the `_venue_account` singleton (D-13),
  `:1262-1266` the portfolio-config restart layering (D-09), `:1583-1585` the false
  restart-stability comment (F-1), `:1273+` `build_live_system`.
- `itrader/trading_system/system_spec.py:38-48` `PortfolioSpec(name, cash)`, `:126`
  `SystemSpec.account_id` (D-26 rename); `venue_spec.py:52`.
- `itrader/trading_system/backtest_trading_system.py:507-525` — the existing N-portfolio
  cross-product subscription loop (the pattern live lacks).
- `migrations/versions/` — chain head is **`p10_strategy_portfolio_subs`**; `p10_strategy_portfolio_subs.py`
  is the D-29 template (guard-before-destructive-op, `batch_alter_table` for SQLite, hand-written
  type import). **NOTE:** revision id `venue_config` builds the table actually named `venue_store`.

### Gates (must stay green — restated, not re-decided)
- `tests/integration/test_backtest_oracle.py` — byte-exact `134 / 46189.87730727451`. P11 is
  backtest-dark, but D-27 touches `ExecutionHandler.on_order`/`exchanges` and D-09 touches portfolio
  config — **both are shared-path edits and MUST be oracle-verified**.
- `tests/integration/test_okx_inertness.py` — import inertness. The `CredentialResolver` Protocol and
  the `credential_model` exposure must stay SQL/ccxt-free; `venue_accounts`/`portfolios` store imports
  stay **LAZY** inside the `build_live_system` gate; never barrel-export.
- `tests/integration/test_live_system_okx_wiring.py:292,319` and
  `tests/integration/test_live_portfolio_durable_wiring.py:148` call
  `_link_venue_account_to_portfolios` directly — they will break when MPORT-01 deletes it.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`ConnectorProvider._memo` is ALREADY `(venue, account_id)`-keyed** (`provider.py:69-80`) —
  MPORT-06's shape is shipped. But see the D-12 caveat: `_plugins` behind it is venue-only.
- **Signal fan-out is ALREADY multi-portfolio** — `strategies_handler.py:524-536` loops
  `strategy.subscribed_portfolios` emitting one `SignalEvent` per portfolio; `subscribe_portfolio` /
  `unsubscribe_portfolio` exist (`base.py:1063-1075`) and persist (`strategy_registry_store.py:239`).
  **P11 changes nothing here.**
- **`AdmissionManager` is ALREADY fully per-`portfolio_id`** — every read goes through
  `PortfolioReadModel` keyed by portfolio. The D-22 quarantine gate is one guard clause.
- **`portfolio_id` is ALREADY a typed first-class field** on `SignalEvent`/`OrderEvent`/
  `OrderAckEvent`/`FillEvent`/`Order` — D-17 needs no event changes.
- **Backtest ALREADY builds N portfolios** from `spec.portfolios` with a full cross-product
  subscription (`backtest_trading_system.py:507-525`) — the pattern live lacks.
- **`SafetyController` already has quarantine's exact shape** as global scalars — D-22 is a
  per-portfolio set beside them, not new machinery.
- **`alert_sink` (P8 CRITICAL egress) + the `state.*` read-model (RTCFG-06)** — D-04/D-22/D-24 need
  no new channel.
- **P10's migration is the D-29 template** — guard-before-destructive-op, `batch_alter_table` for the
  SQLite test path, hand-written custom-type import.

### Established Patterns
- **Indentation is SPLIT per file — MEASURE BYTES, never generalize the package.** Measured this
  session: **4-space** — `live_trading_system.py`, `reconciliation_coordinator.py`,
  `portfolio_handler.py`, `account/{base,venue,simulated,conformance}.py`, all of `venues/`,
  `connectors/provider.py`. **TABS** — `system_spec.py`, `venue_spec.py`,
  `backtest_trading_system.py`, `order_handler/order_handler.py`, `admission/admission_manager.py`,
  `strategy_handler/{strategies_handler,base}.py`, `execution_handler/exchanges/{okx,venue_correlation}.py`.
  Note `trading_system/` is **mixed** — `live_trading_system.py` is 4-space while its siblings are tabs.
- **Loud rejection over silent no-op** — D-11, D-15, D-18, D-29 all follow it.
- **Import inertness (GATE-01)** — live/SQL imports stay LAZY inside `build_live_system` gates.
- **Registrar = single source of truth** (`build_*_tables` feeds both the test `create_all` and
  Alembic `target_metadata`); schema-pure stores (never `create_all` at runtime); parameterized Core
  only (SEC-01); caller-supplied `at` via `UtcIsoText` (clock-free).
- **Events are `msgspec.Struct`** (NOT the frozen `@dataclass` CLAUDE.md describes).
- **Money is Decimal end-to-end**; enter via `to_money` (string path) — never `Decimal(float)`.

### Integration Points
- `build_live_system` — construct the two new stores (lazy, SQL-gated), receive the injected
  `CredentialResolver`, run portfolios rehydrate, run the D-14/D-15 invariant check **before** any
  account is minted.
- **ORDERING CONSTRAINT (inherited from P10):** portfolios must rehydrate **BEFORE** strategies
  re-subscribe to them (`live_trading_system.py:1583-1585`) — and after F-1, those ids are finally
  genuinely restart-stable.
- `ExecutionHandler.exchanges` / `on_order` — the D-27 routing change.
- `ReconciliationCoordinator` — D-19/D-20/D-21/D-22.
- `AdmissionManager` — the D-22 quarantine guard clause.

### Discovered Defects (carried into execution — NOT in CONTEXT before this session)
- **F-1 (HIGH — `portfolio_id` is not restart-stable, contradicting two in-tree comments):**
  `portfolio.py:71` does `self.portfolio_id = PortfolioId(idgen.generate_portfolio_id())` — a fresh
  UUIDv7 on **every** construction, with **no way** to pass an existing id through
  `Portfolio.__init__` or `add_portfolio`. Yet `portfolio.py:68` claims state persists "keyed by
  `portfolio_id` (surviving a process restart)" and `live_trading_system.py:1583-1585` claims strategy
  rehydrate "binds to ids that already exist and are **restart-stable**". Both hold **only within one
  process**. On restart the prior run's `portfolio_account_state` rows are orphaned and P10's
  persisted `strategy_portfolio_subscriptions.portfolio_id` rows point at portfolios that no longer
  exist. **Pre-existing, not caused by P11** — but P11 is where it stops being survivable, because
  per-portfolio reconciliation must match a portfolio to its venue account across a restart. P11 must
  make `portfolio_id` supplyable **and correct both comments** (folded into the W4 bootstrap plan).
- **F-2 (MEDIUM — the baseline guard returns on first mismatch):**
  `_run_session_baseline_guard` (`reconciliation_coordinator.py:216`) `return`s after the first
  portfolio mismatch. Benign with one portfolio; with N it stops the scan early. Must become
  evaluate-all (D-21) — and D-22's per-portfolio quarantine makes it mandatory, not merely tidier.

### Research Items (must resolve)
1. **Where portfolios rehydrate runs** vs the deferred-session-wiring contracts in `build_live_system`
   — the **same** research risk P10 hit ("the pervasive add-strategy-after-construction +
   monkeypatch-`_initialize_live_session`-before-`start()` contracts across the live test suite").
   D-08's rehydrate **creates portfolios**, so this must be resolved against those contracts.
2. **The D-09 config migration** — confirm the exact shape stored in
   `portfolio_account_state.config_json` today, that moving it preserves RTCFG-03 semantics, and that
   P12's TEST-03 gate still passes. This is the highest-regression-risk item in the phase.
3. **How `ExecutionHandler` keys and looks up per-account exchanges** (D-27), and whether the
   `id()`-based alias dedup in `on_market_data` needs adjusting now that multiple distinct exchange
   objects share a venue.
4. **Whether `max_portfolios` (default 50, `config/portfolio.py:42`) and `Account`/`conformance.py`
   need any change** — flagged, not investigated.

</code_context>

<specifics>
## Specific Ideas

- **The owner's driving architecture (drove D-02/D-03):** an **integrations page** in the FastAPI web
  app listing every supported venue; connecting a venue means entering the keys that venue's Pydantic
  model declares; those secrets go to **a secret manager usable both locally and in production**.
  Explicitly: *"i do not want to define venues keys in the .env files, that was just temporary."*
  D-03's `credential_model` exposure exists so that page renders its form from the venue registry
  rather than hardcoding per-venue fields.
- **The owner rejected nested JSON storage outright (drove D-05):** *"i do not like this nested
  structure. i want a flat one, a raw for each account"* — overriding a YAGNI/speculative-schema
  objection. It is also the correct end-state cardinality (LR-21), and the same instinct produced
  the flat `portfolios` table in D-08.
- **The owner's redundancy catch (drove D-07):** *"i believe i do not need an exchange column since i
  can get it via the account_id key"* — correct in substance; `Portfolio.exchange` is now derived
  from `venue_name` rather than stored twice. The refinement was only that identity is the *pair*, so
  the reference is two columns.
- **The owner's schema-continuity catch (drove the B2 fold-in):** *"since we already have a list of
  portfolios to which a strategy is subscribed, I think we implemented it in the previous phase…
  Maybe we need a new primary foreign key relationship between what we introduced in the previous
  phase and what we will introduce here"* — exactly right, and it converted B2 from cosmetic tidying
  into a prerequisite for a real FK.
- **The owner asked for cost before committing (drove D-22):** *"Is it a big task to implement the
  quarantine logic now?"* — answered with a per-piece breakdown showing most of it already exists;
  the owner then took the more correct blast radius rather than the smaller diff.
- **The owner asked for the architecturally correct answer rather than a menu (drove D-27):** *"what
  would the correct solution be here architecturally speaking?"* — which forced the investigation
  showing every piece of `OkxExchange` state is already account-scoped, making the answer unambiguous
  instead of a trade-off.
- **The owner chose to defer work they intend to redesign (drove D-26):** *"i'll redesign the data
  connector logic. should i defer this?"* — deferred, with only the naming guard kept.

</specifics>

<deferred>
## Deferred Ideas

- **Vault/AWS/GCP-backed `CredentialResolver` implementation** → the web-app repo, post-milestone.
  Blocked in P1–P12 by the zero-new-dependency gate; lands as one more implementation of D-02's
  Protocol with no `itrader` change.
- **Encrypted-credential-blob-in-Postgres** → revisit post-milestone if the operational simplicity of
  one storage system outweighs the backup-exposure argument. A `DbCredentialResolver` is one more
  implementation of the same Protocol. Gate-blocked now (`cryptography` is transitive-only).
- **The data-provider connector's account model** (D-26) → folds into the spec §14 **multi-provider
  feed-router** redesign the owner intends to do. P11 leaves only the `SystemSpec.account_id` rename
  + a todo. **Todo required.**
- **Per-`account_id` pre-trade throttle keying** (D-30) → P7 D-03's shaped seam stays shaped. Wrong in
  a multi-account system but fails *conservatively*. **Todo required.**
- **Single-connector-multi-`account_id` optimization** (OKX master key + per-account routing on one
  session) → spec §14, explicitly not built. D-12 takes the per-account connector instead.
- **Shared-`account_id` risk allocator** (multiple portfolios pooling one venue account, pooled buying
  power the venue cannot split back out) → spec §10a/§14. D-15 fails loud instead.
- **Auto-clearing quarantine** → D-23 is operator-only. Revisit if transient drift proves common
  enough to be operationally annoying.
- **Splitting `Portfolio.exchange` semantics further** — D-07 derives it from `venue_name`; if a
  portfolio ever needs to trade multiple venues, this becomes a real modelling question.
- **An explicit MPORT-07 entry in REQUIREMENTS.md for D-27** — the planner should confirm with the
  owner whether the discovered exchange-cardinality scope warrants a numbered requirement to keep the
  64/64 coverage table honest, or stays a recorded discovered-scope note.

### Reviewed Todos (not folded)
- `shared-strategy-admission-seam.md` — strategy-admission exception policy; unrelated to portfolio
  cardinality.
- `margin-equity-double-counts-notional-wr01.md` — the WR-01 margin-equity defect touches
  `Portfolio.total_equity` and the reconcile path, but it is a valuation-correctness issue orthogonal
  to multi-portfolio wiring, and its frozen goldens were never externally cross-validated. Not folded.
- `operator-emergency-shutdown-command.md` / `operator-force-close-position-command.md` — adjacent to
  D-23's new operator CONTROL verb and worth batching **with each other** in a future operator-command
  phase, but out of MPORT scope.
- `claude-md-alembic-migration-chain-path-wrong.md` — doc drift, not P11 work.
- The remaining ~18 pending todos matched only on generic tokens and are out of this domain.

</deferred>

---

*Phase: 11-Multi-Portfolio-Live ★*
*Context gathered: 2026-07-21*
