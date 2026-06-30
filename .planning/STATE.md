---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Live Trading Readiness
status: planning
last_updated: "2026-06-30T17:30:00.000Z"
last_activity: 2026-06-30
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-30 — v1.7 Live Trading Readiness active; roadmap created)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle 134 / `46189.87730727451`; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 adds a **live operating mode (paper-first on OKX)** with a real correctness gate
(**paper-parity vs that oracle**) — **without disturbing the byte-exact backtest path**.
**Current focus:** Phase 1 — Account Abstraction + Portfolio/Handler refactor (oracle-gated). Ready to plan.

## Current Position

Phase: 1 of 6 (Account Abstraction + Portfolio/Handler Refactor)
Plan: — (not yet planned)
Status: Ready to plan
Last activity: 2026-06-30 — v1.7 roadmap created (6 phases, numbering reset to Phase 1); 32/32 requirements mapped

Progress: [░░░░░░░░░░] 0%

## Milestone Gate (v1.7 — applies to EVERY phase)

The live machinery is **inert on the backtest hot path**. Each phase carries the recurring gate:

1. **Oracle byte-exact** — SMA_MACD stays **134 / `46189.87730727451`** (`check_exact=True`),
   determinism double-run identical.
2. **No W1/W2 perf regression** vs the v1.5 frozen baseline (15.7 s / 152.8 MB) — the backtest path
   imports no async/connector code.

**Phase-specific gates:** Phase 1 = oracle re-confirmed byte-exact after the Account extraction (ACCT-03);
Phase 4 = **paper-parity gate (DoD)** — golden dataset replayed through the live-paper path yields the
oracle byte-exact (PAPER-04); Phase 5 = sandbox-validated real path (RECON-06).

**Held throughout, all phases:** Decimal money end-to-end (`to_money` at the connector edge — ccxt
returns floats); single UUIDv7; determinism (business `time`, never wall-clock); single seeded RNG +
injected clock; `mypy --strict` clean on new code; `filterwarnings=["error"]` green (`pytest-asyncio`
configured, global filter never relaxed); tabs/spaces indentation matched to the file.

## Phase Map (v1.7 — Phases 1-6, numbering reset)

Execution order: 1 (gates all) → 2 → 3 → 4 (DoD) → 5 → 6. Hard dependencies (design §7 / research
ARCHITECTURE): Phase 1 oracle-gated, gates everything; Phase 2 data arm feeds Phase 3; **Phase 4 DoD
reachable on 1 + 3 + connector data arm only (NOT the order arm)**; Phase 5 needs Phase 2 order arm +
Phase 1 `VenueAccount` + the v1.6 store; Phase 6 pairs with Phase 3 backfill. LX-15 topology (RUN-01)
decided in the Phase 3→4 handoff before Phase 4 wiring. Phase dirs `01-*..06-*` will not collide with the
`999.3` backlog placeholder (different prefix).

| Phase | Name | Requirements | Research flag |
|-------|------|--------------|---------------|
| 1 | Account Abstraction + Portfolio/Handler Refactor | ACCT-01..06 | SKIP (v1.2 MOD-01 playbook) |
| 2 | OKX Connector | CONN-01..06 | **NEEDS plan-time research** (OKX confirm + ccxt.pro gap list) |
| 3 | LiveBarFeed | FEED-01..05 | **NEEDS plan-time research** (ring capacity, reconnect, correction policy) |
| 4 | Paper Path (DoD) | PAPER-01..04, RUN-01, COV-01 | **NEEDS plan-time research** (parity harness + LX-15 topology) |
| 5 | Real/Sandbox + Reconciliation + Persistence Live-Drive | RECON-01..06, RES-01 | **NEEDS plan-time research SPRINT** (reconciliation + write-through boundary) |
| 6 | Dynamic Universe Membership | UNIV-01, UNIV-02 | SKIP (reuses Phase 3 backfill) |

**Cross-cutting homes:** RUN-01 → Phase 4 (decided before wiring), RES-01 → Phase 5 (pieces in 2–3),
COV-01 → Phase 4 (infra in 2, extends to 5). Coverage: **32/32 mapped, 0 orphans** (the pre-map "31"
was an off-by-one — see REQUIREMENTS.md count note).

## Performance Metrics

**Velocity (program cumulative through v1.6):**

- Total plans completed: 236 (v1.0 62 + v1.1 28 + v1.2 23 + v1.3 20 + v1.4 35 + v1.5 26 + v1.6 21)
- v1.7 plans completed: 0

*Updated after each plan completion. Per-milestone velocity is archived in the respective MILESTONE-AUDIT.md.*

