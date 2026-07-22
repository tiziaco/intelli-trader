# Phase 11: Multi-Portfolio-Live ★ - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 11-Multi-Portfolio-Live
**Areas discussed:** account_id identity + credentials · live portfolio bootstrap · new_account() plugin surface + connector cardinality · distinct-account_id invariant · client_order_id rename + tagging · per-portfolio reconciliation · P11-vs-P12 test boundary · portfolio config home · data-provider connector account · wave decomposition + migration shape · exchange cardinality (discovered)

---

## Area 1 — account_id identity + credentials

### Namespace

| Option | Description | Selected |
|--------|-------------|----------|
| Per-venue: identity is the (venue, account_id) pair | Matches the ConnectorProvider memo key already shipped in P5 | ✓ |
| Global: account_id unique across the engine | Simpler invariant; diverges from the shipped memo key | |

### Credential resolution

| Option | Description | Selected |
|--------|-------------|----------|
| CredentialResolver Protocol + secret-ref pattern | DB stores a pointer; env resolver ships now, vault resolver later in the app repo | ✓ |
| Same Protocol, DB-backed resolver as the target | Accepts secrets in Postgres once a crypto dep is allowed | |
| Defer credentials out of P11 | All portfolios share one venue login | |

**User's choice:** Protocol + secret-ref — but only after redirection. The user's stated preference was option 2: *"ideally i'd go with option 2, implementing a more durable solution to store venue's credentials… i was thinking to a secret manager that can be used both locally and in a production setup. but also a database table if you think it's doable."*
**Notes:** Two blocking findings changed the answer, both surfaced by inspection rather than assumed — (1) `venue_store.py:40-77` already ships `_assert_no_secret_keys` (D-05), a recursive denylist raising ValidationError with *"credentials are connector-owned and must never be persisted to VenueStore"*; (2) the milestone-wide zero-new-dependency gate blocks every secret-manager SDK **and** blocks promoting `cryptography` (transitive via ccxt only) for envelope encryption. The user's actual workflow requirement — an integrations page, no `.env` — is fully served by the pointer pattern.

### P11 credential scope

| Option | Description | Selected |
|--------|-------------|----------|
| Protocol + env resolver only; durable record deferred | Smallest P11 | ✓ (later SUPERSEDED) |
| Protocol + env resolver + durable table now | Schema settled on day one | |

**Notes:** Superseded later in the same area when the user chose a flat `venue_accounts` table in P11.

### Venue plugin exposes credential schema

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — plugin exposes its settings model | Integrations page renders forms with zero hardcoding | ✓ |
| No — web app imports the settings models directly | Zero P11 surface change | |

### Venue-UID assertion

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — capture UID post-connect and assert, halt on mismatch | Only mechanism catching a swapped credential | |
| Yes, but observe-only — log/alert, don't block | CRITICAL alert, no halt | ✓ |
| No — stay deferred past P11 | Smallest scope | |

### Expected-UID source

| Option | Description | Selected |
|--------|-------------|----------|
| Trust-on-first-use | Record on first connect, assert thereafter | ✓ |
| Operator-declared | Entered up front via the integrations page | |
| Planner decides | | |

### Per-account data storage

| Option | Description | Selected |
|--------|-------------|----------|
| Nest an accounts sub-map in VenueStore.config_json | Zero new table, zero migration | |
| New dedicated column on venue_config | Still venue-keyed | |
| New flat venue_accounts table, keyed (venue, account_id) | Correct end-state cardinality | ✓ |

**User's choice:** Flat table — *"i do not like this nested structure. i want a flat one, a raw for each account. would that be option 3?"*
**Notes:** Overrides the YAGNI/speculative-schema objection that had been raised against it. The user first asked *"couldn't i simply add a credentials column in the current VenueStore table without adding any new table just for a ref to the credentials?"* — which was answered by showing VenueStore's PK is venue-only, so any per-account data must be keyed by account regardless.

### venue_accounts PK / columns

| Option | Description | Selected |
|--------|-------------|----------|
| Composite natural PK (venue_name, account_id) | Matches memo key + P4 D-06 convention | ✓ |
| Surrogate UUID + UNIQUE constraint | FK-friendly opaque id | |

**User's choice:** Composite natural PK; and for columns — *"i'd say option 1, but maybe in a dedicated config_json column, that is separated from the credentials ref one?"*
**Notes:** Produced the three-lifecycle split: `secret_ref` (pointer), `venue_uid` (engine-written TOFU), `config_json` (operator-authored). Naming gotcha recorded: the denylist is exact lowercased membership, so `credential` is denied while `credentials` and `secret_ref` pass — hence `secret_ref`, never `credentials`.

