# v1.7 Phase-5 live-path bug register + action roadmap

**Source:** adversarial code review of `v1.7/phase-5-sandbox-path` vs `main` (2026-07-04).
Scope was the live OKX reconciliation / partial-fill / persistence cluster. All findings
below were verified by direct code trace unless marked *Plausible*. Line numbers refer to
the branch as of commit `cfaed3f1`.

**Headline:** the sandbox e2e "8/8 passed" status is consistent with a completely broken
settlement path — V17-01 explains how every online test goes green while no fill ever
settles into the portfolio. Do not run against real money until V17-01..V17-04 are
confirmed-and-fixed and the sandbox e2e is re-run with the strengthened assertions (CONF-B).

---

## Findings

### CRITICAL

**V17-01 — VenueAccount lacks the concrete account surface the settlement/admission paths call**
- Where: `portfolio_handler/account/venue.py:53` vs `portfolio_handler/portfolio.py:381,397,888`,
  `portfolio_handler/portfolio_handler.py:300`; wiring `trading_system/live_trading_system.py:565`
- `Portfolio.transact_shares` calls `account.assert_funds_invariant()` / `account.apply_fill_cash_flow()`,
  and the admission read-model calls `account.available_balance` — all `SimulatedCashAccount`
  concretions. `VenueAccount` implements only the ABC (`balance/available/positions/reserve/release`).
  After `_link_venue_account_to_portfolios()`:
  - every SIGNAL admission → `AttributeError` → swallowed by publish-and-continue → no order admitted;
  - every BUY fill → raises before position mutation → fill never settles (silent divergence);
  - every SELL fill → raises AFTER `process_position_update` → **partial mutation** (position moved,
    cash not, transaction unrecorded, settled-set not written → redelivery re-mutates position).
- Why e2e stayed green: `tests/e2e/test_okx_sandbox_recon.py` bypasses admission (helper docstring
  says so), asserts only the order mirror + emitted fills, never portfolio position/cash; the
  drift-tolerance loop iterates an empty venue-positions map (see V17-04).
- Test gap: no test drives `transact_shares` on a VenueAccount-linked portfolio.

**V17-02 — `venue_order_id` never populated/persisted on the live submit path → two-sided restart is inert**
- Where: `execution_handler/exchanges/okx.py:313-321` (venue id goes only into the in-memory
  `VenueCorrelationIndex`); sole production writer of `Order.venue_order_id` is
  `venue_reconciler.py:404-406` (restart-time bracket re-link only).
- After any real session every stored order has `venue_order_id = NULL`, so on restart:
  `_adopt_fill_deltas` adopts nothing (downtime fills silently lost), `_adopt_venue_correlation`
  repopulates nothing (post-restart fills for rehydrated orders buffered forever; cancels are
  silent no-ops), bracket venue-id-first re-link never fires. Subsumes the
  crash-between-venue-ack-and-store-write window — the ack is *never* stored.
- Test gap: all restart tests hand-stamp `venue_order_id` into fixtures
  (`test_two_sided_restart.py:123`, `test_bracket_restart_relink.py:118`, e2e:465).

**V17-03 — startup halt clobbered to RUNNING**
- Where: `live_trading_system.py:993` (`_event_processing_loop` → unconditional
  `_update_status(RUNNING)`); `_update_status` (:745) has no HALTED latch; `start()` continues
  after `reconciler.reconcile()` halts.
- Orphan-position / unconfident-bracket halt during `start()` → engine thread starts → status
  flips back to RUNNING → SIGNAL/ORDER gate reopens → engine trades on state the reconciler
  declared untrustworthy; `get_status()` shows `status=running, halt_reason=reconciliation-unresolved`.
- Test gap: reconciler tests use a `_HaltSpy` directly; halt-policy tests never start the loop
  after a halt. Nothing exercises halt-during-start.

