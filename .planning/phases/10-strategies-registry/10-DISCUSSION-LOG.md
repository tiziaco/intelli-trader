# Phase 10: Strategies Registry ★ - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-17
**Phase:** 10-Strategies Registry ★
**Areas discussed:** Rehydrate & reconstruction, Verbs & enable/disable (+ data model), Atomic reconfig & quiesce, Pair-strategy reconfig scope, Naming, Rehydrate failure semantics (surfaced), Bootstrap & test surface (surfaced)

---

## Area 1 — Rehydrate & "add" reconstruction

| Option | Description | Selected |
|--------|-------------|----------|
| Class registry (name→class) | Registry of shipped classes; `config_json` carries `strategy_type`; rehydrate + add instantiate `cls(**config)` | ✓ (as refined) |
| State-only onto code-declared roster | Code builds the full roster; rehydrate only re-applies enabled/config/subscriptions; "add" = enable a known strategy | (initially recommended, then rejected) |
| You decide | — | |

**User's choice:** Type catalog + instance store (the refined "class registry").
**Notes:** Non-linear path worth recording. Claude initially recommended **state-only**, on the basis that the user's strategies are code in a private IP submodule and they'd deferred UI-created strategies. **The user overturned it** with the decisive objection: *"if I do `handler.add_strategy(SMAMACDStrategy(name=..., ...))` from the FastAPI app at startup, doesn't this mean the strategies I have in my db are no longer the source of truth?"* — correct: hardcoding instances in app startup reduces the store to a side-cache of flags. They then articulated the fix: *"we need to differentiate between the strategies available to trade (coming from my other repo with IP) and the instances of these strategies."* That type-vs-instance split IS the class-registry model, reframed — the catalog holds **types** (code), the store holds **instances** (data, source of truth). Claude conceded the user's architecture reasoning was better.

### Sub-decision: per-instance identity
| Option | Description | Selected |
|--------|-------------|----------|
| Instance-unique `name` as durable key (store unchanged) | `name` is already a per-instance kwarg; store already PKs on it | ✓ |
| New stable `strategy_id` field + re-key store | Introduce a config-assigned id; `name` becomes a display label | |

**User's choice:** `strategy_name` as the per-instance durable key.
**Notes:** The user proposed *"why don't we define a `strategy_id` for each instance?"* — right instinct, but the code check found a trap: the existing `base.py:192` `strategy_id` is a **fresh UUIDv7 minted per construction** (not restart-stable); keying durability on it would corrupt rehydrate — exactly why P4's D-06 chose the natural name PK. Once a stable, config-assigned, instance-unique key is required, that *is* `name`. Resolved with zero new machinery + a loud duplicate-name reject.

### Sub-decision: serializer/deserializer
| Option | Description | Selected |
|--------|-------------|----------|
| Defer non-scalar round-trip | Persist scalar overrides only; policies come from class-attr defaults | |
| Build a structured tagged-union codec now | Generic dataclass codec + injectable kind→class registry; Decimals as strings | ✓ |

**User's choice:** Build it now — *"I'd rather build a serializer-deserializer logic now, no?"*
**Notes:** Claude had flagged non-scalar policy round-trip as the main risk of the catalog model. Investigation showed `to_dict()` serializes policies as `repr()` (one-way, not reconstruction-safe), but the policies themselves are **frozen dataclasses with typed Decimal fields** — making a generic introspective codec tractable. The user asked *"is it ok to have the params that are not relative to the strategy in the config_json column?"* and *"will I be able to differentiate between timeframe and long_window?"* — which produced the key clarification: the codec keys off **declared type resolved from the class**, not the declaring layer; `get_type_hints` merges base+subclass via MRO, so base-vs-strategy-specific is irrelevant to storage. The split that matters is **authoring / derived / runtime**.

### Sub-decisions confirmed
- Runtime policy update (Q1) → yes, via `reconfigure` with tagged policy blobs.
- Same type, different ticker + different policies (Q2) → yes, as **separate instances** (policies are per-instance, not per-ticker).
- Same type, different ticker + params, same policies (Q3) → yes, also separate instances.

---

## Area 2 — Verbs, enable/disable & data model

| Question | Options | Selected |
|--------|-------------|----------|
| enable/disable mechanism | is_active gate keep-warm ✓ / remove-from-list | is_active gate |
| Payload shape | Extend `StrategyCommandEvent` ✓ / separate typed events | Extend |
| Portfolio fan-out persistence scope | P10 persists full instance state ✓ / defer to P11 | P10 persists |
| Portfolio fan-out mutable at runtime | subscribe/unsubscribe verbs ✓ / fixed at add-time | Runtime verbs |
| `add` + warmup | Add-dark then warm via P7 ✓ / add only if already-warm | Add-dark + P7 |
| `remove`/`disable` with open positions | Force-flat on remove, disable stops new entries ✓ / orphan / defer to Area 3 | Force-flat on remove |

