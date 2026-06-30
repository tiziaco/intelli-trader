# Project Research Summary

**Project:** iTrader v1.7 — Live Trading Readiness (paper-first OKX, trimmed N+4)
**Domain:** Live crypto trading deployment layer over an event-driven, Decimal-exact, deterministic backtest engine
**Researched:** 2026-06-30
**Confidence:** HIGH (all four researchers grounded in the locked design LX-01..LX-15 + direct source reading; MEDIUM on two OKX/ccxt externals called out below)

---

## Executive Summary

iTrader v1.7 adds live OKX trading to a proven event-driven backtest engine — paper-first, with a correctness gate anchored to the byte-exact oracle (`134 trades / 46189.87730727451`). The defining structural insight from all four researchers is that **v1.5's BarFeed ABC and MatchingEngine were built for this**: the engine above the feed already speaks one contract, and switching the backing store from a precomputed frame to a ring buffer is the bulk of Phase 3's work. Similarly, the `PortfolioReadModel` Protocol seam means the Phase 1 Account abstraction extraction does not ripple into the order domain at all — it is code-motion, not re-architecture. The headline stack finding is equally reassuring: **almost nothing new is strictly required**. ccxt.pro is already inside the free `ccxt` package you ship; the asyncio bridge is stdlib; `pytest-asyncio` is the only real addition. OkxSettings and the order-arm secrets module are deferred to Phase 5.

The six-phase structure is load-bearing: Phase 1 is the universal oracle-gated gate (everything live depends on Account abstraction being behavior-preserving), Phase 3 is where complexity concentrates on the data path (monotonic-forward-only delivery + reconnect gap-fill + warmup-through-update), and Phase 5 is the reconciliation cluster (partial fills, broker-side restart, write-through ordering, VenueAccount drift policy). Phase 4 (PaperConnector + paper-parity gate) is the milestone DoD and is reachable with only the data arm of the connector — no live order I/O required.