**V17-04 — venue position truth is derivatives-only; wired spot pair (BTC/USDC) is blind**
- Where: `portfolio_handler/account/venue.py:127-148` (`_extract_positions` parses
  `fetch_positions`/`watch_positions` — ccxt derivatives endpoints); consumed by
  `portfolio_handler.py:736` (`_compare_symbol_drift`), `:772` (`_run_drift_sweep`),
  `venue_reconciler.py:336` (`_halt_on_orphan_positions`).
- OKX spot holdings never appear in positions; `VenueAccount.positions` is permanently `{}` for
  BTC/USDC spot. Two arms, both defects:
  - today (with V17-01 unfixed): venue 0 vs engine 0 → drift + orphan halt structurally blind —
    missed fills / manual trades / restart position loss undetectable;
  - once V17-01 is fixed: first spot fill → engine 0.0001 vs venue 0 at 1e-8 tolerance →
    `halt("drift")` on every position-opening fill (live path cannot hold a position).
- Related: `VenueAccount` is constructed with default `quote_currency="USDT"`
  (`live_trading_system.py:400`) while the pair trades USDC — balance/available cache tracks the
  wrong settlement currency (admission gates against USDT free).
- Test gap: `test_venue_account_drift.py` feeds derivative-shaped payloads production spot never
  produces; e2e test (ii) tolerance loop is vacuous (empty map).

### HIGH

**V17-05 — restart forgets portfolio state; the "durable venue_trade_id ledger" is never written at runtime**
- No portfolio/transaction storage is wired in live (`PortfolioHandler(self.global_queue)` only;
  `self._portfolios` in-memory). `_settled_venue_trade_ids` (CR-01 dedup) is volatile. The
  `transactions.venue_trade_id` column (hl5 migration) is written only by tests.
- Restart with positions from completed (terminal) orders → engine flat, venue holding → on spot
  undetectable (V17-04) → strategy re-buys → doubled real exposure, silently.

**V17-06 — order mirror has no `venue_trade_id` dedup → duplicate delivery corrupts `filled_quantity`**
- Where: `order_handler/reconcile/reconcile_manager.py:154-216`; dedup only at
  `portfolio_handler.py:838`. Exchange ring capacity 10 000 (`venue_correlation.py:44`) vs
  portfolio 100 000; ring empty after restart.
- Sequence: reconciler adopts partial T1=0.2; stream re-delivers T1 (post-restart ring empty;
  portfolio rejects, mirror accumulates again → filled 0.4 vs truth 0.2) → completing fill T2=0.8
  rejected by over-fill guard → order stuck PARTIALLY_FILLED, reservation held forever → next
  restart's skip-budget mis-splits T2 → 0.6 of an already-settled trade re-applied to the
  portfolio (settled-set volatile per V17-05). Same in-session after ring eviction (>10k trades)
  on a long-lived partial (bracket legs).

**V17-07 — stream-death blind spots (taxonomy holes, unobserved tasks, unsupervised VenueAccount streams)**
- `okx.py:541-576` / `okx_provider.py:324-341`: supervisors catch only NetworkError-family
  (transient) and AuthenticationError/PermissionDenied (fatal) — a plain `ccxt.ExchangeError`,
  `BadRequest`, or `json.JSONDecodeError` (`okx_provider.py:274`, outside the guard) kills the
  task. `connectors/okx.py:182`: `spawn`'s done-callback only discards the handle — task
  exceptions never observed. `venue.py:160-179`: `_stream_account`/`_stream_positions` are bare
  `while True` loops with NO supervisor — first transient error kills venue cache updates for the
  session (drift/admission read a frozen cache).
- Test gap: `test_reconnect_resilience.py` feeds only the two handled families.

