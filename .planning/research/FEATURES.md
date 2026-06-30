# Feature Research

**Domain:** Live crypto-trading deployment layer (paper-first, single-venue OKX) over a complete event-driven backtest engine
**Researched:** 2026-06-30
**Confidence:** HIGH (locked design + verified venue/lib specifics; LOW flags called out inline)

> Scope guard: this researches the FEATURE-LEVEL behaviors that must work *within* the locked
> milestone design (`docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md`,
> LX-01..LX-15). It does NOT re-litigate locked decisions. Where a behavior is fixed by a locked
> decision it is tagged (e.g. `[LX-13]`) and treated as a constraint, not an open option.
> "Complexity" is engineering cost *given the existing engine*; "Dependencies" name the existing
> components a behavior leans on. Phase tags map to the 6 locked phases.

---

## Verified venue/library facts (the load-bearing ones)

These three facts shape almost every table-stakes behavior below:

1. **OKX `candle{tf}` WS channel carries a `confirm` flag** — the candle payload is
   `[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]`; `confirm="1"` = closed/final,
   `confirm="0"` = still forming. The first message after subscribe may be an incomplete bucket.
   *(HIGH — OKX v5 docs.)* This is the authoritative bar-close signal (LX-08); wall-clock inference
   is unnecessary and wrong.
2. **ccxt.pro `watchOHLCV` returns the still-forming last candle** — it emits the current bucket on
   every update (and typically the prior formed candle), so a naive "take `[-1]`" leaks an unconfirmed
   bar into the engine. The LiveBarFeed MUST gate on `confirm` (native field) and only emit on the
   transition `0→1` (or the arrival of a new bucket that closes the prior one). *(HIGH — ccxt issues +
   pro manual; this is exactly why LX-12 keeps a native escape hatch for confirm-flag fidelity.)*
3. **REST `fetch_ohlcv` returns closed bars** and is the correct warmup/backfill/gap-fill source;
   it is paginated and rate-limited. *(HIGH — ccxt unified method.)*

A fourth, lower-confidence flag carried for plan-time: OKX `orders`/`fills` private channels deliver
partial fills as incremental `fillSz`/`accFillSz` updates with an order `state`
(`live`/`partially_filled`/`filled`/`canceled`); fees and funding arrive on their own events. *(MEDIUM
— consistent across OKX docs + ccxt `watchOrders`/`watchMyTrades`, exact field cadence is the Phase 2/5
plan-time research item already flagged in the sketch §8.)*

---

## Feature Landscape

The 7 question areas are grouped under each category. Each row notes complexity and the existing
component it depends on.

### Table Stakes (Required to be Correct/Safe)

