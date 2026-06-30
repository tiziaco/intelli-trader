# Requirements: iTrader v1.7 — Live Trading Readiness (trimmed N+4 / Backlog 999.3)

**Defined:** 2026-06-30
**Core Value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct,
deterministic, cross-validated numbers (oracle 134 / `46189.87730727451`; v1.5 W1 baseline 15.7 s /
152.8 MB). v1.7 adds a **live operating mode (paper-first on OKX)** with a real correctness gate
(**paper-parity vs that oracle**) — **without disturbing the byte-exact backtest path**.

**Design source:** `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` (LOCKED,
LX-01..LX-15) + `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS,SUMMARY}.md` (2026-06-30).

**Milestone gate (applies to EVERY phase):** the SMA_MACD backtest oracle stays **byte-exact**
(134 / `46189.87730727451`) with **no W1/W2 regression** vs the v1.5 baseline — the live machinery is
inert on the backtest hot path. Held throughout: Decimal money end-to-end (`to_money` at the connector
edge — ccxt returns floats); single UUIDv7; determinism (business `time`, never wall-clock); single
seeded RNG + injected clock; `mypy --strict` clean on new code; `filterwarnings=["error"]` green;
tabs/spaces indentation matched to the file.

## v1 Requirements

Requirements for the v1.7 milestone. Each maps to exactly one roadmap phase.

### Account Abstraction — Phase 1 (oracle-gated, behavior-preserving refactor)

- [x] **ACCT-01**: The engine exposes an `Account` abstraction owning balance/margin truth, with
  `SimulatedCashAccount` (CashManager code-motion) and `SimulatedMarginAccount` leaves; `Portfolio`
  delegates accounting to its injected `account` (`Portfolio.cash` → `Portfolio.account`). (LX-03)
- [x] **ACCT-02**: Margin/liquidation math (maintenance_margin, margin_ratio, liq price/penalty,
  liquidation *decision*, reserve/release) lives in the Account; the liquidation *emission*
  (`global_queue.put`) stays in `PortfolioHandler` (queue-only rule preserved).
- [ ] **ACCT-03**: The backtest oracle is re-confirmed **byte-exact** (134 / `46189.87730727451`)
  after the extraction — determinism double-run identical, `mypy --strict` clean, no float-for-money.
- [ ] **ACCT-04**: `Portfolio.user_id` is removed (app-layer multi-tenancy concern; NOT relocated onto
  `Account`); the constructor-signature ripple is resolved with the oracle held byte-exact.
- [x] **ACCT-05**: `TradingInterface` is evaluated and removed (or deliberately slimmed) per LX-14 —
  the surviving engine command surface is decided, scoping the FL-13 live-test coverage.
- [x] **ACCT-06**: The `LiveConnector` interface is defined (interface-only), with the `VenueAccount`
  leaf shaped interface-only, so Phases 2–5 implement against a stable contract.

### OKX Connector — Phase 2 (`LiveConnector` / `OkxConnector`)

- [ ] **CONN-01**: `OkxConnector` implements the `LiveConnector` **data arm** — ccxt.pro `watch_ohlcv`
  by default plus the native OKX candle **`confirm` flag** via the escape hatch, both behind the
  interface (LX-05/LX-08). (ccxt's unified `watchOHLCV` drops `confirm` — the native read is required.)
- [ ] **CONN-02**: `OkxConnector` implements the **order arm** — async `create_order` + cancel +
  `watch_orders`/`watch_fills` (exercised against sandbox in Phase 5).
- [ ] **CONN-03**: A single `sandbox: bool` routes **both** ccxt (`set_sandbox_mode`) and the native
  path (`x-simulated-trading` header) to OKX demo, and selects demo-vs-live keys — no split-brain.
- [ ] **CONN-04**: The connector runs its own asyncio loop on its own daemon thread and emits domain
  events onto `global_queue` only (D-19 single-writer preserved); the engine stays synchronous and the
  backtest path imports no async/connector code.
- [ ] **CONN-05**: Every ccxt float (price/amount/fee/balance) crosses the Decimal boundary at the
  connector edge via `to_money`; outbound quantities are rounded to OKX lot/tick using ccxt's string
  precision helpers (no `Decimal(float)`).
- [ ] **CONN-06**: OKX secrets (apiKey + secret + **passphrase**) load via an `OkxSettings(BaseSettings)`
  `SecretStr` layer (`ITRADER_OKX_*`); never in code or logs; the backtest path stays credential-free.

### Live Data Engine — Phase 3 (`LiveBarFeed`)

- [ ] **FEED-01**: `LiveBarFeed` implements the existing `BarFeed` ABC as a ring buffer (bounded
  `deque(maxlen)` per `(symbol, timeframe)`, capacity from the same wiring-time `cache_capacity()`
  derivation as backtest); strategies/screeners/execution consume it unchanged. (LX-07)
- [ ] **FEED-02**: A `BarEvent` is emitted **only on a completed bar** (`confirm == 1`), with bar
  `time` from the venue bar-open stamp (never wall-clock) — the 7-rule look-ahead contract holds. (LX-08)
- [ ] **FEED-03**: Live-start and gap warmup replay REST-fetched bars **one-by-one through the identical
  `update(bar)` path** — there is no bulk `warmup_from()` fast-path (LX-09, parity audit).
- [ ] **FEED-04**: Bar delivery is **monotonic-forward-only** (LX-10): gap → REST-backfill-and-replay;
  duplicate → drop; stale/out-of-order → reject; reconnect → gap-fill the interim (stateful indicators
  never fed backward).
- [ ] **FEED-05**: `LiveBarFeed` replaces `TimeGenerator`'s role on the live path (event-driven
  closed-bar arrival), preserving the engine's TIME-before-BAR route ordering downstream.

