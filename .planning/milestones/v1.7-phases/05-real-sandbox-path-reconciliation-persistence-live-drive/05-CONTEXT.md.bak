# Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring up the **real OKX order path against sandbox** and close the live loop — the reconciliation
cluster, the heaviest phase by unique live complexity. Concretely: give `VenueAccount` a real body
(cache the injected connector session's balance/margin/position streams; per-symbol drift detection
under 1 account : 1 portfolio), make partial-fill ingestion idempotent, drive the **v1.6 SQL store
with the real feed** (completing the deferred live composition-root wiring — `VenueAccount` is
constructed at `live_trading_system.py:317` but its body is `NotImplementedError` and it is not yet
linked into `Portfolio`; the live signal store is still the in-memory backtest factory), implement
**two-sided restart rehydration** (reconstruct from store AND reconcile against the live venue), and
harden live resilience (RES-01) — all **sandbox-validated**, real-money execution a gated stretch (not
the DoD). All live/venue machinery stays **inert on the backtest hot path** (oracle byte-exact
`134 / 46189.87730727451`, no W1/W2 regression vs the v1.5 baseline 15.7 s / 152.8 MB).

**Requirements touched:** RECON-01, RECON-02, RECON-03, RECON-04, RECON-05, RECON-06, RES-01 (home
phase). Several are **refined/revised** by this discussion (see the ⚠️ flags) — ROADMAP + REQUIREMENTS
carry stale text (compounding an inherited Phase-4 drift) and need a doc-sync pass.

**Locked upstream (not re-litigated here):** 1 account : 1 portfolio (LX-04, per-symbol drift, no
attribution); venue is source of truth in live (`VenueAccount` caches + reconciles, never computes,
Pitfall 10); OKX subaccount assumed under **exclusive** engine control; async bottled at the connector
edge; Decimal-at-edge (`to_money`, never `Decimal(float)`); single UUIDv7; business-time (never
wall-clock); D-19 single-writer (portfolio state mutates only on the engine thread).

</domain>

<decisions>
## Implementation Decisions

### Drift-repair & halt semantics (RECON-01, RECON-03)

- **D-01 — Auto-correct within a precision-based epsilon; unexplained drift beyond it → halt the WHOLE
  engine.** Tolerance model is precision-based (nautilus `is_within_single_unit_tolerance` style — one
  unit at the instrument's quantity/price precision, i.e. least-significant-digit dust), ties naturally
  to `core/money.py` quantize scales. Drift within the band auto-corrects silently to venue truth;
  drift beyond it that can't be explained stops **all** new order submission engine-wide (streaming,
  reconciling, and persisting continue). This matches nautilus's terminal "System will terminate
  immediately to prevent operation in degraded state" fallback and is the conservative,
  money-correctness-first posture for a sandbox-first v1. **⚠️ REFINES RECON-03** (policy principle was
  locked "halt-and-alert default + tolerance-band auto-correct"; this concretizes *what halt does* and
  *how tolerance is defined*).

- **D-02 — On halt: freeze venue state IN PLACE (nautilus-style).** Stop new submissions, alert
  (D-06), and leave the existing position and any resting/working orders exactly as-is for the
  operator. Do NOT auto-flatten or auto-cancel — the engine has just declared its own state
  untrustworthy, so it must not act on that state. (Trade-off accepted: stale working orders remain
  live on the venue until the operator intervenes.)

### Restart & external-action reconciliation (RECON-05)

- **D-03 — Restart conflict = venue-wins-within-band, halt-and-alert on the truly unexplained.**
  Authority split: **venue is truth for balances/positions/fills; the store is truth for INTENT**
  (which orders we meant to place, strategy linkage, bracket structure). On restart, reconstruct the
  working set from the store, reconcile against the live venue, and auto-adopt venue deltas that map to
  known intent or fall within tolerance (generate reconciling events, nautilus-style). Anything
  unexplained (e.g. a venue position with NO matching stored intent — a hand-opened position) →
  halt-and-alert. "Adopt" is deliberately broader at restart than in steady-state (D-01) because
  disagreement after downtime is *expected*.

- **D-04 — Live external/manual actions: adopt-and-continue (self-heal).** During steady-state live
  running, actions the engine did not originate are absorbed as venue truth: an external **cancel**
  (terminalize the affected mirror) AND an external **fill / hand-closed position** (set position/cash
  from the venue) are adopted and the engine keeps running. Only genuinely nonsensical drift trips the
  D-01 whole-engine halt. This softens the strict exclusive-control posture so manual intervention on
  the subaccount reconciles gracefully (nautilus `generate_missing_orders` / adopt-external analog).
  **Consequence for D-01:** an external fill is NOT treated as unexplained drift — it is adopted; the
  halt is reserved for drift that can't be reconciled to any venue event.