**V17-15 — live gap backfill self-deadlocks the connector loop → BAR delivery livelock + 30s stalls of ALL streams** *(source: AUD-4, v17_audit_results.md)*
- Where: `price_handler/feed/live_bar_feed.py:298` (`_backfill_gap` → `fetch_ohlcv_backfill`)
  → `okx_provider.py:484,490` (`connector.call(client.fetch_ohlcv(...))`) →
  `connectors/okx.py:162-166` (`run_coroutine_threadsafe(...).result(timeout=30)`).
  `LiveBarFeed.update()` runs ON the connector loop thread (bar sink wiring
  `live_trading_system.py:411`; thread model `live_bar_feed.py:20-22`), so the gap branch
  (`live_bar_feed.py:171-173`) invokes the blocking `call()` FROM the loop thread: the
  scheduled coroutine can never run while `.result()` blocks the loop → guaranteed 30s
  full-connector stall (fills/balance/orders streams all frozen) then `TimeoutError`.
- Aftermath: the `TimeoutError` propagates out of `update()` into the candle consume loop;
  the supervisor classifies it TRANSIENT (`asyncio.TimeoutError` ≡ builtin `TimeoutError` on
  3.13, in the transient tuple `okx_provider.py:324-326`) → reconnect → OKX snapshot-on-subscribe
  re-delivers the post-gap bar → gap branch again → another 30s stall → **livelock**: the gap
  never fills, `L` never advances, no BarEvent is ever delivered again, and every cycle stalls
  the private streams 30s. A single missed bar (brief WS drop across a bar close) arms it.
- The warmup path is safe (engine thread, pre-stream — `live_trading_system.py:1100-1101`);
  only the mid-session gap path deadlocks. `backfill_on_resume` (the third caller) is dead
  code today (LOW-batch item) — wiring it onto the engine thread would ALSO be unsafe
  (second writer racing the connector-thread `update()` on ring/guard state, see AUD-5).
- Fix shape: make the gap fetch loop-native — e.g. an async `fetch_ohlcv_backfill` awaited
  directly inside the candle coroutine (no `call()` bridge), or hand the gap range to a
  dedicated backfill coroutine spawned on the loop; never a blocking bridge from loop-thread
  code. (The `LiveConnector.call` contract note in AUD-4c pins the rule.)
- Test gap: no test drives `update()`'s gap branch through a REAL connector-loop thread —
  gap tests call `update()` from the test thread where the blocking bridge works fine.

**V17-08 — fills during a disconnect are never recovered mid-session**
- `live_trading_system.py:691-725`: resume = REST balance/position snapshot only (WR-04 decision);
  no `fetch_my_trades` catch-up; OKX/ccxt do not replay missed private pushes on resubscribe.
  `okx.py:563`: an attempt==1 reconnect fires no pause → not even a snapshot. `okx.py:662-671`:
  `_consume_orders` only logs — venue-side cancels/expiries never reconcile the mirror
  (steady-state arm acknowledged in the Phase-7 spec `127402fc`, but the missed-fill window is
  not covered there either).

### MEDIUM

**V17-09 — submit timeout misclassified as venue rejection**
- `okx.py:210-252` + `connectors/okx.py:166`: `call()` timeout (30s) → treated as
  submit-never-reached-venue → `FillEvent(REFUSED)` → mirror REJECTED, reservation released —
  while the un-cancelled `create_order` coroutine may still succeed at the venue. Later fill
  correlates onto a terminal mirror; venue id never registered → order un-cancellable.
  Correct semantics: unknown/in-flight + reconcile (Nautilus-style).

**V17-10 — restart fill adoption assumes one unpaginated `fetch_my_trades()` is complete history**
- `venue_reconciler.py:131,449-452`: no symbol, no `since`, no pagination; ccxt OKX default hits
  `/trade/fills` (recent-days window, capped rows). Persisted `filled_quantity` covering aged-out
  trades → skip-budget mis-attributes skips to newer trades → downtime deltas silently dropped or
  wrong remainders emitted. *Plausible→Confirmed structurally* (unguarded completeness assumption).

**V17-11 — halt/pause gate silently DROPS system-generated ORDER events (no deferral)**
- `live_trading_system.py:736-743`: while paused/halted, ALL ORDER events are discarded —
  including bracket-child submissions and OCO/orphan cancels generated by a FILL that drains
  during the pause (one-shot, no retry queue) → position can exit a pause window permanently
  unprotected at the venue. Also swallows operator CANCELs while halted.