### Paper Path — Phase 4 (the milestone DoD)

- [ ] **PAPER-01**: `PaperConnector` implements `LiveConnector` by composing the **reused pure
  `MatchingEngine`** + the shared cost helper + `SimulatedAccount`, with **bar-based fills only**
  (LX-06/LX-13) and no OKX I/O.
- [ ] **PAPER-02**: Fee/slippage is extracted into a shared `apply_costs` helper used by **both**
  `SimulatedExchange` and `PaperConnector` (one cost core, byte-exact) — no dual fill-pricing drift.
- [ ] **PAPER-03**: `LiveTradingSystem` is wired end-to-end on the paper path (live feed → strategy →
  order → paper fill → `SimulatedAccount`/`Portfolio`), with the determinism seams (seeded RNG +
  business-time stamping) threaded through.
- [ ] **PAPER-04**: **Paper-parity gate (DoD)** — replaying the fixed golden dataset through the
  live-paper path yields the backtest oracle **byte-exact** (134 / `46189.87730727451`,
  `check_exact=True`). (LX-11)

### Real / Sandbox Path + Reconciliation + Persistence Live-Drive — Phase 5

- [ ] **RECON-01**: `VenueAccount` caches the connector's balance/margin/position streams and
  reconciles **per-symbol drift** under 1 account : 1 portfolio (LX-03/LX-04) — it caches venue truth,
  it does not compute.
- [ ] **RECON-02**: Partial-fill handling is correct and idempotent (fill-ID dedup, accumulation,
  terminalize only on full fill or venue-reported closed); the venue is source of truth in live.
- [ ] **RECON-03**: The drift-repair policy is **halt-and-alert by default**, with auto-correct only
  within a defined tolerance band.
- [ ] **RECON-04**: The v1.6 operational store (order / portfolio-state / signal) is **driven by the
  real OKX feed** — the live composition-root wiring is completed (resolves v1.6 D-01 / RETAIN-03),
  with create/terminalize writes sync-durable.
- [ ] **RECON-05**: Restart rehydration is **two-sided** — reconstruct the working set from the store
  AND reconcile against the live venue (the broker side the v1.6 store-only tests did not cover).
- [ ] **RECON-06**: Order I/O + `VenueAccount` reconciliation + persistence live-drive + restart
  rehydration are **validated against OKX sandbox** (real-money execution is a gated stretch, not in
  the DoD). (LX-01)

### Dynamic Universe Membership — Phase 6 (lean poll seam)

- [ ] **UNIV-01**: A lean universe-membership **poll seam** supports mid-run add/remove of symbols
  (grows `universe/membership.py` per its D-20 target) — NOT the full production screener.
- [ ] **UNIV-02**: Warmup-on-add replays the new symbol's history through the same `update(bar)` path
  (reuses the Phase 3 backfill machinery); the open-position-handling-on-remove policy is defined.

### Cross-Cutting (woven through Phases 2–5; each has one definite home phase)

- [ ] **RUN-01** (home: Phase 4): The live runtime/deployment topology is decided (LX-15) **before
  Phase 4 wires the runtime** — a separate worker process (ship option (b) architected as (c) with
  N=1), with Postgres `LISTEN/NOTIFY` as the default command/status channel (zero new dep, reuses the
  v1.6 store). Decided in the Phase 3→4 handoff; architected for Phases 2–5.
- [ ] **RES-01** (home: Phase 5): Live resilience is in place — websocket reconnect with gap recovery,
  rate-limit handling (coordinated across ccxt + native paths), partial-fill handling, and stream-gap
  recovery; `LiveTradingSystem`'s publish-and-continue error policy is hardened for live. Pieces build
  across Phases 2 (rate-limit) / 3 (reconnect+gap-recovery, FEED-04); fully verified on the real path.
- [ ] **COV-01** (home: Phase 4): The surviving live surface (`LiveTradingSystem` + the engine command
  surface from ACCT-05) has test coverage (**FL-13**) via mocked/recorded connectors, with
  `pytest-asyncio` configured (`asyncio_mode`, `asyncio_default_fixture_loop_scope`) so
  `filterwarnings=["error"]` stays green — the global filter is never relaxed. Established on the first
  end-to-end live surface (Phase 4); the `pytest-asyncio` infra lands in Phase 2; real-path surface
  coverage extends into Phase 5.

## v2 Requirements

Deferred to a future release — tracked, not in this roadmap.

### Perp Realism (Phase B)

