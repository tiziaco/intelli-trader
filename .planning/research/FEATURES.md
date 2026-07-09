# Feature Research — v1.8 Live System Refactor & Live-Readiness Hardening

**Domain:** Live-trading engine internals — composition root, event bus, venue plugin system, runtime-config platform, safety/reconciliation subsystem (single-operator, crypto-first)
**Researched:** 2026-07-09
**Confidence:** HIGH (framework grounding verified against Nautilus Trader + QuantConnect LEAN docs); MEDIUM on the trim-boundary judgment calls (P10–P12)

> **What "features" means here.** This is a brownfield architecture refactor, not a user-facing product. The "users" of these features are (1) the single operator running the live engine, (2) the downstream FastAPI app that will consume the seams, and (3) the strategy author. So "table stakes" = what any mature live engine (Nautilus, LEAN) must have to be trusted with real money; "differentiators" = capabilities beyond the LEAN/Nautilus baseline that this engine deliberately adds; "anti-features" = machinery that mature single-operator engines correctly avoid.
>
> **Job of this doc (per the brief):** validate the spec's seven capability areas against how Nautilus/LEAN actually do it, flag any **table-stakes gap** the spec misses, and flag any **over-engineering risk** for a single-operator crypto engine — the ★ P10–P12 feature-adds are the trim-risk zone. The spec already LOCKS the design (LR-NN / CF-NN); each capability below carries an explicit **Spec reconciliation: AGREE / GAP / OVER-ENGINEERING RISK** verdict.

---

## How the reference frameworks are built (grounding)

| Concern | Nautilus Trader | QuantConnect LEAN | iTrader v1.8 spec |
|---|---|---|---|
| Shared core | `NautilusKernel` shared by backtest + live; `TradingNodeConfig` **inherits** `NautilusKernelConfig` | `LeanEngineSystemHandlers` / `LeanEngineAlgorithmHandlers` swapped per mode | `compose_engine(ctx, spec)` shared seam; `build_live_system` vs `build_backtest_system` factories (LR-10) |
| Event transport | single `MessageBus`, **single-threaded, strict FIFO**, deterministic | job-packet-driven pipeline | two-tier `PriorityEventBus` (CONTROL > BUSINESS) live; `FifoEventBus` backtest (LR-11) |
| Execution venue registry | `add_exec_client_factory(name, Factory)` | `IBrokerageFactory` + `IBrokerageModel` via **Composer** | `ExecutionVenueRegistry` + `VenuePlugin` (LR-17) |
| Data provider registry | `add_data_client_factory(name, Factory)` — **separate** from exec | `IDataQueueHandler` (Composer part) — **separate** from brokerage | `DataProviderRegistry` + `LiveDataProvider` Protocol (LR-17) |
| Pre-trade safety | `RiskEngine`: `TradingState ∈ {ACTIVE, HALTED, REDUCING}` + submit/modify rate limits + max-notional | brokerage-model order controls | `SafetyController` state latch + CF-1 aggregate circuit breaker |
| Multi-account | one `Account` **per venue**, aggregated in one `Portfolio` | single algorithm → single portfolio | one `Account` **per `account_id`**, M:N strategy↔portfolio (LR-03/LR-20) |
| Runtime config mutation | set at node build (immutable at runtime) | set at job packet (immutable at runtime) | durable scoped `ConfigUpdateEvent` platform (LR-04) — **beyond both** |

**Two structural facts that anchor most verdicts below:**
1. **The two-registry split (exec vs data) is table stakes, not novel.** Both Nautilus (`add_exec_client_factory` / `add_data_client_factory`) and LEAN (`IBrokerageFactory` / `IDataQueueHandler`) ship exactly this separation. The spec's LR-17 is the proven pattern, not an invention.
2. **Nautilus/LEAN both freeze config at construction.** Neither ships a durable runtime-config-override-via-events platform. That makes iTrader's P10 a genuine *differentiator* — and simultaneously the single biggest over-engineering risk for a one-operator engine.

---

## Feature Landscape

### Table Stakes (any trusted live engine has these)

