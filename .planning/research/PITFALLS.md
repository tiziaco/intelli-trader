# Pitfalls Research

**Domain:** Live-trading God-object decomposition + live-readiness hardening (brownfield, event-driven Python 3.13)
**Researched:** 2026-07-09
**Confidence:** HIGH (grounded in the authoritative v1.8 design spec §4/§15/§18, the v1.7 carry-forward TODO, and CLAUDE.md-locked constraints; general refactor/concurrency/Alembic knowledge cross-checked)

> These pitfalls are specific to **this** refactor. The two blocking gates — the byte-exact backtest
> oracle (`134 / 46189.87730727451`, `check_exact=True`) and the OKX import-inertness gate
> (`tests/integration/test_okx_inertness.py`) — are the epicenters; behavior-drift, inertness-regression,
> and threading-contract pitfalls are covered in depth because a single mistake there silently invalidates
> the whole milestone.

## Critical Pitfalls

### Pitfall 1: Behavior-drift smuggled into "pure code-motion"

**What goes wrong:**
Extracting `UniverseWiring`, storage-init, or config values from `LiveTradingSystem`/`compose_engine`
into shared helpers *looks* like moving code, but silently changes a value that feeds the backtest run —
membership derivation order, an instrument-scale default, an rng-seed resolution path, a dict-iteration
order that a `searchsorted`/reserve loop depends on — and the oracle drifts off `46189.87730727451`.
The most dangerous case: `SessionInitializer` + shared `UniverseWiring` is **explicitly oracle-sensitive**
(spec §13a/§15) because `BacktestRunner._initialise_backtest_session` calls the *same* helper. If the
extracted helper reorders `derive_membership → derive_instruments → build Universe → inject → feed.bind`
or changes a default, backtest results move.

**Why it happens:**
"It's just moving code" lowers vigilance; reviewers don't diff *values*, they diff *structure*. Extraction
tempts small "harmless" normalizations (a default argument, a `dict` → `OrderedDict`, a re-sorted list, a
`Decimal` default folded from a module constant into a config field). Any of these can change money math or
iteration order. The P1 config-centralization pass is the highest-risk because relocating a scattered
constant into `SystemConfig` changes *where the value comes from*, and a typo or unit mismatch is invisible
until the run.

**How to avoid:**
- **Hold invariant, not just green:** every P1–P4 and P7-UniverseWiring plan must run the oracle with
  `check_exact=True` AND the determinism double-run (two runs byte-identical) as a per-plan gate, not a
  per-phase gate. The equity string `46189.87730727451` and trade count `134` are the invariants.
- **Extract by reference-preservation:** move the code *verbatim* (byte-for-byte, same indentation family —
  see Pitfall 9), then wire it back; do NOT "improve" during the move. Mirror the proven v1.2 Phase-6
  OrderManager decomposition discipline (pure code-motion, `on_fill` moved as one intact unit).
- **Value-diff, not structure-diff:** when relocating a constant into config, assert the new config value
  `==` the old module constant in a test before deleting the constant.
- **Re-baseline is never silent (LR-02):** if a change legitimately must move results, it is gated on
  external cross-validation (backtesting.py + backtrader) + owner sign-off, documented in a REFREEZE note.
  The default target is byte-exact.

**Warning signs:**
Oracle diff shows *any* delta (even in a trailing digit); determinism double-run diverges; a P1–P4 plan
touches a `Decimal` default or a membership/instrument path; a code-motion diff contains a `sorted(...)`,
`OrderedDict`, changed default arg, or a `Decimal(float)` that wasn't there before.

**Phase to address:**
P1 (config constants), P3/P4 (storage-init + SqlEngine rename), **P7 (`UniverseWiring` — the oracle-sensitive
extraction).** Gate: byte-exact oracle + determinism double-run on every plan in these phases.

---

### Pitfall 2: Inertness regression — an eager import sneaks onto the backtest path

**What goes wrong:**
The backtest import path must stay async/`ccxt.pro`/SQL-free (`test_okx_inertness.py`). A refactor
re-introduces heaviness four classic ways: (a) a **barrel re-export** — adding the live stack to an
`__init__.py` so `from itrader.trading_system import ...` transitively imports `ccxt.pro`; (b) a
**non-lazy `SqlSettings`** — `SystemConfig` constructing the Postgres arm at import (which *raises* without
a credential and definitely pulls SQL); (c) a **registry that imports concretions at registration** — the
`ExecutionVenueRegistry`/`DataProviderRegistry` importing `OkxExchange`/`OkxConnector` when `'okx'` is
*registered* rather than when a venue is *built*; (d) `FifoEventBus` or `EngineContext(sql_engine=None)`
pulling something heavy on construction.

**Why it happens:**
Python import side-effects are transitive and invisible — one new top-level `import` in a module that's on
the backtest path drags its whole dependency subtree. Registries feel like the natural place to `import`
the thing you're registering. Config aggregation (P1) tempts eagerly constructing every settings block.

