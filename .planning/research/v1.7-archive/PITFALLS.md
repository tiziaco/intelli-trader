# Pitfalls Research

> ## ⚠ Superseded framing — read `phases/02-okx-connector/02-CONTEXT.md` first
>
> The Phase-2 discussion (2026-07-01) revised the live architecture; this snapshot
> predates it and still describes the **two-arm `LiveConnector`** model. The pitfalls
> themselves remain valid — only the connector-shape wording is stale. **Superseded framings:**
> - Connector is a **session/transport primitive**, not a two-arm venue object; the data/order/account arms are **domain adapters** (`OkxDataProvider` / `OkxExchange` / `VenueAccount`), **injected** with the session.
> - The **`OkxExchange` adapter emits `FillEvent`** — the connector emits no domain events.
> - Paper needs **no connector**: the paper execution adapter implements **`AbstractExchange`** (not `LiveConnector`).
> - `OkxSettings` reads **plain `OKX_API_*` (no env prefix)** — not `ITRADER_OKX_*`.
>
> See design-doc LX-05/LX-06 revision notes and `02-CONTEXT.md` D-01..D-10.

**Domain:** Adding live crypto (OKX) trading to an event-driven, Decimal-exact, deterministic backtest engine — paper-first, oracle-gated (iTrader v1.7)
**Researched:** 2026-06-30
**Confidence:** HIGH on engine-internal pitfalls (read from source + locked sketch); MEDIUM-HIGH on OKX/ccxt integration facts (verified against ccxt issues + OKX v5 docs; firm up at plan-time)

> Scope note: these are pitfalls specific to grafting a live OKX arm onto **this** engine — the
> byte-exact SMA_MACD oracle (`134 / 46189.87730727451`), Decimal-end-to-end money, single-writer
> `global_queue`, stateful no-rewind indicators, `filterwarnings=["error"]`, and the paper-parity
> gate (LX-11). Generic "trading is hard" advice is omitted. Each pitfall names the v1.7 phase
> (1-6) that should own its prevention.

---

## Critical Pitfalls

### Pitfall 1: Acting on a forming (unconfirmed) bar — wall-clock close inference

**What goes wrong:**
The live feed emits a `BarEvent` for a candle that has not actually closed, so strategies compute
indicators on a partial bar and fire signals the backtest would never produce. Paper-parity fails
immediately and silently (the live run trades on data the oracle never saw).

**Why it happens:**
Two compounding traps. (a) ccxt's unified `watchOHLCV` does **not** expose a `closed`/`confirm`
boolean — it streams the in-progress candle and you can only distinguish finalized bars by watching
the timestamp roll over (ccxt issue #21885). (b) The naive fix — "the bar is closed when
wall-clock ≥ open + timeframe" — is wrong under clock skew, late venue ticks, and the engine's own
bar-stamping contract (rule 2: the tick at `T` means "the bar stamped `T` just closed", whose
wall-clock semantics are `T + tf_base`). Inferring close from local time re-introduces exactly the
look-ahead the 7-rule contract (`bar_feed.py`) was built to forbid.

**How to avoid:**
Drive "closed" off OKX's native `confirm` field (the last element of the WS candle array:
`0`=forming, `1`=closed), never wall-clock (LX-08). Because ccxt drops this field, the OKX
`confirm` read is precisely the "proven gap" that justifies the **native escape hatch** (LX-05) —
the `OkxConnector` must reach the native OKX candle channel (or its own ccxt subclass) to recover
`confirm`, and `LiveBarFeed` must emit `BarEvent` **only** on `confirm == 1`. Encode the bar-timing
contract's rule 2 into the feed: the emitted `BarEvent.time` must be the bar's **open** stamp `T`,
identical to backtest, so downstream `window()` cutoff math is unchanged.

**Warning signs:**
More signals live than in the oracle backtest on the same dates; a `BarEvent` whose timestamp equals
the current wall-clock minute/day; indicator values that change between two events carrying the same
bar timestamp (the tell-tale of a forming bar being re-delivered).

**Phase to address:** Phase 3 (LiveBarFeed, LX-08); the native-`confirm` plumbing is Phase 2 (connector).

---

### Pitfall 2: Off-by-one between backtest next-bar-open fills and live closed-bar arrival

**What goes wrong:**
The backtest decides at tick `T` and fills the market order at the **open of `T + tf_base`** through
the resting book (bar-timing rule 5, `FillEvent.time = T + tf_base`). A live/paper path that fills
"now" on the same bar `T` (or fills on the close of `T`) shifts every fill by one bar. Equity curves
diverge cumulatively; paper-parity never holds even with identical signals.

**Why it happens:**
In live, the decision and the next bar's arrival are separated by real time, so it feels natural to
fill against the bar you just received. The backtest's "rest now, fill at next open" semantics are an
engine invariant, not an obvious default — easy to lose when re-implementing fills in `PaperConnector`.

**How to avoid:**
`PaperConnector` must reuse the **pure `MatchingEngine`** (LX-06), not re-implement matching: the
matching core already rests the market order and fills it on the *next* `on_bar` at that bar's open,
preserving rule 5 by construction. Local paper stays strictly **bar-based** (LX-13) — no sub-bar /
tick fills. The parity harness must replay the *same* dataset bar-stream so the "next bar" the paper
path fills against is byte-identical to the oracle's.