| # | Capability | Why expected (framework precedent) | Complexity | Spec phase / reconciliation |
|---|---|---|---|---|
| TS-1 | **God-object → composition root + shared engine seam + run-driver + thin facade** | Nautilus `NautilusKernel` shared, `TradingNode` thin over it; LEAN system/algorithm handler split. A 2,171-line God object is the anti-pattern both avoid. | HIGH | P1–P7. **AGREE** — LR-10 mirrors the Nautilus kernel/node split precisely. |
| TS-2 | **Venue parametrization (zero `if exchange==...`)** | Nautilus/LEAN both dispatch venues through a factory registry; hardcoded venue branches are the smell being removed. | HIGH | P6. **AGREE** — `VenueLifecycle` None-guards + registry kills every branch (LR-17). |
| TS-3 | **Separate execution-venue + data-provider registries** | Nautilus `add_exec_client_factory` vs `add_data_client_factory`; LEAN `IBrokerageFactory` vs `IDataQueueHandler`. The decoupling (paper-exec + real-data) is why both keep them separate. | MEDIUM | P6. **AGREE** — LR-17 two registries, directly matches both frameworks. |
| TS-4 | **Connector sharing / memoization per venue** | Nautilus shares one client per venue across data+exec; opening N duplicate authenticated sessions is wasteful and rate-limit-hostile. | MEDIUM | P6. **AGREE** — `dict[(venue, account_id)]` memoization (LR-17/LR-20). |
| TS-5 | **Halt / kill-switch state machine** | Nautilus `RiskEngine.TradingState=HALTED` (new orders denied, cancels pass). A live engine with no hard-stop is untrustworthy. | MEDIUM | P8. **AGREE** — `SafetyController` latch, `VALID_STATUS_TRANSITIONS`, `HALTED` no-exit-except-operator. |
| TS-6 | **Durable halt record + startup refusal** | A crashed-while-halted engine that silently resumes RUNNING is a money-loss bug. | MEDIUM | P8. **AGREE** — `check_durable_halt_on_start()` runs first, re-latches from persisted reason (LR-22 `halt_records`). |
| TS-7 | **Startup reconciliation (venue truth vs local intent)** | Every restart-safe live engine reconciles broker state on boot; drift-then-trade is catastrophic. Nautilus reconciles execution state on connect. | HIGH | P8. **AGREE** — `ReconciliationCoordinator` rehydrate→reconcile→baseline guard, per-portfolio. |
| TS-8 | **Stream reconnect + gap recovery + resume gate** | ccxt.pro / any WS feed drops; catch-up + snapshot + health-gate before resuming submission is standard. | HIGH | P8. **AGREE** — `StreamRecoveryHandler` (CF-2 backfill-on-resume, loop-native). |
| TS-9 | **Injected error policy (fail-fast backtest / publish-and-continue live)** | A single handler failure must not abort a live session nor false-green a backtest. Nautilus isolates component faults. | MEDIUM | P9. **AGREE** — `ErrorPolicy` injected (removes the monkeypatch), per-handler granularity, WR-06 guards. |
| TS-10 | **Aggregate error-rate circuit breaker** | Nautilus `RiskEngine` submit/modify **rate limits**; a money route failing every event while "publish-and-continue" runs infinitely green is the exact hole CF-1 closes. | MEDIUM | P9 (CF-1). **AGREE — and this is the one table-stakes safety item that is a genuine *add*, not just a refactor.** Route-classified ring (SETTLEMENT halt-on-first, ORDER-IO N=3/60s, etc.). |
| TS-11 | **Handler-owns storage init (uniform backtest/live)** | Storage wiring living in the composition God object is the smell; the `PortfolioHandler` pattern already proves the shape. | MEDIUM | P3. **AGREE** — LR-13, `(environment, sql_engine)` + `storage=` override. |
| TS-12 | **Centralized, import-safe config** | One config surface, not scattered module constants; import must not do credential I/O (inertness gate). | MEDIUM | P1. **AGREE** — `SystemConfig` eager/lazy split; lazy `sql`, per-venue creds never global. |

