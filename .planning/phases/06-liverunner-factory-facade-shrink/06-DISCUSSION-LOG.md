# Phase 6: LiveRunner + Factory + Facade Shrink - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 6-LiveRunner + Factory + Facade Shrink
**Areas discussed:** UniverseWiring cut line, P6/P7 facade boundary, LiveRunner scope, Factory handoff + routes, UniverseHandler dep collapse (RUN-06), SessionInitializer scope, run_paper_replay integrity, CF-10 depth-hint seam

---

## UniverseWiring cut line — what's in the shared helper

| Option | Description | Selected |
|--------|-------------|----------|
| Byte-exact backtest block only | Shared = exactly what backtest does today; strategies injection + warmup register stay live-only. Trivially byte-exact. | |
| Include strategies injection | Shared helper also calls `strategies_handler.set_universe` (matches RUN-04 literal); requires proving the added backtest call inert. | ✓ |

**User's choice:** Include strategies injection.
**Notes:** Grounded mid-discussion: the addition is inert BY CONSTRUCTION — `Universe.__init__`
marks all members `Readiness.READY` (`universe.py:106/127`, "oracle-inert"), backtest membership ⊇
strategy tickers → `is_ready` True → gate at `strategies_handler.py:214` never skips. Structural,
not fragile. Still per-PLAN oracle-gated. (→ CONTEXT D-01)

## UniverseWiring cut line — form & home

| Option | Description | Selected |
|--------|-------------|----------|
| Free function in `trading_system/` | `wire_universe(engine) -> Universe` in `trading_system/universe_wiring.py`. | ✓ |
| Free function in `universe/` | Same shape, homed in `universe/wiring.py` beside membership/instruments. | |
| Small class / shared runner base | A class both runners compose/subclass. | |

**User's choice:** Liked both trading_system/ and universe/; asked for a recommendation.
**Notes:** Recommended `trading_system/` — decisive factor is that `universe/` is documented
"no queue/feed/store import" (pure derivation), but the helper does `feed.bind` + handler injection
(composition wiring). Homing it in `universe/` would breach that purity. Owner accepted. (→ D-02)

## P6/P7 facade boundary — the ~200-line target

| Option | Description | Selected |
|--------|-------------|----------|
| 200 = milestone-exit gate; P6 lands interim | P6 acceptance is structural; safety/reconcile/stream untouched; facade ~650 interim; ~200 verified at P7 close. | ✓ |
| Force ~200 at P6 via interim relocation | Move safety/reconcile/stream to temp homes now, P7 refines — double-work on fragile seams. | |
| Pull SafetyController into P6 | Re-scope P7's extraction into P6. | |

**User's choice:** Option 1 (asked for recommendation, then confirmed).
**Notes:** Locked with the refinement that P6 must NOT touch the safety/reconcile/stream method
BODIES — P7 extracts from an unchurned baseline. (→ D-03, D-04)

## LiveRunner scope — ErrorPolicy depth

| Option | Description | Selected |
|--------|-------------|----------|
| Shape minimal injected seam | LiveRunner ctor takes injected `error_policy`; publish-and-continue moved verbatim + WR-06 guard; P8 formalizes. | ✓ |
| Leave error seam as-is, defer all to P8 | Keep the monkeypatch; P8 introduces injection wholesale. | |

**User's choice:** Shape minimal injected seam. (→ D-07)

## LiveRunner scope — WorkerSupervisor

| Option | Description | Selected |
|--------|-------------|----------|
| LiveRunner owns it directly (recommended) | Move `_run_poll_timer` into LiveRunner; defer a separate class (YAGNI). | |
| Extract WorkerSupervisor class now | Build the §5 collaborator; LiveRunner composes it. | ✓ |

**User's choice:** Extract WorkerSupervisor class now (against the recommendation).
**Notes:** Owner wants the §5 collaborator built now rather than folded-then-re-extracted. (→ D-05)

## Factory handoff — construction relationship