---

## Area 2 — Where a live portfolio declares its account_id

| Option | Description | Selected |
|--------|-------------|----------|
| Pinnable id + account_id params; the app owns portfolio definitions | Matches ACCT-04's app-layer posture | |
| Add the missing portfolios definition table + rehydrate | Parallels venue_store and strategy_registry | ✓ |
| Minimal: account_id param only, leave ids ephemeral | Literal MPORT-05 | |

**User's choice:** The definition table. The user first challenged the premise — *"don't i already have a portfolio table in itrader actually, where i store the balance, is_active and other?"* — which was checked and answered: seven portfolio-scoped child tables exist (balance included, via `portfolio_account_state.cash_balance`), but **no** definition row anywhere.
**Notes:** Reframed the area — portfolios are the only major entity in the system with child state tables and no parent.

### portfolio_id restart-stability defect (F-1)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix in P11, tracked as a discovered defect with its own plan | Like P10's F-1 | |
| Fix in P11, folded into the bootstrap plan | Less ceremony | ✓ |
| Todo for a later phase | | |

### Venue/account reference columns

| Option | Description | Selected |
|--------|-------------|----------|
| venue_name + nullable account_id; drop exchange, derive from venue_name | No redundant column | ✓ (nullable half later SUPERSEDED) |
| Globally-unique account_id so one column suffices | Reverses the namespace choice | |
| Keep exchange alongside account_id | Avoids nullable-FK awkwardness | |

**User's choice:** *"i'd like to go with option 1, but i believe i do not need an exchange column since i can get it via the account_id key."*
**Notes:** Correct in substance — `exchange` is redundant and becomes derived from `venue_name`. One refinement applied: identity is the *pair*, so `account_id` alone cannot derive the venue and the reference is inherently two columns.

### FK to venue_accounts

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, nullable — enforced only when account_id is set | | ✓ (later SUPERSEDED to unconditional) |
| No FK — validate in application code | | |
| Planner decides | | |

---

## Area 3 — new_account() plugin surface + connector cardinality

**User asked for worked examples of all three options before answering.** Writing them out produced a correction to the orchestrator's own earlier claim — see Notes.

| Option | Description | Selected |
|--------|-------------|----------|
| A — new_account() as a typed VenuePlugin Protocol method | Consolidates on the plugin, matches spec §10b | ✓ |
| B — keep the bundle field, tighten Callable[..., Account] | Smallest diff | |
| C — Protocol method plus a delegating shim | Gentlest migration | |

**Notes:** The orchestrator had claimed option A "kills the arg-swallowing trap structurally via mypy --strict". **That was wrong and was retracted before the user answered:** `(*args: Any, **kwargs: Any)` is the universally-compatible signature in mypy and satisfies any Protocol method, and `VenuePlugin` is a structural Protocol that plugins don't subclass. The surface choice governs where code lives, not whether wrong-wiring is possible.

### The actual structural guard

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — account_id as a required keyword arg on VenueAccount, no default | Wrong-wiring becomes a TypeError | ✓ |
| Yes, but with a "default" fallback | Smoother migration | |
| No — scope it another way | | |

### Connector cardinality

| Option | Description | Selected |
|--------|-------------|----------|
| One connector per (venue, account_id) | What the memo already implements; spec §14 defers the alternative | ✓ |
| One per venue, routing orders by account_id | OKX master-key model | |

### Facade's _venue_account singleton

| Option | Description | Selected |
|--------|-------------|----------|
| Delete it — each Portfolio owns its account | | ✓ |
| Replace with a dict keyed by (venue, account_id) | | |
| Planner decides | | |

---

## Area 4 — the distinct-account_id invariant

### NULL scope

| Option | Description | Selected |
|--------|-------------|----------|
| No — invariant covers only non-NULL pairs | Many paper portfolios allowed | |
| Yes — every portfolio must have a distinct account_id, NULL included | One rule, no exceptions | ✓ |

**Notes:** This **conflicted** with Area 2's nullable decision and was surfaced rather than silently reconciled. Literal enforcement would need Postgres `NULLS NOT DISTINCT`, permitting at most one paper portfolio system-wide. Resolved in a follow-up question below.

### Conflict resolution