### Differentiators (beyond the LEAN/Nautilus single-operator baseline)

| # | Capability | Value proposition | Complexity | Spec phase / reconciliation |
|---|---|---|---|---|
| DF-1 | **Two-tier priority event bus (CONTROL > BUSINESS)** | Nautilus is strict single-tier FIFO; a kill-switch or config command queues *behind* a market-data backlog. Priority-lifting only operational/safety/config events (never trading intents) lets the kill switch preempt without breaking causal trading FIFO. | MEDIUM–HIGH | P2. **AGREE, with a caveat.** Genuinely beyond Nautilus and solves a real latency problem. Risk is subtle: any event mis-classified into CONTROL that participates in trading causality corrupts state — the spec correctly pins `SIGNAL` to BUSINESS. Keep `_CONTROL_EVENT_TYPES` a tiny, reviewed frozenset. Unbounded-but-monitored is fine at single-operator volume; a real depth cap/backpressure is correctly deferred. |
| DF-2 | **Durable runtime-config platform (scoped, allowlisted, survives restart)** | Neither Nautilus nor LEAN can mutate config at runtime — both freeze at construction. A FastAPI-controllable engine that changes fee params / poll cadence / risk limits / strategy enablement live, durably, and re-applies on restart is a real operator win. | HIGH | P10 ★. **AGREE that it's valuable; OVER-ENGINEERING RISK on scope — see below.** |
| DF-3 | **Durable strategies registry (which strategies trade survives restart; runtime enable/disable)** | Nautilus adds strategies at node config (static); LEAN is one-algorithm-per-deploy. A registry where the active set is durable and toggle-able at runtime via `STRATEGY_COMMAND` is an operator capability neither ships out of the box. | MEDIUM | P11 ★. **AGREE.** Split value: *durable-resume* is near-table-stakes once multi-strategy is real; *runtime toggle mid-session* is the differentiator slice (and the trimmable one). |
| DF-4 | **Multi-strategy / multi-portfolio-live, per-`account_id` keying (M:N)** | LEAN is single-portfolio; Nautilus is account-per-venue aggregated into one portfolio. iTrader's signal-fan-out to N portfolios, each sizing independently against its own `account_id` venue account, is a superset — one strategy trading across multiple accounts at once. | HIGH | P12 ★. **AGREE.** Aligned with Nautilus's account-per-venue truth model, generalized to account-per-portfolio. The hard-but-right part is `client_order_id` correlation + per-portfolio reconcile. |
| DF-5 | **Stats/state snapshot as a store-backed UI read-model** | Exposing `state.*` / `stats.*` from a key-value store the UI reads without touching hot-path locks is a clean seam for the downstream FastAPI app. | LOW–MEDIUM | P10 ★ (`system_store`). **AGREE** — cheap, and it's the read-side the FastAPI milestone needs. |
| DF-6 | **First-class `paper` venue plugin (simulated fills + real live data)** | Paper-trading against a *live* feed as a production venue (not a test hack) is how you validate a strategy pre-real-money. LEAN/Nautilus support paper accounts; making it a registry plugin (aliasing `SimulatedExchange`) is the clean expression. | LOW–MEDIUM | P6/P13. **AGREE** — `paper` = production plugin; `replay` = test-only fixture (clean split, LR test-migration). |

### Anti-Features (correctly avoided — do NOT build for a single-operator crypto engine)