| # | Feature | Why Required | Complexity | Phase / Depends on |
|---|---------|--------------|------------|--------------------|
| **Live data engine** |
| 1 | **Bar-close detection via OKX `confirm` flag** — emit a `BarEvent` only on a *completed* bar; never on the forming bucket | Strategies/indicators are built on closed-bar semantics (bar-feed rule 2); a forming bar = look-ahead + indicator corruption. ccxt streams the forming candle, so this gate is mandatory, not optional | MEDIUM | P3. `BarFeed` ABC; 7-rule contract in `bar_feed.py`; OKX connector data arm (P2) |
| 2 | **Warmup/backfill at live-start through the *identical* `update(bar)` path** [LX-09] | Stateful O(1) indicators (SMA/EMA/MACD/RSI) need K prior bars to be "ready"; a second bulk-warm path diverges and re-opens the parity audit. REST `fetch_ohlcv` last-K, replayed one-by-one | MEDIUM | P3. Stateful indicators (v1.5); `cache_capacity()` derivation; REST data arm |
| 3 | **Monotonic-forward-only delivery** [LX-10] — gap→backfill-and-replay; duplicate→drop; out-of-order/stale→reject; reconnect→gap-fill interim | Stateful indicators have **no rewind**; feeding state backward silently corrupts every downstream decision. This is the single hardest correctness property of the live feed | HIGH | P3. Ring-buffer feed; stateful indicators; connector reconnect (P2) |
| 4 | **Ring-buffer `BarFeed` impl serving `window()`/`newest_bar()`/`current_bars()`** [LX-07] | The engine above the feed speaks one contract; only the backing store changes (precompute→stream). Bounded deque per `(symbol, tf)` sized by the same wiring-time capacity as backtest | MEDIUM | P3. `BarFeed` ABC (the seam already exists) |
| 5 | **Event-driven time source replacing `TimeGenerator`** — closed-bar arrival drives the cycle | Backtest iterates a pinned grid; live has no grid — the closed bar *is* the clock tick | MEDIUM | P3. `EventHandler` TIME/BAR routes; `generate_bar_event` factory |
| **Live execution loop** |
| 6 | **Order submit→ack→fill-stream lifecycle** (market/limit/stop on OKX) | A live venue is async and authoritative: you submit, get an order-id ack, then fills arrive asynchronously on a stream — unlike backtest where `on_bar` returns fills synchronously | HIGH | P2/P5. `LiveConnector` interface; order mirror (v1.6); async/sync bridge |
| 7 | **Partial-fill handling** — accumulate `accFillSz`, weighted-avg fill price, terminalize only at full fill/cancel | Real venues fill in pieces; the engine's `MatchingEngine` is full-quantity-only (D-06). The *live* path must reconcile partials the matching engine never produces | HIGH | P5. Order mirror reconcile (`on_fill`); `VenueAccount` |
| 8 | **Order-status reconciliation from venue truth** — map OKX `state` → mirror status (`live`→PENDING, `partially_filled`/`filled`→FILLED, `canceled`→CANCELLED, rejected→REJECTED) | The venue, not the engine, is the source of truth live. Mirror must follow venue state transitions, same shape as today's `OrderHandler.on_fill` reconcile | MEDIUM | P5. Order mirror; `VALID_ORDER_TRANSITIONS`; SQL order store (v1.6) |
| 9 | **Idempotent client order IDs** (`clOrdId`) on every submit | Resend after a timeout/reconnect must not double-submit; the venue dedupes on client id. The engine already has a single UUIDv7 scheme to source these | LOW | P2. `idgen` (UUIDv7); `LiveConnector` |
| **Paper trading** |
| 10 | **Local paper reuses the pure `MatchingEngine` + fee/slippage, bar-based fills only** [LX-06/LX-13] | This is the milestone DoD's correctness anchor: same matching core → deterministic → paper-parity holds. A `PaperConnector` composes the I/O-free engine (`submit`/`on_bar→decisions`) | MEDIUM | P4. `MatchingEngine`; fee/slippage models; `SimulatedAccount` (P1) |
| 11 | **Paper-parity gate vs the backtest oracle on a fixed dataset** [LX-11] | Live has no golden-master; paper-parity-vs-backtest is the closest equivalent. Replaying a fixed dataset through the live path offline must reproduce `134 / 46189.87730727451` | HIGH | P4. Oracle harness; `SimulatedAccount`; `LiveBarFeed` |
| 12 | **`SimulatedAccount` computes balance/margin locally (paper + backtest)** [LX-03] | Paper shares the *backtest's* computation column — that shared math is exactly what preserves parity. Same spot/margin code, verbatim | MEDIUM | P1. `Portfolio`/`cash` managers; margin model (v1.4) |
| **Account abstraction** |
| 13 | **`Account` ABC owning balance/margin truth; `Simulated*` vs `Venue*` leaves; cash-vs-margin axis** [LX-03] | Margin/liq logic currently mis-housed in `PortfolioHandler` is an *account* concept; extracting it cleanly is the oracle-gated Phase 1 refactor that everything live depends on | HIGH | P1. `Portfolio`, `PortfolioHandler` (margin/liq methods); v1.4 margin model. **Must stay byte-exact** |
| 14 | **`VenueAccount` caches venue balance/margin/position streams** [LX-03] | Live cannot compute truth locally (fees, funding, venue rounding diverge); it caches what the venue reports and reconciles | MEDIUM | P5. `LiveConnector` balances/positions stream; `Account` ABC (P1) |
| 15 | **1 account : 1 portfolio** [LX-04] — one OKX subaccount per strategy-portfolio | Dissolves venue-aggregate→per-portfolio *attribution* at the source; reconciliation collapses to per-symbol drift. Assumes exclusive control of the (sub)account | LOW (constraint, not code) | P1/P5. `Portfolio`; `Account` |
| **Venue reconciliation** |
| 16 | **Per-symbol drift detection** (partial fills, fees, funding, liquidations) under 1:1 | Without it, cached `VenueAccount` silently diverges from reality and the engine trades on a phantom balance — the core live-safety property | HIGH | P5. `VenueAccount`; SQL portfolio-state store (v1.6); connector streams |
| 17 | **Repair policy: halt-and-alert on unexplained drift** (auto-correct only within a defined tolerance) | Trading through an unreconciled discrepancy is how live systems blow up. Default-safe = stop and surface; auto-correct is the *narrow* exception, not the rule | MEDIUM | P5. `LiveTradingSystem` publish-and-continue error seam; `ErrorEvent` |
| **Persistence live-drive** |
| 18 | **Drive the v1.6 operational store with the real feed** (orders / portfolio-state / signals write-through) | The store was built + testcontainer-verified but never driven by a live feed; live is where write-through/purge-on-terminalize actually run | MEDIUM | P5. SqlOrderStorage, SqlPortfolioStateStorage, SqlSignalStorage (v1.6) |
| 19 | **Restart rehydration against a live venue** — reconstruct working set from store *and* reconcile vs venue | v1.6 rehydration was store-only; the broker side needs the live adapter so a restart doesn't resurrect a stale position the venue already closed | HIGH | P5. v1.6 open-only restart rehydration; `VenueAccount`; reconciliation (#16) |
| **Resilience / operational** |
| 20 | **WebSocket reconnect with gap recovery** — connector owns transport reconnect; feed owns bar-gap fill | Streams drop; a silent reconnect that skips bars corrupts indicators. Reconnect must trigger the gap-fill path (#3) | HIGH | P2 (transport) + P3 (gap-fill). Connector; ring-buffer feed |
| 21 | **Rate-limit handling** shared across ccxt + native paths | OKX throttles REST + WS subscribe; uncoordinated calls across the two paths get the connection banned | MEDIUM | P2. `OkxConnector` (ccxt.pro + native escape hatch) |
| 22 | **Secrets management** — real OKX key/secret out of code; sandbox vs live key separation tied to the single `sandbox` flag | Live adds real credentials; leaking them = direct financial loss | LOW | P2/cross-cutting. `pydantic-settings` `Settings` (`ITRADER_` prefix), `SecretStr` |
| 23 | **Single `sandbox: bool` routing both ccxt (`set_sandbox_mode`) and native (`x-simulated-trading` header)** [LX-05] | A split-brain live/demo state (one path live, one demo) is a catastrophic foot-gun; one flag, both paths | LOW | P2. `OkxConnector`; `Settings` |
| 24 | **FL-13: test coverage on the live surface** (`LiveTradingSystem`/`TradingInterface`) | The live composition root is currently uncovered; build coverage as each phase lands, not after | MEDIUM | All live phases. `LiveTradingSystem`; LX-14 `TradingInterface` decision |
| **Dynamic universe** |
| 25 | **Warmup-on-add** — a newly added symbol replays history through the same `update(bar)` path | Adding a symbol mid-run with cold indicators = garbage signals; reuses Phase 3's backfill machinery | MEDIUM | P6. Phase 3 backfill-through-update; `universe/membership.py` (D-20) |
| 26 | **Open-position-handling-on-remove** | Dropping a symbol that holds an open position silently orphans risk; must have a defined policy (force-close vs orphan-and-track) | MEDIUM | P6. `Portfolio` position manager; order submit path |

### Differentiators (Beyond Correct-and-Safe)

| Feature | Value Proposition | Complexity | Phase / Depends on |
|---------|-------------------|------------|--------------------|
| **Connector abstraction is ours, not ccxt's** [LX-05] — `LiveConnector` shaped on OKX reality, ccxt.pro default + native escape hatch hidden behind it | Keeps OKX fidelity (confirm flag, order-status nuance) *and* a cheap 2nd-venue path; most frameworks either marry ccxt or hand-roll one venue. This is the structural bet | HIGH | P2. New interface; reuse `ccxt_provider.py`/`binance_stream.py` plumbing |
| **Trade-aggregation-capable bar source seam** [LX-12] — klines now, trades behind the same bar-close interface later | Future optionality (slippage research, tick-backtester) without paying for it now; justified by optionality, NOT by paper fills | LOW (seam only) | P3. Ingestion seam in `LiveBarFeed` |
| **Separate-worker / process-per-portfolio runtime** [LX-15] — engine as its own service, FastAPI controls lifecycle via the Postgres system-of-record | Crash isolation, independent scaling, thin web layer. This is *precisely* what v1.6's durable store + restart rehydration were built to enable | HIGH | Cross-cutting (decide before P4 wiring). v1.6 store-as-truth; restart rehydration |
| **Deterministic offline parity harness** — replay a recorded/fixed dataset through the live thread | Turns "did live break?" from a guess into a regression test; reuses the byte-exact oracle | MEDIUM | P4. Oracle; determinism seams (seeded RNG, injected clock) |
| **OKX sandbox-validated real order arm** | A real I/O path proven against demo before any capital — de-risks the eventual real-money stretch | MEDIUM | P5. `OkxConnector` order arm; `x-simulated-trading` |

### Anti-Features (Out of Scope — Do NOT Build)

| Feature | Why It Seems Appealing | Why Problematic Here | Instead (locked) |
|---------|------------------------|----------------------|------------------|
| **Tick-level local-paper fills** | "More realistic" sub-bar fills | Breaks determinism + the paper-parity gate (the whole DoD); explodes complexity; sub-bar realism is what OKX *sandbox* is for | Bar-based local paper via reused `MatchingEngine` [LX-13]; sub-bar realism lives in OKX sandbox |
| **Full production screener** | Mature frameworks have rich universe selection | Massive scope; not needed to deploy one strategy live | Lean poll seam only — `UniverseSelectionModel` growing `membership.py` [sketch §1, P6] |
| **Multi-venue / multi-asset** | "Trade everywhere" | Each venue is months of fidelity work; dilutes the OKX correctness focus | Crypto-first, OKX-only; `LiveConnector` *shaped* for a 2nd venue but only OKX implemented [LX-05] |
| **Perp realism "Phase B" (funding accrual, mark-price liq trigger, funding pipeline, freqtrade 4th oracle)** | Perps are the dominant crypto product | Additive on the v1.4 Phase-A core; its own future milestone; would derail the paper-parity gate | Deferred (FUND-01..04) [sketch §1] |
| **Cross-margin pooling** | Capital efficiency across positions | A backtest-accounting driver, distinct from live reconciliation; conflicts with 1:1 | Deferred beyond N+2 Phase B; isolated-margin under 1:1 [sketch §1, LX-04] |
| **Bulk `warmup_from(series)` fast-path** | Faster live-start than one-by-one replay | A second state-building path diverges from the live `update(bar)` path and re-opens the parity audit | Replay K bars one-by-one through the identical `update(bar)` path [LX-09] |
| **Wall-clock bar-close inference** | Works when a venue has no confirm flag | OKX *has* a confirm flag; wall-clock guessing mis-fires on venue latency/clock skew and emits a forming bar | Drive "closed" off OKX `confirm`, never wall-clock [LX-08] |
| **In-process engine inside the FastAPI process** | Simplest to wire | Couples engine + web lifecycles, mixes 3 event loops in one process, one crash kills both | Separate worker / process-per-portfolio via Postgres SoR [LX-15 b/c] |
| **Async engine core** | The venue is async | Would rewrite the whole synchronous event engine; the async boundary belongs only at the connector edge | Async bottled in the connector thread; engine stays synchronous [sketch P2] |
| **Auto-correct-everything reconciliation** | "Self-healing" | Trading through unexplained drift hides real bugs/loss | Halt-and-alert default; auto-correct only within a defined tolerance (#17) |

---

## Feature Dependencies

```
Phase 1: Account abstraction (Account ABC, Simulated* leaves, Venue* interface-only)
    ├──gates──> SimulatedAccount math (#12)        ──required-by──> Paper parity (#11)
    └──gates──> VenueAccount interface (#14)        ──required-by──> Reconciliation (#16)

Phase 2: OKX connector (LiveConnector + OkxConnector, data arm + order arm)
    ├── data arm ──required-by──> LiveBarFeed (#1,#4) [Phase 3]
    └── order arm ──required-by──> Live real path (#6,#7,#8) [Phase 5]

Phase 3: LiveBarFeed
    ├── bar-close detection (#1) ──requires──> connector data arm + OKX confirm flag
    ├── warmup-through-update (#2) ──requires──> stateful indicators (v1.5)
    ├── monotonic-forward-only (#3) ──requires──> ring buffer (#4) + reconnect (#20)
    └── backfill machinery ──reused-by──> warmup-on-add (#25) [Phase 6]

Phase 4: Paper path (DoD)
    └──requires──> Phase 1 (SimulatedAccount) + Phase 3 (LiveBarFeed) + connector DATA arm
        (NOT the order arm) ──validated-by──> paper-parity gate (#11)

Phase 5: Live real path
    └──requires──> Phase 2 order arm + Phase 1 VenueAccount + v1.6 SQL store
        ├── reconciliation (#16) ──required-by──> restart rehydration vs venue (#19)
        └── partial fills (#7) ──feeds──> order-status reconcile (#8) ──writes──> SQL order store

Phase 6: Dynamic universe
    └──pairs-with──> Phase 3 (reuses backfill-through-update for warmup-on-add #25)

Cross-cutting (Phases 2–5): runtime topology [LX-15] ──decide-before──> Phase 4 wiring
                            reconnect/rate-limit/secrets/FL-13 ──woven-through──> each phase
```

### Dependency Notes

- **Paper parity (#11) requires SimulatedAccount (#12) sharing the backtest computation column.**
  Paper sits in the middle column of the parity spine but borrows the *left* (backtest) column's math —
  that shared computation is the only thing that makes parity hold. If paper computed anything its own
  way, the gate is meaningless.
- **LiveBarFeed monotonic-forward-only (#3) requires reconnect (#20) to route into gap-fill, not
  re-subscribe-fresh.** A reconnect that just resubscribes silently skips the interim bars; it must
  detect the gap and REST-backfill-and-replay through `update(bar)`.
- **Restart rehydration vs venue (#19) requires reconciliation (#16).** Rehydrating the working set
  from the store alone (v1.6 behavior) can resurrect a position the venue closed while the worker was
  down; the broker-side reconcile is the new live half.
- **Phase 1 is the universal gate** — it is behavior-preserving and oracle-gated; *no live code may
  depend on the Account abstraction until backtest is re-confirmed byte-exact* (`134 / 46189.87730727451`).
- **Warmup-on-add (#25) reuses Phase 3 backfill (#2)** — same `update(bar)` replay path, so Phase 6 is
  cheap *only if* Phase 3 built the seam generically (per-symbol, not start-only).

---

## Paper-Parity Requirements (concrete + testable — the DoD anchor)

For the paper-parity gate [LX-11] to be meaningful and pass, ALL must hold:

1. **Same matching core.** Local paper composes the *same* `MatchingEngine` instance class the backtest
   uses (full-quantity fills, next-bar-open, OCO, STOP-beats-LIMIT, trailing ratchet) — no
   paper-specific fill logic. [LX-06]
2. **Same account math.** `SimulatedAccount` runs the verbatim spot/margin/carry/liquidation code
   extracted in Phase 1 — Decimal end-to-end, same quantization boundaries. [LX-03]
3. **Same closed bars, same order.** The fixed dataset replayed through `LiveBarFeed` must deliver the
   identical sequence of closed `Bar`s (same timestamps, same Decimal OHLCV) the `BacktestBarFeed`
   produces — proving bar-close detection + warmup-through-update introduce no drift.
4. **Same determinism seams.** The seeded `random.Random` (`performance.rng_seed=42`) and injected
   clock must thread into the paper path; fills must not consume wall-clock time or unsourced RNG.
5. **Byte-exact equality, not tolerance.** The parity assertion reuses the oracle's exact-diff
   discipline: `134` trades and `final_equity == 46189.87730727451` — `check_exact=True`, no float
   tolerance.
6. **Inertness on the backtest hot path.** The live machinery must be provably inert when not running
   live — no W1/W2 regression vs the v1.5 baseline (15.7 s / 152.8 MB), same as the v1.6 import-quarantine
   discipline.

**Testable harness shape (open item, sketch §4):** prefer *replay a fixed dataset through the live path
offline* (deterministic, CI-runnable) over *record-a-live-session-then-replay* (non-deterministic,
network-bound). The offline replay feeds a recorded/fixed bar stream into `LiveBarFeed` and asserts the
oracle numbers — this is also the differentiator "deterministic offline parity harness."

---

## MVP Definition (maps to the locked phases)

### Launch With (the milestone DoD)

- [ ] **Phase 1 — Account abstraction** (#13, #12, #14-interface, #15) — gates everything; backtest stays byte-exact
- [ ] **Phase 2 — OKX connector data + order arm** (#6, #9, #21, #23) — feeds Phases 3/5
- [ ] **Phase 3 — LiveBarFeed** (#1, #2, #3, #4, #5, #20) — the real-time data engine
- [ ] **Phase 4 — Paper path + parity gate** (#10, #11, #12) — *this is the DoD* (LX-01)
- [ ] **Phase 5 — Real/sandbox path** (#7, #8, #14, #16, #17, #18, #19) — sandbox-validated
- [ ] **Phase 6 — Dynamic universe** (#25, #26) — lean poll seam
- [ ] **Cross-cutting** — secrets (#22), FL-13 (#24), runtime topology decision (LX-15)

### Add After Validation (gated stretch / next milestones)

- [ ] **Real-capital execution** — gated stretch beyond sandbox validation [LX-01]; trigger = sandbox path proven + owner sign-off
- [ ] **Async/buffered write-through** — keep-only-measured; build only if the live loop profiles a stall [sketch P5]
- [ ] **Trade-aggregation bar source** — slot behind the LX-12 seam; trigger = slippage-research or tick-backtester need

### Future Consideration (explicitly deferred)

- [ ] **Perp realism Phase B** (FUND-01..04) — own milestone
- [ ] **Full production screener** — beyond the lean poll seam
- [ ] **Multi-venue / multi-asset** — 2nd connector against the shaped interface
- [ ] **Cross-margin pooling** — backtest-accounting driver, distinct concern

---

## Feature Prioritization Matrix

| Feature | Safety/Value | Implementation Cost | Priority |
|---------|--------------|---------------------|----------|
| Account abstraction (oracle-gated) (#13) | HIGH (gates all) | HIGH | P1 |
| Bar-close via confirm flag (#1) | HIGH | MEDIUM | P1 |
| Monotonic-forward-only delivery (#3) | HIGH | HIGH | P1 |
| Warmup-through-update (#2) | HIGH | MEDIUM | P1 |
| Paper-parity gate (#11) | HIGH (the DoD) | HIGH | P1 |
| Local paper via reused MatchingEngine (#10) | HIGH | MEDIUM | P1 |
| Submit→ack→fill lifecycle (#6) | HIGH | HIGH | P1 |
| Partial-fill handling (#7) | HIGH | HIGH | P1 |
| Per-symbol drift reconciliation (#16) | HIGH | HIGH | P1 |
| Halt-and-alert repair policy (#17) | HIGH | MEDIUM | P1 |
| WS reconnect + gap recovery (#20) | HIGH | HIGH | P1 |
| Restart rehydration vs venue (#19) | HIGH | HIGH | P1 |
| Secrets + single sandbox flag (#22, #23) | HIGH | LOW | P1 |
| Idempotent client order IDs (#9) | MEDIUM | LOW | P1 |
| Rate-limit handling (#21) | MEDIUM | MEDIUM | P2 |
| Persistence live-drive (#18) | MEDIUM | MEDIUM | P2 |
| Dynamic universe add/remove (#25, #26) | MEDIUM | MEDIUM | P2 |
| Separate-worker runtime (LX-15) | MEDIUM | HIGH | P2 |
| Trade-aggregation seam (LX-12) | LOW | LOW | P3 |

**Priority key:** P1 = required for the DoD; P2 = should-have in-milestone; P3 = seam-only/future.

---

## Competitor Feature Analysis (how mature frameworks handle these)

| Feature | Nautilus Trader | freqtrade | Hummingbot | QuantConnect LEAN | iTrader approach |
|---------|-----------------|-----------|------------|-------------------|------------------|
| Bar-close detection | Bar aggregator emits on close; venue confirm where available | Polls closed candles; treats last as incomplete | Real-time order-book/trade driven; candles secondary | Consolidators emit on bar close; data feed-driven | OKX `confirm` flag, never wall-clock [LX-08] |
| Warmup/backfill | History request → same handler path; "warmup range" | `startup_candle_count` REST prefetch | N/A (order-book first) | Warm-up period replays through algorithm | One-by-one replay through identical `update(bar)` [LX-09] |
| Gap/reconnect | Reconnect + subscription resync; data-quality checks | Re-fetch on each loop (poll model masks gaps) | Auto-reconnect; order-book resync | Brokerage reconnect + data resync | Gap→REST-backfill-replay; forward-only [LX-10] |
| Account truth | `Account` per venue; cached from venue, reconciled | Wallet object synced from exchange | Per-connector budget checker | `SecurityHolding`/cash synced from brokerage | `Simulated*` computes / `Venue*` caches [LX-03] |
| Paper trading | `BacktestEngine` reuse + sandbox adapters | dry-run mode (simulated wallet, live data) | paper_trade mode (simulated balances) | Paper brokerage on live data | Reused pure `MatchingEngine`, bar-based [LX-06/13] |
| Reconciliation | Built-in venue reconciliation on start/stream | Re-sync open trades vs exchange | Status polling per order | Brokerage reconcile of holdings/orders | Per-symbol drift under 1:1, halt-and-alert [LX-04] |
| Connector model | Native per-venue adapters | ccxt-based | Native per-connector | Native brokerage plugins | Ours over ccxt.pro + native escape hatch [LX-05] |
| Universe | Full instrument provider / discovery | pairlists (rich) | Fixed config markets | Universe selection framework | Lean poll seam only (anti: full screener) |
| Runtime | Standalone node/process | Single process + (optional) API | Standalone | Cloud/standalone engine | Separate worker via Postgres SoR [LX-15] |

**Takeaway:** every behavior in the table-stakes list is something *all four* mature frameworks
implement — confirming they are genuine table-stakes, not gold-plating. iTrader's distinctive choices
(reused pure matching engine for paper, ours-over-ccxt connector, Postgres-as-system-of-record runtime)
are deliberate differentiators that fall out of the existing engine's structure (the parity spine, v1.6
durable store). The deferred items (full screener, multi-venue, perps) are exactly where the mature
frameworks have spent years — correctly out of scope for "minimum surface to deploy live."

---

## Sources

- OKX v5 WebSocket candle channel `confirm` flag — [OKX API guide](https://www.okx.com/docs-v5/en/) (HIGH)
- ccxt.pro `watchOHLCV` returns forming last candle — [CCXT Pro Manual](https://docs.ccxt.com/docs/pro-manual), [ccxt #24107](https://github.com/ccxt/ccxt/issues/24107) (HIGH)
- Locked milestone design — `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` (LX-01..LX-15) (HIGH)
- Existing engine seams — `itrader/price_handler/feed/bar_feed.py` (7-rule contract), `itrader/execution_handler/matching_engine.py` (pure I/O-free engine), `CLAUDE.md` architecture (HIGH)
- Project state — `.planning/PROJECT.md` (v1.7 section, validated requirements) (HIGH)
- Framework patterns (Nautilus/freqtrade/Hummingbot/LEAN) — training-data + design-sketch references; the per-cell behaviors are MEDIUM (well-established, not freshly re-verified per framework this session)

---
*Feature research for: live crypto-trading deployment layer (paper-first OKX) over an event-driven backtest engine*
*Researched: 2026-06-30*