**Notes:** Claude surfaced that `calculate_signals` does **not** check `is_active` (the flag is inert), and that three "subscription-ish" concepts were conflated (`tickers`, the `strategy_subscriptions` table, `subscribed_portfolios`), plus a spec-vs-code mismatch (design spec §9 says subscriptions = "which portfolios"; the built table is `(venue, symbol, timeframe)` with no portfolio column, while the real portfolio fan-out is unpersisted).

### Sub-decision: the data model (user-driven redesign)
| Option | Description | Selected |
|--------|-------------|----------|
| A: Instance table + portfolio-subs child (2 tables) | Named instance row = addressable unit; portfolios as child rows; `enabled` per-instance | ✓ |
| B: Instance + per-(instance,portfolio) `enabled` | Enable/disable independently per portfolio | |
| C: Single denormalized subscription table | Each row = type+config+portfolio; dedup identical configs on load | |

**User's choice:** Option A.
**Notes:** The user challenged the model twice, productively. First: *"why do we have `enabled bool` and `config_json JSONB`?"* → answered by the authoring-vs-runtime lifecycle split (they are not redundant; `enabled` is operational state and must stay queryable). Second, the sharper one: *"the same instance of a strategy can be initialized multiple times... I believe our model doesn't reflect this... maybe we do not need a strategy_registry at all in the database, but just a subscription table"* → forced Claude to make the cardinality explicit (the engine runs ONE strategy object fanning out to N portfolios, NOT N objects) and to present the three options. The user also asked *"how many tables concerning strategies do we plan to have?"*, which exposed that the P4 `strategy_subscriptions` table is **redundant** (derivable from the live venue + `config_json.tickers` + `config_json.timeframe`; its only unique job is an in-memory reverse index) → **dropped**. Two tables, not three.

---

## Area 3 — Atomic reconfiguration & quiesce (STRAT-03)

| Question | Options | Selected |
|--------|-------------|----------|
| Open positions on reconfigure | Param-classified / Always flatten / **Always apply live, keep positions** ✓ | Apply live, keep |
| Persist-failure semantics | **Adopt P9 D-15 validate→persist→apply** ✓ / apply-then-persist | P9 D-15 |
| Timeframe mutability | Immutable at runtime / mutable w/ feed re-subscribe / **constrained-mutable** ✓ | Constrained-mutable |

**Notes:** The user pushed back on Claude's blanket "timeframe immutable" recommendation — *"why do you recommend to keep it immutable? we already re-warm up when changing any other parameter anyway, I do not see big problems with it."* **The pushback was correct.** Tracing the code (`check_timeframe` = alignment to multiples; `LiveBarFeed.base_timeframe` + off-grid bar rejection; `min_timeframe` = a plain `min()` that doesn't re-subscribe anything at runtime) showed the common case (a multiple of / coarser than the base cadence) is just a re-warm — no heavier than a window change. The recommendation was refined rather than defended: **constrained-mutable**, rejecting only finer-than-base (which needs a shared-stream re-subscribe). The user asked to save that as a future todo. One genuine unknown remains → research item (does the feed aggregate base bars up, or subscribe per timeframe?).

The user also caught that Claude had compressed real questions into "recommendations" (*"didn't you have more questions for me in area 3?"*) — prompting the reconfigure-allowlist question (which params are immutable at runtime) that had been under-asked.

---

## Area 4 — Pair-strategy reconfiguration scope (folded todo B2)

| Question | Options | Selected |
|--------|-------------|----------|
| Build B2 leg-swap in P10? | **Defer to next milestone** ✓ / build in P10 / defer all pair reconfig | Defer B2 |
| Pairs in the registry lifecycle? | **Full registry instances** ✓ / excluded from registry | Full instances |
| Refusal scope | **Refuse ALL pair reconfiguration** ✓ / allow params only when FLAT / allow params fully | Refuse all |

**User's choice / path:** The user asked *"is it a lot of work to do it now or better doing it in the new milestone?"* → given P10 is already multi-wave and B2's hard part is the flatten→wait-until-flat→swap state machine (spans event cycles) + 280-bar×2-leg fixtures, deferral to the planned next milestone was recommended and accepted.

**Notes — the most important correction of the session.** The user initially reasoned *"I'm ok to fully support their reconfiguration. In the end it's the same as reconfiguring a single leg strategy. Isn't it? I'd go with option 3 now if this doesn't introduce problems."* Claude checked rather than agreed, and **the premise did not hold**: (1) `pair_base._entry` sets **no** `stop_loss`/`take_profit` (unlike single-leg `_intent`) → an open spread has no resting bracket and its only exit path is `evaluate_pair()`, gated on `is_pair_ready()`; (2) `PairStrategy._run_init` **unconditionally** wipes `_buf_A`/`_buf_B` and resets `_pair_bar_count=0`, and `reconfigure()` always calls it → even a `sizing_policy` change blanks a pair (a single-leg strategy would stay warm and trading); (3) `is_pair_ready()` needs 280 bars. Net: an open spread would be stranded unhedged with no exit for ~12 days (1h bars) / 280 days (1d). Presented with the evidence the user chose the **total guard** over the flat-gated middle ground — *"ok then maybe better option 1, I'll deal with pair strategy later."*

