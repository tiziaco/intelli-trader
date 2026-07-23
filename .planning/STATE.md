---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: Live System Refactor & Live-Readiness Hardening
current_phase: 11.2
current_phase_name: INSERTED — split out of Phase 11.1
status: ready_to_execute
stopped_at: Phase 11.2 planned — 14 plans across 8 waves, verification passed, ready to execute
last_updated: "2026-07-23T12:14:12.762Z"
last_activity: 2026-07-23
last_activity_desc: Phase 11.2 planned — 14 plans / 8 waves, plan-checker VERIFICATION PASSED (`15c1e17b`)
progress:
  total_phases: 15
  completed_phases: 11
  total_plans: 81
  completed_plans: 53
  percent: 65
---

# Project State

## Project Reference

See: .planning/PROJECT.md (Current Milestone: v1.8 — Live System Refactor & Live-Readiness Hardening)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle **134 / `46189.87730727451`**; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 shipped a live operating mode (paper-first on OKX) without disturbing that oracle.
**Current focus:** Phase 11.2 — account-provisioning-bootstrap-review-closures
thin ~200-line facade over focused, venue-parametrized, FastAPI-ready collaborators — **without
disturbing the byte-exact oracle or the OKX import-inertness gate**. FastAPI itself is out of scope
(LR-01). Full scope: core refactor (P1–P8 + P12 + P13) + the three ★ feature-adds (P9–P11).

## Current Position

Phase: 11.2 — Account Provisioning Bootstrap + Review Closures (INSERTED — split out of Phase 11.1)
Plan: 0/14 complete (8 waves)
Status: Planned — 14 plans, plan-checker VERIFICATION PASSED. Resume: `/gsd-execute-phase 11.2`.
Last activity: 2026-07-23 — Phase 11.2 planned, 14 plans / 8 waves committed (`15c1e17b`)

**Discussion session (2026-07-23).** Ten gray areas, **23 decisions locked (D-20..D-42)** — numbering
continues from 11.1's D-01..D-19, whose D-09..D-13/D-15 were the pre-locked 11.2 set and are NOT
re-litigated. Four owner reframings rewrote the phase rather than filling in details, and each rejected a
Claude-proposed framing first:

- **D-24/D-25 (the big one).** The source defect is that `add_portfolio` conflates a durable **write** with a
  runtime **build** — `rehydrate_portfolios` calls `add_portfolio` (`portfolio_rehydrate.py:130`), and
  `_persist_definition`'s "GATED ON ABSENCE" (`portfolio_handler.py:454`) exists ONLY to survive that
  re-entry. A composition-owned **`PortfolioFactory`** splits create from materialize; rehydrate materializes
  only; `PortfolioHandler` loses its `VenueBundles` injection. **ACCT-07 closes structurally** and **ACCT-05
  becomes trivially true** (one creation path). Three earlier framings were rejected as "moving the mess
  around", including one this session had already locked as D-22 — now superseded, `add_portfolio` keeps its
  plain-data signature and the 133 call sites are untouched.

- **D-20 — COMP-07 lands HERE, not Phase 12.** Assembly moves above rehydrate; `_attach_venue_accounts`
  (116 lines) is deleted. **⚠ Phase 12's criterion 7 and COMP-07 must be amended** — it declares the current
  boot order a hard invariant and requires `test_distinct_account_invariant.py` unmodified.

- **D-32 — the phase's only migration.** `enabled` (pause, keeps its account) and `is_deleted` (retire,
  releases the pair) become two flags, and `portfolios`' unique constraint becomes **partial**
  (`WHERE NOT is_deleted`, both `postgresql_where` and `sqlite_where`). Driven by the owner's real workflow —
  retire a portfolio, run a new one on the same real venue account — which the plain constraint blocks. This
  revises `portfolio_definition_store.py:23`'s documented "PLAIN (never partial)"; that rationale is about
  *simultaneous* sharing and predates `enabled` having any writer (which is WR-04/ACCT-10 itself).

- **D-35/D-26/D-36 — nothing is added to `live_trading_system.py`.** Owner-stated twice. Provisioning lives on
  `VenueAccountManager.provision(...)` (there is no `system.provision_venue_account`); "primary account" is
  deleted outright (`_primary_lifecycle` has **zero production consumers** — 28 test sites, 7 files) and the
  feed binds to a *connection*, rebinding when that account is retired. That file may only SHRINK.

**Found during discussion, not in the roadmap:**

- `delete_portfolio` (`portfolio_handler.py:495-520`) **never touches the definition store**, so a deleted
  portfolio returns on the next boot with its persisted id and its child tables reattached — a worse instance
  of WR-04 than the INACTIVE case ACCT-10 names.

- `VenueAccountStore` has **no `read_enabled_for`** (only `upsert`/`record_venue_uid`/`get`/`read_all`), and
  `config_json`/`enabled` have **zero readers** today.

- ACCT-08 collapses: two of its four reach-ins are DELETED by D-20/D-25 rather than converted, and the
  roadmap's line numbers are stale — the real remaining site is `live_trading_system.py:1367`, the WR-02 loop.

- `ExecutionErrorCode` has no member fitting either surviving ACCT-09 path; D-42 adds two.
- `scripts/run_live_paper.py` depends on boot-time minting today, so it breaks the moment `_mint_account_rows`
  goes — hence D-29 (existing scripts become provisioning callers; no new script).

- Full feed/account decoupling is **verified** blocked at `OkxSettings`' required credential fields
  (`okx_plugin.py:136-150`), not merely assumed — deferred to the market-data phase.

**Wave shape locked (D-39):** W1 foundations (required kwarg + the migration + two 11.1-review closures) →
W2 `VenueAccountManager` (ACCT-01/02/04 + the assembly move) → W3 `PortfolioFactory` (ACCT-03/05/07 + the
WR-11 fixture) → W4 lifecycle persist (ACCT-10) → W5 corrections ∥ (ACCT-06 · ACCT-08+WR-02 · ACCT-09) →
W6 tests. ACCT-01 and ACCT-02 **must land together**; the required-kwarg **must** precede ACCT-05.

**Planning session (2026-07-22).** Research → pattern-map → plan → check, all gates green:
8/8 VENUE requirements covered, **12/12** CONTEXT decisions (D-01..D-08, D-14, D-17..D-19) cited by
`D-NN` token in `must_haves`/`objective`, 17/17 spec-less probe edges authored (10 plain truths +
3 flat-scalar `verification: backstop` markers + 4 flagged `unclassified` assumptions, never
auto-backstopped), 4 descriptor-less prohibitions. Plan-checker: **VERIFICATION PASSED**, zero
blockers, one warning (see below). Artifacts: `11.1-RESEARCH.md` (73d97b1e), `11.1-VALIDATION.md`
(74292922), `11.1-PATTERNS.md` (7e6c063a), plans (c80899fd, 4c67e8ac).

**Research corrected 11 factual claims in CONTEXT.md.** The five that reshaped the plan:

- **F-2 (CRITICAL, now Wave 1 / plan 01):** `ConnectorProvider` is NOT import-inert —
  `itrader/connectors/__init__.py:11-12` eagerly re-exports `OkxConnector`, pulling `ccxt` **and**
  `itrader.connectors.okx`, both in `test_okx_inertness.py`'s `_FORBIDDEN`. D-04 puts
  `ConnectorProvider` on the backtest import path, so GATE-01 reddens unless the barrel is fixed
  FIRST. Zero consumers tree-wide; two-line deletion. CONTEXT's D-04 GATE-01 evidence was correct
  but about a different package (`itrader.venues`).

- **F-5 (CRITICAL):** the byte-exact oracle runs the **legacy** construction arm
  (`scripts/run_backtest.py:68` → `BacktestTradingSystem(exchange="csv", …)`), NOT
  `build_backtest_system`. Editing only the factory arm would leave the oracle green while proving
  nothing. Plans 04/06/07 name both arms.

- **F-1 (CRITICAL):** D-03's "`new_account` loses its `portfolio_ref` parameter" is false for
  `OkxVenuePlugin` — it uses `portfolio_ref` for D-11 account-identity resolution via
  `_account_id_for`, which D-01 does not touch. Decision stands; plan 09 passes `account_id` on the
  config from `add_portfolio` and preserves the raise-on-absent-id guard verbatim.

- **F-3 / F-4 (CRITICAL):** the `'csv'`→`'paper'` blast radius is **27 files**, not "roughly six test
  sites". Two production sites CONTEXT never named: `order_validator.py:117`'s allowlist (would
  reject **every** order → 0 trades) and `universe_wiring.py:98`'s silent `.get` + `isinstance`
  guard (Universe never injected, money arithmetic moves under a green suite — the phase's top
  silent-corruption risk). Plan 06 asserts the lookup is non-None rather than trusting the oracle diff.

- **F-10:** CONTEXT's "~360 lines deleted" spans 11.1 **and** 11.2; 11.1's real budget is **≈186**.
  It is nowhere a plan gate, and a ROADMAP correction note was added.

**Two owner decisions taken this session (post-research):**

1. The `('simulated', DEFAULT_ACCOUNT_ID)` registry key is **retired in full**, not kept as a
   transitional alias — so F-4 and F-11 land in the same commit as the re-key (plan 06).

2. **D-06 and D-08 land in ONE wave** (plan 07). Landing D-06 alone makes `compose.py:239` return
   `None` and the estimate degrade to `Decimal("0")` — *also* the golden value, so the oracle would
   stay green while the reservation path is structurally broken.

**Planner inverted RESEARCH's wave order:** D-05/D-19 (plan 06, wave 3) now lands *before* D-06/D-08
(plan 07, wave 4). Renaming first means `('paper', default)` already exists and resolves when plan 07
changes *who builds* the object behind it, so the green-and-wrong state never exists. Plan-checker
scrutinised and confirmed this.

**✓ RESOLVED — owner sign-off 2026-07-22. Deferred to Phase 12 as COMP-07.** Plan 09 retains
`_attach_venue_accounts` (116 lines) rather than deleting it, for a boot-order fact neither CONTEXT
nor RESEARCH states: live portfolios are rehydrated (`portfolio_rehydrate.py:130`) **before**
`_build_account_specs` builds their `VenueSpec`, so a `VenueAccount` cannot be minted at
portfolio-creation time. The construction-time account is therefore always the compute leaf.
Accepted consequence: the phase's headline "composition stops reaching in afterwards" holds for the
**compute-account path** (backtest + paper, fully fixed by D-01/D-02/D-03); the **live venue-truth
swap** remains and its removal is now **COMP-07** (REQUIREMENTS.md + ROADMAP Phase 12 criterion 8).
Plan 09's flagged block records the sign-off so no executor reopens it.

**⚠ Carried to Phase 12's discuss step — COMP-07 conflicts with Phase 12's own scope fence.** COMP-07
requires the live boot ORDER to change (venue/account assembly before portfolio rehydrate), but
Phase 12 is declared *"pure code-motion — no semantic change to any live contract"* and its criterion
7 pins the current order as *"a hard invariant, not an implementation detail,"* enforced by
`test_distinct_account_invariant.py` passing **unmodified**. COMP-07 is therefore the one semantic
change in an otherwise behaviour-preserving phase. Decide at discuss time: widen the fence for it
(then that test must change, and the four load-bearing reasons at `live_trading_system.py:1896-1929`
must be re-derived against the new order), or split COMP-07 into its own phase. A conflict note is
recorded inline in both ROADMAP.md and REQUIREMENTS.md.

---

*Historical (Phase 11, superseded — retained for the record):* Phase 11 locked a seven-wave
decomposition; plan-checker VERIFICATION PASSED with zero blockers and zero warnings; gates green —
7/7 MPORT requirements covered, 30/30 CONTEXT decisions cited by ID in must_haves, 14/14 spec-less
probe edges authored (8 covered truths + 3 flat-scalar backstop markers + 3 flagged unclassified
assumptions). Preceded by CONTEXT.md + DISCUSSION-LOG.md (13945336): eleven gray areas discussed,
30 decisions (D-01..D-30) locked, three sub-decisions explicitly superseded and reconciled in-file.

**Carried into planning (found during discussion):**

- **D-27 / MPORT-07 (discovered, now a numbered requirement):** the **exchange** must become per-`(venue, account_id)`.
  `ExecutionHandler.exchanges` is keyed by bare name (`execution_handler.py:66,126`) while `OkxExchange` holds
  exactly one connector (`okx.py:101`) — so two portfolios on `okx` with different accounts both route to the same
  exchange and **account B's orders would submit through account A's connector**, even with per-account credentials
  and accounts all correct. Verified architecturally sound: every mutable field on `OkxExchange` is already
  account-scoped and the markets/precision map lives on the connector (`okx.py:952-955`), so this makes an existing
  dimension explicit rather than adding one. `watch_my_trades` being a private per-account stream makes it mandatory.
  Now a numbered requirement: **MPORT-07** in REQUIREMENTS.md, mapped to P11, ROADMAP success criterion 5. SETTLED.