**How to avoid:**
- **Lazy-import concretions inside `build_bundle`/method bodies, never at module top or registration**
  (spec §8a). Registering `'okx'` registers a *plugin object/factory*, not the exchange class. The plugin
  imports `ccxt.pro` only inside `build_bundle`, i.e. only when a venue is actually built.
- **`sql` is a cached-property/method accessor on `SystemConfig`, resolved on first access, never at import**
  (spec §6a). Eager fields (`performance`, `monitoring`, `runtime`, templates) are plain safe-default
  `BaseModel`s with no env I/O. `OkxSettings`/venue creds stay out of `SystemConfig` entirely.
- **Never re-export the live stack from package barrels.** `EngineContext`, `FifoEventBus`,
  `PriorityEventBus` must be importable without pulling live backends; keep live-only modules out of
  `__init__.py` re-exports (the v1.7 proven pattern).
- **Treat `test_okx_inertness.py` as a per-plan gate for P1, P2, P5, P6** — the phases that add config
  aggregation, the bus, SQL stores, and the venue registry. Extend the inertness test to assert
  *registering* a venue imports no `ccxt.pro` (spec §15).

**Warning signs:**
`test_okx_inertness.py` red; import time of the backtest path grows; a new top-level `import ccxt`/`import
sqlalchemy`/`import asyncio`-heavy module appears in a backtest-path file; a registry `.register()` call
takes a class rather than a factory/plugin; `SystemConfig.default()` touches env vars or raises on a
missing DB credential at import.

**Phase to address:**
P2 (bus — assert `FifoEventBus`/`EngineContext(sql_engine=None)` inert), P5 (stores — lazy), **P6 (venue
registry — the highest-risk: lazy plugins, register-vs-build).** P1 owns the lazy-`sql` split. Gate:
inertness test green on every plan in P1/P2/P5/P6.

---

### Pitfall 3: Priority-queue pathologies (starvation, non-orderable fall-through, lost causal FIFO)

**What goes wrong:**
The two-tier `PriorityEventBus` (`(tier, seq, event)`) introduces four failure modes:
1. **BUSINESS-tier starvation** — a flood of CONTROL events (e.g. rapid `STREAM_STATE` flap, or a
   `CONFIG_UPDATE` storm) monopolizes the single consumer so `BAR`/`SIGNAL`/`ORDER`/`FILL` never drain,
   stalling the trading flow indefinitely.
2. **Tuple-comparison fall-through** — if two entries compare equal on `(tier, seq)`, `PriorityQueue` falls
   through to comparing the **frozen event dataclass**, which is not orderable → `TypeError` crash mid-drain.
3. **Lost strict causal FIFO within BUSINESS** — if `seq` isn't a single monotonic thread-safe counter, two
   events at the same tier can reorder, breaking the causal `BAR→SIGNAL→ORDER→FILL` chain and corrupting
   position state.
4. **Mis-tiering a trading intent** — putting externally-injected `SIGNAL` on CONTROL would let an operator
   signal jump ahead of a bar/fill it must interleave *after*, desyncing position state.

**Why it happens:**
`queue.PriorityQueue` compares the *whole tuple* and only stops at the first differing element — a well-known
Python footgun. Developers reach for `(priority, event)` and get bitten when priorities tie. Starvation is
invisible in low-volume tests and only appears under a real CONTROL flood.

**How to avoid:**
- **Unique monotonic `seq` from a single `itertools.count()`** (thread-safe) as the second tuple element
  guarantees the tuple *never* falls through to the event (spec §4a) AND preserves strict FIFO within a tier.
  This is the load-bearing invariant — test it explicitly: two same-tier events dequeue in put-order; a
  same-`(tier)` pair never triggers event comparison.
- **Bound the starvation risk with monitoring, not just priority:** the bus is "unbounded-but-watched" via
  `depth_by_tier`. Add a guard/alert if BUSINESS depth grows while CONTROL is being serviced, or cap
  CONTROL drain (e.g. drain at most N CONTROL between BUSINESS items) if a real flood source emerges.
  CONTROL is *designed* low-volume (safety/operator/config) — enforce that assumption with a monitor.
- **Freeze the tier assignment in P2** via the declarative `_CONTROL_EVENT_TYPES` frozenset; keep
  externally-injected `SIGNAL` on **BUSINESS** (spec §4a) — control priority is for *operational* commands,
  not trading intents. Review the frozenset in code review as a security/correctness-sensitive list.
- **Determinism is a non-issue by construction — but verify the reasoning:** the priority bus is *live-only*.
  Backtest uses `FifoEventBus` over `queue.Queue` and its synchronous `process_events()` drain, which never
  touches the priority bus (spec §4a "Determinism note"). Live events already arrive in non-deterministic
  wall-clock order, so priority ordering adds **zero oracle risk**. Verify: `compose_engine` selects
  `FifoEventBus` for backtest, and no backtest-path test constructs a `PriorityEventBus`.