**V17-12 — trade-id dedup keyed on raw OKX `tradeId` (instrument-scoped) in one global set**
- `portfolio_handler.py:838` + `venue_correlation.py:168`: OKX tradeIds are per-instrument
  sequences; two symbols colliding on the same numeric id → the second symbol's legitimate fill
  rejected as duplicate → silently lost. Latent today (single symbol), armed by the first
  multi-symbol wiring.

**V17-13 — reservation overlay double-counts the venue's own hold**
- `venue.py:252,307`: OKX `free` already excludes funds frozen for acked resting orders; the
  overlay subtracts `_pending` on top → buying power understated by every resting order until the
  next snapshot. Over-conservative (blocks trading, not capital loss).

**V17-14 — remaining unguarded concretion surface beyond V17-01: serialization path + cast-based margin narrowing** *(source: AUD-1 census, v17_audit_results.md)*
- Where: `portfolio_handler/portfolio.py:888-889` (`to_dict` reads `account.available_balance`
  / `account.reserved_balance` — neither on the `Account` ABC nor on `VenueAccount`);
  `portfolio.py:438` + `:834` (`cast(SimulatedMarginAccount, self.account)` — zero runtime
  check — gating the full margin surface `:495,522-524,543-549,580` and `accrue_borrow_interest`).
- On a VenueAccount-linked portfolio: any `to_dict()` consumer raises AttributeError; with
  `enable_margin=True` the cast sites die **mid-settlement** with the same partial-mutation
  hazard as V17-01's SELL arm. Latent today: the only `to_dict` route is
  `generate_portfolios_update_event` (`portfolio_handler.py:1034`), which has NO production
  caller (itself an orphan producer — see AUD-2), and live wiring is spot-only. Armed by the
  first monitoring/API surface that serializes portfolios, or the first live-margin wiring.
- Fix rides the V17-01 / ARCH-1 contract decision: whichever surface lands on the ABC must
  include (or re-point) these two serialization reads, and the margin narrowing needs a runtime
  guard (isinstance + typed error) instead of a bare `cast`.
- Test gap: nothing serializes a venue-linked portfolio; no test constructs a margin+venue
  combination.

**V17-16 — live external order entry is a zero-validation raw-queue injection; OKX preflight is dead code** *(source: AUD-6, v17_audit_results.md)*
- Where: `live_trading_system.py:1323` (`add_event` — the only external entry surface since
  `trading_interface.py` was deleted in `26b914e3`, v1.7 Phase 1); ORDER route is
  execution-handler-only (`full_event_handler.py:99`); `okx.py:254-311` `_submit_order` never
  calls `validate_order` (`okx.py:734`, qty>0) or `validate_symbol` (`okx.py:743`) — only
  `SimulatedExchange` invokes its own preflight (`simulated.py:202,473`).
- An externally injected `OrderEvent` reaches the venue with NO field/symbol/price/quantity/
  funds/direction checks, no cash reservation, and NO order mirror: the clOrdId correlates the
  eventual fill to an order id `OrderStorage` has never stored → `ReconcileManager.on_fill`
  lookup fails → unreconcilable fill; portfolio settles (post V17-01 fix) against an order the
  order domain doesn't know. The halt/pause gate is the path's ONLY check.
- Also stales D-03a: the dual-validator decision's live-bypass rationale referenced the
  deleted `TradingInterface`, and the exchange-side layer it leans on is uncalled on the live
  venue (see AUD-6d proposed CONVENTIONS.md note).
- Fix shape: route external order creation through the admission pipeline (signal-form entry
  or direct `AdmissionManager` call) so validation+sizing+reservation+mirror engage; wire
  `OkxExchange.on_order` preflight (`validate_order` + `validate_symbol`) as defense-in-depth,
  mirroring `simulated.py:202/473`; optionally restrict `add_event` to non-ORDER event types.
- Test gap: no test injects an OrderEvent via `add_event` on a live-wired system.

### STILL-OPEN carried items (re-confirmed in current code)

