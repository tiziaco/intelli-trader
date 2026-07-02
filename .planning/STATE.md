---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Live Trading Readiness
status: planning
stopped_at: Phase 5 context gathered
last_updated: "2026-07-02T15:56:59.392Z"
last_activity: 2026-07-02
progress:
  total_phases: 7
  completed_phases: 4
  total_plans: 20
  completed_plans: 20
  percent: 57
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-30 — v1.7 Live Trading Readiness active; roadmap created)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle 134 / `46189.87730727451`; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 adds a **live operating mode (paper-first on OKX)** with a real correctness gate
(**paper-parity vs that oracle**) — **without disturbing the byte-exact backtest path**.
**Current focus:** Phase 5 — real/sandbox path + reconciliation + persistence live drive

## Current Position

Phase: 5
Plan: Not started
Status: Ready to plan
Last activity: 2026-07-02

Progress: [██████████] 100%

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

- Total plans completed: 251 (v1.0 62 + v1.1 28 + v1.2 23 + v1.3 20 + v1.4 35 + v1.5 26 + v1.6 21)
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

- [Phase ?]: D-04 resolved: SMA_MACD oracle runs the SPOT path — SimulatedCashAccount is the verbatim-critical leaf for plan 01-02 (enable_margin=False default + run_backtest.py LONG_ONLY)
- [Phase ?]: [Phase 1 / 01-04] D-09 recorded: only the surviving engine-command-surface PRINCIPLE is locked (FastAPI -> thin typed command surface, never into LiveTradingSystem internals); concrete method set deferred to Phase 4 (scopes FL-13). TradingInterface deleted (D-08/LX-14) — dead pre-FastAPI bridge with a quantity: float live-path leak; removal helps the no-float-money gate (ACCT-05).
- [Phase 01]: 01-02: SimulatedCashAccount = CashManager moved byte-for-byte (D-05); .available is a thin Decimal alias of verbatim available_balance to satisfy the Account ABC without altering internals (byte-exact)
- [Phase 01]: 01-02: SimulatedMarginAccount gains set_universe/_universe — the margin/liq math-pulldown (ACCT-02) moves its Universe dependency down with the math; dark this wave, wired in 01-03. Liquidation emission shell stays in PortfolioHandler
- [Phase ?]: 01-03: Portfolio/PortfolioHandler delegate all balance/margin/liq truth to the injected Account leaf behind the FROZEN PortfolioReadModel seam; margin surface narrowed via cast/isinstance; liquidation shells skip spot accounts; CashManager deleted; oracle held byte-exact.
- [Phase ?]: 01-03c: e2e margin scenarios construct the SimulatedMarginAccount leaf at CONSTRUCTION via enable_margin portfolio_config (01-03 D-03) — the post-construction update_config toggle no longer rebuilds the leaf; account caches no config at construction so a minimal enable_margin config suffices. e2e suite green (72 passed); user_id grep-zero across tests/e2e.
- [Phase ?]: 01-05: Terminal gate PASSED (ACCT-03) — Account extraction proven behavior-preserving: oracle byte-exact (134 / 46189.87730727451), determinism double-run identical, mypy --strict clean (214 files), full suite 1463 passed under filterwarnings=[error], no float-money introduced (edge casts only), no orphaned cash_manager/user_id reference, W1 oracle run within the 15.7s baseline
- [Phase 02]: 02-01: OkxSettings binds .api_key/.api_secret/.api_passphrase to plain OKX_API_* via validation_alias while keeping env_prefix='' (a bare field under env_prefix='' would read API_KEY not OKX_API_KEY); SecretStr masks the auth triple; passphrase required; OKX_SANDBOX aliases the demo flag (CONN-06 / D-10)
- [Phase 02]: 02-01: LiveConnector reshaped from a two-arm marker to a session/transport contract (call sync-RPC / spawn stream-task / client / sandbox / connect / disconnect) — the D-02 seam the three arms type against; async/sync bridge bottled at the connector edge; wspap demo-host correction recorded (WS demo via host, not the REST-only x-simulated-trading header)
- [Phase 02]: 02-02: OkxConnector = loop-on-daemon-thread + one ccxt.pro client built INSIDE the loop (Pitfall 3); single sandbox bool drives set_sandbox_mode (REST header + ccxt WS wspap host swap) AND the exposed flag the native socket keys off — no split-brain (CONN-03); call/spawn async-sync bridge, stream-task set cancelled on disconnect (CONN-04); no domain-event imports (D-02); exported from barrel (D-04)
- [Phase 02]: 02-03: OkxExchange = live sibling of SimulatedExchange (AbstractExchange), injected OkxConnector session (D-04, never the concretion); create/cancel via connector.call, watch_orders/watch_my_trades via connector.spawn; the EXCHANGE emits FillEvents on global_queue itself (D-07, D-19 MPSC-safe); Decimal edge held (to_money(str) inbound, ccxt amount/price_to_precision strings outbound, CONN-05); FillEvent.time from venue ms timestamp, never wall-clock; on_market_data no-op for live (CONN-02)
- [Phase 02]: 02-04: OkxDataProvider data arm — native /ws/v5/business candle socket is the confirm-flag escape hatch (ccxt watch_ohlcv drops confirm); gate on confirm==1 index 8 (forming bars dropped, CONN-01); native host driven off connector.sandbox (wspap vs ws, host not header, CONN-03); REST fetch_ohlcv backfill via shared client with to_money(str) Decimal edge (CONN-05); minimal set_bar_sink seam for Phase-3 LiveBarFeed (D-03); types LiveConnector Protocol only (D-04); mypy --strict clean
- [Phase ?]: 02-05: OkxConnector constructed ONCE at the LiveTradingSystem composition root and the LiveConnector session injected into the three arms (OkxExchange registered 'okx', OkxDataProvider, VenueAccount) — whole OKX stack lazy-imported inside the live path; init_exchanges unchanged; disconnect() wired into stop() (D-04/CONN-04)
- [Phase ?]: 02-05: VenueAccount LiveConnector import is TYPE_CHECKING-guarded because the account barrel is on the backtest hot path — a runtime connectors-barrel import would pull ccxt.pro and break inertness; body still Phase 5 (RECON-01)
- [Phase ?]: 02-05: milestone gate green — fresh-subprocess inertness test asserts itrader.connectors.okx + ccxt.pro absent after a backtest-root import; SMA_MACD oracle byte-exact (134 / 46189.87730727451); suite 1498 passed / 1 skipped
- [Phase ?]: 03-01: D-12 resolved — ClosedBar carries its own (symbol, timeframe) routing keys; live path stamps from self._symbol/self._timeframe, backfill path from method params (ad-hoc symbol correctness); keys never read from the untrusted venue row (T-03-01-TAMPER). Shared socket-free tests/unit/price/conftest.py fixtures (closed_bar, closed_bar_sequence, _StubProvider) stand up the LiveBarFeed offline matrix.
- [Phase 03]: 03-02: LiveBarFeed(BarFeed) — capacity-sized deque ring per (symbol,timeframe) + FEED-04 monotonic guard (in-sequence/gap-backfill-replay/duplicate/revision/stale, D-06/D-07) + direct single-ticker BarEvent emission (D-02/D-03/D-04); dormant no-op generate_bar_event (D-05); public set_provider seam (D-01/D-13); TYPE_CHECKING ClosedBar import + absent from feed barrel keeps it hot-path-inert
- [Phase ?]: 03-04: LiveBarFeed lazy-wired as the live driver at the LiveTradingSystem composition root (FEED-05) — provider-less unconditional construct + okx-arm set_provider injection (writes private _provider warmup reads) + set_bar_sink(feed.update); D-13 _LiveWarmupConsumer(max strategy.warmup) registered before bind so cache_capacity()==100 (Pitfall 1 guard); warmup OKX-gated before start_stream. Inertness probe extended to forbid live_bar_feed on the backtest path; oracle byte-exact.
- [Phase 04]: 04-01: ReplayDataProvider = offline synchronous stand-in for OkxDataProvider replaying the golden CsvPriceStore as Decimal-edge ClosedBar dicts (to_money(str) edge, ts=int(index.value//1e6) epoch-ms bar-open, symbol/timeframe stamped from config not the row D-12); drop-in on set_bar_sink/fetch_ohlcv_backfill + synchronous replay_bar replacing the async _stream_candles (D-03); ClosedBar imported not redefined; golden rows via CsvPriceStore so iter is byte-identical to backtest (parity anchor D-01/D-02). PAPER-03/COV-01 fixture.
- [Phase 04]: Paper venue reuses the 'simulated' SimulatedExchange as-is (D-04/D-05/D-06); run_paper_replay() drives golden bars synchronously through the real live seam with backtest per-tick + run-end discipline (parity by construction, D-01/D-09)
- [Phase ?]: 04-03: RUN-01 runnable paper worker (scripts/run_live_paper.py) delivered per D-08 — offline run_paper_replay (CI-safe default) + opt-in okx manual smoke over start/stop/get_status; channel + web-framework wrapper deferred to Phase 5. COV-01 lifecycle half added (FL-13: clean startup / graceful thread-joining stop / status-before-start, exchange=paper offline).
- [Phase ?]: 04-04: paper-parity DoD gate shipped (PAPER-04/COV-01) — one test drives run_paper_replay() AND a fresh backtest on the golden dataset, asserts trades+equity frame-equal EXACT (tz-normalized UTC); anchored to the fresh backtest not the frozen 46189 artifact (D-01), survives a backtest-loop rework; inertness _FORBIDDEN extended to replay_provider (D-12), oracle untouched

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

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260701-l33 | Add `smoke` pytest marker (register + tag 3 files + `make test-smoke` + tagging rule) | 2026-07-01 | 40c13992 | [260701-l33-add-smoke-marker](./quick/260701-l33-add-smoke-marker/) |
| 260702-m8d | Apply Phase 04 code-review fix-now bucket (IN-01..04, WR-05, WR-03, WR-02 window guard) + sync stale REQUIREMENTS.md | 2026-07-02 | 148836a6 | [260702-m8d-apply-phase-04-code-review-fix-now-bucke](./quick/260702-m8d-apply-phase-04-code-review-fix-now-bucke/) |
| Phase 03 P01 | 3min | 2 tasks | 4 files |
| Phase 03 P02 | 9min | 2 tasks | 2 files |
| Phase 03 P03 | 3min | 1 tasks | 2 files |
| Phase 03 P04 | 14min | 2 tasks | 4 files |
| Phase 04 P01 | 6min | 2 tasks | 2 files |
| Phase 04 P02 | 8min | 2 tasks | 1 files |
| Phase 04 P03 | 6min | 2 tasks | 2 files |
| Phase Phase 04 P04 P04 | 5min | 2 tasks | 2 files |

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
| Phase 01 P01 | 3min | 3 tasks | 5 files |
| Phase 01 P04 | 2min | 2 tasks | 3 files |
| Phase 01 P02 | 4min | 2 tasks | 2 files |
| Phase 1 P3 | 10 | 3 tasks | 11 files |
| Phase 01 P03b | 26min | 3 tasks | 38 files |
| Phase 01 P03c | 5min | 2 tasks | 59 files |
| Phase 01 P05 | 3min | 2 tasks | 1 files |
| Phase 02 P01 | 7min | 3 tasks | 8 files |
| Phase 02 P02 | 12min | 2 tasks | 3 files |
| Phase 02 P03 | 9min | 2 tasks | 2 files |
| Phase 02 P04 | 18min | 2 tasks | 2 files |
| Phase 02 P05 | 9min | 3 tasks | 4 files |

## Bookkeeping

- **At v1.6 close (done 2026-06-30):** v1.6 phase dirs `git mv`'d to `milestones/v1.6-phases/`;
  `ROADMAP`/`REQUIREMENTS`/`MILESTONE-AUDIT` archived as `milestones/v1.6-*`. Only the `999.3` backlog
  seed dir remains in `.planning/phases/`, so the new v1.7 `01-*..06-*` dirs will not collide.

- **At v1.7 close (reminder):** `git mv` the v1.7 phase dirs to `milestones/v1.7-phases/` and archive
  `ROADMAP`/`REQUIREMENTS`/`MILESTONE-AUDIT` as `milestones/v1.7-*`.

## Session Continuity

Last session: 2026-07-02T15:56:59.384Z
Stopped at: Phase 5 context gathered
Resume file: .planning/phases/05-real-sandbox-path-reconciliation-persistence-live-drive/05-CONTEXT.md
Carried todo: live-backfill-through-update (now Phase 3 / FEED-03); single-pass valuation (deferred, future perf)

## Operator Next Steps

- Plan Phase 1 (Account Abstraction) with `/gsd:plan-phase 1`.