**Warning signs:**
A `TypeError: '<' not supported between instances of ...Event` in the drain (fall-through hit); BUSINESS
`depth_by_tier` climbing under load; an integration test where an operator `SIGNAL` fills before an
in-flight bar; any `PriorityQueue.put((tier, event))` **without** a `seq` between them.

**Phase to address:**
P2 (bus design + `seq` uniqueness test + tier frozenset). Starvation-monitor lives with P2's `depth_by_tier`;
CONTROL-flood backstop coordinates with P9's LOOP-BACKSTOP breaker.

---

### Pitfall 4: Threading-contract violations (blocking the connector loop / second ring writer / external direct calls)

**What goes wrong:**
The single-writer engine-thread contract (LR-12) has three violation modes, each corrupting state or
deadlocking:
1. **Blocking venue I/O on the connector asyncio loop** — doing a resume snapshot, reconcile, or durable
   halt write inside a stream callback on the connector loop. This blocks `ccxt.pro` streaming (bars/fills
   stop arriving) and can deadlock. All such I/O must run on the **engine thread** inside the CONTROL-event
   handler (spec §4b.4).
2. **A second concurrent ring-buffer writer** — the CF-2 `backfill_on_resume` wiring is the trap: if it runs
   on the **engine thread**, it races the connector-loop `update()` on the ring/`_replaying_backfill` guard
   state (two writers, one buffer). It MUST land **loop-native** (connector loop, via the reconnect
   callback), which is only safe now that V17-15 `spawn_gap_backfill` landed.
3. **External/web threads calling handler methods directly** — a caller mutating handler state off-thread
   instead of going through `bus.put()` (trading intents/config/commands) or a thin thread-safe status-latch
   facade method (`halt/pause/reset/get_status/start/stop`).

**Why it happens:**
The "just do the I/O where the event arrives" instinct puts blocking work on the loop. The connector loop
*already* has the fill/bar data, so it's tempting to also write it. `backfill_on_resume` naturally reads like
engine-thread work ("resume the engine") when it's actually a ring-writer op. External callers see public
handler methods and call them.

**How to avoid:**
- **The queue is the bulkhead (spec §4c):** the connector loop does *only* venue I/O + `bus.put()` — fills/
  bars → BUSINESS, stream-up/down + connector-fatal → CONTROL. It **never** touches handler state, never
  blocks. Any blocking work triggered by a stream event runs on the engine thread inside the CONTROL handler
  (`StreamRecoveryHandler.on_reconnect` does `catch_up_missed_fills()`/`account.snapshot()` on the engine
  thread).
- **CF-2 lands loop-native, asserted:** wire `LiveBarFeed.backfill_on_resume` on the connector loop via the
  reconnect callback (P8), and add a test/assertion that no engine-thread path invokes it (would be a second
  writer). This is a hard acceptance criterion for CF-2 in P8.
- **External ingress is fail-closed and event-only:** `LiveTradingSystem.add_event` admits only externally-
  originated `SIGNAL`/`STRATEGY_COMMAND` (D-10 default-deny, preserved); everything else is a thin thread-safe
  facade delegating to `SafetyController`'s status latch. No external caller reaches a handler method.
- **Add the CF-3 connector-contract docstrings** (`connectors/base.py` `call`/`spawn`/`disconnect`) so the
  next connector author can't re-introduce a call-from-loop-thread or timeout-≠-didn't-happen bug — the
  Protocol is where implementers read the rules.

**Warning signs:**
Bars/fills stall after a reconnect (loop blocked); a `snapshot()`/`reconcile()`/durable-write call inside a
connector callback; `backfill_on_resume` reachable from the `LiveRunner`/engine-thread drain; two writers
touching `_replaying_backfill`/ring state; a web/test thread calling `portfolio_handler.on_fill` or similar
directly; intermittent ring-buffer corruption or non-monotonic bar delivery only under reconnect.

**Phase to address:**
P8 (SafetyController + StreamRecoveryHandler + CONTROL routes + **CF-2 loop-native backfill** + CF-7
reconciler guard). P6 owns CF-3 connector-contract docstrings. The single-writer contract itself is
established in P7's `LiveRunner`.

---

### Pitfall 5: Alembic migration-chain hazards (relocation, multi-head, create_all divergence)

**What goes wrong:**
P4 relocates `itrader/storage/migrations/` → project-root `migrations/`, and P5 chains **three new stores**
(`d10_halt_records → system_store → venue_config → strategy_registry`). Classic breakages:
1. **Relocation breaks `script_location`** — `alembic.ini` still points at the old package path, or `env.py`
   loses its import of the `build_*_table` registrars + `NAMING_CONVENTION` from `itrader.storage`, so
   migrations run against an empty/wrong metadata.
2. **Multi-head / branched revision tree** — three new stores authored in parallel (or across plans) each
   set `down_revision` to the same parent → Alembic reports multiple heads and `upgrade head` becomes
   ambiguous or errors.