- **D-05 — Brackets (parent/child OCO) on restart: re-adopt from venue, per-bracket halt fallback.**
  Read resting orders from the venue, re-link parent/child using the stored bracket metadata
  (`parent_order_id` / `child_order_ids`), and resume OCO enforcement — never leave an open position
  without its live protective legs. If a specific leg cannot be **confidently** re-linked, escalate
  THAT bracket to halt-and-alert rather than guess. (Re-establishment mechanics are a plan-time
  research item, already flagged in the ROADMAP.)

### Operator alerting surface (RES-01)

- **D-06 — Alert egress = CRITICAL `ErrorEvent` + marked structured log, behind a thin pluggable alert
  sink; external push DEFERRED.** Reuse the existing publish-and-continue plumbing (`ErrorEvent` on the
  queue → `EventHandler._log_error_event`), but escalate halts/unrecoverable errors to a distinct
  CRITICAL severity and route them through a thin **pluggable alert-sink seam** so an external push
  (Telegram/webhook/email) can drop in later **without touching engine code**. Implement ONLY the
  log/ErrorEvent sink this milestone; defer the external channel post-milestone (pairs with FastAPI).
  Matches nautilus's "emit a clean signal, leave delivery to infra" posture.

- **D-07 — Distinct machine-readable HALTED status.** `get_status()` reports a distinct **HALTED**
  state with a reason (drift / reconciliation-unresolved / connector-fatal / paused-on-disconnect),
  separate from running/stopped, so a supervisor / future control channel / FastAPI can detect it and
  act. Makes halt-and-alert observable to automation, not just humans reading logs.

### Phase scope & DoD evidence (RECON-04, RECON-06, RUN-01)

- **D-08 — DEFER the RUN-01 control plane (Postgres `LISTEN/NOTIFY` command/status channel AND the
  FastAPI wrapper) to the later FastAPI application-layer plan.** v1.7 is the *trimmed / minimum surface
  to deploy live*; sandbox validation drives the worker **directly** (local/interactive), so the
  out-of-process channel buys nothing for the DoD. The worker runs standalone; the D-07 HALTED status
  lives on `get_status()` + is persisted in the now-live-driven store, so a future controller has the
  data it needs when it arrives. **⚠️ REVISES RUN-01 again** — Phase 4 (D-08) deferred the channel
  *to* Phase 5; this discussion defers the channel AND FastAPI *past* Phase 5. See [[fastapi-application-layer-plan]].

- **D-09 — "Sandbox-validated" DoD evidence = offline reconciliation gate + opt-in live-sandbox
  suite.** CI gate = automated **offline** reconciliation coverage (mocked/recorded OKX fixtures)
  exercising drift detection, partial-fill idempotency, and restart rehydration — deterministic,
  credential-free, regression-locked. PLUS an **opt-in, network-gated, marked-`slow` live-sandbox
  suite** (`skipif-no-creds`, the Phase-2 D-09 pattern) running the real order→fill→reconcile→restart
  loop against OKX demo as the "validated" evidence, run locally. Real-money execution stays gated
  regardless. (This is the "automated real-connector coverage" Phase-4 D-11 deferred here.)

### Store durability contract (RECON-04)

- **D-10 — Split write paths.** The **sync-durable working set** (must survive a crash for a correct
  two-sided restart) = **order lifecycle (create/terminalize) + position/cash mutations (on fill)**.
  Everything else — the per-bar equity curve, metrics, portfolio-state valuation — is **derived**
  (recomputable from the working set + live prices on restart) and rides the **async/best-effort**
  writer. Equity IS recorded per bar in live (like backtest, for the curve/observability), just off the
  critical path so it can never stall the engine thread or the connector's asyncio loop (Pitfall 9). A
  crash losing the tail of the equity curve is harmless (recomputable).