| Feature | Why it gets requested | Why problematic here | Spec status / verdict |
|---|---|---|---|
| **Config audit-trail table** (`system_config_audit`) | "Track who changed what config when." | Single operator, no compliance driver; a full audit table + write path is machinery for a governance need that doesn't exist yet. | Spec **defers** (§14). **AGREE — keep deferred.** |
| **Errors-history table** | "Persist every error for forensics." | The ERROR route already logs (structured) + persists `state.last_error`; a full history table contends with hot-path writes for no single-operator payoff. | Spec **defers** (§14). **AGREE — keep deferred.** Latest-error-in-`system_store` is the right minimum. |
| **Multi-provider feed-router** (crypto aggregator + forex concurrently) | "Trade multiple asset classes at once." | Needs `set_provider` → a symbol/asset-class-keyed router; premature for a crypto-first single-venue operator. The two-registry decoupling *enables* it later without building it now. | Spec **defers** (§14). **AGREE.** |
| **Shared-`account_id` risk allocator** (N portfolios pooling one venue account) | "Split one account's buying power across strategies." | The venue can't partition pooled buying power back out — needs a whole risk-allocation subsystem. Express "many strategies, shared account" as many strategies on *one* portfolio instead. | Spec **defers, fail-loud** (§10a). **AGREE — the distinct-`account_id` invariant is the right guardrail.** |
| **Single-connector-multi-`account_id` optimization** (OKX master key routing) | "One session for all accounts." | Micro-optimization; one connector per `account_id` is simpler and correct. Only worth it at many-accounts scale. | Spec **defers** (§14). **AGREE.** |
| **Plugin auto-discovery** (entry-points / Composer-style dynamic class loading) | "Drop a venue in and it's found." | LEAN's Composer exists because it's a hosted multi-tenant platform. A single-operator engine registering venues explicitly in a factory is simpler, inertness-safe, and grep-able. Dynamic loading would fight the lazy-import inertness gate. | Not in spec. **AGREE with the omission — explicit factory registration is correct; do not add discovery.** |
| **N-tier priority bus (>2 tiers) / per-event priority** | "Fine-grained scheduling." | Two tiers (CONTROL/BUSINESS) already exceed Nautilus. More tiers multiply the risk of causal reordering bugs for zero single-operator benefit. | Spec = exactly 2 tiers. **AGREE — hold the line at 2.** |
| **General dynamic config-mutation framework** (arbitrary key mutation, type registry, schema DSL) | "Make everything runtime-tunable." | The over-engineering trap inside P10 — see risk note. Only a small allowlist of keys actually needs runtime mutation. | Spec has an **allowlist** (§6e). **AGREE — the allowlist IS the anti-over-engineering guard; enforce it narrowly.** |

---

## Table-stakes GAP check (does the spec miss anything mature frameworks have?)

Only one candidate gap surfaced against the Nautilus/LEAN baseline, plus two minor notes:

- **GAP (MEDIUM): pre-trade order-rate / max-notional throttle, distinct from the post-error circuit breaker.** Nautilus `RiskEngine` enforces **submit/modify rate limits** and **max-notional-per-order** *before* an order reaches the venue (`OrderDenied`). iTrader has `EnhancedOrderValidator` + cash-reservation admission (pre-trade sizing/cash gates) and CF-1 (a *post-hoc* error-rate breaker), but **no pre-trade throttle on order submission velocity**. A runaway strategy spamming valid orders is caught by neither the validator (each order is individually valid) nor CF-1 (no errors are raised). For a live crypto engine this is a real safety surface. **Recommendation:** flag as a candidate requirement in P8/P9 (`SafetyController` or admission) — a simple submit-rate ceiling + max-notional-per-order guard. It is *not* in the spec's 26 concerns or CF list. Low-cost to add (a counter + threshold on the admission path); high safety value. Rank it against P9's CF-1 work since they share the "runaway protection" theme.
- **Minor note (REDUCING state):** Nautilus has a third trading state, `REDUCING` (accept only exposure-reducing orders). iTrader has `halt` (freeze) + `pause_submission` (reversible quiesce). `pause_submission` with deferred-protective-order replay covers most of the operational need; a full `REDUCING` mode (let stops/exits through, block entries) is a *nice-to-have*, not a gap — the deferred-protective queue already prioritizes protective orders on resume. Do not build `REDUCING` now; note it as a future safety refinement.
- **Minor note (no gap):** Nautilus's `RiskEngine` is a *first-class engine on the submit path*; iTrader spreads the equivalent across `AdmissionManager` + `SafetyController` + CF-1. That's a topology choice, not a missing capability — coverage is equivalent once the pre-trade throttle above is added.

---

## Over-engineering risk zone (the ★ P10–P12 trim boundary)