- **FUND-01..04**: Funding-rate accrual, mark-price liquidation trigger, funding-data pipeline,
  `freqtrade` 4th cross-validation oracle. Additive on the v1.4 margin core; its own future milestone.

### Optimization

- **OPT-01**: Optuna sampler + parameter-sweep loop over the v1.6 results-store substrate (Optuna-FK-ready).

### Live data fidelity

- **TRADE-01**: Trade-aggregation bar source behind the same bar-close interface (LX-12 — klines now,
  trades-capable later); enables future slippage research / a tick-backtester. Local paper stays
  bar-based regardless (LX-13).

## Out of Scope

Explicitly excluded for v1.7. Documented to prevent scope creep (anti-features from research).

| Feature | Reason |
|---------|--------|
| Tick-level / sub-bar local-paper fills | LX-13 — local paper stays bar-based (the parity gate); sub-bar realism lives in OKX sandbox |
| Bulk `warmup_from(series)` fast-path | LX-09 — a second state-building path diverges and re-opens the parity audit |
| Wall-clock bar-close inference | LX-08 — bar-close is always driven from the venue `confirm` flag |
| Full production screener / ranking / rebalance loop | Only the lean membership poll seam lands here (D-screener) |
| Multi-venue / multi-asset | Crypto-first (locked 2026-06-08); the connector is *shaped* for a 2nd venue, only OKX implemented |
| Cross-margin pooling | A backtest-accounting driver, distinct from live reconciliation; consistent with 1 account:1 portfolio |
| Perp realism Phase B (funding / mark-price liq) | Additive on the v1.4 core; deferred to its own future milestone (v2 FUND-01..04) |
| In-process engine inside FastAPI | LX-15 — separate worker process; in-process couples web + connector asyncio + engine sync thread |
| Auto-correct-everything reconciliation | Halt-and-alert is the safe default; auto-correct only within a tolerance band (RECON-03) |
| Real-money (real-capital) live execution | LX-01 — the real path is sandbox-validated; real-money is a gated stretch beyond the DoD |

## Traceability

Which phases cover which requirements. Every v1 requirement maps to exactly one phase (the 3
cross-cutting requirements each have a definite home phase, flagged cross-cutting in the phase notes).

| Requirement | Phase | Status |
|-------------|-------|--------|
| ACCT-01 | Phase 1 | Complete |
| ACCT-02 | Phase 1 | Complete |
| ACCT-03 | Phase 1 | Pending |
| ACCT-04 | Phase 1 | Pending |
| ACCT-05 | Phase 1 | Complete |
| ACCT-06 | Phase 1 | Complete |
| CONN-01 | Phase 2 | Pending |
| CONN-02 | Phase 2 | Pending |
| CONN-03 | Phase 2 | Pending |
| CONN-04 | Phase 2 | Pending |
| CONN-05 | Phase 2 | Pending |
| CONN-06 | Phase 2 | Pending |
| FEED-01 | Phase 3 | Pending |
| FEED-02 | Phase 3 | Pending |
| FEED-03 | Phase 3 | Pending |
| FEED-04 | Phase 3 | Pending |
| FEED-05 | Phase 3 | Pending |
| PAPER-01 | Phase 4 | Pending |
| PAPER-02 | Phase 4 | Pending |
| PAPER-03 | Phase 4 | Pending |
| PAPER-04 | Phase 4 | Pending |
| RECON-01 | Phase 5 | Pending |
| RECON-02 | Phase 5 | Pending |
| RECON-03 | Phase 5 | Pending |
| RECON-04 | Phase 5 | Pending |
| RECON-05 | Phase 5 | Pending |
| RECON-06 | Phase 5 | Pending |
| UNIV-01 | Phase 6 | Pending |
| UNIV-02 | Phase 6 | Pending |
| RUN-01 | Phase 4 (home; decided in Phase 3→4 handoff, cross-cutting 2–5) | Pending |
| RES-01 | Phase 5 (home; pieces build in Phases 2–3, cross-cutting 2–5) | Pending |
| COV-01 | Phase 4 (home; infra in Phase 2, extends to Phase 5, cross-cutting 1–5) | Pending |

**Coverage:**
- v1 requirements: 32 total (29 phase-specific + 3 cross-cutting)
- Mapped to phases: 32 (Phase 1: 6, Phase 2: 6, Phase 3: 5, Phase 4: 6, Phase 5: 7, Phase 6: 2)
- Unmapped: 0

> **Count note (2026-06-30, roadmapper):** the pre-map coverage summary stated "31 total"; the
> traceability table enumerates **32** requirement IDs (ACCT ×6, CONN ×6, FEED ×5, PAPER ×4, RECON ×6,
> UNIV ×2 = 29 phase-specific; RUN-01 / RES-01 / COV-01 = 3 cross-cutting). The earlier "31" was an
> off-by-one; the actual count is 32, all mapped (0 orphans).

---
*Requirements defined: 2026-06-30*
*Last updated: 2026-06-30 — roadmap created (6 phases, numbering reset to Phase 1); cross-cutting homes finalized (RUN-01→P4, RES-01→P5, COV-01→P4); 32/32 mapped, 0 orphans.*