The dominant risk is the forming-bar / confirm-flag problem: ccxt's unified `watchOHLCV` does not surface OKX's `confirm` field (ccxt issue #21885), so a native escape hatch at the connector edge is mandatory before the feed can safely emit `BarEvent`s. This single fact — verified against the OKX v5 docs and ccxt tracker — is the anchor for LX-05/LX-08 and must be plumbed in Phase 2 before Phase 3 can close. The second dominant risk is the Phase 5 reconciliation cluster, where broker-side restart, partial fills, fee ingest, and write-through ordering converge and interact; that phase warrants its own plan-time research sprint.

---

## Key Findings

### Recommended Stack

The existing stack needs only a minor ccxt bump (`^4.5.56` -> `^4.5.62`), stdlib `asyncio` for the bridge (no new library), and `pytest-asyncio ^1.4.0` in the dev group. ccxt.pro is free, in-package, and already shipped; `import ccxt.pro as ccxtpro` unlocks `watch_ohlcv`, `watch_orders`, `watch_balance`, and `create_order_ws` with zero additional install. The asyncio bridge follows a proven, dependency-free pattern: connector owns `asyncio.new_event_loop()` on a daemon thread; `run_coroutine_threadsafe` submits work into the loop; outbound `global_queue.put(event)` is thread-safe stdlib. OkxSettings (`ITRADER_OKX_*` env prefix, `SecretStr` for all three credentials including the mandatory passphrase, `sandbox: bool`) is deferred to Phase 5.

**Core technologies:**
- `ccxt ^4.5.62` (bump existing pin): ccxt.pro live data + order arm via in-package async/WS surface — no new install, no license key
- Python stdlib `asyncio` (3.13): connector event loop on daemon thread, `run_coroutine_threadsafe` bridge — zero new dependencies
- `pytest-asyncio ^1.4.0`: async test driver — required; must be configured with `asyncio_mode` + `asyncio_default_fixture_loop_scope` or `filterwarnings=["error"]` escalates its deprecation warnings
- `aiohttp` (transitive via ccxt async): verify it resolves in `poetry.lock`; do not pin explicitly
- `python-okx 0.4.1` / `janus 2.0.0` / `redis ^5`: do NOT add up front — each is a flagged candidate only on a proven, documented gap

**Critical version interaction:** `pytest-asyncio` emits `PytestDeprecationWarning` when `asyncio_default_fixture_loop_scope` is unset; under `filterwarnings=["error"]` this fails the suite. Set both `asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "function"` in `pyproject.toml`. Do not redefine the `event_loop` fixture.

### Expected Features

The 26 identified behaviors split cleanly across the six phases. The DoD is Phase 4 (paper-parity gate). Phase 5 is the "should-have in-milestone" cluster; Phase 6 is the lean poll seam only.

**Must have — Phase 1 (gates everything):**
- Account ABC + `SimulatedCashAccount` / `SimulatedMarginAccount` leaves (code-motion, byte-exact)
- `Portfolio` receives injected `self.account`; `cash` -> `account.balance`
- Margin/liq math moved from `PortfolioHandler` to `SimulatedMarginAccount`; liquidation *emission* stays in the handler (queue-only rule preserved)
- `Portfolio.user_id` stripped (app-layer concern); `TradingInterface` deleted (replaced by typed engine command surface)
- `LiveConnector` Protocol defined (interface-only in Phase 1)
- Oracle re-confirmed byte-exact after extraction

**Must have — Phases 2 + 3 (feed pipeline):**
- `OkxConnector` data arm: `watch_ohlcv` via ccxt.pro + native OKX `confirm` flag via escape hatch (LX-05/LX-08) — the confirm field is the enabling prerequisite for the whole feed
- `LiveBarFeed(BarFeed)` ring buffer: `deque(maxlen=cap)` per `(symbol, timeframe)`, capacity derived from `cache_capacity()` same as backtest
- Bar-close detection emits `BarEvent` only on `confirm == 1`; bar `time` = venue bar-open stamp (not wall-clock)
- Warmup/backfill: REST `fetch_ohlcv` last-K, replayed one-by-one through the identical `update(bar)` path (LX-09) — no bulk fast-path exists
- Monotonic-forward-only delivery: gap -> REST-backfill-and-replay; duplicate -> drop; stale/OOO -> reject; reconnect -> gap-fill
- WS reconnect with gap recovery; rate-limit handling coordinated across ccxt and native paths

**Must have — Phase 4 (the DoD):**
- `PaperConnector(LiveConnector)`: composes `MatchingEngine` + `apply_costs` helper (extracted from `_emit_fill`) + `SimulatedAccount` — no OKX I/O
- Paper-parity gate: replay fixed dataset -> assert `134 / 46189.87730727451`; byte-exact, not tolerance-based
- `TimeEvent` synthesized on each closed-bar arrival so existing `_routes` TIME-before-BAR ordering holds
- Determinism seams: seeded RNG + business-time stamping thread through the paper path

**Must have — Phase 5 (real/sandbox path):**
- `OkxConnector` order arm: `create_order` (async REST) + `watch_orders` / `watch_fills`; single `sandbox: bool` routes both ccxt (`set_sandbox_mode`) and native (`x-simulated-trading` header)
- `VenueAccount` impl: caches venue balance/margin/position streams, reconciles per-symbol drift (LX-04 1:1)
- Partial-fill handling: accumulate by fill ID; terminalize only at full fill or venue-reported closed
- Restart rehydration two-sided: store + broker reconcile (not store-only)
- Write-through live-drive: create/terminalize sync-durable; append/metrics writes buffered only if profiled necessary
- Halt-and-alert drift policy; auto-correct only within defined tolerance
- `OkxSettings(BaseSettings)` with `SecretStr` for all three OKX credentials

**Must have — Phase 6:**
- Warmup-on-add (reuses Phase 3 `update(bar)` backfill path per-symbol)
- Open-position-handling-on-remove (force-close vs orphan-and-track policy defined)
- Lean universe membership poll seam only — not the production screener

**Defer (explicitly out of scope — do not build):**
- Tick-level local-paper fills (LX-13: bar-based only; sub-bar realism lives in OKX sandbox)
- Bulk `warmup_from(series)` fast-path (LX-09: forbidden — opens parity audit)
- Wall-clock bar-close inference (LX-08: always drive from `confirm`)
- Perp realism Phase B (FUND-01..04): own future milestone
- Full production screener: lean poll seam only
- Multi-venue / multi-asset: connector interface *shaped* for a 2nd venue but only OKX implemented
- Cross-margin pooling: deferred beyond N+2 Phase B
- In-process engine inside FastAPI (LX-15: separate worker process)
- Auto-correct-everything reconciliation: halt-and-alert is the safe default

### Architecture Approach

The integration spine is the `PortfolioReadModel` Protocol at the center: the order domain already reads through it, so re-homing balance/margin truth into an `Account` abstraction does not ripple into `OrderManager` or the validator. Phase 1 is pure code-motion behind an existing seam. The async->sync boundary is bottled entirely at the connector edge: the connector runs its own asyncio loop on its own daemon thread and only calls `global_queue.put(frozen_event)` — the existing D-19 single-writer contract is never crossed. All state mutation stays on the engine's dispatch thread.

**Major new/modified components:**
1. `Account` ABC + `portfolio_handler/account/` package — NEW; `SimulatedCashAccount` (CashManager code-motion), `SimulatedMarginAccount` (liq math from PortfolioHandler); `VenueAccount` interface-only in P1, implemented in P5
2. `Portfolio` — MODIFIED: inject `self.account`; `cash` -> `account.balance`; `user_id` stripped
3. `PortfolioHandler` — MODIFIED: margin/liq math moved out; `_run_liquidation_pass` emission stays (queue-only rule)
4. `TradingInterface` — DELETED; replaced by typed engine command surface consuming from Postgres command channel
5. `LiveConnector` Protocol — NEW: data arm (`watch_ohlcv` / `fetch_ohlcv`), order arm (`submit` / `cancel` / `watch_fills`), account arm (`fetch_balances` / `watch_balances` / `fetch_positions`)
6. `OkxConnector` — NEW: ccxt.pro default + native OKX escape hatch behind the interface; single `sandbox: bool` routes both arms
7. `LiveBarFeed(BarFeed)` — NEW: `price_handler/feed/live_bar_feed.py`; ring buffer; same ABC the engine already consumes
8. `apply_costs` helper — NEW: extracted from `SimulatedExchange._emit_fill` (byte-exact); shared by both `SimulatedExchange` and `PaperConnector`; eliminates dual fill-pricing drift
9. `PaperConnector(LiveConnector)` — NEW: `MatchingEngine` + `apply_costs` + `SimulatedAccount`; no OKX I/O; bar-based fills only
10. `VenueAccount` impl — NEW (Phase 5): caches + reconciles connector balance/position/fill streams under LX-04
11. Worker process + Postgres command/status channel — NEW (Phase 5): ships as (b) architected as (c) with N=1

**Runtime topology recommendation (LX-15):** Ship option (b) — separate worker — architected as (c) per-portfolio with N=1. Rationale: (a) in-process couples FastAPI + connector asyncio + engine sync thread in one OS process; (b)/(c) activates the v1.6 store-as-truth investment; LX-04's 1:1 constraint makes per-portfolio process isolation natural from day one. Decide before Phase 4 wiring. Default IPC: Postgres LISTEN/NOTIFY (zero new dep, reuses v1.6).

### Critical Pitfalls

1. **Forming-bar acted on (confirm-flag gap in ccxt)** — ccxt's `watchOHLCV` does not surface OKX's `confirm` field (ccxt #21885); paper-parity fails immediately and silently. Prevention: `OkxConnector` reads native OKX candle `confirm` field via escape hatch; `LiveBarFeed` emits `BarEvent` only on `confirm == 1`. Plumbed in Phase 2; enforced in Phase 3.

2. **ccxt returns floats — Decimal boundary violation** — every ccxt price/amount/fee/balance is a float; `Decimal(some_ccxt_float)` is binary-float poison. Prevention: all ccxt->Decimal conversion at connector edge through `to_money(x)` = `Decimal(str(x))` (D-04); string precision helpers for outbound quantities. Applies Phase 2 + Phase 5.

3. **Wall-clock leaking into business `time`** — existing `LiveTradingSystem` already has multiple `datetime.now(UTC)` usages; the pattern is contagious. Prevention: connector stamps domain events from venue bar-open timestamps; audit every `datetime.now` on the live path before merge. Business time never equals wall clock.

4. **Backfill divergence from a fast-path (LX-09 violation)** — a bulk `warmup_from(series)` alongside `update()` is a second state-building path; stateful indicators have no rewind. Prevention: LX-09 is absolute — one-by-one `update(bar)` only; never add `warmup_from`/`seed`/`prime` to any indicator or feed API.

5. **Phase 5 reconciliation cluster — broker-side restart gap** — v1.6 restart rehydration was store-only; a live restart on store-only resurrects positions the venue closed. Prevention: two-sided restart: store rehydration + live venue fetch + idempotent downtime fill replay + bracket parent/child re-establishment from venue truth.

---

## Implications for Roadmap

### Phase 1: Account Abstraction Extraction (Oracle-Gated Refactor)

**Rationale:** The universal prerequisite. Every live component depends on `Account` being the stable truth surface. Behavior-preserving code-motion behind the existing `PortfolioReadModel` seam — does not ripple into the order domain. Must be oracle-confirmed byte-exact before any live code merges.

**Delivers:** `Account` ABC + `SimulatedCashAccount` (CashManager code-motion) + `SimulatedMarginAccount` (liq math from PortfolioHandler); `Portfolio` receives `self.account`; `PortfolioHandler` emission path untouched; `Portfolio.user_id` stripped; `TradingInterface` deleted; `LiveConnector` Protocol defined (interface-only); oracle byte-exact confirmed (`134 / 46189.87730727451`).

**Key constraint:** `_process_transaction_spot` is byte-exact site #2 — operand-for-operand identical Decimal ops, in order; `apply_fill_cash_flow` full-precision no-quantize contract preserved. Gate: oracle numbers + determinism double-run + `mypy --strict`.

**Avoids:** Liquidation math left in PortfolioHandler (A6); user_id on Account (A5); downstream parity failures from mis-homed truth.

**Research flag:** Skip — v1.2 MOD-01 OrderManager-decomposition playbook; well-established pattern.

---

### Phase 2: OKX Connector (Data Arm + Order Arm)

**Rationale:** The connector supplies the closed-bar stream Phase 3 consumes and the order arm Phase 5 exercises. The data arm's native `confirm` flag read is the enabling prerequisite for the whole feed. Must precede Phase 3.

**Delivers:** `OkxConnector(LiveConnector)` with ccxt.pro `watch_ohlcv` + native OKX `confirm` field; REST `fetch_ohlcv`; async REST `create_order` + `watch_orders`/`watch_fills` (order arm for Phase 5); single `sandbox: bool` routes both ccxt and native paths; `load_markets` lot/tick/contract-size validation; idempotent client order IDs via `idgen` UUIDv7; rate-limit coordination; `SecretStr` secret loading.

**Architecture:** connector owns its asyncio loop on a daemon thread; only calls `global_queue.put(...)` on the engine side (D-19 preserved). `pytest-asyncio` unit tests use mocked transports.

**Avoids:** Pitfalls 1 (forming bar), 6 (ccxt float), 7 (OKX rounding), 8 (async races), 9 (blocking loop), 15 (split-brain), 16 (secrets leakage), 18 (strict-suite warnings).

**Research flag:** NEEDS PLAN-TIME RESEARCH — OKX `confirm` exact behavior + ccxt.pro gap list; `set_sandbox_mode` WS header verification; demo key requirements.

---

### Phase 3: LiveBarFeed (Real-Time Data Engine)

**Rationale:** Most unique live complexity concentrates here. Monotonic-forward-only delivery with reconnect gap-fill has no backtest equivalent. Must follow Phase 2.

**Delivers:** `LiveBarFeed(BarFeed)` ring buffer (`deque(maxlen=cap)` per symbol/tf, same capacity derivation as backtest); bar-close detection on `confirm == 1`; warmup/backfill through `update(bar)` one-by-one (LX-09); monotonic-forward-only enforcement; `TimeEvent` synthesized on each closed bar (recommended — preserves TIME-before-BAR route ordering); event-driven time source replaces `TimeGenerator` on the live path.

**Key seam decision at plan time:** emit paired `TimeEvent` on bar close (recommended) vs. move metric recording to BAR route.

**Avoids:** Pitfalls 1 (forming bar), 4 (backfill fast-path), 5 (backward indicator feed).

**Research flag:** NEEDS PLAN-TIME RESEARCH — ring-buffer capacity with multiple timeframes/consumers; reconnect debounce strategy; after-the-fact venue bar correction policy (re-warm vs forward-only-and-log).

---

### Phase 4: Paper Path + Parity Gate (The DoD)

**Rationale:** The milestone DoD. Requires Phase 1 + Phase 3 + connector data arm only — no order arm, no OKX credentials. The paper path is reachable without any live order I/O.

**Delivers:** `PaperConnector(LiveConnector)` composing `MatchingEngine` + shared `apply_costs` helper (byte-exact extraction) + `SimulatedAccount`; bar-based fills only (LX-13); `FillEvent.time = T + tf_base` (next-bar-open via reused `MatchingEngine`); determinism seams throughout (seeded RNG + business-time stamping); paper-parity gate: `134 / 46189.87730727451`, `check_exact=True`.

**Pre-wiring requirement:** LX-15 topology decision must be committed before Phase 4 wires the live runtime.

**Avoids:** Pitfalls 2 (next-bar-open off-by-one), 3 (wall-clock in business time), A3 (dual fill pricing from two separate cost implementations).

**Research flag:** NEEDS PLAN-TIME RESEARCH — parity harness design (offline replay of fixed dataset recommended); LX-15 topology decision + Postgres LISTEN/NOTIFY vs Redis; determinism seam threading in live runtime.

---

### Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive

**Rationale:** The reconciliation cluster — heaviest phase by unique live complexity. Five concerns converge: VenueAccount, partial fills, broker-side restart, write-through ordering, fee ingest. Warrants its own plan-time research sprint.

**Delivers:** `OkxConnector` order arm vs OKX demo; `VenueAccount` implementation (per-symbol drift under LX-04 1:1); partial-fill handling (fill-ID dedup, `accFillSz` accumulation, terminalize on venue-closed); two-sided restart reconciliation; halt-and-alert drift policy; v1.6 SQL store driven by real feed (create/terminalize sync-durable; writes buffered only if profiled stalling); venue fee ingest via `to_money`; `OkxSettings` with three `SecretStr` credentials.

**Avoids:** Pitfalls 6 (ccxt float in VenueAccount), 10 (engine as source of truth), 11 (partial/duplicate fills), 12 (fee drift), 13 (broker-side restart gap), 14 (write ordering / loop stall).

**Research flag:** NEEDS PLAN-TIME RESEARCH — reconciliation drift/repair policy (tolerance thresholds, halt triggers, auto-correct scope); write-through transaction boundary design; OKX partial-fill field cadence; bracket restart from venue truth.

---

### Phase 6: Dynamic Universe (Lean Poll Seam)

**Rationale:** Pairs with Phase 3 — warmup-on-add reuses the Phase 3 `update(bar)` backfill path. Cheap only if Phase 3 built the seam generically (per-symbol, not start-only).

**Delivers:** Lean universe membership poll seam; warmup-on-add via `update(bar)` (reuses Phase 3 path); open-position-handling-on-remove policy defined. Does NOT deliver full screener, multi-venue, cross-margin, or perp funding.

**Avoids:** Pitfall 17 (over-building screener/screener chains).

**Research flag:** Skip — reuses Phase 3 backfill seam; standard patterns if Phase 3 is built generically.

---

### Phase Ordering Rationale

- **Phase 1 is the hard gate** — oracle-gated; no live code may be written against Account until backtest re-confirmed byte-exact. Non-negotiable.
- **Phase 2 before Phase 3** — `LiveBarFeed` consumes the connector's data arm + native `confirm` field. Cannot build the feed without the connector.
- **Phase 4 DoD reachable at Phase 3 + data arm only** — critical sequencing insight: paper-parity requires no order arm, no OKX sandbox access, no live credentials. Fastest path to the milestone gate.
- **Phase 5 after Phase 4** — order arm + VenueAccount + reconciliation require the paper path proven before real money is risked, even on sandbox.
- **Phase 6 last** — pairs with Phase 3's backfill seam; no new hard dependencies beyond the live path being live.
- **LX-15 topology decided before Phase 4 wiring** — worker process structure is cross-cutting; wiring Phase 4 without a topology decision creates rework.

---

### Watch Out For

These are the failure modes all four researchers independently flagged:

1. **Forming-bar / confirm-flag paper-parity risk** — the single most likely source of parity failure; the native escape hatch is mandatory. Plan-time: produce the OKX ccxt-vs-native gap list before Phase 2 design is locked.

2. **ccxt returns floats everywhere** — no `to_money` call exists yet in any ccxt order/balance/fee path (existing providers only convert OHLCV rows). Every new connector method handling prices/amounts/fees/balances must route through `to_money`. The failure mode is invisible until reconciliation drift accumulates.

3. **Wall-clock in business time is contagious** — the existing `LiveTradingSystem` has multiple `datetime.now(UTC)` usages. Audit every new `datetime.now` before merge; especially likely in error-handling paths.

4. **Phase 5 reconciliation policy is the most under-specified area** — do not start Phase 5 without decisions on: (a) auto-correct tolerance thresholds, (b) halt-and-alert trigger conditions, (c) bracket parent/child restart re-establishment, (d) write-through transaction boundary. Build a research sprint into Phase 5 planning.

5. **`filterwarnings=["error"]` + async tests** — any unclosed ccxt.pro session/transport or unset `asyncio_default_fixture_loop_scope` fails the entire suite. Use mocked/recorded connectors for unit tests. Never relax the global filter.

6. **Scope creep is the second most likely derailer** — the connector interface invites generalization; sub-bar fills feel "more real"; screener seam looks half-built. The trimmed-N+4 posture is explicit: paper-parity DoD at Phase 4, one venue, bar-based only, lean screener. Every "while I'm here" must be deferred with a note, not absorbed.

---

### Research Flags

**Needs plan-time research sprint:**
- **Phase 2:** OKX `confirm` flag exact behavior + ccxt.pro gap list; `set_sandbox_mode` WS header; demo key requirements
- **Phase 4:** Parity harness design (offline replay recommended); LX-15 topology decision; determinism seam in live runtime
- **Phase 5:** Reconciliation drift/repair policy; write-through transaction boundary; OKX partial-fill field cadence; bracket restart from venue truth

**Standard patterns (skip dedicated research phase):**
- **Phase 1:** v1.2 MOD-01 playbook; `PortfolioReadModel` seam already in place; code-motion only
- **Phase 3:** `BarFeed` ABC seam exists; ring buffer is bounded deque; monotonic enforcement mirrors BacktestBarFeed cursor discipline
- **Phase 6:** Reuses Phase 3 backfill-through-update; lean membership seam is well-scoped

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | ccxt.pro packaging verified (in-package, free, merged v1.95); asyncio bridge pattern (stdlib, dependency-free, canonical); `pytest-asyncio` filterwarnings interaction documented. MEDIUM: `python-okx`/`janus` as candidates — flagged, not selected |
| Features | HIGH | All 26 behaviors grounded in locked design LX-01..LX-15 + existing engine code. LOW flag: OKX partial-fill field cadence (consistent across docs, not freshly re-verified live) |
| Architecture | HIGH | Account layering read from source (`portfolio.py`, `portfolio_handler.py`, `cash/cash_manager.py`, `core/portfolio_read_model.py`); `TradingInterface` deletion grep-confirmed no production consumers; BarFeed ABC seam; MatchingEngine purity. MEDIUM: OKX confirm-flag exposure in ccxt.pro (web-sourced; verify at Phase 2 plan time) |
| Pitfalls | HIGH (engine-internal) / MEDIUM-HIGH (OKX/ccxt) | Engine-internal pitfalls read directly from source. OKX/ccxt pitfalls verified against ccxt issues + OKX v5 docs; exact behavior confirmed at plan time |

**Overall confidence:** HIGH on Phase 1 (pure internal refactor); HIGH on Phases 2-4 except confirm-flag gap-list detail (MEDIUM); MEDIUM-HIGH on Phase 5 (reconciliation policy and write-through boundary are the under-specified areas).

### Gaps to Address

The following five open questions were flagged independently by all four researchers (sketch §8 convergent open items):

1. **OKX `confirm` flag reliability + native-vs-ccxt gap list** — determine the full list of OKX behaviors ccxt.pro does not surface; validate `set_sandbox_mode(True)` applies `x-simulated-trading` on both REST and WS. How to handle: Phase 2 plan-time research; block Phase 2 design until resolved.

2. **Reconciliation drift/repair policy** — specific tolerance thresholds, halt-and-alert triggers, auto-correct scope, bracket parent/child re-establishment on restart. How to handle: Phase 5 plan-time research sprint; do not start Phase 5 coding until decided and documented.

3. **Parity harness design** — offline replay of a fixed dataset (recommended: CI-runnable, deterministic) vs. record-a-live-session-then-replay (non-deterministic, network-bound). How to handle: decide in Phase 4 planning; offline replay strongly recommended, aligns with byte-exact oracle discipline.

4. **Write-through transaction boundary** — which operations are sync-durable before the irreversible venue action (create, terminalize), which can be buffered (append, metrics), and when buffering is profile-gated vs. always-on. This is the v1.6 carried flag. How to handle: Phase 5 plan-time; default sync for create/terminalize, measure before buffering anything else.

5. **LX-15 topology decision before Phase 4 wiring** — option (b) separate worker architected as (c) with N=1 is recommended; Postgres LISTEN/NOTIFY default (zero new dep). How to handle: decide in Phase 3/4 planning handoff; default to Postgres LISTEN/NOTIFY and revisit only if a concrete latency/durability gap is proven.

---

## Sources

### Primary (HIGH confidence)
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` (LX-01..LX-15) — locked design, phase structure, parity spine
- `itrader/portfolio_handler/portfolio.py`, `portfolio_handler.py`, `cash/cash_manager.py` — Account layering source analysis
- `itrader/core/portfolio_read_model.py` — seam confirmation
- `itrader/price_handler/feed/bar_feed.py` — 7-rule bar-timing contract; BacktestBarFeed cursor discipline; BarFeed ABC
- `itrader/execution_handler/matching_engine.py`, `exchanges/simulated.py` — MatchingEngine purity; `_emit_fill` cost helper extraction site
- `itrader/trading_system/live_trading_system.py`, `trading_interface.py` — `TradingInterface` no-consumer grep; existing `datetime.now` wall-clock usages
- `itrader/core/money.py` — D-04 `to_money(x)` = `Decimal(str(x))`
- https://docs.ccxt.com/docs/pro-manual — ccxt.pro `watch_*` surface, `createOrderWs`, import structure
- https://pypi.org/project/ccxt/ — ccxt 4.5.62; in-package ccxt.pro (free, merged v1.95, issue #15171)
- https://www.okx.com/docs-v5/en/ — OKX v5 WS candle `confirm` field; `x-simulated-trading` header; passphrase requirement
- https://pypi.org/project/pytest-asyncio/ — `asyncio_default_fixture_loop_scope` config; `event_loop` fixture deprecation

### Secondary (MEDIUM confidence)
- https://github.com/ccxt/ccxt/issues/21885 — ccxt `watchOHLCV` does not surface `closed`/`confirm` flag; native escape hatch required
- https://github.com/ccxt/ccxt/issues/17710 — OKX amount precision / contract-size multiple rejection
- https://github.com/ccxt/ccxt/issues/7415 — OKX `create_order` `InvalidOperation` (float precision symptom)
- https://github.com/ccxt/ccxt/issues/11923, /11855, /17295 — OKX `set_sandbox_mode` + demo header + WS demo caveats
- https://pypi.org/project/python-okx/ (0.4.1), https://github.com/burakoner/okx-sdk (5.5.812) — native escape-hatch candidates (flagged, not selected)
- https://pypi.org/project/janus/ (2.0.0) — sync/async queue candidate (flagged, not recommended)
- Framework patterns (Nautilus 1.227.0, freqtrade, Hummingbot, QuantConnect LEAN) — table-stakes feature confirmation; iTrader's distinctive choices mapped against industry norms

---
*Research completed: 2026-06-30*
*Ready for roadmap: yes*