- **F-1 (HIGH, confirmed):** `portfolio.py:71` mints a fresh UUIDv7 `portfolio_id` on every construction with no way
  to supply one, while `portfolio.py:68` and `live_trading_system.py:1583-1585` both assert restart-stability that
  does not exist. On restart the prior run's `portfolio_account_state` rows orphan and P10's persisted
  `strategy_portfolio_subscriptions` rows dangle. Pre-existing; P11 is where it stops being survivable. Fix + correct
  both comments in the W4 bootstrap plan.

- **F-2 (MEDIUM):** `_run_session_baseline_guard` (`reconciliation_coordinator.py:216`) returns on the first
  portfolio mismatch — benign at N=1, wrong at N>1. Must become evaluate-all.

- **Highest regression risk:** D-09 moves per-portfolio config off `portfolio_account_state.config_json` (P9 D-25)
  onto the new `portfolios` row — that is the tested RTCFG-03 path **P13's TEST-03 gate verifies** (was P12 before the 2026-07-22 renumber). The migration
  must move data, not just repoint reads.

- **Folded todo:** `b2-strategy-subscription-portfolio-id-uuid-column` — String→Uuid **and** the FK to `portfolios`
  (CASCADE). The type change is a prerequisite for the FK, not cosmetic.

- **Decomposition locked (D-28):** seven waves, ONE phase — W1 Schema → W2 Credentials → W3 Accounts →
  W4 Bootstrap → W6 Reconcile, with W5 Attribution parallelizable and W7 Tests last.

Note (P11 planning): as predicted, the starred header `### Phase 11 ★:` broke `roadmap.get-phase` (`found:false`)
and the phase dir had to be created by hand. Expect `init.plan-phase` to return `phase_req_ids: null` — inject
MPORT-01..07 manually into the researcher/planner/checker prompts, and expect `roadmap.annotate-dependencies` to
no-op so the wave list must be written by hand. Also: `state.record-session` does not refresh `last_activity_desc`
(no registered handler for that field) — it was corrected by direct edit.

Note (P11 planning, CONFIRMED + two new failure modes): every prediction above held — `roadmap.get-phase 11`
`found:false`, `phase_req_ids:null` (MPORT-01..07 injected by hand into all three agent prompts),
`roadmap.annotate-dependencies` `updated:false` (wave list written by hand). Two more starred-header casualties
found this session, both silent:

1. **The BLOCKING decision-coverage gate could not parse 7 of the 30 decision bullets** (D-02/04/11/17/18/24/27),
   reporting `could-not-parse, total: 23`. Causes: a line-wrapped `):**` header (D-02/11/17), a second colon in
   the header with no em-dash (D-04/18/27), and a bare `*` inside `` `state.*` `` (D-24). The parser accepts
   `- **D-NN <no colon, no asterisk>:**`, or one colon then `**`, or an em-dash form with the closing `**` on the
   SAME line. Fixed by reformatting headers only (`dc47ff08`); all 30 now parse and the gate passes 30/30.

2. **`state.planned-phase` no-opped (`updated: []`).** It is template-aware by design — it only overwrites
   KNOWN_TEMPLATE_DEFAULTS, so the executor-authored `Status:`/`Last activity:` in `## Current Position` were
   preserved and nothing moved. STATE.md was updated by hand to what the handler would have written.

Note (P11.2 planning, 2026-07-23): the **unstarred** header `### Phase 11.2:` resolved cleanly — `roadmap.get-phase`
`found:true`, `phase_req_ids` populated (ACCT-01..10), and the decision-coverage gate parsed all **23** bullets
(D-20..D-42) on the first try with no reformatting needed. So the starred-header failure mode is confirmed to be
**the star, not the decimal**. Two known no-ops recurred and were handled by hand: `state.planned-phase`
(`updated: []`, template-aware — STATE.md written by hand as before) and `roadmap.annotate-dependencies`
(`updated:false`) — though the latter was a genuine idempotent skip this time, because the planner had already
written the wave list into ROADMAP.md itself. Also: `query commit` needs **repo-relative** `--files` paths; an
absolute path silently returns `nothing_to_commit`.

⚠ **CROSS-PHASE OBLIGATION surfaced during P11.2 planning — must reach the ROADMAP before Phase 12 is planned.**
D-20 moves venue assembly above portfolio rehydrate, which **invalidates Phase 12's criterion 7** (it declares the
current boot order "a hard invariant, not an implementation detail" and requires `test_distinct_account_invariant.py`
to pass **unmodified** — P11.2 amends that test). **COMP-07 must be struck from Phase 12's scope**, since D-20 lands
it here instead. Plans 11.2-07 and 11.2-14 require this to be recorded in their summaries.

Note: `phase.complete` again advanced current_phase to 12 (its next-phase dir-scan skips the not-yet-created
P11 ★ dir); corrected to 11 per the roadmap sequence. P12 (core-final) depends on P11.

Note (P10 planning): the starred header `### Phase 10 ★:` again broke `roadmap.get-phase` (`found:false`) and
`init.plan-phase` (`phase_req_ids:null`); REQ IDs STRAT-01..03 were injected manually into the researcher/planner/
checker prompts, and `roadmap.annotate-dependencies` no-opped (`updated:false`) so the ROADMAP wave list was
written by hand. Expect the same on P11 ★.

**Carried into execution (P11 — found during planning, not in CONTEXT):**

- **F-3 (HIGH):** **the D-25 two-paper-account test structurally CANNOT prove MPORT-07.**
  `live_trading_system.py:1473` builds `PaperVenuePlugin(execution_handler.exchanges['simulated'])`, so both paper
  accounts resolve to the *same* exchange object by construction. Paper stays the right venue for the
  lifecycle/restart path, but MPORT-07 got its own gate in **11-06** using a fake multi-account plugin. 11-11's
  docstring must state why it does not gate routing.

- **F-4 (MEDIUM, and larger than research found):** bare-name `exchanges[...]` lookups are **35 sites across 22
  files**, not the single `on_order` site CONTEXT names (`execution_handler.py:126`). Research found 10 source
  sites; the planner grepped `tests/`/`scripts/` too and found 25 more, including **all 10 e2e scenario files**.
  Three of the source sites hardcode `'simulated'` on the **backtest-shared** path — missing those is an oracle
  break, so 11-06 enumerates them and gates on the e2e suite.

- **F-5 (LOW, sequencing):** F-1's pinnable `portfolio_id` and D-06's `account_id` are the **same signature edit**
  on the same lines of `Portfolio.__init__` / `add_portfolio`. Merged into one task (**11-05**) and pulled into
  **wave 1** — D-28 groups it under W4, but `account_for` reads `portfolio.account_id`, making it a hard
  prerequisite of the W3 exchange keying. A sequencing change, not a decomposition change.

- **C-1 (correction to D-16):** `clOrdId` spans **three** files, not the two CONTEXT claims — `okx.py` (23),
  `venue_correlation.py` (22), and one at `reconciliation_coordinator.py:172` inside the `RuntimeError` string
  MPORT-01 deletes. Since W5 is parallelizable, a two-file completion grep false-passes or false-fails depending
  on W3/W5 ordering: 11-02 scopes its check by file allowlist, 11-07 carries the repo-wide assertion.

- **`id()` alias dedup in `on_market_data` is DO-NOT-TOUCH.** It dedups *aliases* (one object under two keys);
  distinct per-account exchanges have distinct `id()` and are correctly driven separately. It is what keeps the
  oracle byte-exact through D-27. Marked explicitly in 11-06 so an executor does not "fix" it.

- **Two open questions assigned, not dropped:** (a) whether two paper portfolios sharing one `MatchingEngine`
  resting book interfere on brackets/OCO — an 11-07 task that **must complete before 11-11 writes the lifecycle
  test**; if interference exists it is a real defect, not a test artifact. (b) the D-15 invariant runs over the
  **union** of persisted and spec portfolios (11-08) — checking one source is a hole.

- **Watch item — D-09 (11-03).** `load_config()` returning `None` degrades clean with no warning
  (`live_trading_system.py:1266,1268`), so a repointed-but-unmoved config yields a **green suite and silently
  default-config portfolios**. The gate asserts the migrated value by **equality**; a non-null assertion is
  written into the prohibitions as insufficient. PATTERNS found **no shipped analog** — all 11 existing Alembic
  revisions are pure DDL, none move data.

**Carried into execution (P10 — found during planning, not in CONTEXT):**

- **F-1 (HIGH, confirmed real):** `cache_registration.py:226::derive_warmup_depth` is a bare `max(s.warmup)` with no
  timeframe scaling, while `warmup` counts strategy-timeframe bars and the ring is sized in base bars → a coarser-
  timeframe strategy silently never warms. Fixed in 10-03 (opt-in `base_timeframe`; omitted → byte-identical, which
  is what protects the oracle) + loud-reject gates in 10-07/10-08. Ring resize deferred to the finer-than-base todo.

- **Three CONTEXT errors corrected in the plans, not inherited:** `universe_handler.py` is **4-SPACE** (measured
  0/559, CONTEXT says tabs — would break the file); migration head is **`system_stats`** (CONTEXT says
  `strategy_registry`); D-03's policy list omits **`PercentFromDecision`** (`core/sizing.py:278`, a live union member).

- **CR-01 pair guard is broader than D-16 permits** — it refuses ALL verbs; 10-06 re-scopes it to
  `{reconfigure, add_ticker, remove_ticker}` so pairs can still add/remove/enable/disable/rehydrate.

- **A1 (unverifiable from source):** the D-06 drop assumes `strategy_subscriptions` is empty in every deployed DB.
  10-02 counts rows first and raises on non-empty. Worth a manual `SELECT count(*)` before running the migration.

Progress: [██████████] 100% (8/9 core phases; the three ★ feature-adds P9–P11 are in scope on top)

## Milestone Gate (v1.8 — applies to EVERY phase)

1. **Oracle byte-exact** — `SMA_MACD` stays **134 / `46189.87730727451`** (`check_exact=True`),
   determinism double-run identical. **Per-PLAN gate** on P1–P4, P5, and **P6's `UniverseWiring`
   extraction** (highest oracle risk). Any re-baseline (LR-02) is explicit + externally cross-validated
   (backtesting.py + backtrader), never silent. Live-only phases (P7–P11) stay byte-exact (backtest-dark).

2. **OKX import-inertness** — `tests/integration/test_okx_inertness.py` stays green, extended to assert
   **register-vs-build** on P1/P2/P4/P5 (registering a venue imports no `ccxt.pro` until built;
   `SystemConfig` never constructs Postgres `SqlSettings` at import). **Zero new dependency / no poetry
   change** anywhere in P1–P13.

3. **Held throughout** — Decimal money end-to-end; single UUIDv7; determinism (business `time`, seeded
   RNG, injected clock); `mypy --strict` clean on new code; `filterwarnings=["error"]` green; tabs/spaces
   indentation matched to the file (never normalized).

## Phase Map (v1.8 — Phases 1-12, numbering reset)

Dependency graph (not strict numeric order): `P1 · P2` (no deps) → `P3{P1,P2}` → `P4{P3}`; `P5{P2,P3}`;
`P6{P4,P5}` → `P7{P6}` · `P8{P6}`; `P9★{P4,P7}`; `P10★{P4,P6}`; `P11★{P5,P7}` → `P11.1{P11}` → `P12{P11.1}`; `P13{P6,P11,P12}`.

| Phase | Name | Requirements | Notes |
|-------|------|--------------|-------|
| 1 | Config Centralization | CFG-01..06 | oracle-gated; lazy `sql` inertness lever; `HaltReason` (CF-8); CF-6 doc |
| 2 | Event Bus | BUS-01..04 | oracle-gated; +CONTROL EventTypes + minimal `EngineContext` skeleton (refinements 2/3) |
| 3 | EngineContext + Storage-in-Handler | CTX-01..04 | oracle-gated; `SqlBackend→SqlEngine` folded in (refinement 4) |
| 4 | Storage Schema: Migrations Relocation + New Durable Stores | SQL-01..02, STORE-01..05 | merged (old P4+P5); oracle-gated relocation FIRST, then live-only stores; single-head + parity Alembic gate over the FULL chain + rehydrate |
| 5 | Venue Registry + Bundle | VENUE-01..07 | oracle-gated; **highest inertness risk**; CF-3/4/9 |
| 6 | LiveRunner + Factory + Facade Shrink | RUN-01..07 | **highest oracle risk** (`UniverseWiring`); CF-10 |
| 7 | Safety + Reconciliation + Stream Recovery | SAFE-01..06 | CF-2 loop-native; CF-7; SAFE-06 pre-trade throttle |
| 8 | Error Subsystem | ERR-01..04 | **CF-1 aggregate breaker MUST trip** (hard criterion); CF-5 |
| 9 ★ | Runtime-Config Platform | RTCFG-01..06 | feature-add; allowlist + venue-kind-aware fee/slippage gate |
| 10 ★ | Strategies Registry | STRAT-01..03 | feature-add; STRAT-03 atomic re-config folds pair-strategy TODO |
| 10.1 | StrategiesHandler Decomposition | DECOMP-01, 01a, 02, 03 | INSERTED follow-up to P10 |
| 11 ★ | Multi-Portfolio-Live | MPORT-01..07 | LR-03 (never trim); distinct-`account_id` fails loud |
| 11.1 | Account Provisioning + Mandatory Account Identity | ACCT-01..11 | INSERTED follow-up to P11; DB as sole account-truth source |
| 12 | Live Composition-Root Dissolution | COMP-01..06 | INSERTED 2026-07-22; `build_live_system` disappears; behaviour-preserving |
| 13 | Test Migration + Gates | TEST-01..04 | lands last; production replay-free; attribution gate |