- **D-11 — Signal store live-driven on the async/best-effort path.** Drive the real signal store live
  (today it's the in-memory backtest factory, `live_trading_system.py:171`), but async/best-effort —
  signals are advisory audit/analysis records, NOT part of the restart working set, so they must not
  block the engine or need sync durability. Satisfies RECON-04's "signal" driven, cheaply.

### Partial-fill terminal policy (RECON-02)

- **D-12 — Partial-then-cancel keeps the fills → CANCELLED.** The accumulated partial fills stand
  (position already reflects them); the unfilled remainder is cancelled and the order terminalizes as
  **CANCELLED** (map onto `VALID_ORDER_TRANSITIONS`). NOT an error/halt — partial-then-cancel is normal
  venue behavior.

- **D-13 — No engine-imposed timeout on long-open partials.** An order stays open (partially filled)
  until fully filled, venue-reported closed, or explicitly cancelled by the strategy. Resting legs
  (brackets/stops/limits) are *meant* to rest — an engine-level auto-cancel would kill legitimate
  orders. Aging/timeout is a strategy concern, kept out of the reconciliation core. Resume-mid-partial
  on restart follows D-03: **venue fill history is authoritative**, the store's cumulative-filled is the
  working-set cross-check.

### Reconciliation cadence & VenueAccount ingestion (RECON-01; Phase-2 D-11 deferred the data-flow shape here)

- **D-14 — Ingestion = push stream + REST pull for snapshot/gap.** `VenueAccount` subscribes to the
  venue's balance/margin/position private stream and updates its cache on each arrival (a thread-safe
  cache write on the connector's asyncio thread); REST pull is used for the startup snapshot, the
  restart reconcile (D-03), and gap recovery on reconnect (D-16). Mirrors the bar feed (stream + REST
  backfill) and the `OkxExchange` fill stream — lowest latency-to-detect, architecturally consistent.

- **D-15 — Drift COMPARE + halt DECISION runs on the ENGINE thread, on fill + on bar.** The async
  thread only writes the cache; the per-symbol drift comparison and the halt decision execute on the
  engine thread — triggered when a `FillEvent` changes our books (immediate, where drift almost always
  surfaces) and once per closed bar as a periodic backstop sweep (catches fee/funding/manual-trade
  drift with no matching fill). This preserves **D-19 single-writer** and avoids the phantom-drift race
  (comparing venue-cache vs engine-computed from the async thread before the queue has drained the fill
  — Pitfall 8). On 1d bars the on-bar backstop is up to a day, which is fine for slow-accrual drift; a
  faster backstop (a timer that *marshals onto the engine thread*) is a post-v1 option, not v1.

### Phase-4 code-review carry-over (04-REVIEW.md deferrals)

- **D-16 — WR-01 resolved-by-decision (BAR-keyed live metrics).** The live daemon
  `_event_processing_loop` currently records portfolio metrics only on `EventType.TIME`
  (`live_trading_system.py:606-608`), but `LiveBarFeed` emits **only `BarEvent`** (no `TimeEvent` on the
  live path) → `record_metrics` is **never called** live (no equity curve). D-10's per-bar live equity
  is delivered by keying metric recording on **`EventType.BAR`** (using `event.time`) — the WR-01 fix,
  on the D-10 async/best-effort path.

- **D-17 — WR-04: split error policy.** The deterministic replay/parity driver runs **fail-fast**
  (matches the backtest it's diffed against — a handler failure aborts loudly so the parity gate can
  never pass on a swallowed error); the **real live path keeps publish-and-continue**, hardened per
  RES-01 (a live session can't abort on one handler error). Resolves the WR-04 false-green window.

- **D-18 — WR-02 (structural half): fold in a shared-parity-config cleanup.** Construct the paper
  replay store window/symbol AND the backtest window from **one shared config literal** so paper/backtest
  parity cannot silently desync (today they agree only because store defaults equal the test literals /
  the default exchange preset admits `BTCUSD`). The Phase-4 assertion/window-guard half is already done;
  this completes the structural half. (Cleanup task, no further decision.)

### Live resilience hardening (RES-01)

- **D-19 — Pause new order submission while any venue stream is disconnected; resume after reconnect +
  REST reconcile.** The engine cannot see fresh venue truth during a gap, so it quiesces order
  submission (surfaced via a paused/HALTED status, D-07) and resumes only after reconnect + a fresh REST
  snapshot/reconcile (D-14). Don't trade when you can't see the venue. A short debounce (so a sub-second
  blip doesn't pause) is a researcher tuning detail.

- **D-20 — Classify connector failures; bounded retry → HALT on exhaustion/fatal.** Transient errors
  (network drop, rate-limit) → retry with bounded backoff, stay running (publish-and-continue). Fatal
  (auth failure) or retries exhausted past a ceiling → escalate to HALTED + CRITICAL alert (D-06/D-07).
  Never spin forever silently. This is what "harden publish-and-continue for live" means.

### Claude's Discretion (plan-time / research-sprint mechanics)
- Exact drift thresholds / precision-epsilon numbers per instrument (D-01); reconnect debounce window
  (D-19); reconnect retry ceiling (D-20) — researcher sets from the OKX error/fee surface.
- OKX partial-fill field cadence / fill-ID semantics (D-12/D-13); `watch_my_trades` vs `watch_orders`
  correlation for accumulation.
- Write-through transaction boundary for the sync-durable working set (D-10) — the v1.6 research flag
  carried forward; async/buffered write-through stays **keep-only-measured** (build only if the live
  loop profiles a stall).
- Rate-limit bucket accounting across ccxt + native paths (RES-01, Phase-2 established it's
  IP-connection-level / light).
- Exact bracket parent/child re-link mechanics on restart (D-05); the store↔venue reconciling-event
  construction (D-03).
- `VenueAccount` cache data structures + the connector→cache push mechanism (D-14) under
  `runtime_checkable` LiveConnector Protocol.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone design & requirements (authoritative; note the revisions this phase makes)
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` — LOCKED LX-01..LX-15. Read
  §"Phase 5" (reconciliation + persistence live-drive), §"5. Cross-cutting" (LX-15 runtime topology,
  resilience, secrets), §"6. Definition of done", §"8. Carried-forward research flags". **This phase
  further defers the LX-15 channel + FastAPI (D-08) and concretizes the reconciliation drift policy.**
- `.planning/ROADMAP.md` — v1.7 Phase 5 goal + success criteria (RECON-01..06, RES-01) + the recurring
  milestone gate. **STALE text to fix (D-18 doc-sync):** RUN-01 still says "Postgres LISTEN/NOTIFY in
  Phase 4"; PAPER-01/02/04 still say "byte-exact vs the oracle 46189…" (inherited Phase-4 drift,
  04-04-SUMMARY.md:89).
- `.planning/REQUIREMENTS.md` — RECON-01..06 full text (lines 105–121), RES-01 (home Phase 5, line 137),
  RECON-04 references v1.6 D-01 / RETAIN-03. **RECON-03/04 refined + RUN-01 stale — flag for doc update.**
- `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS,SUMMARY}.md` (2026-06-30). **PITFALLS.md is
  load-bearing here:** Pitfall 8 (async→single-writer races, D-15), Pitfall 9 (don't stall the loop with
  DB writes, D-10), Pitfall 10 (venue = truth), Pitfall 11 (partial/duplicate/mis-sequenced fills,
  D-12), Pitfall 12 (fees/funding drift).

### Phase-4 carry-over (deferred inputs — MUST read)
- `.planning/phases/04-paper-path-milestone-dod/04-REVIEW.md` — WR-01 (live daemon records no metrics,
  D-16), WR-02 structural (coincidental parity config, D-18), WR-04 (error-policy divergence, D-17).
  Resolution table lines 33–45.
- `.planning/phases/04-paper-path-milestone-dod/04-CONTEXT.md` — D-08 (channel deferred here), D-11
  (real-connector coverage automated here). The paper path this phase builds the real sibling of.
- `.planning/phases/04-paper-path-milestone-dod/04-VERIFICATION.md` — "Known Drift" (stale RUN-01 text).

### Prior-phase seams (build against these)
- `.planning/phases/02-okx-connector/02-CONTEXT.md` — D-02 (connector = session/transport primitive),
  D-03 (arm/adapter split; `VenueAccount` account arm), D-04 (injection at composition root), D-07 (the
  exchange emits `FillEvent`), D-11 (VenueAccount push-vs-pull data-flow deferred to Phase 5 → D-14).
- `.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-CONTEXT.md` — the `Account` ABC
  + `VenueAccount` interface-only leaf; the surviving ACCT-05 engine command surface (D-07 HALTED status).

### The seams to implement / wire (Phase-5 code targets)
- `itrader/portfolio_handler/account/venue.py` — `VenueAccount`: constructor holds the injected
  `LiveConnector` session; abstract methods (`balance`/`available`/`reserve`/`release`) are
  `NotImplementedError` stubs — implement the cached-venue + reconcile body here (D-01/D-03/D-14/D-15).
  **Import discipline: `LiveConnector` stays `TYPE_CHECKING`-only** (backtest-inertness gate).
- `itrader/portfolio_handler/account/base.py` — `Account` ABC (the contract `VenueAccount` fulfils).
- `itrader/connectors/okx.py` — `OkxConnector` session (the injected `call`/`spawn`/`client` surface).
- `itrader/connectors/base.py` — `LiveConnector` Protocol (the session/transport contract).
- `itrader/execution_handler/exchanges/okx.py` — `OkxExchange`: `_handle_trade`/`_stream_fills`
  (`watch_my_trades`), `_stream_orders` (`watch_orders`), venue-id→OrderEvent correlation — the
  partial-fill accumulation + idempotency (D-12/D-13) lands against this stream.
- `itrader/price_handler/providers/okx_provider.py` — `OkxDataProvider` (data arm; the reconnect/gap
  pattern to mirror for the account stream, D-14/D-19).
- `itrader/price_handler/feed/live_bar_feed.py` — `LiveBarFeed._emit` (BAR-only emission; the reason
  metrics must key on BAR, D-16).
- `itrader/trading_system/live_trading_system.py` — composition root: `VenueAccount` constructed at
  :317 (wire into `Portfolio`), `_event_processing_loop` :606-608 (WR-01/D-16 TIME→BAR fix),
  `SignalStorageFactory.create('backtest')` :171 (D-11 live-drive), `SYSTEM_DB_URL` store wiring
  :183-204 (interim Postgres-or-in-memory — complete the live-drive), `_publish_and_continue` :358
  (D-17 error-policy split), `get_status` :651 (D-07 HALTED state), `run_paper_replay` (D-17/D-18).
- v1.6 stores (drive live per RECON-04/D-10/D-11): `itrader/order_handler/storage/{sql_storage,
  cached_sql_storage}.py`, `itrader/portfolio_handler/storage/{sql_storage,cached_sql_storage}.py`,
  `itrader/strategy_handler/storage/{sql_storage,cached_sql_storage}.py`. The `cached_sql_storage`
  (write-behind) variants are the natural home for the async/best-effort path (D-10/D-11).
- `itrader/events_handler/events/error.py` (`ErrorEvent`/`PortfolioErrorEvent`) +
  `itrader/events_handler/full_event_handler.py::_log_error_event` — the alert-sink seam target (D-06).
- `scripts/run_live_paper.py` — the standalone worker; `--mode okx` is the live-sandbox smoke entry
  (D-09).

### External verification (nautilus-trader — installed reference for the reconciliation model)
- `.venv/.../nautilus_trader/live/execution_engine.py` — startup + continuous reconciliation:
  `_process_cached_position_discrepancies`, retry-then-resolve, and the "terminate immediately to
  prevent operation in degraded state" fallback (line ~553) — the D-01 whole-engine-halt precedent.
- `.venv/.../nautilus_trader/live/reconciliation.py` — `is_within_single_unit_tolerance` (D-01
  precision-epsilon), `create_inferred_order_filled_event` (D-03 reconciling-event generation),
  `get_existing_fill_for_trade_id` (D-12 fill-ID dedup). Config knobs `filter_unclaimed_external_orders`
  / `generate_missing_orders` (D-04 adopt-external precedent).
- `.venv/.../nautilus_trader/adapters/okx/{data,execution}.py` — OKX adapter reference.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`VenueAccount` stub** (`account/venue.py`) — constructor + Account contract already shaped (Phase 1
  D-11); implement the body only. `LiveConnector` session already injected at the composition root.
- **`OkxExchange` fill/order streams** (`exchanges/okx.py`) — `watch_my_trades`/`watch_orders`
  consume-loops + venue-id→OrderEvent correlation already exist; partial-fill idempotency layers on top.
- **v1.6 SQL stores** (order / portfolio-state / signal) with **direct + `cached_sql_storage`
  write-behind** variants — built + tested on testcontainers Postgres in v1.6; this phase drives them
  with the real feed. Write-behind variant = the async/best-effort path (D-10/D-11).
- **`OkxDataProvider` reconnect/backfill** — the stream + REST-backfill pattern to mirror on the account
  stream (D-14/D-19).
- **Publish-and-continue plumbing** (`ErrorEvent` → `_log_error_event`) — the alert egress to escalate
  + wrap in a pluggable sink (D-06).
- **nautilus-trader reconciliation** (installed) — the reference algorithm for D-01/D-03/D-12.

### Established Patterns
- **DI at the composition root / injection over cross-domain import** — `VenueAccount` gets the session;
  wire it into `Portfolio` at `LiveTradingSystem.__init__` (D-14).
- **Queue-only cross-domain writes / D-19 single-writer** — cache writes on the async thread, but the
  drift/halt DECISION and portfolio mutation on the engine thread (D-15). Multiple queue producers OK
  (`queue.Queue` MPSC-safe).
- **Decimal edge** — `to_money(str(x))` at every ccxt float boundary (venue balances/positions/fills);
  never `Decimal(float)`.
- **Backtest hot path stays inert** — no async/connector/SQLAlchemy import on the backtest path;
  `LiveConnector` `TYPE_CHECKING`-only in `venue.py`; SQL imports lazy inside the live arm.
- **Business-time stamping** — `FillEvent.time` / metric time from venue/bar stamps, never wall-clock.

### Integration Points
- OKX private stream → `VenueAccount` cache (push, D-14); REST → snapshot/reconcile/gap (D-14/D-19).
- `FillEvent` (from `OkxExchange`) → `PortfolioHandler.on_fill` → drift compare on the engine thread
  (D-15); partial accumulation + fill-ID dedup at this seam (D-12).
- BAR route (engine thread) → periodic drift sweep (D-15) + `record_metrics` (D-16, was TIME-keyed).
- Working-set writes → sync-durable stores; equity/metrics/signals → async/best-effort stores (D-10/D-11).
- Restart: store rehydrate + venue REST reconcile → reconciling events / halt (D-03); bracket re-adopt
  (D-05).
- Halt/fatal → CRITICAL `ErrorEvent` + pluggable sink + `get_status()` HALTED (D-06/D-07).

</code_context>

<specifics>
## Specific Ideas

- User anchored the halt model on **what real frameworks do**: chose the **nautilus** posture
  (auto-correct within precision tolerance → else terminate the whole engine) as the conservative v1
  default over freqtrade/Hummingbot's silent self-heal.
- User explicitly wants **manual venue intervention to reconcile gracefully** ("will this reconcile a
  manually closed order?") → drove D-04 (adopt-and-continue for external actions), softening strict
  exclusive-control.
- User's own current practice: **equity stored per bar in backtest** — wants the same live equity curve
  → confirmed D-10 (record per bar in live too, but on the async/best-effort path, not the sync-critical
  path; the WR-01 TIME→BAR fix is what actually delivers it live).
- User surfaced the **Phase-4 code-review deferrals** (WR-01/02/04) unprompted — folded as D-16/17/18.
- User deferred the control plane deliberately: "I'll design this part later" → D-08 (channel + FastAPI
  to the app-layer plan).

</specifics>

<deferred>
## Deferred Ideas

- **Postgres `LISTEN/NOTIFY` command/status channel + FastAPI wrapper** — the worker's out-of-process
  control plane; the D-07 HALTED status + persisted store hold the data a future controller reads.
  Belongs to the dedicated FastAPI application-layer plan (D-08). See [[fastapi-application-layer-plan]].
- **External alert push (Telegram / webhook / email)** — drop into the D-06 pluggable alert-sink seam
  post-milestone; wanted before real-money running.
- **Real-money execution** — a gated stretch beyond the DoD (LX-01); sandbox is the milestone bar.
- **Faster on-timer drift backstop** (a timer that marshals onto the engine thread) — post-v1; v1 uses
  on-fill + on-bar (D-15).
- **Strategy-level partial-fill aging/timeout** — out of the reconciliation core (D-13); a strategy
  concern if wanted.
- **Async/buffered write-through** for the sync-durable working set — keep-only-measured; build only if
  the live loop profiles a stall (D-10, v1.6 research flag).
- **ROADMAP + REQUIREMENTS doc-sync** — stale RUN-01 (channel-in-Phase-4) + PAPER-01/02/04 (byte-exact
  framing) text; fold the update into Phase-5 planning (D-18 scope). Inherited from Phase-4's
  non-blocking flag, now compounded by this phase's revisions.

### Reviewed (carried from Phase 4, still deferred)
- **`margin-equity-double-counts-notional-wr01.md`** (WR-01 margin-equity gap) — a valuation defect
  present in both paths; NOT the same as Phase-4-review WR-01 (the metrics-recording one, D-16). Still
  deferred, never externally cross-validated. See [[wr01-margin-equity-frozen-golden-gap]].
- **`single-pass-portfolio-valuation.md`** — valuation/perf; out of Phase-5 reconciliation scope.

</deferred>

---

*Phase: 5-real-sandbox-path-reconciliation-persistence-live-drive*
*Context gathered: 2026-07-02*