- **05-13 WR-02 (upgrade to High):** `resolve` marks a trade id seen BEFORE `_emit_fill`
  validates (`venue_correlation.py:181-183` + `okx.py:434`) — a malformed-then-corrected re-send
  is dropped as duplicate → a settled trade permanently lost.
- **05-13 WR-01:** clOrdId map leaks on submit-failure and fast-fill-full-fill; `register()`
  re-adds dead entries after self-release (`okx.py:320,420`).
- **05-13 WR-03:** buffered re-sends not deduped; `release()` drain emits via `_emit_fill`
  directly, bypassing `resolve` dedup (`okx.py:490-491`) → double FillEvents (mirror
  double-count feeds V17-06).
- **05-13 IN-01:** `capacity=0` → unbounded seen-set.
- New in same family: `_pending_fills_by_venue_id` buffers manual/out-of-band account trades
  forever (unbounded, never emitted, never alarmed — `venue_correlation.py:178`); `adopt()` never
  seeds the cumulative counter with rehydrated `filled_quantity` → release-on-terminal can't fire
  for pre-filled rehydrated orders.

### LOW (batch)

- `_order_trades` tie-break sorts trade ids lexicographically (`venue_reconciler.py:271-274`) —
  deterministic across restarts (adopt-once holds) but can mis-order same-ms trades vs venue
  order, skewing boundary-straddle commission proration.
- `_relink_bracket` `matched["id"]` KeyError if a fallback-matched resting order carries no id
  (fail-loud at start, not silent).
- Bracket-leg fallback matching hardcodes precisions 2/8 instead of instrument-derived.
- `make test` default (`-m "not live"`) does not exclude the slow e2e suite.
- Alert egress is log-only (documented deferral) — a 3am halt reaches nobody.
- `LiveBarFeed.backfill_on_resume` is never called by the resume path (boundary bar recovers only
  at the next delivered bar — up to one bar-period stall on 1d).
- Duplicated ~100-line supervisor state machine in `okx.py` vs `okx_provider.py`.

### Verified clean (no action)

- Float-for-money: no `Decimal(float)` in the diff; all venue ingress via `to_money(str(x))`
  with None-guards; outbound via ccxt string precision helpers.
- `drift.py` epsilon primitive; halt idempotency latch (per se); SQL order writes transactional
  (single `engine.begin()`); WR-04 base62 clOrdId; WR-06 ERROR-route terminal-safety.

---

## Action roadmap

### Phase CONF-A — offline confirmation (no network, no credentials; RED tests that pin each bug)

Write these as failing tests first — they become the regression suite for the fixes.

1. **A1 (V17-01):** unit test — build a portfolio, set `portfolio.account = VenueAccount(fake_connector)`
   (snapshotted), then (a) call the admission read-model `available_cash` → expect AttributeError
   today; (b) drive `transact_shares` with a BUY transaction → expect AttributeError before
   position mutation; (c) SELL against an existing position → assert the partial-mutation hazard
   (position mutated, no cash ledger entry, no transaction recorded).
2. **A2 (V17-02):** unit test — `OkxExchange._submit_order` against a fake connector returning
   `{"id": "OKX-1"}`; assert the STORED order's `venue_order_id` is stamped + persisted
   (fails today: only the in-memory index is written).
3. **A3 (V17-03):** integration test — `start()` a system whose reconcile path calls
   `system.halt("reconciliation-unresolved")`; after the engine thread starts, assert
   `get_status()["status"] == "halted"` (fails today: RUNNING).
4. **A4 (V17-04):** unit test — VenueAccount-linked portfolio, empty venue positions (the real
   spot payload), apply one EXECUTED fill → assert no `halt("drift")` fires AND the divergence is
   still surfaced somewhere (this test encodes the chosen fix semantics; today it halts —
   once A1 is fixed — or is blind).
5. **A5 (V17-06):** unit test — adopt partial T1 via a reconciling fill, re-deliver T1 through the
   FILL route with a fresh exchange index; assert mirror `filled_quantity` unchanged (fails today).