**Coverage: 86/86 mapped, 0 orphans.** *(was stated as 69/69 through 2026-07-22 — stale: it predated the eleven `ACCT-*` reqs from the inserted P11.1, so the true count was 80 before the six `COMP-*` were added 2026-07-22. Earlier "64/64" was likewise stale from before the four `DECOMP-*` of P10.1.)* ★ = trimmable feature-add (in scope — owner chose full scope; the
trim boundary P1–P8+P12+P13 core vs P9–P11 ★ is noted, not taken). Research flags (plan-time research): P6
(`UniverseWiring` byte-exact discipline), P8 (CF-1 route-classification + livelock test), P11
(`client_order_id`/`portfolio_id` two-key attribution). Skip research-phase: P2/P4/P5 (specified/mechanical).

## Performance Metrics

**Velocity (program cumulative through v1.7):**

- Total plans completed: 381 (v1.0 62 + v1.1 28 + v1.2 23 + v1.3 20 + v1.4 35 + v1.5 26 + v1.6 21 + v1.7 75)
- v1.8 plans completed: 0

*Updated after each plan completion. Per-milestone velocity is archived in the respective MILESTONE-AUDIT.md.*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 12 | 3 tasks | 3 files |
| Phase 01 P02 | 12 | 2 tasks | 4 files |
| Phase 01 P03 | 4m | 1 tasks | 1 files |
| Phase 01 P04 | 25min | 3 tasks | 15 files |
| Phase 02 P01 | 3min | 3 tasks | 3 files |
| Phase 02 P02 | 6min | 3 tasks | 4 files |
| Phase 02 P03 | 18min | 3 tasks | 10 files |
| Phase 03 P01 | 11min | 2 tasks | 41 files |
| Phase 03 P02 | 2min | 1 tasks | 2 files |
| Phase 04 P01 | 1min | 2 tasks | 4 files |
| Phase 04 P02 | 6min | 3 tasks | 6 files |
| Phase 04 P03 | 12min | 3 tasks | 6 files |
| Phase 04 P04 | 20m | 3 tasks | 16 files |
| Phase 05 P01 | 29min | 3 tasks | 17 files |
| Phase 05 P02 | 6m | 3 tasks | 9 files |
| Phase 05 P03 | 4min | 2 tasks | 4 files |
| Phase 05 P04 | 5min | 3 tasks | 7 files |
| Phase 05 P05 | 7min | 3 tasks | 5 files |
| Phase 05 P06 | 11min | 3 tasks | 6 files |
| Phase 06 P01 | 4 min | 2 tasks | 2 files |
| Phase 06 P02 | 12 min | 3 tasks | 3 files |
| Phase 06 P03 | 6min | 1 tasks | 1 files |
| Phase 06 P04 | 13min | 2 tasks | 7 files |
| Phase 06 P05 | 9min | 3 tasks | 3 files |
| Phase 06 P06 | 50min | 3 tasks | 26 files |
| Phase 06 P07 | 70min | 3 tasks | 21 files |
| Phase 06.1 P01 | 22min | 3 tasks | 7 files |
| Phase 06.1 P02 | 18 | 3 tasks | 1 files |
| Phase 06.1 P03 | 4 | 3 tasks | 4 files |
| Phase 06.1 P04 | 6 | 3 tasks | 3 files |
| Phase 07 P01 | 12 min | 3 tasks | 10 files |
| Phase 07 P02 | 15 min | 2 tasks | 7 files |
| Phase 07 P03 | 6min | 2 tasks | 4 files |
| Phase 07 P04 | 6 min | 2 tasks | 4 files |
| Phase 07 P05 | 20 min | 1 tasks | 2 files |
| Phase 07 P06 | 45min | 3 tasks | 15 files |
| Phase 09 P01 | 25min | 3 tasks | 11 files |
| Phase 09 P02 | 11min | 3 tasks | 5 files |
| Phase 09 P03 | 21min | 3 tasks | 14 files |
| Phase 09 P04 | 30min | 3 tasks | 9 files |

## Accumulated Context

### Roadmap Evolution