## Accumulated Context

### Roadmap Evolution

- v1.7 roadmap created 2026-06-30 (promotes Backlog 999.3 / N+4 Live, trimmed): 6 phases derived from the
  LOCKED design sketch §4 (LX-01..LX-15) + research SUMMARY/ARCHITECTURE build order; all 32 requirements
  mapped (100% coverage, 0 orphans). Numbering reset to Phase 1 (matching v1.1–v1.6). Backlog 999.3 marked
  PROMOTED-TO-v1.7 (design intent retained as historical seed). The recurring milestone gate (oracle
  byte-exact + no W1/W2 regression — live machinery inert on the backtest hot path) is restated as a
  success criterion in every phase.

- Cross-cutting requirements given definite home phases: RUN-01 → Phase 4 (LX-15 topology decided before
  Phase 4 wires the runtime), RES-01 → Phase 5 (resilience fully verified on the real path; rate-limit
  built in Phase 2, reconnect+gap-recovery in Phase 3 FEED-04), COV-01 → Phase 4 (FL-13 on the first
  end-to-end live surface; `pytest-asyncio` infra lands Phase 2; real-path coverage extends to Phase 5).

### Decisions

Active program constraints live in PROJECT.md. v1.7-relevant locked decisions (design LX-01..LX-15):

- **Paper-first DoD (LX-01) + refactor-first (LX-02):** Phase 1 extracts the Account abstraction
  (oracle-gated, behavior-preserving) BEFORE any live code depends on it; the milestone DoD is the
  paper-parity gate (Phase 4), reachable on the connector **data arm only**.
- **Account owns balance/margin truth (LX-03), 1 account : 1 portfolio (LX-04):** `Simulated*` leaves
  compute, `Venue*` leaves cache; the order domain reads through the existing `PortfolioReadModel` seam,
  so Phase 1 is pure code-motion (no ripple into `OrderManager`/validator).