The brief asks specifically to flag over-engineering for a single-operator crypto engine. Assessment per ★ phase:

| Phase | Verdict | Reasoning |
|---|---|---|
| **P10 ★ Runtime-config platform** | **HIGHEST trim/scope risk.** Keep — but scope hard. | Value is real (FastAPI-controllable engine), but the failure mode is building a *general* config-mutation framework when **~5–8 keys** actually need runtime mutation (fee/slippage params, poll cadence, `universe_remove_policy`, risk limits, strategy enable/disable). The **allowlist is the discipline** — if the allowlist stays small and the "framework" is just `event → route-to-owner → persist → overlay`, it's proportionate. The risk is the allowlist quietly growing and a schema/validation DSL accreting. **Guidance for requirements:** cap the initial allowlist explicitly; treat "add a runtime-mutable key" as a deliberate decision, not a default. Stats-snapshot + `system_store` read-model (DF-5) is cheap and should stay even if the mutation path is trimmed. |
| **P11 ★ Strategies registry** | **Keep the durable half; the runtime-toggle half is the trimmable slice.** | *Durable resume* (restart re-registers the active set) is near-table-stakes the moment multi-strategy live is real — without it a restart silently drops strategies. *Runtime enable/disable mid-session via `STRATEGY_COMMAND`* is the differentiator and the part that could defer to the FastAPI milestone if P11 needs trimming. Complexity is moderate (mirror `HaltRecordStore`). Low over-engineering risk as long as it stays a store + rehydrate + one command route. |
| **P12 ★ Multi-portfolio-live** | **Keep — it's the LR-03 reason this milestone exists; not over-engineered.** | Deleting the single-portfolio guard + `client_order_id` correlation + per-portfolio reconcile is the correct generalization of Nautilus's account-per-venue model. The genuinely-hard parts (per-`account_id` reconcile, attribution) are inherent to multi-account live, not gold-plating. The **deferred shared-`account_id` risk allocator is the right cut** — that one *would* be over-engineering. Distinct-`account_id` fail-loud invariant is the correct guardrail. |

**Net:** the spec's own trim boundary (P1–P9+P13 core; P10–P12 ★) is well-drawn. If schedule pressure hits, trim in this order: **(1)** P10's runtime-*mutation* path (keep the read-model), **(2)** P11's runtime-*toggle* (keep durable-resume), **(3)** never trim P12 (it's the milestone's LR-03 mandate) and never trim P8/P9 safety.

---

## Feature Dependencies

```
P1 Config centralization ──┐
                           ├──> P3 EngineContext + storage-in-handler ──> P4 SqlEngine rename ──> P5 New stores
P2 Event bus ──────────────┘                                                                        │
                                                                                                    ├──> P6 Venue registry + bundle
P2 ─────────────────────────────────────────────────────────────────────────────────────────────┘        │
P5 + P6 ──> P7 LiveRunner + factory + facade shrink (SessionInitializer / UniverseWiring — ORACLE-SENSITIVE)
P7 ──> P8 Safety + reconciliation + stream recovery ──┐
P7 ──> P9 Error subsystem (CF-1 circuit breaker)      │
                                                       ├──> P10 ★ Runtime-config platform  (needs P5 stores + P8 CONTROL routes)
P5 + P7 ──> P11 ★ Strategies registry                 │
P6 + P8 ──> P12 ★ Multi-portfolio-live                │
P7 + P12 ──> P13 Test migration (replay→fixture, gates)

CONTROL-plane routes (P8) ──enable──> P10 ConfigUpdateEvent + P11 STRATEGY_COMMAND
PriorityEventBus (P2) ──enables──> CONTROL > BUSINESS preemption for all of the above
Venue registry (P6) ──enables──> P12 connector memoization by (venue, account_id)
```

### Dependency notes (framework-grounded)