6. **A6 (V17-07):** unit tests — feed `ccxt.ExchangeError` (and garbage JSON to the provider
   consume loop) into the supervisors → assert halt/pause fires instead of silent task death;
   kill `_stream_account` with one `NetworkError` → assert it resumes or escalates.
7. **A7 (V17-09):** unit test — `connector.call` raising `TimeoutError` on submit → assert the
   mirror is NOT terminalized to REJECTED (encodes the in-flight fix semantics).
8. **A8 (V17-11):** unit test — FILL drains during pause → bracket-child/cancel OrderEvents are
   deferred and replayed on resume, not dropped (encodes fix semantics).

### Phase CONF-B — one gated sandbox run (OKX demo, human-triggered)

Extend `tests/e2e/test_okx_sandbox_recon.py` with the assertions the current suite lacks, then
run once online:

- after the demo fill: `portfolio_handler.get_position(pid, "BTC/USDC")` is non-None with
  qty ≈ filled qty; portfolio cash decreased by ≈ cost+fee; `status != HALTED`.
- assert `fetch_positions()` result for the spot pair (expected `[]` — empirically pins V17-04).
- assert the stored order's `venue_order_id` is non-NULL post-fill (pins V17-02 online).
- Expected today: these additions FAIL — that failure is the confirmation artifact. Record the
  output in `.planning/debug/` before fixing anything.

### Phase FIX — proposed solutions (dependency order)

**Wave 1 — make settlement possible (blocks everything else):**
- **V17-01:** decide the account contract, then enforce it.
  Option (a) *recommended*: keep the engine-side cash ledger authoritative for settlement —
  extend the `Account` ABC with the members Portfolio actually calls
  (`available_balance`, `assert_funds_invariant`, `apply_fill_cash_flow`) and implement them on
  `VenueAccount` (ledger-backed locally, reconciled to venue truth by snapshot/drift). Option (b):
  restrict `Portfolio` to the ABC surface and route settlement through a separate ledger object.
  Either way: add `mypy` coverage (remove `live_trading_system` from the ignore list or add a
  typed conformance test) so ABC-vs-concretion drift can never ship again.
- **V17-04:** venue truth must be venue-type aware — for spot, derive per-symbol position truth
  from base-currency balances (`fetch_balance`/`watch_balance` totals), not `fetch_positions`;
  key `VenueAccount` by the actual quote currency (USDC) from wiring, not the USDT default; wire
  a minimal `drift_reconciler` (or widen the band policy) so a just-applied engine fill vs a
  not-yet-refreshed venue snapshot doesn't spuriously halt.
- **V17-03:** make HALTED latching: `_update_status` refuses HALTED→RUNNING (only an explicit
  operator `reset()` clears it); `start()` checks `_is_halted()` after `reconcile()` and aborts
  (status stays HALTED, thread not spawned or spawned in drain-only mode).

**Wave 2 — make restart real:**
- **V17-02:** persist the venue ack. Cleanest inside the architecture: `OkxExchange` emits a
  small ORDER-ACK event (new frozen event + route) carrying `order_id → venue_order_id`;
  `OrderHandler` consumes it, stamps the mirror, `update_order()` persists. (Minimal alternative:
  a direct injected callback from exchange to order storage — faster, but bends the queue-only
  rule.) Then delete the fixture hand-stamping from the restart tests and drive the real path.
- **V17-05:** wire the existing portfolio SQL storage in live (same `SqlBackend` spine) so
  transactions (with `venue_trade_id`) persist; on restart, rehydrate the settled-trade ledger
  from the transactions table (bounded window) before the reconciler runs.
- **V17-06:** per-order dedup — persist applied `venue_trade_id`s on the order mirror (or check
  the rehydrated settled-ledger from V17-05) inside `ReconcileManager._apply_executed` before
  accumulating; key both dedup layers as `f"{symbol}:{trade_id}"` (also fixes V17-12).