**Warning signs:**
Paper trade count matches the oracle but fill prices are shifted to the previous/next bar's open;
first divergence appears at the first trade and compounds; `FillEvent.time` in paper equals the
deciding `BarEvent.time` instead of the following bar's.

**Phase to address:** Phase 4 (paper path / `PaperConnector` reuse of `MatchingEngine`, LX-06/LX-13).

---

### Pitfall 3: Live wall-clock leaking into business `time`

**What goes wrong:**
A live component stamps an event, order, transaction, or metrics row with `datetime.now(UTC)`
instead of the bar's business `time`. This corrupts determinism, breaks the paper-parity replay
(records carry replay-time wall-clocks, not dataset times), and pollutes the persisted system of
record with non-reproducible timestamps.

**Why it happens:**
The existing `LiveTradingSystem` already does this in several non-event-critical spots
(`_stats['last_event_time'] = datetime.now(UTC)`, idle detection, `ErrorEvent` fallback
`getattr(event, 'time', datetime.now(UTC))`), and the pattern is contagious. In live, "what time is
it?" genuinely has two answers (the bar's business time vs. the wall clock for transport/heartbeat),
and the wrong one is the convenient one.

**How to avoid:**
Hold the line from CLAUDE.md: business `time` is **always** the bar's stamp, never wall clock.
Wall-clock is permitted **only** for transport/observability concerns that never enter accounting or
event causality (heartbeat, reconnect backoff, idle-warning, log lines) — and those must never be
written into a `FillEvent`/`OrderEvent`/transaction/metrics row. Introduce a live "session clock"
seam that mirrors the injected `BacktestClock` (core/clock.py): the connector translates each
confirmed bar into a `TimeEvent`/`BarEvent` whose `time` is the venue bar-open stamp, and that stamp
is the only time the engine sees. Audit every `datetime.now` on the live path for "is this allowed to
touch money/events?".

**Warning signs:**
Determinism double-run is no longer byte-identical on the paper path; persisted order/fill rows carry
timestamps near real time rather than dataset dates; the parity harness output differs run-to-run.