- **Everything routes through P2 (the bus) and P6 (the registry).** These are the two structural seams the rest hang off — exactly the `MessageBus` + client-factory-registry pair that anchor a Nautilus `TradingNode`. Sequence them early (spec does: P2 foundation, P6 first live-decomposition phase).
- **P10/P11 depend on the CONTROL plane (P8) *and* the durable stores (P5).** Runtime config and strategy toggles are only meaningful once (a) a CONTROL event can preempt the business flow and (b) a store makes them survive restart. This is why they're correctly last.
- **P12 depends on the venue registry (P6) for per-`account_id` connector keying and on safety (P8) for per-portfolio reconcile.** Multi-account without reconciliation is the drift-then-trade hazard.
- **P7 is the oracle-sensitive chokepoint.** `UniverseWiring` is *shared* with backtest — the refactor may only extract it if the backtest path stays byte-identical (LR-02). This is the one live-decomposition phase with real oracle risk; the priority bus and stores carry *zero* oracle risk (backtest uses `FifoEventBus` + `sql_engine=None`).

---

## MVP Definition (the trim boundary, restated for requirements)

### Core refactor — must ship this milestone (P1–P9 + P13)

- [ ] TS-1 God-object decomposition (factory + `compose_engine` + `LiveRunner` + ~200-line facade) — the milestone's north star (LR-00)
- [ ] TS-2/TS-3/TS-4 Venue parametrization + two registries + connector memoization — kills every `if exchange==` (P6)
- [ ] TS-5/TS-6/TS-7/TS-8 Safety state machine + durable halt + reconciliation + stream recovery (P8)
- [ ] TS-9/TS-10 Injected `ErrorPolicy` + **CF-1 aggregate circuit breaker** (P9) — the one HIGH-priority safety add
- [ ] TS-11/TS-12 Handler-owns storage + centralized import-safe config (P1/P3/P4/P5)
- [ ] DF-1 Two-tier priority bus (P2) — foundational, everything else preempts through it
- [ ] DF-6 `paper` production venue plugin; `replay`→test fixture (P6/P13)
- [ ] **CANDIDATE GAP:** pre-trade order-rate / max-notional throttle (evaluate into P8/P9)

### ★ Feature-adds — in scope this milestone, but the trim boundary if pressure hits (P10–P12)

- [ ] DF-4 Multi-portfolio-live (P12) — **do not trim** (LR-03 mandate)
- [ ] DF-3 Strategies registry, durable-resume half (P11) — near-table-stakes once multi-strategy is real
- [ ] DF-5 Stats/state store-backed read-model (P10) — cheap; the FastAPI seam
- [ ] DF-2 Runtime-config mutation path (P10) — **scope hard via a small allowlist; first trim candidate**
- [ ] DF-3 runtime enable/disable-mid-session (P11) — second trim candidate

### Future / deferred (correctly out of scope — the anti-features above)

- [ ] Config audit-trail table, errors-history table, multi-provider feed-router, shared-`account_id` risk allocator, single-connector-multi-account optimization, `REDUCING` trading state, plugin auto-discovery

---

## Feature Prioritization Matrix

| Capability | Operator/Live value | Impl cost | Priority | Note |
|---|---|---|---|---|
| God-object decomposition (TS-1) | HIGH | HIGH | P1 | The milestone reason |
| Venue registry + two registries (TS-2/3) | HIGH | MEDIUM | P1 | Proven pattern (Nautilus/LEAN) |
| Safety state machine + durable halt (TS-5/6) | HIGH | MEDIUM | P1 | Real-money trust floor |
| Reconciliation + stream recovery (TS-7/8) | HIGH | HIGH | P1 | Restart-safety |
| CF-1 circuit breaker (TS-10) | HIGH | MEDIUM | P1 | Only table-stakes *add* |
| Pre-trade rate/notional throttle (GAP) | HIGH | LOW | P1–P2 | **Missing from spec — evaluate in** |
| Two-tier priority bus (DF-1) | MEDIUM–HIGH | MEDIUM | P1 | Beyond Nautilus; hold at 2 tiers |
| Injected ErrorPolicy (TS-9) | HIGH | MEDIUM | P1 | Removes monkeypatch |
| Multi-portfolio-live (DF-4) | HIGH | HIGH | P1 (★) | LR-03 mandate — don't trim |
| Strategies registry, durable-resume (DF-3a) | MEDIUM–HIGH | MEDIUM | P2 (★) | Near-table-stakes |
| Stats/state read-model (DF-5) | MEDIUM | LOW | P2 (★) | FastAPI seam; keep even if P10 trims |
| Runtime-config mutation (DF-2) | MEDIUM | HIGH | P2/P3 (★) | Scope via allowlist; first trim candidate |
| Runtime strategy toggle (DF-3b) | MEDIUM | LOW | P3 (★) | Second trim candidate |