| Option | Description | Selected |
|--------|-------------|----------|
| account_id NOT NULL everywhere; venue_accounts holds paper rows too | Plain index, unconditional FK, no exceptions | ✓ |
| Keep nullable; invariant applies only to non-NULL | Simplest paper setup | |
| Nullable but at most ONE NULL portfolio | Literal reading | |

### Enforcement / failure

| Option | Description | Selected |
|--------|-------------|----------|
| Both — DB unique index + application check | Defense-in-depth (CONVENTIONS.md D-03a precedent) | ✓ |
| Application check only | | |
| DB constraint only | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Refuse to start — hard fail before any account is minted | Matches MPORT-02 wording | ✓ |
| Quarantine the colliders, boot the healthy ones | P10 D-19 style | |
| Planner decides | | |

---

## Area 5 — client_order_id rename + portfolio tagging

| Option | Description | Selected |
|--------|-------------|----------|
| Engine symbols only; wire strings stay clOrdId | Contained to 2 files | |
| Engine symbols + normalize response readers behind one helper | Wire spelling in exactly one place | ✓ |
| Planner decides | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Index + durable orders row; do NOT change the id format | Attribution already derivable three ways | ✓ |
| Encode an account/portfolio tag into the clOrdId string | Self-describing at the venue | |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — convert the bare assert at okx.py:230 to a real raise | Stripped under python -O today | ✓ |
| No — log a todo instead | | |

---

## Area 6 — per-portfolio reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Ask each portfolio for its own account | Single source of truth | ✓ |
| Inject a dict[(venue, account_id) -> Account] | Easier isolated testing | |

| Option | Description | Selected |
|--------|-------------|----------|
| Every symbol the account reports a position in | Closes a latent gap that exists today | ✓ |
| Union of the portfolio's subscribed symbols | Tighter scope | |
| Keep the single configured symbol, just per-account | Minimal change | |

### Drift failure semantics

**User asked for a cost estimate first:** *"Is it a big task to implement the quarantine logic now?"* — answered with a per-piece breakdown showing `SafetyController` already has the shape as global scalars, `AdmissionManager` is already portfolio-keyed, and the alert channel and read-model already exist; only the release path is novel design. Estimated 1–2 plans.

| Option | Description | Selected |
|--------|-------------|----------|
| Quarantine that portfolio; the rest keep trading | Correct blast radius for isolated accounts | ✓ |
| Keep today's behaviour — global latched halt | Zero new machinery | |
| Global halt in P11; quarantine as a follow-up todo | Keeps P11 bounded | |

| Option | Description | Selected |
|--------|-------------|----------|
| Operator-only release via a CONTROL command | Mirrors the halt posture | ✓ |
| Auto-clear on a subsequent clean reconcile | | |
| Both — auto-clear transient, operator for persistent | | |

---

## Area 7 — P11 vs P12 test boundary

| Option | Description | Selected |
|--------|-------------|----------|
| P11 proves the full lifecycle incl. restart; P12 owns the gate | P10 D-22 / P9 D-23 precedent | ✓ |
| P11 proves mechanism only; P12 owns end-to-end | Cleanest separation | |
| P11 proves everything; fold TEST-04 forward | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Two paper accounts on the simulated venue | Deterministic, CI-safe, no credentials | ✓ |
| Paper for CI + an opt-in OKX demo test | | |
| Planner decides | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Defer per-account_id throttle keying with a todo | Fails conservatively | ✓ |
| Build it in P11 | Completes the isolation story | |

---

## Area 8 — portfolio config home (raised in the second round)

**Surfaced as a collision in what had already been locked:** the `config_json` proposed for the new `portfolios` table duplicated P9 D-25's existing `portfolio_account_state.config_json`.

| Option | Description | Selected |
|--------|-------------|----------|
| Drop config_json from portfolios; P9's home stays the only one | Zero disruption to the tested RTCFG-03 path | |
| Split authoring vs runtime across the two blobs | Mirrors P10 D-04 | |
| Move config onto the portfolios definition row entirely | Cleanest end state | ✓ |

**Notes:** The riskiest decision in the phase — it touches the RTCFG-03 restart path that P12's TEST-03 gate verifies. Flagged as a research/regression item for the planner, and the migration must move existing data, not just repoint reads.

---

## Area 9 — data-provider connector account

**User's question:** *"i'll redesign the data connector logic. should i defer this?"* — answered yes, with the reasoning that deferring costs one extra connector (a cost, not a defect) and that spec §14 already carries the multi-provider feed-router as the natural home.