- **V17-10:** reconciler fill fetch: per-symbol, paginated, `since = oldest active order's
  created_at`; log loudly when the venue window cannot cover the oldest active order.

**Wave 3 — resilience hardening:**
- **V17-07:** add `except Exception → _escalate_connector_halt` catch-all to BOTH supervisors
  (fail-safe: unknown ⇒ halt, never silent death); move `json.loads` inside the per-message
  guard; wrap `_stream_account`/`_stream_positions` in the same supervisor (extract the
  duplicated state machine into one shared helper — also clears the LOW duplication item);
  `connector.spawn` done-callback logs `task.exception()` and escalates.
- **V17-08:** on resume (and on the attempt==1 path), run a bounded `fetch_my_trades(symbol,
  since=disconnect_ts)` and route results through `_handle_trade` (the dedup path makes replays
  safe once V17-06 lands); translate `watch_orders` CANCELLED/EXPIRED into
  `FillEvent(CANCELLED/EXPIRED)` (or fold into the Phase-7 mid-session lifecycle spec — but the
  missed-fill catch-up cannot wait for Phase 7).
- **V17-09:** on `TimeoutError` (and any ambiguous transport error) do NOT emit REFUSED — mark
  the mirror in-flight/unknown and resolve via `fetch_order(clOrdId)` retry or the next
  reconcile; only a definitive venue rejection produces REFUSED.
- **V17-11:** during pause/halt, DEFER system-generated protective orders (bracket children, OCO
  cancels) into a replay queue drained on resume; always let CANCEL commands through (they reduce
  risk); keep suppressing only fresh entry orders.
- **V17-13:** drop the local pending overlay entry once the venue ack for that order arrives
  (venue hold takes over), instead of waiting for terminal release.
- **05-13 carry-overs:** move mark-seen after successful emit (or validate payload inside
  `resolve` before consuming the dedup slot); route `release()` drains through `resolve` instead
  of raw `_emit_fill`; `release_pending(clordid)` on submit failure; reject `capacity < 1`;
  bound + alarm the uncorrelated-fill buffer (an uncorrelated fill on the account is an
  external-trade signal, not just noise); seed `adopt()`'s cumulative counter from rehydrated
  `filled_quantity`.

### Gates (unchanged, apply to every wave)

- SMA_MACD backtest oracle byte-exact (`tests/integration/test_backtest_oracle.py`) — all fixes
  must stay oracle-dark (live-path only).
- `mypy --strict` clean; full suite via `poetry run pytest tests` (not `make test` — see memory:
  env quirks).
- CONF-B (sandbox e2e with strengthened assertions) re-run GREEN after Wave 1 and again after
  Wave 2 — it is the only online proof of the settlement path.

### Suggested sequencing note

CONF-A tests are independent → can be written in one wave. Wave 1 is the go/no-go for any
further sandbox work (nothing downstream is observable until settlement works). V17-08's
steady-state arm overlaps the Phase-7 mid-session-reconciliation spec (`127402fc`) — fold the
`watch_orders` translation there, but pull the missed-fill catch-up forward into Wave 3.

### Systemic patterns to audit beyond Phase 5 (candidate review widening)

> Expanded into a full audit campaign + architecture-decision register in
> [`v17_widen_audit_architecture.md`](v17_widen_audit_architecture.md) (AUD-1..AUD-7,
> ARCH-1..ARCH-4). The summary below is kept for context.

1. ABC-swap seams verified by identity, not by driving money through them (V17-01/04 root) —
   audit Phase 1's Account refactor and Phase 4's paper-path seams the same way.
2. Schema/field landed without its producer (`venue_order_id`, `transactions.venue_trade_id`) —
   grep Phases 2–4 for columns/fields with no production writer.
3. Publish-and-continue as a silent money sink — consider an N-errors-on-FILL/ORDER-route →
   halt circuit breaker.
4. Tests that hand-build the state production is supposed to produce (fixture-stamped venue ids,
   derivative-shaped payloads, admission bypass) — each is a place production wiring can be
   missing with green tests.