- **`LiveConnector` is ours over ccxt.pro (LX-05) + native escape hatch:** ccxt's unified `watchOHLCV`
  drops the OKX `confirm` flag (ccxt #21885) — the native read is mandatory before the feed can emit
  `BarEvent`s. Single `sandbox: bool` routes both ccxt + native (no split-brain).
- **`PaperConnector` reuses the pure `MatchingEngine` (LX-06) + a shared `apply_costs` helper** extracted
  byte-exact from `SimulatedExchange._emit_fill` (one matching core + one cost core; no dual fill-pricing).
- **`LiveBarFeed` = ring-buffer `BarFeed` (LX-07); confirm-flag closed-bar (LX-08); warmup through the
  identical `update(bar)` path, no bulk fast-path (LX-09); monotonic-forward-only (LX-10).**
- **Topology (LX-15):** ship separate worker process (option (b) architected as (c) with N=1), Postgres
  `LISTEN/NOTIFY` command/status channel (zero new dep, reuses the v1.6 store). Decide before Phase 4 wiring.
- **`TradingInterface` deleted (LX-14)** — no production consumer; replaced by a thin typed engine command
  surface routing through the real order domain. `Portfolio.user_id` stripped (app-layer concern).

### Pending Todos

[From .planning/todos/pending/ — carried; both now in-scope for v1.7]

- Live-start indicator backfill through the same `update(bar)` path (`live-backfill-through-update.md`)
  — **now Phase 3 (FEED-03 / LX-09)**: REST warmup replayed one-by-one through `update(bar)`, no bulk
  `warmup_from` fast-path.
- Correct single-pass per-bar portfolio valuation (`single-pass-portfolio-valuation.md`) — deferred
  v1.5, profile-first gated (future perf phase, NOT v1.7).

### Blockers/Concerns

- **Confirm-flag / forming-bar risk (research Pitfall 1):** the single most likely source of
  paper-parity failure — ccxt.pro does not surface OKX's `confirm` flag. The native escape hatch is
  mandatory; produce the OKX native-vs-ccxt gap list at Phase 2 plan time before locking the design.
- **ccxt returns floats everywhere (Pitfall 2):** every new connector price/amount/fee/balance must
  route through `to_money` (= `Decimal(str(x))`); failure is invisible until reconciliation drift accrues.
- **Wall-clock in business `time` is contagious (Pitfall 3):** existing `LiveTradingSystem` has multiple
  `datetime.now(UTC)` usages; audit every new `datetime.now` on the live path before merge.
- **Phase 5 reconciliation is the most under-specified area:** do not start coding without decisions on
  auto-correct tolerance, halt-and-alert triggers, bracket parent/child restart, write-through boundary
  (the v1.6 carried flag). Build a research sprint into Phase 5 planning.
- **`filterwarnings=["error"]` + async tests:** unclosed ccxt.pro session/transport or unset
  `asyncio_default_fixture_loop_scope` fails the whole suite. Use mocked/recorded connectors; never
  relax the global filter (`pytest-asyncio` configured in Phase 2).
- **Hot-path inertness (carried from v1.6):** the live machinery must add zero backtest hot-path cost —
  the backtest path imports no async/connector code. W1/W2 within v1.5 ±5% is the proof, every phase.
- **Indentation hazard:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`,
  `itrader/storage/`, events package use 4 spaces. New files MUST match the sibling — a mixed-indent tab
  file fails to import.
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not
  silently folded into a running phase.

## Deferred Items

Program-level items deferred across milestones; v1.7-relevant rows promoted INTO this milestone are marked.

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Live drive | Persistence driven by a real live feed + venue reconciliation (v1.6 store built/tested on testcontainers) | ⏳ **Promoted to v1.7** (Phase 5, RECON-04/05) | v1.7 |
| Live account | `Account` abstraction + reconciliation mirror (ACCT) | ⏳ **Promoted to v1.7** (Phase 1 + Phase 5 `VenueAccount`) | v1.7 |
| Live coverage | `LiveTradingSystem` test coverage (FL-13) | ⏳ **Promoted to v1.7** (COV-01, Phase 4→5) | v1.7 |
| Cleanup | `Portfolio.user_id` removal (app-layer multi-tenancy) | ⏳ **Promoted to v1.7** (ACCT-04, Phase 1) | v1.7 |
| D-screener | Production screener / ranking / rebalance loop | Deferred (v1.7 ships only the lean poll seam, Phase 6) | v2 |
| Optimization | Optuna sampler + sweep loop (OPT-01) — v1.6 ships the FK-ready substrate only | Deferred | v2 |
| Turso/libSQL | `sqlalchemy-libsql` opt-in backend (TURSO-01) — interface stays Turso-ready | Deferred | v2 (post-beta + measured) |
| Perp realism (Phase B) | FUND-01..04 (funding accrual, mark-price liq, funding pipeline, freqtrade oracle) | Deferred | v2 |
| Live data fidelity | TRADE-01 trade-aggregation bar source (LX-12; klines now, trades later) | Deferred | v2 |
| Perf (v1.5) | Correct single-pass per-bar portfolio valuation (profile-first gated) | Deferred | future perf phase |
| Perf (v1.5) | Nyquist VALIDATION.md gaps (advisory; oracle + A/B perf gate are the real lock) | Deferred | optional `/gsd:validate-phase` backfill |
| Deferred perf (v2) | PERF-09 / PERF-10 (strategy-level dedup, O(n²)-in-symbol guard) | Deferred | future (large universes) |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions | Deferred | indefinite (crypto-first) |

v1.0–v1.6 milestone-close acknowledgments are recorded in the respective MILESTONE-AUDIT.md files under
`milestones/`. v1.6 audit (`tech_debt`, no blockers): live composition-root wiring → promoted to v1.7
Phase 5 (D-01); draft Nyquist VALIDATION.md records on all 5 phases; ~13 WR-/IN- non-blocking review
warnings — all consciously accepted (see `milestones/v1.6-MILESTONE-AUDIT.md`).

## Bookkeeping

- **At v1.6 close (done 2026-06-30):** v1.6 phase dirs `git mv`'d to `milestones/v1.6-phases/`;
  `ROADMAP`/`REQUIREMENTS`/`MILESTONE-AUDIT` archived as `milestones/v1.6-*`. Only the `999.3` backlog
  seed dir remains in `.planning/phases/`, so the new v1.7 `01-*..06-*` dirs will not collide.
- **At v1.7 close (reminder):** `git mv` the v1.7 phase dirs to `milestones/v1.7-phases/` and archive
  `ROADMAP`/`REQUIREMENTS`/`MILESTONE-AUDIT` as `milestones/v1.7-*`.

## Session Continuity

Last session: 2026-06-30T17:30:00.000Z
Stopped at: v1.7 roadmap created (ROADMAP.md + STATE.md + REQUIREMENTS.md traceability written)
Resume file: None
Carried todo: live-backfill-through-update (now Phase 3 / FEED-03); single-pass valuation (deferred, future perf)

## Operator Next Steps

- Plan Phase 1 (Account Abstraction) with `/gsd:plan-phase 1`.