| Option | Description | Selected |
|--------|-------------|----------|
| Defer + rename SystemSpec.account_id to say it is data-only | Stops a stale name misleading the redesign | ✓ |
| Defer with a todo only; leave the field name alone | | |
| Do not defer — settle the data account model in P11 | | |

---

## Area 10 — decomposition and migration shape

| Option | Description | Selected |
|--------|-------------|----------|
| Seven waves in one phase | Splitting leaves a dangerous intermediate state | ✓ |
| Split into P11 + an inserted P11.1 | 6.1 / 10.1 precedent | |
| Fewer, larger waves (3-4) | | |
| Planner decides | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Two chained revisions: new tables, then the subscriptions alter | Separates create-new from modify-existing | ✓ |
| One revision doing everything | P10 precedent, atomic | |
| Three revisions, one per concern | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Refuse-if-non-empty guard, mirroring P10's migration | | ✓ |
| Cast in place with USING portfolio_id::uuid | Postgres-specific; test path is SQLite | |
| Planner decides | | |

---

## Area 11 — exchange cardinality (DISCOVERED, not in MPORT-01..06)

**User's question:** *"about the exchange question, what would the correct solution be here architecturally speaking?"* — which prompted an investigation of what `OkxExchange` actually holds, rather than a trade-off menu.

**Finding:** every piece of mutable state on `OkxExchange` is already account-scoped (connector, `VenueCorrelationIndex`, `watch_my_trades` stream handles, connection status), and the markets/precision map lives on the **connector**, not the exchange. The exchange's true cardinality already *is* `(venue, account_id)`.

| Option | Description | Selected |
|--------|-------------|----------|
| Exchange becomes per-(venue, account_id) | Makes an existing dimension explicit | ✓ |
| One exchange per venue; pass the connector per call | Impossible — watch_my_trades is a private per-account stream | |
| Encode the account into the exchange name string | Leaks into the persisted orders.exchange column | |

| Option | Description | Selected |
|--------|-------------|----------|
| Lock it and record as discovered scope | | ✓ |
| Raise a REQUIREMENTS.md amendment (MPORT-07) first | Keeps 64/64 coverage honest | |
| Reconsider the scope | | |

---

## Folded Todo — b2-strategy-subscription-portfolio-id-uuid-column

**User's challenge:** *"since we already have a list of portfolios to which a strategy is subscribed, I think we implemented it in the previous phase. We should already have all the tables. Maybe we need a new primary foreign key relationship between what we introduced in the previous phase and what we will introduce here."*

Verified and confirmed: the table exists from P10; the `strategy_name` half has a real FK; the `portfolio_id` half has none, because there was no `portfolios` table to reference. The `String`→`Uuid` change turns out to be a **prerequisite** for the FK, not cosmetic tidying.

| Option | Description | Selected |
|--------|-------------|----------|
| Fold in both: String->Uuid AND the FK to portfolios | One piece of work | ✓ |
| Type change only; FK later | | |

| Option | Description | Selected |
|--------|-------------|----------|
| CASCADE on portfolio delete | A subscription to a nonexistent portfolio has no meaning | ✓ |
| RESTRICT | | |
| Planner decides | | |

---

## Claude's Discretion

- CredentialResolver Protocol shape/location and secret_ref URI format
- Exact venue_accounts / portfolios column types and nullability
- Whether `credential_model` is a class attribute, property, or classmethod
- The `VenueAccountConfig` shape passed to `new_account(portfolio, config)`
- How ExecutionHandler composes its (venue, account_id) key; whether the `id()` alias dedup needs adjusting
- Quarantine read-model entry shape and the CONTROL verb name for release
- Where portfolio rehydrate runs relative to the deferred-session-wiring contracts
- Plan/commit granularity within each of the seven waves

## Deferred Ideas

- Vault/AWS/GCP-backed CredentialResolver → web-app repo, post-milestone
- Encrypted-credential-blob-in-Postgres → revisit post-milestone
- Data-provider connector account model → spec §14 feed-router redesign (**todo required**)
- Per-account_id pre-trade throttle keying → P7 D-03's seam stays shaped (**todo required**)
- Single-connector-multi-account_id optimization → spec §14
- Shared-account_id risk allocator → spec §10a/§14
- Auto-clearing quarantine
- Multi-venue portfolios (Portfolio.exchange derived from venue_name assumes one)
- An explicit MPORT-07 REQUIREMENTS.md entry for the discovered exchange-cardinality scope