**Priority key:** P1 = ship this milestone, core; P2 = ship this milestone, ★ feature-add; P3 = ★ trim-first-if-pressure.

---

## Competitor Feature Analysis

| Capability | Nautilus Trader | QuantConnect LEAN | iTrader v1.8 (our approach) |
|---|---|---|---|
| Composition root | `NautilusKernel` shared; `TradingNodeConfig ⊃ NautilusKernelConfig` | System/Algorithm handler split per mode | `compose_engine` shared + mode factories (LR-10) — **same shape as Nautilus** |
| Event transport | Single-threaded FIFO `MessageBus`, no priority | Job-packet pipeline | Two-tier `PriorityEventBus` live / `FifoEventBus` backtest — **exceeds both** |
| Exec venue registry | `add_exec_client_factory` | `IBrokerageFactory` + Composer | `ExecutionVenueRegistry` + `VenuePlugin` — **matches** |
| Data provider registry | `add_data_client_factory` (separate) | `IDataQueueHandler` (separate) | `DataProviderRegistry` (separate) — **matches** |
| Venue bundle members | client + exec + instrument provider | `IBrokerage`+`IBrokerageModel`+`IDataQueueHandler`+factory | connector + exchange + account-factory + provider (4-collaborator) — **matches LEAN's separation** |
| Pre-trade safety | `RiskEngine`: states + rate + notional limits | brokerage-model controls | `SafetyController` + admission + CF-1 — **equivalent, minus a submit-rate throttle (GAP)** |
| Runtime config mutation | frozen at build | frozen at job packet | durable scoped `ConfigUpdateEvent` — **differentiator, neither has it** |
| Multi-account | Account per venue → one Portfolio | single portfolio | Account per `account_id`, M:N — **superset of Nautilus** |
| Paper trading | paper account mode | paper brokerage | first-class `paper` venue plugin — **cleaner registry expression** |

---

## Sources

- [NautilusTrader — Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) (NautilusKernel shared core; single-threaded MessageBus; ports-and-adapters modularity) — HIGH confidence (official docs)
- [NautilusTrader — Live Trading](https://nautilustrader.io/docs/latest/concepts/live/) (TradingNode, TradingNodeConfig ⊃ NautilusKernelConfig, research-to-live parity) — HIGH
- [NautilusTrader — Risk API / Execution](https://nautilustrader.io/docs/latest/api_reference/risk/) (RiskEngine `TradingState` ACTIVE/HALTED/REDUCING, submit/modify rate limits, max-notional, OrderDenied) — HIGH
- [NautilusTrader — Live API](https://nautilustrader.io/docs/latest/api_reference/live/) (`add_data_client_factory` / `add_exec_client_factory`, TradingNodeBuilder) — HIGH
- [QuantConnect LEAN — Contributing Brokerages / Laying the Foundation](https://www.quantconnect.com/docs/v2/lean-engine/contributions/brokerages/laying-the-foundation) (IBrokerageFactory, IBrokerage, IBrokerageModel, IDataQueueHandler, Composer `AddPart`) — HIGH
- iTrader v1.8 design spec `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` (LR-00..LR-22, CF-1..CF-10) — authoritative locked design
- iTrader `.planning/PROJECT.md`, `CLAUDE.md` — existing architecture (v1.7 live path, Account abstraction, OkxConnector, VenueReconciler)

---
*Feature research for: live-trading engine internals / operational control surface (single-operator, crypto-first)*
*Researched: 2026-07-09*