- v1.8 ROADMAP.md created 2026-07-09 from the LOCKED design spec
  (`docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §16, LR-00..LR-22, CF-1..CF-10)

  + research SUMMARY's 4 build-order refinements. Phases derived 1:1 from the REQUIREMENTS.md
  category→phase mapping (authoritative); all 64 v1 requirements mapped (0 orphans). Numbering reset to
  Phase 1 (matching v1.1–v1.7). The milestone gate (oracle byte-exact + inertness) is a success criterion
  in every phase; per-PLAN oracle gating on P1–P4/P5/P6-UniverseWiring.

- **2026-07-09 revision (13→12 phases):** old P4 (SqlEngine Migrations Relocation, SQL-01/02) folded into
  old P5 (New Durable Stores, STORE-01..05) → a single merged storage-schema phase P4 ("Storage Schema:
  Migrations Relocation + New Durable Stores"). Both are live-only / off the oracle hot path, and
  "relocate the migrations dir, then extend the Alembic chain with 3 new stores" is one cohesive unit of
  work; the SQL-02 single-head + parity gate now validates the FULL chain incl. the 3 new stores. All
  downstream phases renumbered −1 (old P6→P5 … old P13→P12). Owner-approved.

- 4 research refinements folded into the spec §16 graph: (1) P3 depends on {P1,P2}; (2) minimal
  `EngineContext` skeleton lands in P2; (3) P2 adds the CONTROL EventTypes; (4) `SqlBackend→SqlEngine`
  rename folded into P3 (only migrations *relocation* stays in the merged P4).

- Phase 10.1 inserted after Phase 10: StrategiesHandler Decomposition (URGENT)
- Phase 11.1 inserted after Phase 11: Account Provisioning + Mandatory Account Identity — DB becomes sole source of portfolio+account truth; closes code-review CR-02/CR-03/WR-03/WR-05 (URGENT)
- Phase 11.2 inserted after Phase 11.1: Split out of Phase 11.1 (D-16): ACCT-01..11 plus the locked decisions D-09..D-13/D-15 move here; 11.1 keeps the structural half
- Phase 11.3 inserted after Phase 11.2: D-09 Config-Move Migration Guard — ACCT-11 split out of Phase 11.2

### Decisions

Active program constraints live in PROJECT.md. v1.8 locks (design LR-00..LR-22): two-tier priority
`EventBus` CONTROL>BUSINESS (LR-11); single-writer engine-thread contract (LR-12); handler-owns storage
init (LR-13); `EngineContext` infra-only (LR-14); two registries execution-venue + data-provider (LR-17);
connectors memoized `(venue, account_id)` (LR-17/LR-20); `SqlBackend→SqlEngine`, migrations→root (LR-18);
`clOrdId→client_order_id` (LR-19); config at its owner's cardinality (LR-21); one `system_store` KV +
`VenueStore` + `StrategyRegistryStore` (LR-22). Ten backlog TODOs fold in as CF-1..CF-10 across
P1/P5/P6/P7/P8 (all live-only / backtest-dark).

- [Phase ?]: P1-01: SystemConfig.sql is a functools.cached_property (not a pydantic field) — built on first access only, keeping SqlSettings/Postgres off the import graph; extra flipped to forbid (D-05/D-06/D-09)
- [Phase ?]: P1-02: HaltReason(Enum) in core/enums/system.py — 4 minimal members (D-10), .value wire strings preserved for durable-record compat (T-02-01); baseline-residual free string retired at live_trading_system.py:810; halt(reason: str) signature migration deferred to P8 (D-11/CF-8)
- [Phase ?]: P1-03: CF-6 D-03a reconcile — folded §6d nuance (exchange-side layer real only where called = SimulatedExchange) into item 4 without regressing the post-V17-16 D-10 framing; CFG-06 closed (doc-only)
- [Phase ?]: P1-04: live-only supervisor/feed constants folded into pure-pydantic StreamSettings + FeedProviderSettings (config/stream.py); reconnect fields float/int not Decimal; P1 seam = default-constructed instance, shared StreamSupervisor deferred to P5 (CFG-03/D-08)
- [Phase ?]: P1-04: live_trading_system.py is 4-space not tabs (od-verified); _OKX_*/_PAPER_* retired, PAPER_PARITY_* anchor preserved byte-identical (Pitfall 4)
- [Phase 02]: D-09/D-10: event-bus substrate (EventBus Protocol + FifoEventBus + PriorityEventBus) landed in itrader/events_handler/bus.py, import-inert (Event TYPE_CHECKING-only), wired into nothing — Plan 02-01: pure substrate, oracle-dark
- [Phase 02]: Typed bus internal queues concretely (queue.Queue[Event] / PriorityQueue[tuple]) not [Any] to satisfy mypy --strict verification gate (byte-identical at runtime) — Rule 3 blocking fix during 02-01 Task 2
- [Phase 02]: D-02/CTX-02: OrderHandler + StrategiesHandler own storage init from keyword-only (environment=backtest, sql_engine=None), exposing the concrete on .storage/.signal_store for the plan-02-03 compose back-read; purely additive, backtest slice = same in-memory concretes, oracle byte-exact (Plan 02-02)
- [Phase ?]: 02-03: compose_engine folded to two-arg (ctx, spec) end-state; internal queue deleted, ctx.bus owns transport (D-01/CTX-01)
- [Phase 02]: 02-03: EngineContext = 4 loose fields (bus/config/environment/sql_engine); downstream only tightens types, never adds fields (D-05/BUS-04)
- [Phase 02]: 02-03: global_queue retyped to EventBus (name unchanged) across 5 handlers + SimulatedExchange + BacktestBarFeed.bind; no call-site changes (D-07/D-08)
- [Phase ?]: CTX-04: SqlBackend renamed to SqlEngine; module moved to storage/engine.py; no alias (D-02)
- [Phase ?]: D-01: backend/_backend vocabulary unified to sql_engine/_sql_engine across storage factories, PortfolioHandler, and Portfolio
- [Phase 03]: D-03: collapsed redundant signal_store surfaces; accessors read through engine.strategies_handler.signal_store, no @property added
- [Phase ?]: [Phase 04]: 04-01: migrations/ relocated to project root via git mv (D-10, 5 revision IDs preserved unchanged, single head d10_halt_records); alembic.ini script_location=migrations; SQL-01 wheel-exclusion samplable via tomllib assertion; oracle byte-exact + inertness green
- [Phase ?]: [Phase 04]: 04-02: three new live-only durable stores landed (SystemStore KV / VenueStore / StrategyRegistryStore), each a HaltRecordStore-template clone composing SqlEngine; natural NAME PKs (D-06, no idgen/surrogate); VenueStore recursive secret-denylist guard fires before the write (D-05, Pitfall 6); StrategyRegistryStore two-table registry+subscriptions with FK-join rehydrate + file-backed restart survival; oracle byte-exact + inertness green
- [Phase ?]: [Phase 04]: 04-03: 3 hand-authored Alembic revisions off d10_halt_records (system_store → venue_config[builds venue_store table, slug!=name] → strategy_registry[registry+FK'd subscriptions, child-first downgrade]); new single head strategy_registry; env.py target_metadata registers all 4 new tables (D-02, import-inert Table-only); SQL-02 gate = single-head + upgrade-head + create_all/migration parity; inertness _FORBIDDEN + register-vs-build extended; oracle byte-exact
- [Phase ?]: WR-02: SQLite FK enforcement lives on SqlEngine (dialect-guarded PRAGMA connect-hook), not a fixture — engine correctness semantics must be identical on every dialect the engine runs
- [Phase ?]: WR-03/D-14: 7 durable stores schema-pure (no runtime create_all); production Alembic-owned, tests provision via tests.support.schema.provision_schema; ephemeral results store keeps create_all
- [Phase ?]: [Phase 05]: 05-01 (VENUE-07/D-08/CF-4): one parameterized StreamSupervisor (connectors/stream_supervisor.py, 4-space, ccxt-free) owns the reconnect ladder + _reconnect_attempts/_streams_down; the 3 donor arms (okx_provider/venue/okx) HAS-A supervisor and delegate. Parameterized over transient/fatal tuples + reconnect_on_clean_return so each donor's behavior is preserved exactly; venue's reduced surface PRESERVED not normalized. ccxt+supervisor lazy-imported in __init__ so venue stays inert (connectors barrel eagerly pulls ccxt.pro). ~9 coupled test files retargeted to arm._supervisor
- [Phase ?]: [Phase 05]: 05-01 (CF-9/D-11/T-05-04): OkxExchange.validate_symbol fail-CLOSES (False) on a non-dict markets cache; reuses the single validate_symbol->delta.removed removal path. Seeded loaded markets in 4 submit fixtures + added cold-cache unit test. CF-3 additive LiveConnector docstrings (no signature change)
- [Phase ?]: 05-03: set_bar_sink NOT defaulted on BaseLiveDataProvider (fail-loud — a no-op default would silently drop bars); a bare base is intentionally not a conforming LiveDataProvider
- [Phase ?]: 05-03: OkxDataProvider left unedited — conforms to LiveDataProvider structurally; avoids conflict with 05-01 StreamSupervisor delegation
- [Phase 05]: VENUE-04/D-09: precision is an AbstractExchange.resolve_precision capability; precision_to_scale is a shared core/money util; LTS resolvers deleted
- [Phase ?]: 05-04: VenueBundle.lifecycle typed Any until 05-06 VenueLifecycle lands (mypy --strict forward-ref)
- [Phase ?]: 05-05: OKX/paper venue plugins triple-deferral-lazy (D-04); register != build proven by extended inertness gate + module-scope AST scans
- [Phase ?]: 05-05: register-vs-build assertion excludes ConnectorProvider (connectors barrel eagerly re-exports OkxConnector, pre-existing 05-04 decision); proves venue-plugin surface inertness instead
- [Phase ?]: 05-06 (VENUE-06/SC3/D-06): LiveTradingSystem.__init__ delegates venue assembly to assemble_venue; every if exchange==okx/elif==paper branch removed (grep=0); venue-string init/start guards became structural None-guards; start/stop delegate connector connect/disconnect to VenueLifecycle
- [Phase ?]: 05-06 (D-10): VenueLifecycle is a small class encoding the fixed connector start/stop order, None-guarding paper's absent connector (start no-ops when bundle.connector is None; stop prefers ConnectorProvider.close_all, falls back to connector.disconnect)
- [Phase ?]: 05-06: plugin/ConnectorProvider imports stay LAZY inside LTS.__init__ not module top — trading_system/__init__.py imports LiveTradingSystem, so a module-top okx_plugin/paper_plugin/ConnectorProvider import would pull them onto the backtest import graph (inertness _FORBIDDEN) and redden test_okx_inertness
- [Phase ?]: 05-06: VenueBundle.lifecycle retyped Any -> VenueLifecycle | None (05-04 forward-seam closed); TYPE_CHECKING forward-ref keeps the substrate import-inert
- [Phase ?]: [Phase 06]: 06-01 (RUN-04/D-01/D-02): wire_universe(engine)->Universe extracted as ONE intact TABS free function in trading_system/universe_wiring.py; backtest_runner delegates to it, keeps ping-grid+precompute post-step; ADDS strategies_handler.set_universe (inert by construction) PROVEN byte-exact 134/46189.87730727451 on determinism double-run; inertness green
- [Phase ?]: RUN-02: LiveRunner/WorkerSupervisor/ErrorPolicy authored as standalone import-inert 4-space modules; unwired here, build_live_system wires them in 06-05
- [Phase ?]: D-04 held: live_trading_system.py facade byte-untouched this plan; LiveRunner reaches facade side-effects via injected callbacks
- [Phase 06]: 06-03 (RUN-07/D-17): _LiveWarmupConsumer rehomed to price_handler/feed/cache_registration.py as frozen StrategyWarmupConsumer (ONE global ring); derive_warmup_depth(strategies) is the NAMED CF-10 depth boundary (global max(warmup) today, per-concerned-strategy later — body-only change); register_strategy_warmup(feed, strategies) is the reusable entry point for SessionInitializer (06-04). Named distinctly from derive() raw-history ladder (Landmine 4); import-inert, 4-space, mypy clean; old consumer stays in LTS until 06-04; oracle byte-exact 134/46189.87730727451
- [Phase ?]: 06-04/RUN-06: UniverseHandler ctor is (bus, universe, feed, config); timeframe+remove_policy read from a flat UniverseHandlerConfig value object; set_venue_metadata(exchange) collapses the two former OKX-guarded venue setters (zero OKX coupling); 4 read-model setters + set_freeze_gate retained (D-11)
- [Phase 06]: 06-05 (RUN-05/RUN-04-live/D-12): LiveRouteRegistrar (central declarative BUSINESS/live route table, list order = execution order, FILL appended, NO CONTROL route per D-23/LR-16) + SessionInitializer (composes wire_universe + register_strategy_warmup + first-class UniverseHandler + LiveRouteRegistrar); _initialize_live_session is a thin delegator; _LiveWarmupConsumer + inline route mutation removed; live GAINS the WR-03 assert; set_venue_metadata unconditional over resolved venue exchange (zero OKX coupling); interim Engine holder + 2 casts, 06-06 flips to build_live_system/compose_engine; oracle byte-exact 134/46189.87730727451, paper-parity + inertness green, mypy clean, 2125 passed
- [Phase ?]: 06-06: build_live_system(spec) is the live composition root (RUN-01/D-09); facade __init__ is pure injection; live wires PriorityEventBus (D-23); LiveRunner owns the drain loop; D-12 construction-time session-init flip deferred to 06-07 — RUN-03 lands structurally
- [Phase ?]: 06-07/TEST-01/D-18: relocated the whole replay harness to tests/support/replay_harness.py; production is replay-free (paper->OKX feed, D-21); paper EXECUTION venue untouched (D-20)
- [Phase ?]: 06-07/D-16: TestRunner is behavior-preserving (calls _initialize_live_session before its per-bar drive); the D-12 construction-time flip stays DEFERRED per 06-06
- [Phase ?]: 06.1-01 (SEAM-01/D-04): compose_engine spec-free; store/feed on EngineContext (D-01/D-02, LR-14 amended); bind+generate_bar_event lifted to base BarFeed ABC; precompute narrowed at backtest-only runner; oracle byte-exact 134/46189.87730727451 + inertness green
- [Phase ?]: 06.1-02 (SEAM-01/SEAM-02/D-05/D-10): build_live_system consumes compose_engine (hand-rolled 4-handler graph + commission closure deleted, FeeModelCommissionEstimator reused); credential-probe arm selects only environment('live'/'backtest')+shared SqlEngine so compose's handler-owned storage lands the identical durable path on both arms; LiveSystemComponents deleted, facade __init__ = pure injection over Engine+VenueLifecycle+separate SQL/halt handles (D-07/D-09); interim Engine reconstruction removed (reads self._engine); oracle byte-exact + inertness green, mypy clean, bodies untouched (D-08)
- [Phase 06.1]: 06.1-03 (SEAM-03/D-11): typed frozen VenueSpec (execution_venue/data_provider/account_id) + shared build_venue_spec builder replace the twice-written SimpleNamespace fake-spec; build_venue_spec is the SOLE home of the {okx,paper}->okx default-provider map, called by BOTH for_exchange and build_live_system (inline specs+maps at :274-283/:1605-1613 deleted, SimpleNamespace import dropped); feeds assemble_venue only, never compose_engine (spec-free since D-04); spec-equality unit test proves the two entry points cannot drift; oracle byte-exact 134/46189.87730727451 + inertness green, mypy clean
- [Phase ?]: D-12: trading_system barrel drops the live surface entirely (backtest-only); live consumers import from the live submodule directly
- [Phase ?]: D-13: pure imports (SessionInitializer/EngineContext/UniverseHandlerConfig) hoisted to live_trading_system module top; heavy ccxt.pro/SQL/venue imports stay lazy inside build_live_system
- [Phase 07]: OrderRiskRole is enum-only in core/enums/order.py; classify() defers to SafetyController (Plan 03) — D-16 — one-source-of-truth risk vocabulary shared by gate + throttle
- [Phase 07]: ConnectorFatalEvent.reason is a fixed-literal str, never a stringified exception/payload — V7 secret-scrub (T-07-01); enforced by grep-0 in control.py
- [Phase 07]: PreTradeThrottle computes D-10 notional off OrderEvent.price (limit for LIMIT, decision-mark estimate for MARKET/STOP) — no separate feed injection — The order layer already stamps the mark onto OrderEvent.price, so a feed dependency would add untested surface for no correctness gain
- [Phase ?]: P9-01: ITraderConfig frozen root replaces SystemConfig as the process config singleton; rng_seed moved to config.rng_seed (frozen base), oracle byte-exact
- [Phase ?]: P9-01: SystemConfig kept as narrowed legacy aggregator (perf/monitoring+lifecycle stripped) to keep existing config tests green; SystemSettings/UniverseConfig demoted sub-models added
- [Phase 9]: ConfigRouter: the config structure IS the allowlist (D-11/D-12) — routable keys resolved by live model_fields introspection, so the allowlist can never drift from the model
- [Phase 9]: system idle/timeout knobs AND universe poll_cadence/remove_policy both route under the single 'system' scope (scopes locked to 4, D-21); owning sub-model resolved by introspection
- [Phase ?]: P9-03: order-scope config persists to a dedicated order_config table + portfolio-scope config to a nullable config_json column on portfolio_account_state (D-25); each module owns its config, never SystemStore
- [Phase ?]: P9-03: add_event admits CONFIG_UPDATE as the third default-deny external type with synchronous ingress 400-validation; restart-layering reapplies persisted overrides per-scope from each OWN store, degrade-clean when the (Plan-04) config migration is pending
- [Phase ?]: P9-04: system_stats append-only table/store (engine-operational counters only, NO entity duplication D-17) + state.status/halt_reason/last_started_at written at their event sources into SystemStore (D-19); read-model is lock-free domain-store + state.* + system_stats reads (RTCFG-06)
- [Phase ?]: P9-04: migration-owner finalized the phase chain single-head strategy_registry -> module_config (order_config table + portfolio_account_state.config_json column, NO portfolio_config table) -> system_stats; the hardcoded create_all/upgrade-head parity gate extended by hand (A3 dynamic-enumeration assumption was false)

### Pending Todos

Ten v1.7-carryforward TODOs are **folded into v1.8** as CF-1..CF-10 (set `resolves_phase` at milestone
init; migrate to `todos/completed/` when the owning phase verifies): CF-1→P8 (aggregate breaker, HIGH,
the one with teeth), CF-2/7→P7, CF-3/4/9→P5, CF-5→P8, CF-6/8→P1 (CF-8 also P7), CF-10→P6. Deliberately
**not** folded (kept separate): `livebarfeed-depandas-time-model-datetime`, `mutable-instrument-refactor`,
`margin-equity-double-counts-notional-wr01` (owner-gated), `unify-backtest-direct-bar-generation`
(oracle-risky). `pair-strategy-live-reconfiguration` is folded into P10 (STRAT-03).

- **`unify-config-store-save-interface` (deferred, not folded — owner-requested 2026-07-16):** make
  `ConfigRouter` persist through ONE uniform `store.save_config(...)` seam for all four scopes instead of
  today's split (`order`/`portfolio` → `save_config(config, at)`; `system`/`venue` → `upsert(...)`). Finding:
  the four are TWO real shapes, not one — order/portfolio are bound single-record config stores (already
  `save_config(config, at)`+`load_config()`); `system_store` is a GENERIC namespaced KV store used beyond
  config (lifecycle/universe keys) and `venue_store` is multi-key (`venue_name`) + carries a non-config
  `enabled` column. A blanket rename to `save_config` is therefore WRONG (would misrepresent system's KV
  store + drop venue's key/`enabled`). Two viable paths: (A-light) a `ConfigStore` Protocol
  (`save_config`/`load_config`) that order+portfolio already satisfy, system/venue left native; (B-full,
  recommended) a thin per-scope config-adapter so the router always calls `save_config(...)` and delegates
  to the native `upsert` underneath — B also lifts venue's key/`enabled` handling OUT of `ConfigRouter`,
  dissolving the router's cross-store feature-envy smell. Real design work, not a rename.

### Blockers/Concerns

- **P6 `UniverseWiring` = the highest oracle-risk seam** (analogous to v1.2 MOD-01): move as one intact
  unit incl. the WR-03 desync assert; byte-exact oracle + determinism double-run as a per-PLAN gate.

- **Inertness regression** is the recurring failure mode: no eager import via a barrel re-export, no
  non-lazy `SqlSettings`, no registry importing concretions at registration. `test_okx_inertness.py` is
  the P5 acceptance gate (extended register-vs-build for P1/P2/P4/P5).

- **CF-1 must ACTUALLY TRIP** (P8 hard acceptance criterion): a breaker "green with zero settlements" or
  one reintroducing the WR-06 error→error livelock is a false-green failure.

- **CF-2 threading contract** (P7): `backfill_on_resume` must be loop-native (connector loop), never a
  second concurrent engine-thread ring writer — assert no engine-thread path reaches it.

- **Alembic chain divergence** (P4): relocation + 3-store chain must stay single-head with a
  create_all/migration parity test (the merged storage-schema phase owns the full-chain gate).

- **Indentation hazard:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`,
  `itrader/storage/`, events package use 4 spaces. Match the sibling file — never normalize.

- **Zero new dependency / no poetry change** anywhere in P1–P13 (adding a lib regresses inertness).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not
  silently folded into a running phase.

- ✓ RESOLVED (fix `f86fe5d2`, orchestrator post-merge gate): GATE-01 quarantine regression from 01-01 — `config/system.py` module-level `SqlSettings` import pulled sqlalchemy onto the backtest graph. Fixed by moving the import under `TYPE_CHECKING` + a lazy in-body import; `test_import_quarantine.py` + `test_okx_inertness.py` + byte-exact oracle all green. See phase deferred-items.md.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260713-cvb | Fix WR-02: ConnectorProvider.close_all isolates each disconnect + always clears memo (bound logger) | 2026-07-13 | 5045db99 | [260713-cvb-fix-connector-close-all-teardown](./quick/260713-cvb-fix-connector-close-all-teardown/) |
| 260713-dbw | Consolidate live-provider surface to one symbol: drop BaseLiveDataProvider, keep the LiveDataProvider Protocol, inline the 7 no-op seams into ReplayDataProvider | 2026-07-13 | d3dec871 | [260713-dbw-consolidate-the-two-live-provider-symbol](./quick/260713-dbw-consolidate-the-two-live-provider-symbol/) |
| 260713-ncq | Centralize live stream/feed/DB settings under SystemConfig — inject StreamSettings/FeedProviderSettings (kill 10 inline default-constructions + _STREAM_SETTINGS global); DB gate via lazy SqlSettings() probe instead of os.getenv | 2026-07-13 | 33390772 | [260713-ncq-centralize-live-stream-feed-db-settings-](./quick/260713-ncq-centralize-live-stream-feed-db-settings-/) |
| 260713-wr1 | Delete vacuous WR-01 subscription/membership guard in session_initializer.py (unreachable dead code — membership is the sole subscription source since 06-02/D-05); replace with a TODO for the real future-feature guard condition | 2026-07-13 | dc1f5cb8 | (fast — no dir) |
| 260713-phm | Fix Phase 06 review WR-02 (typed StateError guard above start() try-block so an un-wired LiveTradingSystem fails loudly, not masked as generic ERROR) + IN-02 (LiveRunner.stop() warns when the drain thread outlives the join timeout) | 2026-07-13 | a9f3b5ac | [260713-phm-fix-phase-06-review-findings-wr-02-typed](./quick/260713-phm-fix-phase-06-review-findings-wr-02-typed/) |
| 260714-v6n | Fix Phase 07 review IN-01: self-guard PreTradeThrottle.allow() with an ORDER-only top-gate (Option B) + remove now-dead None-guard in _exceeds_notional (Option A) — throttle no longer relies on live_runner's call-site type gate for safety | 2026-07-14 | baa125f8 | [260714-v6n-fix-phase-07-review-in-01-make-pretradet](./quick/260714-v6n-fix-phase-07-review-in-01-make-pretradet/) |
| 260716-k7j | Strip legacy config classes: delete Settings + SystemConfig; move timezone to ITraderConfig frozen base ("Europe/Paris"); re-home log_level/disable_logs via new slim RuntimeSettings under config.logging (ITRADER_* env-parsing preserved); drop the runtime field. Oracle byte-exact (134 / 46189.87730727451), inertness + mypy clean | 2026-07-16 | 6e8e01e9 | [260716-k7j-strip-out-legacy-config-classes-delete-s](./quick/260716-k7j-strip-out-legacy-config-classes-delete-s/) |
| 260716-law | Config-package cleanup (4 refactors): move deep_merge→outils/dict_merge.py::recursive_merge; exchange presets→ExchangeConfig.default()/.high_fee() classmethods (drop realistic/low_latency + string registry); delete redundant config/models.py barrel; rename RuntimeSettings→LogConfig (runtime.py→config/log.py, field stays config.logging). Oracle byte-exact (134/46189.87730727451), 2307 passed, mypy clean, 7 zero-grep gates | 2026-07-16 | 116ceb05 | [260716-law-config-package-cleanup-move-deep-merge-t](./quick/260716-law-config-package-cleanup-move-deep-merge-t/) |
| 260716-mov | Move UniverseConfig into its own itrader/config/universe.py (config/ one-domain-per-file convention); system.py keeps only Environment/LogLevel/SystemSettings; barrel re-exports unchanged. Byte-identical behavior; 2307 passed, oracle byte-exact, inertness + mypy clean | 2026-07-16 | d5a9deac | [260716-mov-move-universeconfig-into-its-own-config-](./quick/260716-mov-move-universeconfig-into-its-own-config-/) |
| 260716-fast | Sync CLAUDE.md "Configuration system" section (+ Import side effects, config Layers, tech-stack/config prose) to ITraderConfig reality — drop SystemConfig/Settings/PerformanceSettings/MonitoringSettings, document frozen base + mutable sub-models + LogConfig + lazy sql, outils.recursive_merge, ExchangeConfig classmethods, config/models.py removal | 2026-07-16 | 03fdf3fd | (fast — no dir) |
| 260716-cfg | Unify dry-validate-on-a-copy pattern in config_router.py: _dry_validate_setattr→_dry_validate_copy returns the validated candidate copy; system/order scopes share it (order drops its inline model_copy+try/except); portfolio merge-validate untouched. Behavior-preserving; 30 tests pass, mypy clean | 2026-07-16 | 4e40f379 | (fast — no dir) |
| 260718-di7 | Fix Phase 10 code-review findings: CR-01 (rehydrate loads full roster via read_all(), disabled rows come back present-but-dark, honoring enabled as is_active — resolves IN-01) + docstring truth on remove/disable restart guarantee; WR-01 (floor derive_warmup_depth at NEWEST_BAR_ONLY, never 0); WR-02/IN-02 docstrings (live-pair BarsLoaded warmup, add-factory config_json payload). 322 passed/9 skipped (env), mypy clean | 2026-07-18 | 992b31a5 | [260718-di7-fix-phase-10-code-review-findings-cr-01-](./quick/260718-di7-fix-phase-10-code-review-findings-cr-01-/) |
| 260718-e36 | Fix Phase 10 re-review WR-01: quarantine an unwarmable (finer-than-base timeframe) stored row at rehydrate per D-19 (skip+alert+continue, row not mutated) instead of raising UnwarmableTimeframeError out of register_strategy_warmup and crashing the whole live boot; + skip is_active==False strategies in the warmup ladder (derive_warmup_depth/register_strategy_warmup), preserving the NEWEST_BAR_ONLY floor. 324 passed/5 skipped (env), mypy clean, inertness preserved | 2026-07-18 | 40e73430 | [260718-e36-fix-phase-10-re-review-wr-01-quarantine-](./quick/260718-e36-fix-phase-10-re-review-wr-01-quarantine-/) |
| 260718-evz | Revert the e36 warmup deactivated-skip (2nd re-review found it net-negative: it broke the pre-provisioning that makes disabled→enable safe, since the `enable` verb has no capacity guard and the ring is a fixed-maxlen deque). derive_warmup_depth again sizes the ring from ALL strategies (NEWEST_BAR_ONLY floor kept); is_active dropped from _SupportsWarmup. Kept Option A's rehydrate quarantine ungated on enabled + documented the WR-02 uniform-quarantine rationale (unwarmable strategy can't manage positions regardless → present-but-dark is illusory; quarantine is loud + non-destructive + recoverable + consistent with the _QUARANTINABLE family). 322 passed/5 skipped (env), mypy clean, inertness preserved | 2026-07-18 | fe15923a | [260718-evz-revert-phase-10-warmup-deactivated-skip-](./quick/260718-evz-revert-phase-10-warmup-deactivated-skip-/) |
| 260720-km2 | Fix Phase 10.1 review CR-01: close the `_add_strategy_verb` never-raise hole with a two-tier ZONE-1 guard (Option B, not the todo's tuple fix — `init()` is arbitrary user code so the escaping exception set is unbounded). Tier 1 appends `ValueError` (validate()/_apply_params raise bare) → WARNING; tier 2 `except Exception` → ERROR + `exc_info=True`. Zone 2 (register/persist/emit) left raising — D-19 fail-loud intact. Closes the D-10 halt-latch path where a routine bad `add` payload reached `ErrorPolicy.record_failure` → tripwire → `halt()`. Intended behaviour change (raise → logged no-op), owner-approved. 2290 unit + 204 integration passed, mypy clean, oracle byte-exact (134 / 46189.87730727451) | 2026-07-20 | b2479e0d | [260720-km2-fix-cr-01-add-verb-never-raise-zone-guar](./quick/260720-km2-fix-cr-01-add-verb-never-raise-zone-guar/) |
| 260720-ljn | Collapse the four divergent strategy-rejection catch tuples onto one `StrategyAdmissionError(ITraderError, ValueError)` ancestor — the CR-01 drift surface itself. Reparents UnknownParamError/MissingParamError (keeping ValidationError structured fields) + UnknownStrategyTypeError/StrategyConfigError (keeping plain-message construction); `_QUARANTINABLE` 5→2 members; all three manager.py sites → `except (StrategyAdmissionError, ValueError)`. D-19 separability (RehydrateInfrastructureError roots at RuntimeError, NOT the base) is now load-bearing and pinned by a falsification-verified regression test. km2's zone-1/zone-2 two-tier guard byte-identical apart from tier-1's tuple members. 2302 unit + 204 integration passed, mypy clean (273 files, no ignore needed for the two-hierarchy MI), oracle byte-exact (134 / 46189.87730727451) | 2026-07-20 | e124a446 | [260720-ljn-strategyadmissionerror-base-collapse-exc](./quick/260720-ljn-strategyadmissionerror-base-collapse-exc/) |
| 260720-owe | Close Phase 10.1 review WR-04 (last open finding) — Option B1: narrow `Strategy.subscribed_portfolios` from `list[PortfolioId \| int]` to `list[PortfolioId]` and delete the vestigial int arm. Both secondary-parse fallbacks removed outright (`rehydrate._resolve_portfolio_id`, `manager._portfolio_id_from`) — each already owned the correct loud-failure arm (StrategyConfigError raise / None no-op), so a rejecting-parser fallback would be dead code reaching the same outcome one branch later; failure semantics byte-identical, only the accepted-input set narrows. `subscribe/unsubscribe_portfolio` signatures narrowed too (forced, not discretionary — mypy errors otherwise). Restored the real `Optional[PortfolioReadModel]` annotation on manager.py's constructor param + attribute (module-top import per the file's own DECOMP-02 convention; core/ pulls no SQL so GATE-01 inertness is untouched) — that `Optional[Any]` was the sole reason the `get_position(PortfolioId, str)` mismatch stayed invisible. Removed the now-unnecessary `cast(PortfolioId, ...)` + obsolete FL-02 comment in strategies_handler. Migrated 14 bare-int portfolio-id test fixtures across 6 files to real PortfolioId values first (3 were hard round-trip breakages via rehydrate, not cosmetic). Rewrote four dead String-column justifications (store docstring + inline comment, rehydrate docstring, migration comment) onto the surviving serialization rationale — `to_dict` writes `str(pid)`, rehydrate parses it back — NOT the int arm. Narrowing surfaced **zero** mypy errors (the arm was purely vestigial); enforcement falsified by deliberately breaking a `get_position` call and confirming mypy caught it. No type-ignores, no re-widening. B2 (String→Uuid column) deliberately out of scope — todo filed. 2299 unit + 204 integration passed / 2 pre-existing OKX-cred skips, mypy clean (273 files), oracle byte-exact (134 / 46189.87730727451). Verified 7/7. | 2026-07-20 | c29ea3c2 | [260720-owe-wr-04-b1-remove-vestigial-int-arm-from-s](./quick/260720-owe-wr-04-b1-remove-vestigial-int-arm-from-s/) |
| 260720-s6b | Close the D-10 reconfigure escape that 260720-ra5 opened, by applying the ZONE MODEL uniformly. **The architectural point:** `init()` is arbitrary operator-supplied code, so the exception set escaping it is UNBOUNDED — the old `(StrategyAdmissionError, ValueError)` tuple caught exactly ONE arbitrary member of that infinite set while TypeError/KeyError/AttributeError always escaped. That was TYPE-shaped protection against an UNBOUNDED hazard: it looked like coverage and was a coincidence. ra5 did not create the hole, it removed the accident concealing it. The km2/CR-01 principle (arbitrary user code needs a ZONE guard, not a TYPE tuple) is a property of what `init()` IS, hence VERB-INDEPENDENT — applied at the add site only because CR-01 happened to point there. **Fix, shaped by zone — deliberately NOT unified:** TRIAL site (pre-persist, throwaway, zone 1) gets a km2-style tier-2 `except Exception` → loud no-op refusal logging the error KIND not payload values (P8 precedent), live instance AND DB untouched. APPLY site (post-persist, zone 2) routes arbitrary exceptions into the EXISTING `_emit_reconfigure_apply_failure` CRITICAL path with semantics preserved exactly — no rollback, DB holds the NEW config, restart heals. A blanket `except Exception` across both would have been WRONG (would swallow zone-2 faults D-19 wants loud). `registry_store.upsert` verified structurally OUTSIDE the widened APPLY try, pinned by a `_RaisingStore` test so a future edit can't quietly move it in. **Coverage that never existed:** TypeError/KeyError from `init()` now caught at BOTH sites — without these the fix would merely restore the old ValueError-only coincidence. Planner corrected the brief twice: `build_strategy` IS `decode_strategy_config` + `cls(**params)`, so "scope to the construction call only" would have made the reconfigure guard NARROWER than the add guard it mirrors; and the not-a-shadow assertion is vacuous at APPLY (both classes route to one handler) so it bites at TRIAL. RED was real and verified non-fake (worktree mypy 251 files ≠ main's 273, proving PYTHONPATH targeted the executor's own tree): 6 failed with the exception propagating out of `on_strategy_command` through `base.py` `_run_init`. Policy recorded in comments (every D-10 verb invoking `_run_init` on operator input carries a zone guard, shape follows zone), cited by SYMBOL; shared-admission-seam refactor filed as a backlog todo (candidate after Phase 11) — that duplication is the root cause behind ljn, CR-01, WR2-02 AND this. mypy clean (273 files), 2324 unit (2316 + exactly 8 new, zero deletions/skips/xfails), 13 integration, oracle byte-exact. base.py + rehydrate.py ZERO diff. Verifier passed 7/7 via an INDEPENDENT A/B probe driving real `on_strategy_command` and draining the queue to confirm the CRITICAL ErrorEvent — not by re-reading the shipped tests. | 2026-07-20 | 40d9f214 | [260720-s6b-close-the-d-10-reconfigure-escape-from-r](./quick/260720-s6b-close-the-d-10-reconfigure-escape-from-r/) |
| 260720-ra5 | Close 10.1 re-review WR2-02 + IN2-02 by removing their SHARED ROOT CAUSE rather than patching each site. New `StrategyValidationError(StrategyAdmissionError)`; both construction spans in `base.py` (`__init__` :209-211 and `reconfigure` :747-748 — `_apply_params` + `validate()` are adjacent at exactly those two sites, verified) wrapped so a bare `ValueError` from validation surfaces typed. No-double-wrap enforced STRUCTURALLY by clause order (`except StrategyAdmissionError: raise` BEFORE `except ValueError as exc: raise StrategyValidationError(str(exc)) from exc`), so `UnknownParamError`/`MissingParamError` propagate unchanged with their ValidationError structured fields intact. Consequences: the three admission sites (`:472/:885/:942` — the review's `:397/:809/:866` had drifted) drop the subsumed bare `ValueError` (IN2-02), and `_QUARANTINABLE` becomes correct AS WRITTEN with NO widening (WR2-02) — a `validate()` failure on one persisted row now quarantines that row instead of killing the whole engine boot. Causal chain traced end-to-end by both checker and verifier, not assumed. `str(exc)` preserved verbatim so `test_strategy.py`'s `pytest.raises(ValueError, match="short_window must be < long_window")` passes UNMODIFIED (0-line diff — the highest-risk silent break). `_run_init`/`init()` deliberately OUTSIDE both spans. **GAP — NOW CLOSED by 260720-s6b:** dropping the bare `ValueError` at the two RECONFIGURE sites removed the coverage it was incidentally providing for a bare `ValueError` from `init()`, which runs outside the wrap. Verifier proved this by A/B probe against pre-task `0f4a00a8` (caught before, escapes now). NOT merely "pre-existing, slightly widened" — it is a behavioral regression, though the ARCHITECTURAL hole predates it: the old tuple caught 1 arbitrary member of the unbounded set `init()` can raise (TypeError/KeyError always escaped), so it was type-shaped protection against an unbounded hazard. Add is unaffected (retains its km2 tier-2 `except Exception`). mypy clean (273 files), 2316 unit + 13 integration passed, oracle byte-exact (134 / 46189.87730727451). Plan-checker 7/7; verifier 6/7. | 2026-07-20 | cdd46971 | [260720-ra5-close-10-1-re-review-wr2-02-in2-02-typed](./quick/260720-ra5-close-10-1-re-review-wr2-02-in2-02-typed/) |
| 260720-qfs | Close 10.1 re-review WR2-01 — the `add` verb silently discarded a MALFORMED `portfolio_id`, registering AND persisting a strategy with zero subscription rows; `_emit_intent` then iterated an empty `subscribed_portfolios` forever, so no SignalEvent was ever enqueued and no order ever placed (the "healthy-looking engine that trades nothing" D-19 rates as worse than failing loudly). The `owe` int-arm removal widened the blast radius: `{"portfolio_id": "7"}` used to subscribe and now landed in the silent arm. The identical payload sent as `subscribe_portfolio` DID warn, so the diagnosis depended on which verb the operator happened to use. **Fix (owner-decided):** malformed REJECTS the whole add — warn + return, no construct/register/persist — matching `_add_strategy_verb`'s established SHORT-01 rejection idiom rather than inventing a policy. ABSENT stays a legal no-op (D-09). Detection via a new `_portfolio_id_supplied` presence probe beside `_portfolio_id_from` (chosen over a three-state enum: smaller diff, leaves `_portfolio_id_from` and both light verbs byte-unchanged). Gate sited AFTER the D-02 duplicate check and BEFORE blob construction/`build_strategy`, so it precedes `_managed.add_strategy` + `_persist_strategy` and never unwinds a completed registration; it is a pure dict read (cannot raise, D-10 intact) and sits OUTSIDE both tiers of the km2/CR-01 zone guard, which has zero diff hunks. Duplicate parse at the old subscribe site deleted, now reusing the gate's handle. **Judgment call, pinned by test:** explicit `{"portfolio_id": null}` counts as ABSENT not malformed — a Pydantic `portfolio_id: str \| None = None` model serializes the unsubscribed case as null on every add, so a bare key-presence probe would reject the most likely legal payload. TDD: malformed-reject test written FAILING FIRST, confirmed failing for the right reason (`assert ['malformed_pid'] == []`, stderr `New strategy added: malformed_pid`). Warning assertions use the file's existing `_LogSpy` injection — the test module's docstring BANS caplog, which the original brief had wrong. 152 test insertions, ZERO deletions (no assertion weakened). mypy clean (273 files), 367 unit passed, oracle byte-exact (134 / 46189.87730727451). Plan-checker passed 6/6 high-value checks; verifier passed 5/5 against real code. | 2026-07-20 | cf442de3 | [260720-qfs-close-10-1-re-review-wr2-01-reject-the-a](./quick/260720-qfs-close-10-1-re-review-wr2-01-reject-the-a/) |
| 260720-q6r | Clear the 10.1 re-review (`10.1-REVIEW-2.md`) documentation/cleanup tier — zero behavior change, zero test edits. **WR2-03**: `rehydrate.py`'s F-1 warmability-gate citation pointed at `strategies_handler.py:770/:1005`, but Wave 3 moved both gates to `lifecycle/manager.py` and the file is only 800 lines (`:1005` was past EOF) — re-cited BY SYMBOL (`StrategyLifecycleManager._add_strategy_verb` / `._reconfigure_warmability_check`), matching the WR-05 remedy. **IN2-01**: deleted the dead `from itrader.core.ids import PortfolioId` in `strategies_handler.py` (owe removed its only use; mypy doesn't flag unused imports and there's no linter, so nothing else would ever catch it). **IN2-03**: IN-04's read-through `_universe` property had re-created the exact cross-object private reach IN-01 removed — added a public `universe` property on `StrategyLifecycleManager` (mirroring `ManagedStrategies.pending_removals`) and forwarded to it; the handler-side name stays `_universe` because `test_strategies_live_membership.py:170,173` asserts on it (the review's "no test touches either name" claim was wrong — caught at planning). **IN2-04**: three drifted citations corrected (`base.py:192→194` strategy_id, `:193→195` is_active, and `has_pending`'s "get_universe above" → "below"). Executor re-located every line by content rather than trusting the plan — the `is_active` citation drifted DOWN (359→362), opposite the plan's prediction, because Task 2 was net +3 in that file. mypy clean (273 files), 358 unit + 13 integration passed, oracle byte-exact. | 2026-07-20 | 3316a16c | [260720-q6r-clear-the-10-1-re-review-documentation-c](./quick/260720-q6r-clear-the-10-1-re-review-documentation-c/) |
| 260718-fxm | Reorganize the events_handler/events/ package to a one-class-per-domain layout (pure relocation, zero behavior change): new portfolio.py/screener.py/strategy.py/feed.py; market.py trimmed to TimeEvent+BarEvent; UniverseUpdateEvent moved market→universe; OrderAckEvent merged into order.py; ack.py deleted; barrel re-pointed with an unchanged public name set (blast-radius shield); 6 direct-submodule importers repointed; STRATEGY_COMMAND enum comment + CLAUDE.md events-split line synced. 2464 passed/75 skipped (env), mypy --strict clean, oracle byte-exact (134 / 46189.87730727451) | 2026-07-18 | 6e3f6f4c | [260718-fxm-reorganize-events-package-by-domain-file](./quick/260718-fxm-reorganize-events-package-by-domain-file/) |
| 260721-b68 | Correct factual drift in CLAUDE.md surfaced by the 2026-07-21 codebase remap (`506f20a9`) — docs-only, 12 insertions / 12 deletions, CLAUDE.md sole file. **8 briefed corrections** (each pre-verified against live code by the orchestrator, not taken from mapper prose): event base is `msgspec.Struct(frozen=True, kw_only=True, gc=False)` at `events_handler/events/base.py:21`, NOT a frozen dataclass; `type` pinned via `type: ClassVar[EventType]`, not `field(default=..., init=False)`; the routes table is PUBLIC `EventHandler.routes` not `_routes` (4 sites; `full_event_handler.py:87`); `SqlBackend`/`backend.py` → `SqlEngine`/`itrader/storage/engine.py` + the 4 newer stores (strategy_registry/system_stats/system/venue); Alembic chain relocated `itrader/storage/migrations/` → repo-root `migrations/` (`alembic.ini::script_location`); and 3 dead-module reference sites for the removed `order_handler/storage/postgresql_storage.py` (live storage is `CachedSqlOrderStorage` wrapping `SqlOrderStorage`). **+2 planner-added** (derived from the same verified facts): Pattern-Overview `slots=True` parenthetical, Data-Flow postgresql storage arm. **+2 executor-found** blocking issues fixed: L82's historical note contained the dead filename its own gate demanded be absent (mutually exclusive), and L445 needed all three real modules not a single swap. Executor declined to game two bad gates — refused to pad prose to satisfy an unsatisfiable `self.routes >= 3` count (the qualified `EventHandler.routes` form splits it 2+2; the substantive `_routes == 0` requirement holds), and reported the plan's `<!-- GSD:` baseline as wrong (14 at HEAD, not 12; integrity preserved 14→14). Suite deliberately not run — no importable code changed, so oracle/inertness gates are structurally unreachable. **Known exposure:** corrections 4–8 + both planner-added ones sit inside GSD-managed blocks regenerated from `.planning/codebase/{STACK,CONVENTIONS,ARCHITECTURE}.md`, which still carry the same drift — next `/gsd-map-codebase` will overwrite them stale. Corrections 1–3 are in the hand-written `## Architecture` section and are not at risk. | 2026-07-21 | e10ee1ef | [260721-b68-update-claude-md-to-correct-factual-drif](./quick/260721-b68-update-claude-md-to-correct-factual-drif/) |
| 260721-cdx | Fix residual factual drift in .planning/codebase/{ARCHITECTURE,STRUCTURE,CONVENTIONS}.md at its source so the next /gsd-map-codebase does not regenerate CLAUDE.md's managed blocks stale (follow-up to 260721-b68): _routes -> public routes (2), postgresql_storage.py -> sql_storage.py/cached_sql_storage.py (3), SqlBackend -> SqlEngine (2), events are msgspec.Struct with type: ClassVar[EventType] not frozen dataclasses (1). CONVENTIONS.md edited on 2 lines only; Pinned Decisions block verified untouched via diff. Gates: zero postgresql_storage/SqlBackend/_routes/slots=True in all three files; CLAUDE.md still clean. | 2026-07-21 | f475d170 | (fast — no dir) |
| 260722-g6w | Close the two Phase 11 code-review BLOCKERS that need no product decision, as two atomic commits. **CR-01 (cross-venue account conflation)** — the live composition root derived its account set and attached venue accounts by bare `account_id` STRING, discarding the venue half of the `(venue_name, account_id)` pair the rest of the phase pins identity on (the `venue_accounts` composite PK, the `portfolios` FK, `ExecutionHandler.exchanges`, `ConnectorProvider._memo`). A durable portfolio on `binance/main` was handed the **OKX** `VenueAccount` on an okx boot — so `ReconciliationCoordinator` snapshotted one venue's account against another venue's positions and `VenueReconciler` could emit reconciling fills into the wrong portfolio. Fix is the venue FILTER, not a re-key: `_account_ids_for_spec` + `_attach_venue_accounts` take a required keyword-only `venue_name` and skip portfolios whose venue isn't the booted one, venue resolved as `venue_name or exchange` so legacy `add_portfolio(name,'okx',cash)` portfolios (venue_name=None) are NOT stripped. The lifecycle map was deliberately NOT re-keyed to a pair — `assemble_venues` keys by `spec.account_id or 'default'` (`assemble.py:178`) and every spec in one call shares `exchange`, so the map is single-venue BY CONSTRUCTION; re-keying would ripple into 5 call sites for zero behavioural gain. Existing fail-loud `ValidationError` for a same-venue unassembled account preserved (guard ORDER is load-bearing: venue guard precedes the lookup). 8 existing test call sites updated. **CR-05 (per-account credential bleed)** — `OkxSettings(**resolved)` is a `pydantic_settings.BaseSettings`, so every field a partial per-account prefix didn't supply was still env-completed via `validation_alias`: a prefix supplying only `OKX_ACCT_B_API_KEY` authenticated with account B's key + the **ambient global** secret+passphrase, silently, reintroducing at FIELD granularity the fallback T-11-18 forbids at REFERENCE granularity (and D-04's UID guard can't catch it — the ambient secret is a real account whose UID is stable, so trust-on-first-use records the wrong one). Fix gates `OkxSettings`' REQUIRED field set (derived from class-level `model_fields`, = exactly the auth triple; `sandbox`/`region` carry defaults) before construction and raises `CredentialResolutionError` naming missing FIELD NAMES only. Env source deliberately NOT suppressed — init kwargs already outrank it, and suppression would strip `sandbox`/`region` and silently flip a configured EEA account to global+sandbox (OKX 50119). Legacy `secret_ref is None` ambient path byte-identical. **RED proof independently reproduced by the orchestrator**, not taken on the executor's word: pre-fix derivation returned `['main']` for a binance portfolio on an okx boot (post-fix `[None]`, while same-venue AND legacy-venue portfolios stay included), and the CR-05 test failed `DID NOT RAISE CredentialResolutionError` with a probe showing the built connector carrying the ambient secret. Gates: 2819 passed / 6 skipped (pre-existing OKX-credential-gated live suites), oracle byte-exact (134 / 46189.87730727451), inertness green, mypy clean (281 files), exactly 5 files touched. **Deliberately left open** (need product decisions): CR-02 (is account_id mandatory in live), CR-03 (post-boot attach), CR-04 (D-09 config migration no-op), and every WR-* — notably WR-03, whose `or DEFAULT_ACCOUNT_ID` registration/raw-read asymmetry touches the same code and is byte-identical to before. | 2026-07-22 | 47a0e185 | [260722-g6w-fix-code-review-blockers-cr-01-cross-ven](./quick/260722-g6w-fix-code-review-blockers-cr-01-cross-ven/) |

| 260722-hpz | Close Phase 11 code-review **WR-08** — the last review finding not folded into Phase 11.1. `LiveTradingSystem.start()` starts EVERY venue lifecycle but `stop()` read `next(iter(lifecycles.values()), None)` and stopped only the primary, justified by "close_all() … the memo is shared across accounts". That justification covers only ONE of `VenueLifecycle.stop()`'s two branches: the `self._connectors is not None` arm drives `ConnectorProvider.close_all()` (shared memo, every account), but its documented `elif self._bundle.connector is not None: disconnect()` fallback exists precisely for lifecycles built WITHOUT a shared provider and covers only THAT bundle — so in that configuration every non-primary connector leaked a dangling authenticated venue socket, and a `ResourceWarning` is a HARD failure under `filterwarnings=["error"]`. Fix: snapshot `_venue_lifecycles.items()` into a list BEFORE the `try` (keeps the defensive `getattr` for a partially-constructed facade, keeps the map available to `finally` on every return path, and avoids dict-mutation-during-iteration), then loop in the `finally`. Safe because `close_all()` clears its memo inside a `finally` (`connectors/provider.py:82-91`) — **idempotency independently verified by the orchestrator**, since it is the load-bearing premise — so extra calls iterate an empty memo. **Guard placement (decision):** the `try/except` sits at the facade call site, per iteration, NOT inside `VenueLifecycle.stop()` — that method must keep raising for its own single-lifecycle callers and its unit contract; isolation is a property of the fan-out, and only the call site knows there are siblings left to stop and a SQL-spine dispose still to run. Swallowing here also stops a teardown failure from masking an exception already propagating out of the `try` body. The old `if lifecycle is not None` guard is gone because an empty-map loop is self-guarding. Error log now names the failing account. **RED independently reproduced by the orchestrator** at the pre-fix commit: exactly 3 failed / 99 passed, all three showing `assert ['acct-a'] == ['acct-a', 'acct-b', 'acct-c']`. The 4th test (partially-constructed facade) passes both before and after and is labelled a preservation guard so its green is not misread as evidence. Gates: 2823 passed / 6 skipped (pre-existing OKX-credential-gated opt-ins), oracle byte-exact (134 / 46189.87730727451), inertness green, mypy clean (281 files), exactly 2 files touched. Executor noted two out-of-scope observations for Phase 11.1: `_streaming_lifecycles()` has no teardown counterpart in `stop()`, and `VenueLifecycle.stop()`'s shared-provider branch has cross-account side effects (the first `close_all()` disconnects every account), which matters if 11.1 ever needs to stop one account without stopping the run. | 2026-07-22 | 59eb44e3 | [260722-hpz-fix-code-review-wr-08-stop-tears-down-ev](./quick/260722-hpz-fix-code-review-wr-08-stop-tears-down-ev/) |
| 260723-dc4 | Close the three no-decision-needed WARNINGs from the Phase 11.1 code review as one hygiene batch, three atomic commits, behaviour-preserving. **WR-02** — `DEFAULT_ACCOUNT_ID` had five homes behind a justification that was factually false: `bundles.py`, `assemble.py` and `venue_uid_guard.py` each re-declared a private `_DEFAULT_ACCOUNT_ID = "default"` commented as "declared locally … so this module keeps its zero-dependency import-inertness posture", while `bundles.py` already imported `itrader.logger` and `assemble.py` already imported `itrader.venues.lifecycle`. `venues/registry.py` — the declared home — has ZERO runtime imports (`__future__` + `TYPE_CHECKING` only), making it the cheapest import in the package, so the stated cost never existed. All three private copies deleted and imported from the registry, plus the two inline `spec.account_id or "default"` literals in `okx_plugin.py`; the planner found FOUR reference sites the brief had not enumerated (`bundles.py:89` docstring, `assemble.py:138`/`:232`, `venue_uid_guard.py:95`). The two false comments were deleted, but `venue_uid_guard.py`'s was NOT — it documents the real NULL-PK-half hazard, so its substance was preserved and moved to the use site rather than swept up with the others. **WR-07** — three `('paper', DEFAULT_ACCOUNT_ID)` lookups still spelled the venue name literally despite `registry.py` pinning `COMPUTE_VENUE` as its single home precisely because "a second literal … is how the two arms end up asking the bundle memo for different venues", and they were mutually inconsistent: `universe_wiring.py` had been hardened this phase into a fail-loud subscript while `live_trading_system.py:637` still used `.get(...)`, whose `None` flowed into `SessionInitializer` and silently degraded venue metadata (`validate_symbol` / `resolve_precision`) with no exception. All three now key off `COMPUTE_VENUE` (each file already imported `DEFAULT_ACCOUNT_ID` from the registry, so this extended one existing import line per file — zero new import edges), and the live `.get` was promoted to a subscript so its fallback arm fails as loudly as the backtest one. **The promotion is inert on a wired engine** — `ExecutionHandler.init_exchanges` (`execution_handler.py:303`) unconditionally resolves `self._venue_bundles.get(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID, None)` — verified independently by the executor rather than inherited from the plan; the streaming arm is untouched. `universe_wiring.py:110`'s `'paper'` inside a `ConfigurationError` f-string was collateral the brief missed and was decided at planning (rendered text byte-identical, no test asserts on the message) rather than left as an executor judgment call. **WR-09** — `VenueBundles.logger` was constructed and never read (2 tree-wide occurrences, both writes) and was itself the import falsifying the module's own inertness comment; deleted with its `get_itrader_logger` import. Two stale docstrings in `assemble.py:184` and `account/conformance.py:6` still described the factory as `lifecycle.bundle.account_factory(portfolio)` — the positional-portfolio signature this phase deleted — and were corrected to the real keyword-only `(*, initial_cash, enable_margin, account_id, state_storage)`; `conformance.py` matters most because its stated purpose is keeping that wiring honest under `mypy --strict`. Five unused imports removed (`FillEvent`, `Callable`×2, `PortfolioUpdateEvent`, `List`), each confirmed to be its file's only occurrence — note `live_trading_system.py` sits under a `[[tool.mypy.overrides]]` `ignore_errors` block so mypy would never have caught leftovers there. **Near-miss worth recording:** the executor's first edit to `backtest_trading_system.py` used five tabs where the file has four; the Edit tool's exact-match requirement rejected it and it was corrected against `cat -et`. That failure mode is SILENT if a file is written rather than edited — the file still parses. All four gates re-run independently by the orchestrator, not taken on the executor's word: oracle byte-exact (134 / 46189.87730727451, `check_exact=True`), inertness 4 passed, `mypy itrader` clean (282 files), full suite 2877 passed / 6 skipped — exactly baseline. 12 files, 37 insertions / 44 deletions (deletions-dominant). Added lines checked per-file against the split indentation regime (`live_trading_system.py` 4-space; `universe_wiring.py` / `backtest_trading_system.py` tabs) — zero violations. **Deliberately out of scope:** the other nine 11.1 findings. CR-02 (reject the `enable_margin` runtime flip), WR-04+WR-08 (required `state_storage` kwarg on the simulated leaves), WR-01 (venue-aware `fee_model_provider`) and WR-03 have owner decisions settled and are queued for Phase 11.2; WR-06 (unlocked check-then-set on the bundle/connector memos) is deferred to Phase 12 with the threading contract. | 2026-07-23 | 264c74bc | [260723-dc4-11-1-review-hygiene-wr-02-wr-07-wr-09-co](./quick/260723-dc4-11-1-review-hygiene-wr-02-wr-07-wr-09-co/) |
| 260723-dq7 | Close four decision-settled Phase 11.1 review findings, four atomic commits. **CR-03 (CRITICAL, live-blocking)** — `EnhancedOrderValidator.supported_exchanges` was `{NYSE, NASDAQ, BINANCE, OANDA, default, paper}` with no `okx`, and `_validate_market_conditions` reads `portfolio_handler.exchange_for(portfolio_id)`, which returns `"okx"` for a live OKX portfolio (`Portfolio.exchange` derives from `venue_name`). A non-member yields `ValidationLevel.ERROR`/`UNSUPPORTED_EXCHANGE` and `validate_order_pipeline` short-circuits at PHASE 2 — so **no `OrderEvent` was ever emitted for the one live venue this milestone ships**. The 11.1 rename pass had repointed `csv`/`simulated` → `paper` and added a "must NEVER be widened … Repoint it; do not weaken it" comment, which then read as an assertion the set was complete. **Owner decision: TACTICAL, not structural** — `"okx"` added, the comment corrected to record that a REGISTERED execution venue must be admissible; deriving the allowlist from the venue registry (the review's preferred fix) was explicitly deferred to avoid coupling the validator to the registry mid-batch. Regression test added beside the three existing default-deny tests, which are pinned as must-not-weaken. Todo `okx-missing-from-validator-allowlist.md` moved pending→completed. **CR-01 residual** — the account-less-portfolio half was fixed earlier (ccfdc3ef); the review's SECOND remedy was never applied, so `_run_replay` still printed "Paper replay complete" with no assertion and an inert composition could again report success with zero trades — the exact "green suite, dead path" shape 11.1 claims to close. `_run_replay` and `_run_okx_smoke` are separate functions so no mode branching was needed (a flat session IS legitimate for `--mode okx`, never for the golden-CSV replay). Guard shaped as a `_refuse_inert_replay(trade_count)` module-level helper matching the script's `_`-prefixed style; **proven end-to-end** by patching `build_trade_log` to `[]` and confirming process exit code 1. Deliberately does NOT assert an exact count — that would duplicate the oracle and couple the smoke script to the golden number. **WR-03** — `OkxVenuePlugin.account_factory` did `replace(account_config, account_id=account_id or account_config.account_id, ...)`, overriding the id but leaving `account_config.spec` — the spec the BUNDLE was built for. `new_account` then calls `connectors.get("okx", account_id, config.spec)`, so a mismatched id would memoize a connector under `("okx","B")` built from `OkxConnectorPlugin.build(spec_of_A)` — account B's session authenticated with **account A's `secret_ref`**, the cross-account misroute D-11/D-12 exist to close. **This was NOT a mechanical fix and was escalated:** two existing tests deliberately asserted the forbidden behaviour with D-11 rationale docstrings, one of them asserting `from_factory._connector is connectors.get("okx","acct-b",spec)` outright. Owner was shown both and chose **ship the guard, rewrite both tests** — the accepted reasoning being that D-11's stated concern is the closure preferring its BUNDLE id over a supplied one (which would attach a portfolio to a different real venue balance), and **refusing a mismatch is not widening**, so D-11's rationale survives while only the assertion chosen for an unreachable case changes. Guard raises `ValidationError` before the `replace(...)`. **Reachability verified before writing it** — unreachable on every current path (`live_trading_system.py:1726` passes the very id it looked the lifecycle up by; `portfolio_handler.py:428` mints under arbitrary ids but always fetches `COMPUTE_VENUE`, the paper arm) — so this is a latent-hazard guard, not a live behaviour change. Exactly two tests changed, no third went red; both kept their D-11 prose, updated to the new contract; the omitted-id fallback and keyword-only-signature tests untouched. Guard deliberately NOT mirrored onto `paper_plugin.py`, where minting under an arbitrary portfolio `account_id` is legitimate and the same guard would refuse every non-default portfolio. **WR-05** — one money scale written three times across a domain boundary: `Portfolio._validate_initial_state` re-derived `to_money(cash).quantize(Decimal('0.01'), ROUND_HALF_UP)` and demanded EXACT equality with `account.balance`, which the account had produced from its own independent literal at `simulated.py:139`, which in turn ignored the account's own declared `self.precision` set nine lines later. A one-line scale change on either side would have raised on EVERY portfolio construction including the oracle path. **The review's proposed fix was wrong and was corrected at planning:** it suggested `core.money.quantize(value, instrument=None, kind="cash")`, but the real signature is `quantize(value, instrument: Instrument, kind)` and derives the cash scale from `instrument.quote_currency` — there is no `Instrument` at portfolio construction, so that helper is unusable here. Fix forced onto the account instead: `precision` hoisted to a class attribute on the `Account` ABC (which already carries non-abstract members `is_venue_truth`/`restore_cash`) with a `quantize_cash` helper, so it resolves under `mypy --strict` where `Portfolio.account` is typed as the ABC. **Second deviation:** the leaf's instance assignment was DELETED rather than reordered — `VenueAccount` has no `precision`, `SimulatedMarginAccount` never reassigns it, `simulated.py:170` was the sole assignment package-wide and no test reads or patches it. Both values were `Decimal('0.01')`, so byte-identical; value-preservation checked site-by-site, not assumed. Also picks up `simulated.py:621`'s existing precision read for free. All gates re-run independently by the orchestrator: oracle byte-exact (134 / `46189.87730727451`, `check_exact=True`), inertness green, `mypy itrader` clean (282 files), full suite **2879 passed / 6 skipped** (+2 from the 2877 baseline: CR-03's test, and WR-03's one-removed/two-added), `run_live_paper.py --mode replay` exit 0 at 134 trades. 9 files, 229 insertions / 21 deletions. Indentation re-measured per file before each first edit (`portfolio.py` tabs; `account/`, `venues/`, `order_validator.py`, `scripts/` 4-space). **Still open from this review:** CR-02, WR-01, WR-04+WR-08 (owner decisions settled, queued for Phase 11.2) and WR-06 (deferred to Phase 12 with the threading contract). | 2026-07-23 | 95b2929c | [260723-dq7-11-1-review-cr-03-okx-allowlist-cr-01-re](./quick/260723-dq7-11-1-review-cr-03-okx-allowlist-cr-01-re/) |
| 260723-eca | Docs-only: make the Phase 11.1 review resolution state durable before 11.2 planning, so four owner decisions that existed only in a session transcript survive into the phase that consumes them. **`11.1-REVIEW.md`** gains an append-only `## Resolution (2026-07-23)` addendum: a disposition table for all 12 findings (7 CLOSED in code by `260723-dc4`/`260723-dq7`; CR-02, WR-01 and WR-04+WR-08 DECIDED and queued for Phase 11.2; WR-06 DEFERRED to Phase 12), plus each decision's RATIONALE — which is the load-bearing part, since rationale is what stops a decision being re-litigated. **CR-02 → reject the flip**: `enable_margin` is read at CONSTRUCTION by five collaborators (`AdmissionManager._enable_margin`, `EnhancedOrderValidator.enable_margin`, `ManagedStrategies.enable_margin`/SHORT-01, the account leaf kind, and `Portfolio.process_transaction` at fill time) while `ConfigRouter._apply_portfolio` calls only `portfolio.update_config` — so a runtime flip desynchronizes FOUR OF THE FIVE already, today, before 11.1 touched anything; the account-leaf mismatch the review reported is the newest symptom, not the defect. **WR-04+WR-08 → required keyword** (one decision, two sites), chosen over a durability guard in `Portfolio._init_managers` because that guard needs an `_is_durable` predicate that does not exist (no durability marker on `PortfolioStateStorage` — it would need a storage-concretion import inside `Portfolio` or a new property on the base and all three implementations) and because it leaves the in-memory default reachable for callers not routing through `Portfolio`; blast radius verified at 6 leaf constructions in 3 test files, the sole production site already compliant. Carries an **ORDERING CONSTRAINT**: must land BEFORE 11.2's ACCT-05, which ADDS portfolio-creation paths — first means the new paths structurally cannot forget the seam, after means adding paths through the trap then closing it behind them. **WR-01 → venue-aware provider + correct the comment**: oracle-safe (OKX yields None, paper yields ZeroFeeModel, both zero today) but breaks the coupling where a venue-scoped fee update on the paper exchange silently moves OKX reservations; the in-code justification is false in its mechanism (the provider never looks at the OKX exchange, it returns paper's model), and giving `OkxExchange` a real fee model was considered and scoped out as live-behaviour work. **WR-03 → guard not support**, recorded because it overrode two tests that deliberately asserted the forbidden behaviour with D-11 docstrings — the accepted reasoning being that D-11's concern is the closure preferring its BUNDLE id over a supplied one, and refusing a mismatch is not widening. Also records the **CR-*/WR-* ID-namespace collision** between `11-REVIEW.md` and `11.1-REVIEW.md`: 11.2's ROADMAP entry folds in findings by IDs that mean something DIFFERENT in 11.1's review (11.2's CR-02 is the account-less-portfolio raise, 11.1's is the margin flip; 11.2's WR-01 is the `_persist_definition`/`save_config` disagreement, 11.1's is the fee provider), so planning 11.2 from the roadmap text alone resolves the wrong set — same failure mode as the `VENUE-*` collision already on file, and cross-linked to it. **Three new todos** — `venue-bundle-memo-check-then-set-race.md` (WR-06, Phase 12, with the RLock-vs-engine-thread-only decision left explicitly open for the threading contract), `account-reservation-ledger-narrow-port.md` (Phase 12 — `SimulatedCashAccount` holds a ~25-method portfolio-wide store and calls 9; the fix is a narrow `ReservationLedger` port onto the SAME instance, NOT a separate store, because `CachedSqlPortfolioStateStorage` must span a fill's position + cash-scalar writes in one transaction — and a separate store is literally the current bug; records that the 11.2 required-kwarg fix is a down-payment on this shape, not throwaway), `fee-model-provider-venue-blind.md` (WR-01, Phase 11.2) — plus a Decision section added to the existing `enable-margin-runtime-flip-vs-fixed-account-kind.md`. Executor surveyed the repo's `*-REVIEW.md` status vocabulary before touching frontmatter and used the existing `partially_resolved` (6 prior uses) rather than inventing a value; it left the body `**Status:** issues_found` header deliberately untouched under the append-only instruction and documented the intentional frontmatter/body divergence inside the Resolution section rather than silently mutating a historical header. **No gates run — deliberate, not skipped:** nothing under `itrader/`, `tests/` or `scripts/` was touched, so the oracle/inertness/mypy gates have no importable change to observe and are structurally unreachable; gate state carried forward from `260723-dq7` (oracle byte-exact 134 / `46189.87730727451`, mypy clean 282 files, 2879 passed / 6 skipped, replay exit 0). Routed here from `/gsd-fast`, which correctly refused it on its own >3-file-edit guardrail. 5 files, 400 insertions / 1 deletion. | 2026-07-23 | 631d7e30 | [260723-eca-record-phase-11-1-review-resolution-4-ow](./quick/260723-eca-record-phase-11-1-review-resolution-4-ow/) |
| 260723-fast | Amend the ROADMAP Phase 11.2 entry ahead of planning it — `.planning/ROADMAP.md` sole file, 35 insertions / 3 deletions (the 3 being lines replaced in place; goal, requirements, all 11 success criteria, pre-locked decisions and cross-cutting constraints untouched). **(1) Review-ID namespace disambiguation.** Every bare `CR-NN`/`WR-NN` in the 11.2 entry resolves against `11-REVIEW.md`, but those IDs now ALSO exist in `11.1-REVIEW.md` meaning different things — 11.2's CR-02 is the account-less-portfolio raise vs 11.1's `enable_margin` flip; 11.2's WR-01 is the `_persist_definition`/`save_config` disagreement vs 11.1's venue-blind fee provider. A planner working from unqualified IDs resolves the wrong set. Added a blockquote warning sited BEFORE the success criteria (so it is hit before any ID is read), qualified the "Folded-in review findings" and "Explicitly NOT in this phase" lines with their source file, and cross-linked `venue-requirement-id-collision-v18.md` as the same failure mode. **(2) Folded in the three decided 11.1-review findings** as a separate, explicitly-namespaced block (`11.1-REVIEW CR-02` / `WR-04+WR-08` / `WR-01`), each with its locked owner decision and a pointer to the rationale in `11.1-REVIEW.md`'s Resolution section + the three todo files, so the planner treats them as settled rather than re-litigating. Also records that the WR-04+WR-08 required-kwarg fix is a down-payment on the Phase 12 `ReservationLedger` narrow port, not throwaway work. **(3) Pinned the ordering constraint** as its own bold ⚠ block adjacent to the wave-relevant material rather than a footnote: the WR-04+WR-08 required kwarg must land BEFORE criterion 5 (ACCT-05), because ACCT-05 ADDS portfolio-creation paths — first means the new paths structurally cannot forget the `state_storage` seam, after means adding paths through the trap then closing it behind them, each one producing a portfolio that reports itself live while persisting nothing behind a green backtest. States plainly that any wave plan scheduling ACCT-05 first is wrong regardless of the rest of the dependency graph. Extended the existing Sizing note (left in place) to record that the three folded findings push the phase from 11 to ~14 requirements-worth of work, strengthening the case for the ACCT-11 split it already nominates. No gates run — docs-only, nothing importable changed, so oracle/inertness/mypy are structurally unreachable. | 2026-07-23 | 92537616 | (fast — no dir) |

## Deferred Items

Program-level items carried across milestones (v1.7-close carry-forward + v2 platform seams). The
substantive owner-gated item is `margin-equity-double-counts-notional-wr01`.

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Owner-gated defect | `margin-equity-double-counts-notional-wr01` — dark on the all-spot golden; a fix moves 6 owner-frozen goldens → needs external cross-validation before any live margin/leverage consumer reads margin equity | ⚠ Owner-gated | next milestone (pre-margin/live) |
| v1.8 deferred seam | Multi-provider feed-router; single-connector-multi-`account_id`; shared-`account_id` risk allocator; config audit table; errors-history table; stats-history split | Marked (spec §14) | v2 / FastAPI-era |
| Downstream consumer | FastAPI application layer / routes / ASGI (LR-01) — v1.8 makes the engine *interfacable* only | Deferred | post-v1.8 milestone |
| Separate refactors | `livebarfeed-depandas-time-model-datetime`, `mutable-instrument-refactor`, `unify-backtest-direct-bar-generation` | Deferred (not folded) | future milestones |
| D-screener | Production screener / ranking / rebalance loop | Deferred | v2 |
| Perp realism (Phase B) | FUND-01..04 (funding accrual, mark-price liq, funding pipeline, freqtrade oracle) | Deferred | v2 |
| Optimization | Optuna sampler + sweep loop (OPT-01) — v1.6 shipped the FK-ready substrate only | Deferred | v2 |
| Turso/libSQL | `sqlalchemy-libsql` opt-in backend — interface stays Turso-ready | Deferred | v2 (post-beta) |
| Perf (v1.5) | Single-pass per-bar portfolio valuation (profile-first gated); PERF-09/PERF-10; advisory Nyquist VALIDATION gaps | Deferred | future perf phase |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions | Deferred | indefinite (crypto-first) |

## Bookkeeping

- **At v1.7 close (done 2026-07-07):** all v1.7 phase dirs `git mv`'d to `milestones/v1.7-phases/`;
  ROADMAP/REQUIREMENTS/MILESTONE-AUDIT archived as `milestones/v1.7-*`; `.planning/phases/` is empty
  (no `999.3` seed dir remained). The new v1.8 `01-*..12-*` dirs will not collide (`phase_dir_count=0`).

- Git tag `v1.7` NOT created (owner deferred tagging to a manual step).

## Session Continuity

Last session: 2026-07-23T10:43:01.527Z
Stopped at: Phase 11.2 context gathered
success criteria + dependencies + 64/64 coverage); STATE.md refreshed for 12 phases; REQUIREMENTS.md
traceability + category tags + gates renumbered.
Resume file: .planning/phases/11.2-account-provisioning-bootstrap-review-closures/11.2-CONTEXT.md
Carried todo: 14 pending todos in `todos/pending/` (10 fold into v1.8 as CF-1..CF-10; `v17-residual-carryforward.md`
is the index; the substantive open item is `margin-equity-double-counts-notional-wr01`, owner-gated).

## Operator Next Steps

- `/gsd:plan-phase 1` (Config Centralization) — or plan **P1 and P2 in parallel** (both dependency-free).
- At milestone init, set each folded TODO's front-matter `resolves_phase: P#` + `status: scheduled` so it
  is not double-tracked against the live backlog (CF-1..CF-10; see spec §18).

- Before any live margin/leverage consumer: adjudicate `margin-equity-double-counts-notional-wr01`
  (owner-gated, oracle-dark) with external cross-validation.