| Option | Description | Selected |
|--------|-------------|----------|
| Factory returns wired facade; `__init__` pure injection | `build_live_system(spec) -> LiveTradingSystem` is the only path; facade `__init__` holds no wiring. | ✓ |
| Facade `__init__` takes spec + orchestrates | Keeps a construction path on the class; blurs factory/facade split. | |

**User's choice:** Factory returns a wired facade; `__init__` is pure injection. (→ D-09)

## Factory handoff — LiveRouteRegistrar

| Option | Description | Selected |
|--------|-------------|----------|
| Central declarative table, installed at construction | One central live+CONTROL route composition; list order = execution order; no runtime mutation. | ✓ |
| Distributed — each handler declares its own routes | `owned_routes()` merged by the registrar; cross-handler ordering becomes emergent. | |

**User's choice:** Central declarative table. (→ D-10)

## UniverseHandler dep collapse (RUN-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Literal RUN-06 ctor + keep read-model setters | Ctor = bus/universe/feed/config; `set_venue_metadata` unconditional; freeze_gate interim callable; 4 read-models stay setters. | ✓ |
| Maximal ctor — fold read-models in | Ctor also takes the 4 read-models; only venue_metadata + freeze_gate post-ctor. | |

**User's choice:** Literal RUN-06 ctor + read-model setters.
**Notes:** Owner asked for two concrete code examples of the shapes before deciding; picked the
smaller-ctor / keep-setters shape. `set_venue_metadata(exchange)` collapses the two OKX-guarded
seams into one unconditional call (P5 VENUE-04 capabilities). (→ D-11)

## SessionInitializer scope

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct class, runs at construction | Named class invoked by `build_live_system` at construction; owns wire_universe + warmup + UniverseHandler + routes. | ✓ |
| Inline in `build_live_system` | No separate class; factory grows a large inline block. | |
| Distinct class, runs at `start()` | Keeps today's timing but conflicts with RUN-05/RUN-06 (routes/handler at construction). | |

**User's choice:** Distinct class, runs at construction. (→ D-12)

## run_paper_replay integrity (parity gate)

| Option | Description | Selected |
|--------|-------------|----------|
| Construct via factory + inject fail-fast ErrorPolicy | Route replay through build_live_system + fail-fast ErrorPolicy + synchronous drain. | |
| Bespoke replay construction path | Replay gets its own construction. | |
| Minimal: drop line 1490, preserve steps 2-3 | Only P6 change is removing `_initialize_live_session()` (now construction-time); steps 2-3 verbatim. | ✓ |

**User's choice:** Minimal (drop line 1490, preserve everything else).
**Notes:** Owner caught that the initial proposal pulled P8 (fail-fast ErrorPolicy) and P12
(relocation to `tests/ReplayRunner`) work into P6. Reading the body confirmed `run_paper_replay`
never used LiveRunner — its only touchpoint with decomposed code is line 1490. Scope corrected to
the one-line minimal. (→ D-16)

## CF-10 depth-hint seam shape (RUN-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Named depth-computation boundary | `register_strategy_warmup(feed, strategies)` computes depth via a named replaceable function (global max today; CF-10 generalizes the body). | ✓ |
| Minimal rehome, inline the max() | Keep `max(s.warmup)` inlined; CF-10 re-touches the wiring later. | |

**User's choice:** Named depth-computation boundary. Per-symbol rings + K-computation stay deferred. (→ D-17)

## Follow-up — pull TEST-01 (replay relocation) forward from P12 into P6

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — move TEST-01 into P6 | Reassign TEST-01 (run_paper_replay→tests/ReplayRunner, fixture-only replay plugin, PAPER_PARITY leaves, production replay-free); ReplayRunner injects fail-fast ErrorPolicy via the D-07 seam. | ✓ |
| Keep TEST-01 in P12 | Leave relocation in P12; P6 keeps the D-16 minimal (production keeps run_paper_replay). | |
| Move it, but keep D-16 minimal (partial) | Relocate the method but defer fixture-only plugin / PAPER_PARITY move. | |