3. **`create_all` vs migration divergence** — tests use `create_all()` (from the registrars) while
   production uses the Alembic chain; if a new column/index is added to a registrar but not to a migration
   (or vice-versa), tests pass green while production migrations produce a *different* schema.
4. **Packaging leak** — `migrations/` accidentally shipped in the wheel, or conversely `env.py` can no longer
   import the registrars because the relocation broke the package boundary.

**Why it happens:**
Relocation is "just moving a folder" (see Pitfall 1's mindset). Parallel store authorship naturally forks the
revision chain. `create_all` in tests is convenient and hides schema drift because nobody runs migrations in
CI unless forced.

**How to avoid:**
- **Relocation is mechanical + verified (spec §7e):** update `alembic.ini` `script_location` to the new
  `migrations/`; keep `env.py` importing the `build_*_table` registrars + `NAMING_CONVENTION` from
  `itrader.storage`; confirm `migrations/` is excluded from the shipped wheel; confirm test-path `create_all`
  is unaffected. Run `alembic upgrade head` against a clean DB as a P4 gate.
- **Linear chain, one head, enforced:** each new store's migration sets `down_revision` to the *previous*
  store in the declared order (`d10_halt_records → system_store → venue_config → strategy_registry`). Add an
  `alembic heads` check (must report exactly one head) to the P5 gate. Author the chain sequentially, not in
  parallel, or reconcile heads before merge.
- **Migration/registrar parity test:** a test that builds the schema via `create_all` (registrars) AND via
  `alembic upgrade head` and asserts identical table/column/index sets. This catches the silent divergence.
- **Each new store follows the `HaltRecordStore` template** (composes `sql_engine`, own `build_*_table`
  registrar, chained migration) — don't invent a new pattern per store.

**Warning signs:**
`alembic heads` reports >1 head; `alembic upgrade head` errors or no-ops against a clean DB; a store's table
exists in tests but not after a real migration; `alembic.ini` still references `itrader/storage/migrations`;
CI never runs `upgrade head`; the wheel build includes `migrations/`.

**Phase to address:**
P4 (relocation — `script_location`/`env.py`/wheel-exclusion + `upgrade head` gate). P5 (three-store chain —
single-head check + create_all/migration parity test). Uses the `SqlEngine` rename from P4.

---

### Pitfall 6: Runtime-config platform footguns (mutating immutables / snapshot-write races / persisting secrets)

**What goes wrong:**
The runtime-config platform (P10) introduces mutation-at-runtime, which threatens correctness three ways:
1. **Mutating an immutable-at-runtime key** — a `ConfigUpdateEvent` that changes `rng_seed`, money precision,
   SQL credentials, `environment`, or IDs would break determinism/money/identity mid-run. These are declared
   immutable (spec §6e) but an over-broad allowlist or a missing validation lets them through.
2. **Snapshot-read vs engine-thread-write race on the `RuntimeConfig` overlay** — handlers read the overlay
   (snapshot-read); the config-update handler writes it (engine-thread-write). If a handler reads a
   half-applied multi-field update, or if a write happens off the engine thread, it observes torn state.
3. **Persisting secrets** — writing venue credentials (`OkxSettings`) into `SystemStore`/`VenueStore` when
   applying/persisting a config override. Secrets must stay env-sourced, per `account_id`, **never** in any
   store.

**Why it happens:**
A generic "config is mutable" platform doesn't distinguish immutable keys unless forced. The overlay pattern
(defaults ← YAML ← env ← persisted) invites "just set the field" without an engine-thread hop. When persisting
a venue config, credentials sit adjacent to the config fields and get serialized together by accident.

**How to avoid:**
- **Allowlist of runtime-mutable keys + type/range check (spec §6e), rejecting immutables loudly.** The
  allowlist is a closed set (fee/slippage params, poll cadence, `universe_remove_policy`, idle/timeout knobs,
  risk limits, strategy enable/disable). `rng_seed`, precision, SQL creds, `environment`, IDs are hard-rejected.
  Test that each immutable key raises on a mutation attempt.
- **Engine-thread-write, snapshot-read (spec §6c):** `ConfigUpdateEvent` routes through the **CONTROL plane**
  to an engine-thread handler that applies the whole update atomically to the overlay + relevant
  `handler.update_config(...)` + persists. Handlers only ever *read* a consistent snapshot. No off-thread
  overlay writes (this is a direct consequence of the LR-12 single-writer contract).
- **Secrets never persisted (spec §6a/§15):** `VenueStore` holds per-venue config but **never** credentials;
  the persist path must be structurally incapable of writing `OkxSettings`. Add a test asserting no store
  round-trip contains a secret; the alert sink binds only declared `ErrorEvent` fields.

**Warning signs:**
An allowlist entry for `rng_seed`/precision/creds; a config write path reachable off the engine thread; a
handler reading a config field that another thread is writing; a `VenueStore`/`SystemStore` row containing an
API key/secret; a multi-field config update visible half-applied.

**Phase to address:**
P10 (runtime-config platform — allowlist, engine-thread-write CONTROL route, no-secret persistence). P1 owns
declaring the immutable-vs-mutable split in centralized config. CF-8's typed `HaltReason` enum (P1) is the
model for closed-vocabulary config values.

---

### Pitfall 7: Multi-portfolio keying errors (shared account_id / attribution confusion / mis-routed fills)

**What goes wrong:**
Multi-portfolio-live (P12) makes `account_id` and `portfolio_id` load-bearing keys, with three failure modes:
1. **Two portfolios sharing one venue `account_id`** — pooled buying power the venue can't split back out.
   This is explicitly **not supported** (deferred, needs a risk-allocator) and MUST fail loud. If it slips
   through silently, two portfolios' positions/cash entangle on one venue account and reconciliation is
   ambiguous.
2. **`client_order_id` vs `portfolio_id` confusion** — `client_order_id` (LR-19, was `clOrdId`) does
   venue↔engine *correlation*; `portfolio_id` does *attribution*. Conflating them (e.g. deriving attribution
   from the venue order id, or keying the account by `client_order_id`) mis-attributes fills.
3. **Fills routed to the wrong `Portfolio.on_fill`** — a fill for account A's order settles against
   portfolio B, corrupting both cash ledgers.

**Why it happens:**
The old model was 1 account : 1 portfolio (LX-04) with a `RuntimeError(>1)` guard, so keying was implicit.
Removing that guard and fanning a signal out to N portfolios makes every attribution path explicit for the
first time — easy to miss a hop. `client_order_id` and `portfolio_id` are both "order-ish ids" and blur.

**How to avoid:**
- **Distinct-`account_id` invariant, fail-loud (spec §10b):** replace the deleted
  `_link_venue_account_to_portfolios` + `RuntimeError(>1)` guard with per-portfolio account minting via the
  plugin's mandatory `new_account(portfolio_ref, config)` **plus** an explicit invariant that no two
  portfolios share an `account_id`. Test that a shared-`account_id` spec raises at composition, not at runtime.
- **Two-key discipline, tested end-to-end (spec §10c):** every submitted order is tagged with its
  `portfolio_id`; fills route `client_order_id`/`venue_order_id` → engine order → `FillEvent(portfolio_id)` →
  the correct `Portfolio.on_fill`. Add a multi-portfolio gate (P13) that submits from two portfolios on two
  `account_id`s and asserts each fill lands in the right ledger.
- **Per-portfolio reconciliation:** `ReconciliationCoordinator` iterates active portfolios, reconciling each
  against *its own* `VenueAccount`/`account_id` — never a pooled reconcile.
- **Connector memoized by `(venue, account_id)`** (LR-17) so per-account credentials/sessions don't cross.

**Warning signs:**
No composition-time error when two `PortfolioSpec`s share an `account_id`; attribution derived from
`client_order_id`; a fill's `portfolio_id` computed from venue order id; reconciliation that sums across
portfolios; a multi-portfolio test where ledgers cross.

**Phase to address:**
P12 (multi-portfolio-live — per-`account_id` factory, distinct-`account_id` invariant, `client_order_id`
rename, per-portfolio reconcile, `(venue, account_id)` connector keying). P13 adds the multi-portfolio
attribution gate. P6 lays the account-factory + connector-memoization foundation.

---

### Pitfall 8: Error-subsystem circuit-breaker failures (CF-1 — livelock, false-green, broken fail-fast)

**What goes wrong:**
CF-1 is the **one HIGH-priority safety fold** and the only one that *adds an acceptance criterion* to P9.
Four ways it goes wrong:
1. **Error→error livelock (WR-06)** — a failing `ErrorEvent` consumer republishes a fresh `ErrorEvent` (no
   type guard) → unbounded error→error recursion. This already bit the codebase (memory WR-06): the fix is a
   **source guard** (don't republish an `ErrorEvent` if the failing event was itself `ERROR`) *plus* a
   **consumer guard** (the `ErrorHandler` swallows its own failures, never re-raises) — two-guard terminal
   safety.
2. **A breaker that false-greens a money route** — the exact gap CF-1 exists to close: `_publish_and_continue`
   increments a counter and emits one `ErrorEvent` per failure then continues **forever**, so a money route
   (settlement/FILL) failing on *every* event produces an infinite green-looking run (the "V17-01 ran an
   entire e2e suite green with zero settlements" bug). Without the aggregate tripwire, the breaker doesn't
   exist.
3. **Breaking backtest fail-fast** — implementing the breaker as a per-event policy change that softens
   backtest's fail-fast (re-raise) would let the parity gate false-green. The breaker is an **aggregate
   tripwire on top of** the live publish-and-continue policy — backtest fail-fast stays untouched.
4. **Wrong route classification** — treating a settlement failure as retryable. SETTLEMENT (FILL →
   portfolio/order handler) must **halt on first** failure; ORDER-IO N=3/60s; ADMISSION N=3/300s;
   LOOP-BACKSTOP N=5/60s; FILL-TRANSLATION (`okx.py` per-trade swallow) must first emit a *counted*
   `ErrorEvent` then treat as SETTLEMENT.

**Why it happens:**
Publish-and-continue is the correct *live* resilience policy — but "continue" with no aggregate bound is
silently unsafe on a money route. The livelock is a subtle recursion that only manifests when the error route
*itself* fails. Injecting the policy vs monkeypatching (`event_handler._on_handler_error = ...  # type: ignore`)
tempts a global override that erases per-handler granularity or the backtest arm.

**How to avoid:**
- **Ship the route-classified ring breaker (CF-1, spec §18 + `v17_audit_results.md §3b` — ready-to-paste):**
  SETTLEMENT halt-on-first, ORDER-IO N=3/60s, ADMISSION N=3/300s, LOOP-BACKSTOP N=5/60s; guard with
  `_stats_lock`; trip via the existing idempotent `halt(reason)`; surface counters + last-trip reason in
  status. This is a hard P9 acceptance criterion, not merely "refactor the error seam."
- **Two-guard terminal safety (WR-06), tested:** source guard in the publish path + consumer swallow in the
  `ErrorHandler`. Test: an `ErrorEvent` whose consumer raises does NOT produce a second `ErrorEvent` (no
  livelock).
- **`ErrorPolicy` injected at construction, not monkeypatched (spec §12a):** backtest/replay → fail-fast
  (re-raise; parity gate can't false-green); live → publish-and-continue. Keep per-handler granularity (a
  route is a list — one failing handler doesn't skip the rest). Assert backtest fail-fast is byte-for-byte
  unchanged (oracle green).
- **Unblocked dependency check:** the breaker's `halt()` no longer gets clobbered back to RUNNING because the
  ARCH-4 HALTED latch (V17-03) landed — verify the latch is in place before wiring the breaker.

**Warning signs:**
A live run stays green while a money route fails every event; an `ErrorEvent` consumer failure spawns another
`ErrorEvent`; a monkeypatched `_on_handler_error`; a settlement failure retried instead of halting; backtest
oracle drifts after the P9 error-policy change; no `last-trip reason`/counters in status; `_stats_lock`
missing around breaker counters.

**Phase to address:**
**P9 (error subsystem — CF-1 aggregate breaker is a hard acceptance criterion, `ErrorPolicy` injected,
two-guard terminal safety, CF-5 pluggable alert-sink seam).** Depends on P7 (`LiveRunner` owns the drain +
injected policy). The breaker's LOOP-BACKSTOP coordinates with P2's CONTROL-flood monitor.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| "Improve" code while extracting it (normalize sort/defaults/indentation) | Cleaner-looking diff | Silent oracle drift; broken tab file; hard-to-bisect regression | **Never** on oracle-gated (P1–P4, P7-UniverseWiring) or tab files |
| Import venue concretions at registration for "simplicity" | Registry is one-liner | Kills inertness gate; drags `ccxt.pro`/SQL onto backtest path | **Never** — lazy-import in `build_bundle` |
| `create_all` in tests, skip running Alembic in CI | Fast test setup | Schema drift between tests and production migrations | Only if a create_all/migration parity test exists |
| Monkeypatch `_on_handler_error` for the live policy | No constructor change | Erases per-handler granularity; risks softening backtest fail-fast | **Never** — inject `ErrorPolicy` (spec §12a) |
| Wire `backfill_on_resume` on the engine thread ("it resumes the engine") | Simpler call site | Second concurrent ring writer racing the connector loop → corruption | **Never** — loop-native only (CF-2) |
| Broad config allowlist ("make everything mutable") | Flexible runtime | Mutable `rng_seed`/precision/creds breaks determinism/money/identity | **Never** — closed allowlist, hard-reject immutables |
| Defer the CF-1 aggregate tripwire to "later" | P9 ships faster | A money route can fail every event, run infinitely green | **Never** — CF-1 is a P9 acceptance criterion |
| Free-string `halt('baseline-residual')` reasons | Quick to write | Unclassified halts; FastAPI control-plane can't reason about them | **Never** — typed `HaltReason` enum (CF-8, P1) |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OKX (`ccxt.pro`) | Blocking venue I/O (snapshot/reconcile) on the connector asyncio loop | Loop does only I/O + `bus.put()`; blocking work on engine thread inside CONTROL handler (§4b) |
| OKX markets map | Stale markets map → a delisted symbol trades on; or adding a parallel drop in the retry loop | Keep markets map fresh (CF-9, P6) so delisting exits via existing `validate_symbol → delta.removed`; close the fail-open-before-load window |
| OKX candle stream | Trusting an in-progress candle snapshot pushed on every WS subscribe (defeats payload-gated reconnect budgets — memory WR-03) | Confirm-gated `ClosedBar` only; don't reset reconnect budget on snapshot payloads |
| `LiveConnector` (any future venue) | Re-introducing call-from-loop-thread / timeout-≠-didn't-happen bugs | Add CF-3 CONTRACT docstrings to `connectors/base.py` (`call`/`spawn`/`disconnect`) — the Protocol is where implementers read the rules |
| Venue credentials | Persisting `OkxSettings` into `VenueStore`/`SystemStore` alongside config | Creds stay env-sourced per `account_id`, never in any store (§6a/§15) |
| Venue reconciliation | Bare `str(matched["id"])` KeyError on a fallback-matched resting order with no `id` (CF-7) | Fail-loud typed error at `venue_reconciler.py:411` (P8) |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| CONTROL-tier flood starving BUSINESS | Bars/fills stop draining; BUSINESS `depth_by_tier` climbs | Monitor `depth_by_tier`; CONTROL is designed low-volume; add a drain backstop if a flood source appears | A stream-flap or config storm generating high CONTROL volume |
| Unbounded event bus | Memory growth; no backpressure signal | "Unbounded-but-watched" via `depth_by_tier` monitoring + alerts | Sustained producer > consumer (e.g. a wedged engine thread) |
| Stats-snapshot upserts contending with config writes on `SystemStore` | Lock contention / slow config apply | Marked seam: split stats-history table if periodic snapshot upserts contend (§14 deferred) | High-frequency `stats.snapshot` upserts |
| Per-portfolio reconcile iterating many accounts serially | Slow startup with N portfolios | Acceptable at current N; watch startup time; parallelize only if measured | Large N portfolios on slow venue snapshot I/O |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Persisting venue API secrets to a durable store | Credential leak from DB dump/backup | Secrets stay in env-sourced `OkxSettings` per `account_id`, never written to any store (§6a/§15) |
| Alert sink binding undeclared event fields | Leaking internal/sensitive state to an external alert channel | Alert sink binds **only** declared `ErrorEvent` fields (§15) |
| Runtime config mutating `environment`/creds/IDs | Privilege/identity/determinism escape at runtime | Closed allowlist; `environment`, SQL creds, IDs, `rng_seed`, precision are immutable-at-runtime (§6e) |
| External thread reaching handler methods directly | Off-thread state mutation bypassing validation/admission | Fail-closed `add_event` (D-10, SIGNAL/STRATEGY_COMMAND only); thin thread-safe facade otherwise (§4b.3) |

## UX Pitfalls

(Operator-facing, not end-user — the "user" here is the operator running/monitoring the live engine.)

| Pitfall | Operator Impact | Better Approach |
|---------|-----------------|-----------------|
| Unclassified free-string halt reasons | Operator/control-plane can't categorize *why* the engine halted | Typed `HaltReason` vocabulary (CF-8, P1/P8) |
| Alert egress log-only | A 3am halt reaches nobody | Thread the pluggable alert-sink seam so CRITICAL can reach a real sink (CF-5, P9); substantive egress is the FastAPI milestone |
| No breaker counters/last-trip reason in status | Operator can't see *why* a breaker tripped | Surface counters + last-trip reason in `get_status()` (CF-1, P9) |
| Status read touching hot-path locks | UI/status polling contends with the engine thread | `state.*`/`stats.*` in `SystemStore` double as the UI read model (§6d) — read without hot-path locks |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Config centralization (P1):** looks done — but `sql` must be lazy-accessed (not constructed at import), and every relocated constant must value-equal its old module constant. Verify: inertness gate green + a constant-equality test.
- [ ] **Priority bus (P2):** looks done — but verify the unique `seq` prevents tuple fall-through (no event comparison) AND preserves within-tier FIFO. Verify: same-tier order test + a same-`(tier)` non-comparison test.
- [ ] **SqlEngine rename + migration relocation (P4):** looks done — but run `alembic upgrade head` against a clean DB and confirm `migrations/` is excluded from the wheel. Verify: `upgrade head` succeeds; `alembic heads` == 1.
- [ ] **New stores (P5):** looks done — but the three-store chain is one linear head, and `create_all` == `upgrade head` schema. Verify: single-head check + create_all/migration parity test.
- [ ] **Venue registry (P6):** looks done — but registering `'okx'` imports no `ccxt.pro` until *built*. Verify: extend inertness test to registration.
- [ ] **UniverseWiring (P7):** looks done — but backtest oracle byte-exact AND determinism double-run identical, because the helper is shared with `BacktestRunner`. Verify: oracle + double-run per plan.
- [ ] **StreamRecovery / CF-2 (P8):** looks done — but `backfill_on_resume` runs loop-native, NOT engine-thread. Verify: no engine-thread path invokes it.
- [ ] **Error subsystem (P9):** looks done as a refactor — but CF-1 aggregate breaker actually trips (SETTLEMENT halt-on-first), two-guard livelock safety holds, backtest fail-fast unchanged. Verify: a money-route-fails-every-event test halts; an ErrorEvent-consumer-fails test spawns no second ErrorEvent; oracle green.
- [ ] **Multi-portfolio (P12):** looks done — but two portfolios sharing an `account_id` fails LOUD at composition, and fills route by `portfolio_id` to the right ledger. Verify: shared-`account_id` raises; two-portfolio attribution gate.

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Oracle drift in a code-motion phase | LOW–MEDIUM | `git bisect` the plan commits (per-plan gate makes this cheap); revert the offending value change; re-extract verbatim |
| Inertness regression | LOW | Read the inertness-test import trace; move the offending `import` into a method body / out of a barrel; re-run gate |
| Priority-queue fall-through crash | LOW | Add/repair the `seq` element so the tuple never compares events; add the regression test |
| Second-ring-writer corruption (CF-2 on wrong thread) | MEDIUM | Move `backfill_on_resume` to the connector loop (reconnect callback); add the no-engine-thread assertion |
| Multi-head Alembic tree | LOW–MEDIUM | Author a merge revision OR re-chain `down_revision`s linearly; add the single-head gate |
| Error→error livelock | MEDIUM | Restore the two-guard (source + consumer) terminal safety; add the consumer-fails-no-second-error test |
| Shared-`account_id` slipped through | MEDIUM–HIGH | Add the composition-time distinct-`account_id` invariant; audit reconciliation for cross-portfolio sums; re-reconcile affected portfolios |
| Persisted secret | HIGH | Rotate the leaked credential; purge the store row; make the persist path structurally unable to write secrets; add the no-secret round-trip test |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Behavior-drift in pure code-motion | P1, P3, P4, **P7 (UniverseWiring)** | Byte-exact oracle (`134 / 46189.87730727451`, `check_exact=True`) + determinism double-run, **per plan** |
| Inertness regression | P1 (lazy `sql`), P2, P5, **P6 (registry)** | `test_okx_inertness.py` green per plan; extended to assert register-vs-build |
| Priority-queue pathologies | P2 | Unique-`seq` no-fall-through test; within-tier FIFO test; backtest selects `FifoEventBus` |
| Threading-contract violations | P7 (single-writer), **P8 (CF-2 loop-native, CF-7)**, P6 (CF-3 docstrings) | No blocking I/O on connector loop; `backfill_on_resume` unreachable from engine thread; fail-closed `add_event` |
| Alembic migration-chain hazards | P4 (relocation), P5 (chain) | `alembic upgrade head` on clean DB; `alembic heads` == 1; create_all/migration parity test |
| Runtime-config footguns | P10 (allowlist/CONTROL-route/no-secret), P1 (immutable split) | Immutable-key mutation raises; no off-thread overlay write; no-secret store round-trip |
| Multi-portfolio keying errors | **P12**, P13 (gate), P6 (account factory) | Shared-`account_id` raises at composition; two-portfolio fill-attribution gate |
| Error-subsystem circuit-breaker (**CF-1**) | **P9** | Money-route-fails-every-event **halts**; ErrorEvent-consumer-fails spawns no second ErrorEvent; backtest fail-fast/oracle unchanged; counters + last-trip in status |
| Indentation hazard (cross-cutting) | Every phase | Match the file's indentation family (tabs: handlers; 4-space: `config/`/`core/`/`feed/`/`events/`); never normalize; mixed-indentation diff review |

## Sources

- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` — §4 (event bus & threading model), §6 (config platform), §7 (storage/migrations), §8 (venue registry), §10 (multi-portfolio), §11 (safety), §12 (error handling), §13 (session init), **§15 (constraints & risks)**, **§16 (phasing P1–P13)**, **§18 (folded-in CF-1..CF-10)** — HIGH confidence (authoritative locked design)
- `.planning/todos/pending/v17-residual-carryforward.md` — CF-1 (ERROR-route circuit breaker spec), CF-2 (loop-native backfill), CF-3 (connector contract docstrings), CF-4 (stream supervisor DRY), CF-5 (alert egress), CF-7 (reconciler guard) — HIGH
- `.planning/PROJECT.md` (Current Milestone v1.8) — phase list, blocking-gate framing — HIGH
- `CLAUDE.md` — indentation hazard, money=Decimal, determinism, inertness conventions; D-10 fail-closed `add_event` — HIGH
- User memory: WR-06 (error→error two-guard terminal safety), WR-03 (OKX candle snapshot-on-subscribe), OKX markets/EEA constraints — MEDIUM–HIGH (prior in-repo findings)
- General knowledge: `queue.PriorityQueue` tuple-comparison fall-through footgun; Alembic multi-head/`script_location`/`create_all`-divergence hazards — HIGH (well-established Python/Alembic gotchas)

---
*Pitfalls research for: v1.8 Live System Refactor & Live-Readiness Hardening*
*Researched: 2026-07-09*