---

## Area 5 — Naming

| Question | Options | Selected |
|--------|-------------|----------|
| Code-side type set name | **`strategy_catalog` / `StrategyCatalog`** ✓ / `strategy_types` / `strategy_registry` | `strategy_catalog` |
| DB table + store | Rename → `strategy_instances`/`StrategyInstanceStore` / **keep `strategy_registry`** ✓ | Keep |

**User's choice:** Keep `strategy_registry` / `StrategyRegistryStore`; `strategy_catalog` for the code side.
**Notes:** Claude initially recommended renaming the table (the word "registry" was overloaded across the code catalog and the DB store). Once the user picked `strategy_catalog` for the code side, **the rename's justification collapsed** — catalog = types, registry = instances is unambiguous — so the recommendation flipped to "keep", saving a migration and preserving STRAT-01/ROADMAP wording. The user floated `strategy` and `strategy_store`; both were argued against on convention grounds (row-collection tables are plural: `halt_records`, `equity_snapshots`; and `*Store` is the *class* convention — `VenueStore`, `SystemStore` — so a `strategy_store` table would blur the table/class layers). Net: zero renaming work.

---

## Area 6 — Rehydrate failure semantics & schema evolution (surfaced by Claude post-Area-5)

| Option | Description | Selected |
|--------|-------------|----------|
| Fail loud and halt | One bad row blocks boot entirely | |
| Skip + warn | Boot continues; failure is a log line | |
| Per-instance quarantine (skip + CRITICAL alert + read-model), fail-loud for wiring errors | Loudness from the alert channel, not from halting; don't mutate `enabled` | ✓ |

**User's choice:** Quarantine. They asked *"what do you think is best? I'm tempted to 'fail loud and halt' but isn't it too drastic?"* — both instincts were right: halt IS too drastic (the failure is per-instance but halt is global — one stale row from a retired class would block all healthy strategies, a self-inflicted outage), and skip+warn IS too quiet. The resolution: **"skip" and "loud" are orthogonal** — loudness comes from the P8 `alert_sink` CRITICAL channel + the read-model, not from halting. Also decided: **do not** mutate the row to `enabled=False` (that would destroy operator intent); and **stamp a `config_version` now** (cheap-now/impossible-later; drift is certain given independent repo evolution) without building a migration framework.

---

## Area 7 — Bootstrap & required test surface (surfaced by Claude post-Area-5)

**User's choice:** *"I am ok to have 0 strategies in the db at the very first start. I'll wrap the package in a FastAPI app soon. But we should still test it simulating what would happen when instantiating a strategy from FastAPI. I guess we have all components to do so now."*
**Notes:** Correct — `add_event`'s D-10 fail-closed allowlist already admits `STRATEGY_COMMAND`, so tests can drive exactly the path FastAPI will. Direct precedent in P9's D-23 (*"with no FastAPI driver yet, P9's own tests must drive the external `CONFIG_UPDATE` path directly so it isn't untested surface"*). Recorded as a phase test requirement: the full external `add → persist → warm → trade → restart → rehydrate` lifecycle.

---

## Claude's Discretion

- Exact codec module location/API; whether the policy `kind→class` registry auto-derives from the catalog or is separately injected.
- Serialize side: a `to_config()` on the base vs codec-side introspection.
- The `_DERIVED_FIELDS` marker mechanism (`warmup`/`max_window` exclusion).
- Store method names/signatures for the portfolio-sub child table; the migration shape (drop `strategy_subscriptions`, add `strategy_portfolio_subscriptions`).
- Where `build_live_system` receives the injected `strategy_catalog` (param vs `SystemSpec` field).
- `config_version` value/format; the quarantine-list representation in the read-model.
- Wave/plan/commit granularity.

## Deferred Ideas

- **All PairStrategy runtime reconfiguration (params + B2 leg-swap)** → next milestone. Todo re-targeted: `.planning/todos/pending/pair-strategy-live-reconfiguration.md` (`resolves_phase: P10 → next-milestone`; body now carries the D-17 evidence).
- **Timeframe change finer than the feed base cadence** → future. New todo created: `.planning/todos/pending/strategy-timeframe-finer-than-base-resubscribe.md`.
- **Runtime addition of new strategy TYPES to the catalog** (UI upload-a-Python-file) — a different axis; explicitly deferred by the user ("not anytime soon").
- **`config_json` migration framework** — `config_version` is stamped now; the mechanism waits until drift bites.
- **DB-queryable "which instances trade symbol X"** — would promote `tickers` to a `strategy_symbols` child table.
- **Persisted market-data subscriptions with per-symbol venue divergence** (multi-venue strategies) — the dropped table's only real justification.
- **Cross-restart signal analytics continuity** — rehydrated instances mint a new ephemeral `strategy_id`; `strategy_name` is the stable key. Pre-existing, but P10 makes restart first-class.