**User's choice:** Yes — move TEST-01 into P6.
**Notes:** Owner raised it AFTER the initial 8 areas: a production replay method would "keep bothering
me for every next phase until phase 12." Assessment confirmed it fits — TEST-01 needs only P6's factory
(zero P7–P11 dependency; P12's "lands last" is about TEST-02/03/04), rides the same construction path P6
builds, has no production caller, and composes with the D-07 ErrorPolicy seam (fail-fast = trivial
re-raise → trustworthy gate from P6). This SUPERSEDES the earlier in-discussion framing (D-16) that
deferred replay fail-fast + relocation wholesale. Guardrail: pure code-motion, test_paper_parity green
continuously, sliced after RUN-04 locks. ROADMAP + REQUIREMENTS updated (TEST-01: P12 → P6). (→ D-16 rev,
D-18)

**Post-decision code check (corrections, → D-19/D-20):** verifying the fail-fast mechanism surfaced
two refinements. (1) The publish-and-continue monkeypatch lives in `start()` (`:1665`), not `__init__`;
`run_paper_replay` never calls `start()`, so replay is fail-fast BY DEFAULT (EventHandler default seam),
not by injection — corrects the D-18(4) "injects fail-fast ErrorPolicy" claim (over-engineered; the
correct model removes a D-07 coupling). (2) `paper` (execution venue, real paper trading, v1.7 DoD) ≠
`replay` (data plugin, test-only) — only the replay data side + parity harness leave production; the
paper venue STAYS. Both captured as D-19/D-20; ROADMAP + REQUIREMENTS SC text corrected to match.

**Owner refinement (2026-07-13, → D-18/D-20/D-21/D-22):** probing the destination further, owner set
firm direction: (1) paper mode stays a **real live production mode** — do NOT touch its execution logic;
(2) move **ALL** replay logic OUT of the `itrader` package into `tests/` (it's test infra); (3) rename
`ReplayRunner` → **`TestRunner`**, `ReplayDataProvider` → **`TestLiveDataProvider`** (rejected
`SimulatedLiveDataProvider` — collides with the production `Simulated*` compute family). Code check
surfaced the paper↔replay coupling (`:535` hardwires `paper→replay`): since replay leaves production,
production `paper` re-points to the **OKX live feed** (`{'okx':'okx','paper':'okx'}` — the only live
provider today; = the v1.7 live-paper-on-OKX DoD) — touches only the data-provider SELECTION, not paper
execution. Owner confirmed paper→live-feed. Also flagged the pytest hazard: `Test*`-prefixed classes are
auto-collected → `filterwarnings=["error"]` makes it a hard failure → set `__test__ = False` (D-22). The
`ReplayDataPlugin` moves to `tests/` too (paper_plugin.py splits: execution stays, data leaves).

---

## Claude's Discretion
- Plan/wave slicing across RUN-01..07 (isolate/verify the RUN-04 `UniverseWiring` extraction as its
  own oracle-gated PLAN).
- Exact module paths / class-function names / signatures beyond the pins (LiveRunner, WorkerSupervisor,
  SessionInitializer, LiveRouteRegistrar, build_live_system, wire_universe, register_strategy_warmup,
  the error_policy object, the facade "components bundle", `set_venue_metadata`'s arg shape).
- The named warmup-depth function's exact name/home within `cache_registration.py`.

## Deferred Ideas
- SafetyController / ReconciliationCoordinator / StreamRecoveryHandler + CONTROL routes + pre-trade
  throttle → **P7** (facade bodies untouched in P6; interim gates repoint there).
- Full ErrorPolicy formalization (EventHandler injection, fail-fast/live split, CF-1 circuit breaker,
  replay fail-fast) → **P8**.
- CF-10 K-computation + per-symbol ring sizing → future deeper-warmup roster.
- TEST-02 (live-smoke) / TEST-03 (config-restart) / TEST-04 (multi-portfolio attribution) → **P12**
  (need the P7/P9/P11 surface). Only TEST-01 was pulled forward.