**Phase to address:** Phase 4 (determinism seam in the live runtime; the "how the live thread/clock
interacts with determinism seams" open item is named in the sketch §4 Phase 4).

---

### Pitfall 4: Stateful-indicator divergence from a backfill fast-path (LX-09 violation)

**What goes wrong:**
Warmup/backfill builds indicator state via a bulk `warmup_from(series)` shortcut while live streaming
uses per-bar `update(bar)`. The two code paths compute the same EMA/MACD/RSI recurrences slightly
differently (seeding, first-value handling, order of operations), so the live indicator state diverges
from what the oracle's per-bar path produced. Signals diverge; paper-parity fails in a way that is
maddening to debug because both paths "look correct" in isolation.

**Why it happens:**
Bulk warmup is faster and feels harmless ("it's just the same data"). But the v1.5 stateful
indicators (hand-written O(1) recurrences) have **no rewind** and are sensitive to seeding — a second
state-building path is a second source of truth that re-opens the parity audit.

**How to avoid:**
LX-09 is absolute: warmup/backfill replays the last K bars **one-by-one through the identical
`update(bar)` path** live streaming uses. **No bulk fast-path exists.** Both warmups (cache hydration
and indicator readiness, §10.D-2 of the stateful-indicator spec) go through the same entry. Make this
structurally impossible to violate: do not add a `warmup_from`/`seed`/`prime` method to the indicator
or feed API at all. Add a test that asserts replaying K bars through `update()` yields byte-identical
indicator state to the backtest feed at the same asof.

**Warning signs:**
Any method named `warmup_from`, `bulk_update`, `seed`, `prime`, `from_series` appears on an indicator
or feed; paper-parity passes only after the warmup window and diverges in the first post-warmup bars;
indicator state after backfill differs from `BacktestBarFeed` at the same timestamp.

**Phase to address:** Phase 3 (LiveBarFeed backfill-through-update, LX-09); reused in Phase 6
(warmup-on-add).

---

### Pitfall 5: Feeding indicator state backward on a gap / duplicate / out-of-order bar

**What goes wrong:**
The feed delivers a bar with a timestamp ≤ the last delivered bar (duplicate, stale re-send,
out-of-order WS frame, or a venue correction). The stateful indicators have no rewind, so feeding an
older bar corrupts state irreversibly — every subsequent signal is wrong, and there is no clean
recovery short of re-warming.

**Why it happens:**
Crypto WS streams routinely re-send, reorder, or correct candles, especially around reconnects. The
backtest never sees this (its `TimeGenerator` is a pinned monotonic grid), so the engine has no
existing guard — the guard must be invented in `LiveBarFeed`.

**How to avoid:**
Enforce monotonic-forward-only delivery (LX-10): **duplicate → drop; out-of-order/stale → reject
(never feed state backward); gap → REST-backfill the missing bars and replay through the same
`update(bar)` path; reconnect → gap-fill the interim**. For after-the-fact corrections, do **not**
patch in place — either re-warm from the ring buffer or forward-only-and-log (decide at plan time;
the sketch leaves this open). The ring-buffer `LiveBarFeed` is the natural enforcement point (mirror
the backtest cursor's "non-monotonic cutoff → safe rebuild" discipline in `window()`).

**Warning signs:**
Indicator values jump non-physically after a reconnect; a `BarEvent` timestamp ≤ `newest_bar`'s;
duplicate timestamps reaching strategies; parity holds on a clean session but breaks on any session
with a disconnect.

**Phase to address:** Phase 3 (LiveBarFeed monotonic-forward delivery + reconnect gap-fill, LX-10).

---

### Pitfall 6: ccxt float money leaking into the Decimal accounting core

**What goes wrong:**
ccxt returns **floats** for every price, amount, fee, and balance (and `amount_to_precision` /
`price_to_precision` historically return floats too). If any of those floats reach the engine via
`Decimal(float)` — or are compared/arithmetic'd before conversion — the binary-float repr artifact
(`Decimal(10.1) == 10.0999999...`) poisons the ledger. This is the locked correctness defect
(money is Decimal end-to-end), now arriving from outside the engine for the first time.

**Why it happens:**
The whole codebase has so far controlled its own data ingress (`Bar.from_row` uses `Decimal(str(x))`).
ccxt is the first money source the engine does not own, and its floats look like ordinary numbers.
`Decimal(some_ccxt_float)` is a one-character mistake away everywhere.

**How to avoid:**
Bottle **all** ccxt→Decimal conversion at the connector edge through the existing `to_money(x)`
(which is `Decimal(str(x))`, D-04) — never `Decimal(float)`, never float arithmetic before
conversion. Treat the connector boundary like `Bar.from_row`: the moment a value crosses into the
engine it is Decimal. For order submission *out* to OKX, convert with ccxt's **string** precision
helpers (`decimal_to_precision` with `TRUNCATE`/`DECIMAL_PLACES`, or the string variants), not the
float-returning `amount_to_precision`, so the venue sees a correctly-rounded string and the engine
keeps its Decimal. Add a mypy/lint guard or a focused test that no `Decimal(` wraps a float on the
live path.

**Warning signs:**
Any `Decimal(` call on the connector path whose argument is not a `str`; balances/fees with 15+ trailing
digits in the ledger; `InvalidOperation` from OKX `create_order` (ccxt issue #7415, a classic
float-precision symptom); reconciliation drift that is always tiny and always present.

**Phase to address:** Phase 2 (connector edge conversion) and Phase 5 (`VenueAccount` balance/fee ingest).

---

### Pitfall 7: Rounding to the wrong OKX tick/lot/contract size

**What goes wrong:**
The engine sizes an order with its own per-instrument Decimal scales (8dp BTC), but OKX enforces its
own `price` tick, `amount` lot step, **and contract-size multiple** — and rejects (or silently adjusts)
anything off-grid. OKX amount must be a multiple of the lot/contract size; sending `0.123456` when the
step is `0.0001` fails with "amount must be greater than minimum amount precision" (ccxt issue #17710).
A silently-adjusted fill then mismatches the engine's intended quantity → reconciliation drift.

**Why it happens:**
The engine's `Instrument` scales (v1.4) were authored for the backtest and may not match OKX's live
filters. The two precision systems (engine `quantize` vs. OKX market `precision`/`limits`) are easy to
conflate.

**How to avoid:**
At connector init, load OKX market metadata (`load_markets`) and reconcile each traded symbol's
OKX `precision`/`limits`/contract size into the engine `Instrument` (or a connector-side filter that
runs after engine sizing). Round outbound quantities to OKX's lot step using ccxt's **string**
precision helper, then re-quantize the resulting Decimal back into the engine so the engine's intended
quantity equals what the venue will actually accept. Validate against `limits.amount.min` /
`limits.cost.min` before submit; reject loud, never silently truncate to zero.

**Warning signs:**
OKX order rejections citing precision/min-amount; a fill quantity that differs from the submitted
quantity; per-symbol drift that correlates with the least-significant digits of order size.

**Phase to address:** Phase 2 (connector market-metadata load + outbound rounding); validated Phase 5 (sandbox).

---

### Pitfall 8: Races translating async ccxt.pro messages onto the synchronous single-writer queue

**What goes wrong:**
The connector's asyncio loop receives fills/balances/bars concurrently and pushes them onto
`global_queue` from a thread/loop that is **not** the engine's single writer. The engine's
single-writer contract (D-19, on which the backtest dropped all portfolio locks) is violated: two
producers interleave, ordering guarantees the FIFO queue assumed are broken, and Portfolio/Account
state mutated from the dispatch thread can race the connector thread.

**Why it happens:**
ccxt.pro is async-native; the engine is synchronous. Bridging them invites "just call
`global_queue.put()` from the websocket callback" — which works until two callbacks fire close
together or until the order-status stream races the bar stream.

**How to avoid:**
Bottle the async boundary **entirely at the connector edge** (Phase 2 design). The connector runs its
own asyncio loop in its own thread and is the **only** producer that translates venue messages into
domain events; the engine keeps its single dispatch thread as the **only** consumer/mutator.
`queue.Queue.put()` is itself thread-safe (the FIFO crossing is fine); the danger is *state mutation*
and *event ordering*, not the put. So: never let the connector thread touch Portfolio/Account/order
state directly (queue-only contract — emit an event); preserve event causality by emitting in venue
order; and keep the live `Portfolio`/`Account` `RLock`s where any read crosses threads (status/metrics
queries from the API thread vs. the dispatch thread). Decide the LX-15 process topology early — a
separate worker process (option b/c) sidesteps much of this by isolating the engine.

**Warning signs:**
`global_queue.put` called from anywhere other than the connector translator or an event handler;
Portfolio/Account fields mutated off the dispatch thread; intermittent, unreproducible state
corruption under load; events arriving out of causal order (fill before its order ack).

**Phase to address:** Phase 2 (async/sync bridge at connector edge); topology decision is cross-cutting
LX-15 (before Phase 4 wiring); thread-safety hardening Phase 4/5 (FL-13).

---

### Pitfall 9: Blocking the asyncio loop with engine/DB/sync work

**What goes wrong:**
A synchronous call (engine dispatch, a Postgres write-through, a `time.sleep`, a heavy pandas
resample) runs inside the connector's asyncio loop coroutine, stalling all websocket I/O. Heartbeats
miss, OKX drops the connection, and a reconnect storm follows — during which bars are missed and the
gap-fill machinery (Pitfall 5) is stressed exactly when it matters most.

**Why it happens:**
The connector lives next to async code; it's tempting to "just await the engine" or do the DB write
inline. The engine and DB are synchronous, so they block the loop.

**How to avoid:**
Strict separation: the asyncio loop does **only** network I/O and message translation, then hands off
to the synchronous engine via the queue (a non-blocking `put`). No engine logic, no DB writes, no
`sleep`, no pandas in a coroutine. Persistence write-through stays **keep-only-measured** (build async
buffering only if the live loop profiles a stall, sketch Phase 5) — and even then it runs on the
engine/storage side, never in the connector's loop. Run blocking work via `run_in_executor` only if
unavoidable.

**Warning signs:**
Websocket reconnects correlate with order submissions or metrics writes; OKX "connection idle/timeout"
disconnects under normal load; the asyncio loop's iteration latency spikes; `time.sleep` or a
synchronous DB call inside any `async def`.

**Phase to address:** Phase 2 (connector loop discipline); Phase 5 (persistence write-through must not stall).

---

### Pitfall 10: Treating the engine (not the venue) as source of truth in live

**What goes wrong:**
On the real path, the engine assumes its computed position/balance is correct and ignores or
overwrites the venue's actual state. Partial fills, fees, funding, and venue-side liquidations make
the venue the only authority; an engine that trusts its own books drifts from reality and can place
orders against positions it doesn't actually hold.

**Why it happens:**
In backtest **and paper**, the `SimulatedAccount` legitimately *computes* truth — that's the parity
spine (sketch §3). The instinct carries over to the real path, where it's wrong: `VenueAccount` must
*cache and reconcile*, not compute (LX-03).

**How to avoid:**
Keep the two account leaves honest to their roles (LX-03): `SimulatedAccount` computes (backtest +
paper, preserving parity); `VenueAccount` mirrors the connector's balance/position/fill streams and
**reconciles** against them. Under 1 account : 1 portfolio (LX-04), reconciliation reduces to
**per-symbol drift detection** (no cross-portfolio attribution) — assuming the portfolio has exclusive
control of its OKX subaccount. Define a drift policy explicitly: auto-correct small drift vs.
halt-and-alert (sketch Phase 5 open item) — never silently continue on unexplained drift.

**Warning signs:**
The real path has no code reading venue balances/positions after submit; engine position ≠ venue
position after a partial fill; no drift threshold/alert; manual venue trades (or another process)
silently desync the engine.

**Phase to address:** Phase 5 (`VenueAccount` reconciliation, LX-04); interface shaped Phase 1.

---

### Pitfall 11: Partial / duplicate / mis-sequenced fill handling

**What goes wrong:**
OKX fills a large order in pieces, re-sends a fill on reconnect, or delivers a fill before the order
ack. The order handler's mirror reconciliation (EXECUTED→FILLED etc.) — built for clean simulated
fills — double-counts a duplicate, marks an order FILLED on the first partial, or chokes on a fill it
has no order for. Position/cash diverge from the venue.

**Why it happens:**
The `SimulatedExchange`/`MatchingEngine` produces one clean terminal fill per order; partials and
duplicates are a live-only reality the order mirror has never had to be idempotent against.

**How to avoid:**
Make fill ingestion idempotent and partial-aware at the connector/order-handler seam: key fills by the
venue's fill/trade id (dedupe duplicates), accumulate partials against the order's filled-quantity
(only terminalize when cumulative filled == order quantity or the venue reports the order closed), and
tolerate fill-before-ack by buffering an orphan fill until its order appears (or reconciling from venue
order status). The order mirror stays a **mirror** — the venue order-status stream, not the engine, is
authoritative on the real path. Persist the cumulative-filled state so a restart can resume mid-partial
(Pitfall 13).

**Warning signs:**
Order marked FILLED while venue shows it partially open; cash/position double-debited after a
reconnect; a `FillEvent` with no matching order in the mirror; cumulative filled quantity exceeding
order quantity.

**Phase to address:** Phase 5 (order/fill reconciliation on the real path); connector fill stream Phase 2.

---

### Pitfall 12: Fees and funding drift the ledger silently

**What goes wrong:**
OKX charges maker/taker fees (and, on perps, funding) that differ from the engine's fee model. The
engine's computed cash diverges from the venue balance by an accumulating fee/funding delta that looks
like "small constant drift" and is easy to dismiss — until it isn't.

**Why it happens:**
Paper uses the engine's own fee/slippage models (correct for parity); the real path must instead ingest
the venue's *actual* charged fees. Funding is explicitly out of scope (perp Phase B / FUND-01..04) but
will be a visible drift source the moment anyone trades a perp.

**How to avoid:**
On the real path, ingest the venue's reported fee per fill (Decimal via `to_money`) into the ledger
rather than recomputing — the engine fee model is for paper/backtest only. Make fee drift a *named,
explained* component of reconciliation, not noise. Keep spot-only in v1.7 (funding out of scope); if a
perp is ever traded, treat funding drift as expected-and-unmodeled and **halt rather than silently
absorb** until Phase B lands.

**Warning signs:**
Reconciliation drift that grows linearly with trade count; engine cash consistently above venue cash by
~the fee rate; any funding line item on a perp position the engine doesn't account for.

**Phase to address:** Phase 5 (venue-fee ingest in reconciliation); funding deferred (out of scope, named).

---

### Pitfall 13: Restart rehydration reconciling store-only, ignoring the live venue (the v1.6 broker-side gap)

**What goes wrong:**
On restart, the engine rehydrates its working set from the v1.6 Postgres store and resumes — but the
store is stale relative to the venue (fills landed while the engine was down, an order was canceled
venue-side, a position was liquidated). The engine resumes on a false picture and acts on it.

**Why it happens:**
v1.6's restart-rehydration tests were **store-only** — they proved cache↔store consistency, never
cache↔**broker** consistency, because there was no live adapter. The broker side is an explicit carried
gap (sketch Phase 5).

**How to avoid:**
Restart reconciliation must be two-sided: rehydrate from the store **and** reconcile against the live
venue (fetch open orders, positions, balances; replay any fills that landed during downtime through the
idempotent fill path; cancel/expire orders the venue no longer holds). Bracket parents need special
care: a parent that filled during downtime must have its children correctly activated/cancelled on
restart (the engine's two-pass bracket gate must be re-established from venue truth, not assumed).
Define the drift-on-restart policy (auto-reconcile vs. halt-and-alert) the same as steady-state
(Pitfall 10).

**Warning signs:**
Restart path reads only the store, never the connector; open orders on OKX that the engine doesn't know
about post-restart; a bracket child resting with no live parent (or vice versa); positions on the venue
absent from the rehydrated portfolio.

**Phase to address:** Phase 5 (cache↔broker restart reconciliation; persistence live-drive).

---

### Pitfall 14: Crash-safe write ordering / write-through stalling the live loop

**What goes wrong:**
Either (a) the engine acts (submits an order, applies a fill) before durably persisting the intent, so
a crash between act-and-persist loses the record and breaks restart reconciliation; or (b) the
write-through runs synchronously on the dispatch thread and stalls the live loop, backing up the queue
and missing bars/fills.

**Why it happens:**
The two goals pull opposite ways — crash-safety wants write-before-act; latency wants act-then-write.
The v1.6 store was built and tested on testcontainers but never *driven by a live feed* (its
transaction-boundary design is an explicit carried research flag).

**How to avoid:**
Decide the transaction boundary per operation (sketch Phase 5 / v1.6 carried flag): **create and
terminalize sync** (durable before the irreversible venue action), append-heavy/metrics writes can be
async/buffered. Keep write-through **keep-only-measured** — only build async buffering if the live loop
profiles a stall (don't pre-optimize). Persist the *intent* (order to be sent) before submit so a crash
mid-submit is recoverable by reconciliation. Never run a Postgres write inside the connector asyncio
loop (Pitfall 9).

**Warning signs:**
Queue depth grows during DB-heavy moments; orders submitted to OKX with no prior store row; restart
finds a venue order with no engine record; p99 dispatch latency tracks DB write latency.

**Phase to address:** Phase 5 (persistence live-drive, write ordering); profile-gated per keep-only-measured.

---

### Pitfall 15: Sandbox vs. live key split-brain

**What goes wrong:**
Part of the system talks to OKX demo and part to OKX live — e.g. ccxt is put in sandbox mode but a
native escape-hatch call (Pitfall 1's `confirm` reader) hits production, or the data feed is live while
the order arm is demo (or vice versa). Result: phantom fills, orders against the wrong book, or
real-money trades when "paper" was intended. Catastrophic.

**Why it happens:**
OKX routes demo via two different mechanisms — ccxt's `set_sandbox_mode(True)` **and** the native
`x-simulated-trading: 1` header — and the connector has two paths (ccxt.pro default + native escape
hatch). Two switches → split-brain if only one is flipped.

**How to avoid:**
A **single `sandbox: bool`** (LX-05) routes *both* arms: it must call ccxt `set_sandbox_mode` **and**
set the native `x-simulated-trading` header, with no second toggle anywhere. Pair sandbox/live with
**separate key sets** keyed off the same flag (sandbox keys can't reach live, by construction). Add a
startup assertion that both ccxt and native paths report the same environment before any order arm goes
live. Paper-first (LX-01) means the order arm is sandbox-only until a deliberate gated promotion.

**Warning signs:**
Two independent sandbox/demo toggles in the codebase; the data feed and order arm configured
separately; no startup check that ccxt and native agree on environment; live API keys present in a
paper/sandbox config.

**Phase to address:** Phase 2 (single-flag routing of both arms); secrets split cross-cutting (LX-05).

---

### Pitfall 16: Secrets leakage in logs / structured events

**What goes wrong:**
API key/secret/passphrase (OKX requires a passphrase) end up in logs, error events, or the persisted
store — via a connector exception that logs the request, a `repr()` of a config object, or an
`ErrorEvent.error_message` that includes the offending payload. The structlog setup logs liberally and
`filterwarnings` won't catch a leaked secret.

**Why it happens:**
ccxt errors often include the request context; the engine's publish-and-continue policy logs every
handler failure (`_publish_and_continue` logs `str(exc)` and emits an `ErrorEvent`); credentials in a
config object get logged on init.

**How to avoid:**
Keys never in code (already the WR-10 posture — no hardcoded fallback). Load from env/secret store as
Pydantic `SecretStr` (the codebase already uses `SecretStr database_url`) so `repr`/log renders
`**********`. Scrub connector exceptions before logging/emitting (strip auth headers, redact request
bodies). Never persist raw credentials in the store or `ErrorEvent`. Add a log/event scrubber on the
live path and a test asserting no key material appears in emitted `ErrorEvent`s or log capture.

**Warning signs:**
API secret visible in any log line or `ErrorEvent`; config object logged without `SecretStr`
wrapping; ccxt request context logged on error; secrets in the Postgres store.

**Phase to address:** Phase 2 (secret loading via SecretStr); cross-cutting secrets hardening (Phases 2-5).

---

### Pitfall 17: Over-building beyond the trimmed scope

**What goes wrong:**
The team builds explicitly out-of-scope machinery — **tick-level local paper fills** (rejected by
LX-13), a **full production screener** (only a lean poll seam is in scope, Phase 6), a
**multi-venue abstraction** beyond shaping the interface (crypto/OKX-first, locked), or **perp Phase B
funding realism** (FUND-01..04, its own future milestone). Each balloons the surface, delays the
paper-parity DoD, and risks destabilizing the byte-exact oracle.

**Why it happens:**
The connector interface invites generalization ("while I'm here, let me support N venues");
sub-bar realism feels more "real" than bar fills; the screener seam looks half-built. The pull toward
completeness fights the trimmed-N+4 posture.

**How to avoid:**
Hold the sketch's explicit out-of-scope list (sketch §1). Local paper stays **bar-based** (LX-13) —
sub-bar realism lives in OKX sandbox, not local paper. The connector is **shaped** for a 2nd venue but
only `OkxConnector` is implemented (LX-05). Phase 6 ships only the lean membership poll seam, not the
production screener. Funding/perp realism is deferred. Treat every "while I'm here" as scope creep to
defer with a note, not absorb.

**Warning signs:**
A `TickPaperConnector` or sub-bar fill logic; a second connector implementation; screener filter
chains beyond add/remove polling; funding-rate accrual code; the milestone slipping while "foundations"
grow.

**Phase to address:** All phases (scope discipline); Phase 4 (resist tick fills); Phase 6 (resist full screener).

---

### Pitfall 18: asyncio/websocket warnings failing the strict suite (`filterwarnings=["error"]`)

**What goes wrong:**
Live tests pull in ccxt.pro/aiohttp/websockets, which emit `ResourceWarning` (unclosed session/
transport), `DeprecationWarning` (asyncio loop/`get_event_loop`), and "coroutine was never awaited"
warnings. Under `filterwarnings=["error"]` **any** of these fails the test — so the live surface is
hard to test at all, and the temptation is to weaken the strict gate globally (which would also weaken
the backtest's correctness net).

**Why it happens:**
The strict suite was tuned for a synchronous, dependency-light engine. Async test teardown reliably
leaks warnings unless sessions/loops are explicitly closed; ccxt.pro holds connections open by design.

**How to avoid:**
Never relax `filterwarnings` globally. Instead: ensure deterministic async teardown (close ccxt
connections, await `exchange.close()`, close the loop) so no `ResourceWarning` escapes; use
`pytest-asyncio` with explicit loop/fixture scoping; and where a third-party warning is genuinely
unavoidable, scope a **narrow** per-test `filterwarnings` marker (or `pytest.warns`/`recwarn`)
targeting that exact warning class+module — never a blanket ignore. Prefer testing the live surface
against a **mocked/recorded connector** (replay fixtures) so most FL-13 coverage needs no live socket
at all; reserve real-socket tests for a small sandbox-gated integration set.

**Warning signs:**
Live tests pass only with a broadened global `filterwarnings`; `ResourceWarning: unclosed`
transport/session in test output; "coroutine never awaited"; pressure to mark the whole live suite
`-W ignore`.

**Phase to address:** Phase 2 onward (every live phase adds FL-13 coverage as it lands, sketch §5).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use ccxt unified `watchOHLCV`, infer close from timestamp roll-over | No native escape hatch needed | Forming-bar bugs, parity failure, fragile to stream quirks | Never for fills — `confirm` flag is mandatory (LX-08) |
| Bulk `warmup_from(series)` for fast backfill | Faster start | Second state path diverges, re-opens parity audit (LX-09) | Never — forbidden by LX-09 |
| `Decimal(ccxt_float)` directly | One line | Binary-float poison in the ledger | Never — route through `to_money` |
| Synchronous write-through on dispatch thread | Simple, crash-safe | Stalls live loop, backs up queue | MVP only if profiled clean; keep-only-measured |
| `VenueAccount` computes instead of caches | Reuse `SimulatedAccount` math | Engine drifts from venue truth (LX-03) | Never on real path; fine for paper (it IS `SimulatedAccount`) |
| Run engine in-process with FastAPI | Simplest wiring | Couples lifecycles, mixes 3 concurrency models, one crash kills both | Throwaway demo only; sketch leans worker/process-per-portfolio (LX-15) |
| Global `-W ignore` to pass live tests | Green suite fast | Destroys the backtest correctness net too | Never — scope warnings per-test |
| Two sandbox toggles (ccxt + native separately) | Quick | Split-brain → real-money risk | Never — single `sandbox: bool` (LX-05) |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OKX kline WS | Trusting ccxt `watchOHLCV` to tell you a bar closed | Read native `confirm` field (last array element, 0/1); ccxt drops it (issue #21885) → native escape hatch (LX-05) |
| ccxt money | `Decimal(float)` on prices/amounts/fees/balances | `to_money(str)` at connector edge; string precision helpers outbound |
| OKX order size | Engine 8dp quantity sent as-is | Round to OKX lot/contract step via ccxt string precision; validate `limits.amount.min` (issue #17710) |
| OKX demo | `set_sandbox_mode` only, native calls hit live | Single flag sets BOTH ccxt sandbox + native `x-simulated-trading` header (LX-05) |
| ccxt.pro async | `global_queue.put` / state mutation from WS callback thread | Connector translator is sole producer; queue-only; no cross-thread state mutation |
| OKX auth | Forgetting the passphrase; logging the request | Passphrase required; `SecretStr`; scrub connector exceptions before log/emit |
| ccxt.pro sessions | Tests leak unclosed sessions → `ResourceWarning` fails strict suite | `await exchange.close()` in teardown; mock/replay connector for most FL-13 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Blocking the asyncio loop with DB/engine/sleep | Reconnect storms under load; bars missed | Loop does only I/O + translate; sync work off-loop | First DB-heavy live session |
| Sync write-through on dispatch thread | Queue depth tracks DB latency | Sync only create/terminalize; rest buffered, profile-gated | High trade rate / slow DB |
| Live machinery imported on the backtest hot path | W1/W2 regression vs v1.5 (15.7s/152.8MB) | Lazy-import the live arm (mirror the existing SQL lazy-import); inertness test | Any backtest run after live code lands |
| Per-bar REST gap-fill on a flaky connection | Latency spikes, rate-limit bans during reconnect | Bounded backfill window; ring buffer; reconnect debounce | Unstable network / frequent disconnects |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| API key/secret/passphrase in logs or `ErrorEvent` | Account takeover | `SecretStr`; scrub connector exceptions; no raw creds in store/events |
| Hardcoded credential fallback | Leaked key in repo | Already WR-10 (no fallback); keep it; env/secret-store only |
| Sandbox/live key split-brain | Unintended real-money trades | Single `sandbox` flag routes both arms + key set; startup environment assertion |
| Persisting credentials in the system-of-record | DB compromise = key compromise | Never persist creds; store references, not secrets |

## "Looks Done But Isn't" Checklist

- [ ] **Bar-close detection:** Often missing the `confirm`-flag read — verify `BarEvent` emits only on `confirm == 1`, never wall-clock
- [ ] **Backfill:** Often missing the through-`update()` guarantee — verify no `warmup_from`/bulk path exists; state byte-matches backtest at same asof
- [ ] **Paper fills:** Often missing next-bar-open semantics — verify `FillEvent.time == T + tf_base` via reused `MatchingEngine`
- [ ] **Determinism:** Often missing the business-time discipline — verify paper double-run byte-identical; no wall-clock in events/ledger
- [ ] **Reconciliation:** Often missing the broker side — verify restart reconciles store AND live venue, not store-only
- [ ] **Partial fills:** Often missing idempotency — verify duplicate fills deduped, partials accumulated, fill-before-ack tolerated
- [ ] **Money:** Often missing the ccxt-float boundary — verify no `Decimal(float)` on the live path; venue fees ingested (not recomputed)
- [ ] **Sandbox:** Often missing dual-arm routing — verify single flag sets ccxt sandbox AND native header; startup env assertion
- [ ] **Secrets:** Often missing exception scrubbing — verify no key material in any log/`ErrorEvent`
- [ ] **Strict suite:** Often missing async teardown — verify live tests pass under `filterwarnings=["error"]` without global relaxation
- [ ] **Backtest inertness:** Often missing the regression check — verify oracle byte-exact + no W1/W2 regression after live code lands

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Forming-bar acted on / parity broken | MEDIUM | Switch to `confirm` flag; replay parity harness from clean dataset; re-validate gate |
| Indicator state corrupted (backward feed / bad backfill) | MEDIUM | Re-warm from ring buffer through `update()`; no in-place patch; re-assert state vs backtest |
| ccxt-float in ledger | HIGH | Audit all `Decimal(` on live path; re-route through `to_money`; reconcile/rebuild affected balances from venue |
| Engine/venue drift undetected | HIGH | Add per-symbol drift detection; reconcile from venue truth; halt-and-alert policy; rebuild from venue + store |
| Restart on stale store (broker gap) | MEDIUM | Add broker-side reconciliation; replay downtime fills idempotently; re-establish bracket parent/child from venue |
| Sandbox/live split-brain | HIGH (if real money) | Halt; single-flag refactor; key-set separation; startup env assertion before any future run |
| Secret leaked to log/store | HIGH | Rotate keys immediately; scrub logs/store; add scrubber + test |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Forming-bar / wall-clock close | Phase 3 (flag plumb Phase 2) | `BarEvent` emitted only on `confirm==1`; parity holds |
| 2. Next-bar-open fill off-by-one | Phase 4 | `FillEvent.time == T+tf_base`; reused `MatchingEngine` |
| 3. Wall-clock in business time | Phase 4 | Paper double-run byte-identical; no `now()` in events/ledger |
| 4. Backfill fast-path divergence | Phase 3 (reused Phase 6) | No `warmup_from`; state == backtest at asof |
| 5. Backward indicator feed | Phase 3 | Dup dropped / stale rejected / gap backfilled; reconnect parity |
| 6. ccxt float in ledger | Phase 2 + 5 | No `Decimal(float)`; balances Decimal-clean |
| 7. OKX tick/lot rounding | Phase 2 (sandbox Phase 5) | Outbound qty multiple of lot; no precision rejects |
| 8. Async→queue races | Phase 2 (+ LX-15 topology) | Single producer; no off-thread state mutation |
| 9. Blocking the asyncio loop | Phase 2 (+ Phase 5 write-through) | No sync/DB/sleep in coroutine; stable reconnects |
| 10. Venue not source of truth | Phase 5 (interface Phase 1) | `VenueAccount` caches+reconciles; drift policy defined |
| 11. Partial/duplicate fills | Phase 5 (stream Phase 2) | Idempotent fill ingest; partial accumulation |
| 12. Fee/funding drift | Phase 5 | Venue fees ingested; drift named/explained; funding halts |
| 13. Restart broker-side gap | Phase 5 | Restart reconciles store AND venue; bracket parents safe |
| 14. Write ordering / loop stall | Phase 5 (profile-gated) | Create/terminalize durable pre-act; no loop stall |
| 15. Sandbox/live split-brain | Phase 2 (LX-05) | Single flag both arms; startup env assertion |
| 16. Secrets leakage | Phase 2 (cross-cutting) | No creds in logs/events/store |
| 17. Over-build out of scope | All (Phase 4/6 esp.) | No tick fills / full screener / multi-venue / funding |
| 18. Strict-suite async warnings | Phase 2 onward (FL-13) | Live tests green under `filterwarnings=["error"]`, no global relax |

## Sources

- [iTrader locked sketch — `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md`](file) — LX-01..LX-15, parity spine, carried research flags (HIGH)
- iTrader source: `itrader/price_handler/feed/bar_feed.py` (7-rule bar-timing contract), `itrader/core/money.py` (D-04 string entry), `itrader/trading_system/live_trading_system.py` (daemon thread, publish-and-continue, wall-clock usage) (HIGH)
- [ccxt issue #21885 — request for `closed`/`confirm` flag in watchOHLCV](https://github.com/ccxt/ccxt/issues/21885) — confirms unified ccxt does NOT expose candle-closed; native read needed (MEDIUM-HIGH)
- [ccxt issue #17710 — OKX amount precision / contract-size multiple rejection](https://github.com/ccxt/ccxt/issues/17710) (MEDIUM)
- [ccxt issue #7415 — OKX create_order InvalidOperation (float precision)](https://github.com/ccxt/ccxt/issues/7415) (MEDIUM)
- [ccxt decimal_to_precision source](https://github.com/ccxt/ccxt/blob/master/python/ccxt/base/decimal_to_precision.py) — string TRUNCATE/DECIMAL_PLACES helpers (MEDIUM)
- [OKX v5 WebSocket candlesticks channel docs](https://www.okx.com/docs-v5/en/) — candle array `[ts,o,h,l,c,vol,...,confirm]`, confirm 0/1 (MEDIUM-HIGH)
- [ccxt OKX exchange docs](https://docs.ccxt.com/docs/exchanges/okx), [ccxt.pro manual](https://docs.ccxt.com/docs/pro-manual) (MEDIUM)

---
*Pitfalls research for: adding live OKX (paper-first) trading to the iTrader event-driven/Decimal/deterministic backtest engine*
*Researched: 2026-06-30*
