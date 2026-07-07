# v1.7 widened audit campaign — results (AUD-1..AUD-7)

**Source:** execution of Part 1 of [`v17_widen_audit_architecture.md`](v17_widen_audit_architecture.md)
(read-only campaign). All line references are branch `v1.7/phase-5-sandbox-path` at commit
`cfaed3f1`. Part 2 (ARCH-1..4) is deliberately NOT decided here; decision-relevant inputs are
flagged inline with **→ ARCH-n**. New confirmed defects surfaced by an audit are appended to
[`v17_bugs.md`](v17_bugs.md) with fresh V17-NN ids and cross-referenced from the audit section.

Status: **all seven audits complete** (2026-07-04). Campaign summary at the end of the file.

---

## AUD-1 — Account-surface conformance census

**Scope covered:** `itrader/portfolio_handler/account/{base,simulated,venue}.py`; every
`account.<member>` access in `portfolio.py`, `portfolio_handler.py`, the four manager subdirs
(`cash/` is an absorbed tombstone — `cash/__init__.py:2`; `position/`, `transaction/`,
`metrics/` contain **zero** direct account references — `metrics_manager.py:498` reads
`portfolio.cash`, which routes through the ABC `balance`), plus reporting/e2e harness surfaces.

### 1a. Member × leaf availability matrix

ABC = declared abstract on `Account` (`account/base.py:34` — the ABC carries exactly four
members: `balance`, `available`, `reserve`, `release`).

| Member | ABC? | SimulatedCash | SimulatedMargin | VenueAccount | Notes |
|---|---|---|---|---|---|
| `balance` | ✓ (base.py:54) | ✓ (:134) | inherited | ✓ (venue.py:220 — StateError if unsnapshotted, loud) | |
| `available` | ✓ (base.py:67) | ✓ (:154, alias of `available_balance`) | inherited | ✓ (venue.py:237 — overlay-netted) | |
| `reserve(order_id, amount)` | ✓ (base.py:80) | ✓ (:413) | inherited | ✓ (venue.py:274 — local overlay) | |
| `release(order_id)` | ✓ (base.py:100) | ✓ (:464) | inherited | ✓ (venue.py:315) | |
| `available_balance` | ✗ | ✓ (:139) | inherited | **✗** | called unguarded (see 1b) |
| `reserved_balance` | ✗ | ✓ (:165) | inherited | **✗** | called unguarded (see 1b) |
| `assert_funds_invariant` | ✗ | ✓ (:390) | inherited | **✗** | V17-01 |
| `apply_fill_cash_flow` | ✗ | ✓ (:344) | inherited | **✗** | V17-01 |
| `get_cash_operations` | ✗ | ✓ (:504) | inherited | **✗** | e2e harness only |
| `deposit` / `withdraw` / `process_transaction_cash_flow` / `get_balance_info` / `validate_balance_consistency` | ✗ | ✓ | inherited | **✗** | **no production callers** (admin surface) |
| `set_universe` | ✗ | ✗ | ✓ (:623) | ✗ | isinstance-guarded |
| `maintenance_margin` / `margin_ratio` | ✗ | ✗ | ✓ (:804/:839) | ✗ | isinstance-guarded |
| `lock_margin` / `release_margin` / `assert_lock_fits_buying_power` / `locked_margin_total` / `get_locked_margin_for` / `accrue_borrow_interest` | ✗ | ✗ | ✓ | ✗ | reached via `cast()` — **no runtime guard** (see 1b) |
| `_liq_inputs` / `_isolated_liq_price` / `_is_breached` / `_liquidation_penalty` | ✗ | ✗ | ✓ (:904/:860/:884/:896) | ✗ | isinstance-guarded; cross-object private access (style) |
| `positions` | ✗ | ✗ | ✗ | ✓ (venue.py:255) | isinstance-guarded at both consumers |
| `snapshot` / `start_streaming` | ✗ | ✗ | ✗ | ✓ (venue.py:195/:181) | called on the held `self._venue_account` reference (`live_trading_system.py:719,1130-1131`), never polymorphically — no hazard |

### 1b. Call-site census (every `account.<member>` access, guard status, live-path verdict)

"Live-path verdict" = behavior after `_link_venue_account_to_portfolios()` swaps
`portfolio.account` to `VenueAccount` (`live_trading_system.py:565`).

| # | Call site | Member | Guard | Live-path verdict |
|---|---|---|---|---|
| 1 | `portfolio.py:104` | attribute **typed as the concretion** `SimulatedCashAccount` | — | Live re-assignment at `live_trading_system.py:565` violates the declared type; mypy blind (live module in `[[tool.mypy.overrides]]` ignore list). **→ ARCH-1 enforcement gap** |
| 2 | `portfolio.py:115,119` | `balance` | none needed | init-time validation, runs pre-link on Simulated leaf — safe |
| 3 | `portfolio.py:223` (`cash` prop) | `balance` | ABC ✓ | Venue: loud StateError pre-snapshot — OK |
| 4 | `portfolio.py:381` | `assert_funds_invariant` | **UNGUARDED** | AttributeError on every settle — **V17-01(a)** |
| 5 | `portfolio.py:397` | `apply_fill_cash_flow` | **UNGUARDED** | **V17-01(b)** (SELL partial-mutation arm) |
| 6 | `portfolio.py:438` → `:495,522-524,543-549,580` | full margin surface via `cast(SimulatedMarginAccount, ...)` | **cast only — zero runtime check** (config-gated: reached iff `enable_margin=True`) | Latent: venue-linked + `enable_margin=True` → cast silently passes, AttributeError **mid-settlement** (same partial-mutation hazard class as V17-01) — **V17-14** |
| 7 | `portfolio.py:626` | `balance` | ABC ✓ | OK |
| 8 | `portfolio.py:834` | `accrue_borrow_interest` via `cast()` | cast only (reached only for open SHORT w/ borrow rate) | same latent class as #6 — **V17-14** |
| 9 | `portfolio.py:888` (`to_dict`) | `available_balance` | **UNGUARDED** | AttributeError — **V17-14** (serialization path) |
| 10 | `portfolio.py:889` (`to_dict`) | `reserved_balance` | **UNGUARDED** | AttributeError — **V17-14**; member exists on NO other leaf |
| 11 | `portfolio_handler.py:300` (admission read-model) | `available_balance` | **UNGUARDED** | **V17-01(c)** — every SIGNAL admission dies |
| 12 | `portfolio_handler.py:324,332` | `reserve`/`release` | ABC ✓ | OK (venue overlay) |
| 13 | `portfolio_handler.py:357` (`total_equity`) | `balance` | ABC ✓ | Venue: loud pre-snapshot — OK |
| 14 | `portfolio_handler.py:380-381` | `set_universe` | `isinstance(SimulatedMarginAccount)` ✓ | silently skipped on venue — OK |
| 15 | `portfolio_handler.py:410-413, 422-425` | `maintenance_margin`/`margin_ratio` | isinstance ✓ (non-margin → `Decimal("0")`) | OK |
| 16 | `portfolio_handler.py:587-592, 626-647` | `_liq_inputs`/`_isolated_liq_price`/`_is_breached` | isinstance ✓ | OK (liq pass silently skipped on venue — acceptable: venue owns liquidation) |
| 17 | `portfolio_handler.py:732-736, 785-789` | `positions` | `isinstance(VenueAccount)` ✓ | OK conformance-wise (spot blindness is V17-04, a different defect) |
| 18 | `tests/e2e/conftest.py:372` | `get_cash_operations` | harness | any live report harness reusing this helper on a venue-linked portfolio breaks |

**Dead-producer note (feeds AUD-2):** the ONLY route to sites #9/#10 is
`Portfolio.to_dict()` ← `portfolios_to_dict()` (`portfolio_handler.py:1027`) ←
`generate_portfolios_update_event()` (`portfolio_handler.py:1034`) — which has **no production
caller anywhere in `itrader/`**. The serialization gap is therefore dormant until any
monitoring/API surface calls it; the producer itself is an orphan.

### 1c. Census verdict

- V17-01's three unguarded concretion calls are confirmed and are the **only** unguarded sites
  on the wired live run path today.
- **Two additional unguarded sites** exist on the serialization path (`to_dict`,
  sites #9/#10) plus the **cast-based margin narrowing** (sites #6/#8) that is latent until
  live-margin wiring — recorded as **V17-14** in `v17_bugs.md`.
- All margin-math consumers in the handler are correctly isinstance-guarded; all venue-only
  consumers are correctly guarded. The conformance failure is concentrated on the
  **cash-settlement + serialization concretion surface**, exactly the V17-01 class.

**→ ARCH-1 decision inputs (flagged, not decided):**
1. Final Option-A ABC-widening member list from this census:
   `assert_funds_invariant`, `apply_fill_cash_flow`, `reserved_balance` — and `available_balance`
   **only if** call sites are not re-pointed. Note: the ABC already has `available`, and
   `SimulatedCashAccount.available` is a pure alias of `available_balance`
   (`simulated.py:154-162`), and `VenueAccount.available` already implements the admission
   semantics (overlay-netted). Sites #9/#11 could switch to `.available` today with zero math
   change — shrinking the true ABC gap to three members
   (`assert_funds_invariant`, `apply_fill_cash_flow`, `reserved_balance`).
2. `Portfolio.account` is annotated as the concretion (`portfolio.py:104`) — either option
   requires re-typing to the ABC + mypy visibility (the live wiring module is currently
   strict-exempt), or the drift recurs.
3. The `cast()` margin sites are invisible to any runtime guard — if Option A keeps the
   concrete margin surface, a venue-margin wiring needs its own conformance story.

### 1d. Pinned conformance test (SPEC ONLY — not committed)

- **File:** `tests/unit/portfolio/test_account_conformance.py` (new; `unit` marker auto-applied
  by folder; no new marker registration needed).
- **Parametrization:** `@pytest.mark.parametrize("account_factory", [cash, margin, venue])`
  where `cash`/`margin` build `SimulatedCashAccount`/`SimulatedMarginAccount` with a lightweight
  portfolio stub + `initial_cash=Decimal("1000")`, and `venue` builds
  `VenueAccount(FakeVenueConnector(...), quote_currency="USDC")` pre-populated via a stubbed
  `snapshot()` (balance 1000 / available 1000 / no positions — reuse
  `tests/support/fake_venue_connector.py`, no network).
- **What it drives (one test per behavior, all three leaves):**
  1. *Admission read:* every member the admission/read-model path calls
     (`available` — plus `available_balance` until call sites are re-pointed) returns a
     `Decimal` — asserts presence AND type, so the leaf set can never silently diverge from the
     caller surface again.
  2. *Reserve → release round-trip:* `reserve(oid, Decimal("100"))` reduces the admission read
     by exactly 100; `release(oid)` restores it; releasing twice is a silent no-op.
  3. *BUY settle:* `assert_funds_invariant(Decimal("100"))` passes, then
     `apply_fill_cash_flow(amount=Decimal("-100"), fee=Decimal("0.1"), ...)` moves `balance`
     by exactly −100.
  4. *SELL settle:* `apply_fill_cash_flow(amount=Decimal("+99.9"), ...)` moves `balance`
     by exactly +99.9.
  5. *Serialization surface:* `reserved_balance` returns a `Decimal` (pins site #10).
- **Expected today:** RED for `VenueAccount` on 1 (partially), 3, 4, 5 — this failure is the
  CONF-A A1 companion. Post-ARCH-1 it flips GREEN and stays as the permanent gate the audit
  doc requires.
- **Assertion style note:** for the two Simulated leaves the balance-delta assertions must be
  exact `Decimal` equality (byte-exact oracle discipline); `VenueAccount` settle semantics
  follow whichever ARCH-1 option lands (locally-ledgered → same exact assertions).

---

## AUD-2 — Storage producer/consumer census

**Scope covered:** all four Alembic migrations, `order_handler/storage/`,
`portfolio_handler/storage/` (incl. the cached SQL wrapper + factory), `strategy_handler/storage/`,
and every composition-root construction site. (Produced by one read-only census subagent;
seed orphans from V17-02/V17-05 verified.)

### 2a. Migration inventory

| Revision file | Milestone/phase | Tables/columns added |
|---|---|---|
| `2cbf0bf6b0b6_operational_baseline.py` (root) | v1.6 operational baseline (OPS-01) | 9 tables: `cash_operations`, `cash_reservations`, `equity_snapshots`, `locked_margin`, `orders` (all columns), `positions`, `signals`, `transactions`, `order_state_changes` |
| `47f2b41f3ffe_portfolio_account_state.py` | v1.6 Phase-4 (A2) | `portfolio_account_state`: `portfolio_id` PK, `cash_balance`, `realized_pnl`, `total_equity`, `peak_equity`, `open_positions_count`, `updated_time` |
| `p05_venue_order_id.py` | v1.7 Phase-5 (05-07, RECON-05/OQ3) | `orders.venue_order_id` (nullable) |
| `hl5_transaction_venue_trade_id.py` (head) | v1.7 Phase-5 hotfix (CR-01) | `transactions.venue_trade_id` (nullable) |

### 2b. Producer/consumer census

Store→table ownership: **orders/order_state_changes** ← order SQL store (wired live);
**signals** ← strategy SQL store (wired live); **positions/transactions/cash_reservations/
locked_margin/cash_operations/equity_snapshots/portfolio_account_state** ← portfolio SQL store,
which is **never constructed on any run path**.

| Table.column | WriterProd | Wired path(s) | ReaderProd | Verdict |
|---|---|---|---|---|
| `orders.venue_order_id` (seed, V17-02) | column persisted `order_handler/storage/sql_storage.py:142`; the ONLY attribute writer is `venue_reconciler.py:405` (restart relink) | live, restart-time only (`live_trading_system.py:1147`); store wired at `live_trading_system.py:274` | `sql_storage.py:206` rehydrate; `venue_reconciler.py:421-422`; `okx.py:349` | **Dormant-on-happy-path** — NULL in steady state; no submit-time writer (confirms V17-02). → ARCH-3 |
| `transactions.venue_trade_id` (seed, V17-05) | durable writer `portfolio_handler/storage/sql_storage.py:217` — on the never-constructed store; domain field populated in prod (`transaction/transaction.py:160`) | **NOT wired** — prod `record()` hits the in-memory backend | durable reader `sql_storage.py:243` (unwired); live dedup reads the FillEvent field only (`portfolio_handler.py:838`) | **ORPHAN-producer-unwired / TEST-ONLY** (confirms V17-05). → ARCH-3 |
| `portfolio_account_state` (whole table incl. `peak_equity`) | `cached_sql_storage.py:215 save_account_state` — **ZERO callers** in itrader/ + scripts/ | NOT wired (only `PortfolioStateStorageFactory.create('live')` builds the host class, `storage_factory.py:97` — no site passes `'live'`) | `cached_sql_storage.py:252` (self-referential, unwired) | **ORPHAN-no-producer** (strongest orphan) |
| `positions.*`, `transactions.*` (core), `cash_reservations.*`, `locked_margin.*`, `cash_operations.*`, `equity_snapshots.*` | writers exist throughout `portfolio_handler/storage/sql_storage.py` | **NOT wired** on backtest/paper/live | unwired readers in the same store | **ORPHAN-producer-unwired** (entire portfolio persistence layer) |
| `orders.*` baseline + `order_state_changes.*` | `order_handler/storage/sql_storage.py:130-145+` | **WIRED live** (`live_trading_system.py:274`, Postgres creds present; in-memory fallback else) | rehydrate path | **OK** |
| `signals.*` | `strategy_handler/storage/sql_storage.py` | **WIRED live** (`SignalStorageFactory.create('live')`, `live_trading_system.py:285`) | signal store reads | **OK** |

### 2c. Storage wiring map

| Factory | Envs supported | Env actually passed | Result backtest / live |
|---|---|---|---|
| `OrderStorageFactory` | backtest/test → InMemory; live → CachedSql | backtest root `'backtest'` (`backtest_trading_system.py:126,414`); live root `'backtest'` fallback (`live_trading_system.py:244`) or explicit CachedSql bypassing the factory (`:274`) | InMemory / CachedSqlOrderStorage |
| `PortfolioStateStorageFactory` | backtest/test → InMemory; live → CachedSql | **`'backtest'` at EVERY site**: `portfolio.py:96`, `metrics_manager.py:112`, `transaction_manager.py:47`, `position_manager.py:65`, `simulated.py:111` — `'live'` never passed | InMemory / **InMemory too** |
| `SignalStorageFactory` | backtest/test → InMemory; live → CachedSql | backtest `'backtest'`; live `'live'` (`live_trading_system.py:285`) | InMemory / CachedSqlSignalStorage |

**Direct answer to the scoped question:** the cached SQL PORTFOLIO storage
(`cached_sql_storage.py`) is **not constructed anywhere in production code** — reachable only
from tests (the factory's own docstring admits it, `storage_factory.py:95`).

### 2d. Orphan summary (each = fix item or explicit dormant annotation)

- `transactions.venue_trade_id` — producer-unwired; live dedup is the volatile in-memory set.
  Wire `create('live')` at the portfolio composition root or annotate the column+migration
  "dormant until portfolio durability lands." **→ ARCH-3** (this IS the durable ledger the
  posture decision hinges on — it does not persist in prod today).
- `portfolio_account_state` — no producer at all (`save_account_state` uncalled). Wire it on
  the settlement path + live factory, or drop/annotate as forward-declaration. **→ ARCH-3**
- Whole portfolio SQL layer (6 baseline tables) — producer-unwired; live portfolio state is
  entirely in-memory/venue-derived. Posture (i) of ARCH-3 = "flip the five `'backtest'`
  hard-codes to environment-aware + call the writers"; posture (ii) = "delete/annotate the
  layer." **→ ARCH-3 (the census is exactly the evidence ARCH-3 said to wait for)**
- `orders.venue_order_id` — wired store but no submit-time attribute writer (V17-02's fix
  Wave 2 adds the ORDER-ACK path; until then annotate "restart-relink-only").
- (From AUD-1) `generate_portfolios_update_event` (`portfolio_handler.py:1034`) — an
  event producer with no caller; its serialization path is also the V17-14 hazard route.

---

## AUD-3 — Silent-swallow census (live path)

**Scope covered:** every `except` reachable from the live FILL/ORDER/SIGNAL/BAR routes:
`execution_handler.py`, `exchanges/okx.py`, `full_event_handler.py`,
`live_trading_system.py` (`_publish_and_continue`, `_event_processing_loop`, lifecycle),
`portfolio_handler.py` (`_operation_context`, `on_fill`, market-value loop),
`order_handler/reconcile/reconcile_manager.py`.

Classification: **MONEY** = swallowed failure can leave money state wrong/partial
(settlement, reservation, mirror) or silently lose a settlement; **SILENT-DEGRADE** =
no state corruption but the system silently stops doing its job; **COSMETIC** = logging,
lifecycle, admin. "Deliberate?" cites the documented policy where one exists.

### 3a. Swallow inventory

| # | Site | What it catches | Class | Verdict / consequence |
|---|---|---|---|---|
| S1 | `live_trading_system.py:490` `_publish_and_continue` | ANY handler exception on ANY route (the live policy seam) | **MONEY** (master swallow) | The single chokepoint every money-route failure passes through. Deliberate (documented run-mode policy) but **unbounded**: it counts `errors_count`, emits one ErrorEvent, and continues forever — V17-01's every-fill-fails scenario produces an infinite green-looking run. This is the circuit-breaker attach point (3b). |
| S2 | `portfolio_handler.py:907-910` `on_fill` | any settle failure → `_publish_error_event` + **re-raise** into S1 | **MONEY** | `transact_shares` can raise **mid-mutation** (V17-01 SELL arm: position moved, cash not, transaction unrecorded); settled-set (`:889-892` mark-after-apply) not written → a redelivery re-mutates. Handler itself is fail-loud; S1 converts it to silent-continue. |
| S3 | `reconcile_manager.py:417-429` order-side `on_fill` | any reconcile failure → log + **re-raise** into S1 | **MONEY** | Mirror can be left part-reconciled; the `finally` (`:430-435` → `_release_reservation`) still releases a terminal fill's reservation — good — but mirror/filled_quantity divergence survives the continue. |
| S4 | `reconcile_manager.py:458-470` `_release_reservation` inner except | release failure when body ALSO raised → log-only | **MONEY** (double-failure edge) | Stuck reservation possible only when body and release both fail; correctly re-raises when body succeeded. Acceptable, but the stuck-reservation case reaches S1 with no distinct signal. |
| S5 | `execution_handler.py:111` `on_order` boundary | any exchange failure routing an ORDER | **MONEY** | Catches BEFORE the dispatch seam, so even backtest fail-fast never sees it (documented broad-except policy). Live consequence: if `OkxExchange.on_order`'s own recovery (S7) itself raises — e.g. queue put, event construction — the mirror stays **PENDING forever with the reservation held**. No REFUSED, no ErrorEvent. |
| S6 | `execution_handler.py:127` `on_market_data` boundary | per-exchange matching failure | SILENT-DEGRADE (backtest MONEY) | Live OKX arm is a no-op (`okx.py:363-369`), so benign live. On the simulated/paper arm a matching failure silently skips a bar of resting-order triggers — but paper reuses fail-fast policy upstream? No: this catch is INSIDE the handler, so it swallows in every mode. Out-of-scope path (backtest oracle-locked) — noted, not filed. |
| S7 | `okx.py:210-252` `on_order` boundary swallow | submit/cancel transport failure | **MONEY (by design, misclassifies)** | Submit arm → `FillEvent(REFUSED)` — correct for reached-and-rejected, WRONG for timeout (V17-09: coroutine may still succeed at venue). Cancel arm → ErrorEvent + mirror left resting — deliberate and auditable (good). |
| S8 | `okx.py:645-652` per-trade swallow in `_consume_fills` | any `_handle_trade` failure | **MONEY** | A malformed/failing fill translation is skipped **permanently — that settlement is lost** (log-only; no ErrorEvent, no reconcile trigger, invisible to the ERROR route AND to any future breaker). Family of 05-13 WR-02. Input to 3b: must emit a counted ErrorEvent. |
| S9 | `live_trading_system.py:1052-1057` `_event_processing_loop` catch-all `continue` | anything escaping `_dispatch_live` / stats / resume | **MONEY** (backstop) | By construction the failure point is unknown → could be post-partial-mutation. Counts `errors_count`, no ErrorEvent (failure may predate dispatch), loops forever. Should share the 3b breaker counter. |
| S10 | `full_event_handler.py:205-222` `_log_error_event` terminal swallow | ERROR-route consumer failure | COSMETIC | Deliberate WR-06 terminal-safety (recursion guard). Correct. |
| S11 | `live_trading_system.py:715-726` `_maybe_resume_after_reconnect` | resume snapshot failure → stay paused + retry | COSMETIC | Fail-safe done right (keeps pause, retries). |
| S12 | `live_trading_system.py:780-782` status-callback except; `:1232,:1242` shutdown disconnect/dispose; `:1344` `add_event` returns False; `execution_handler.py:179,234` back-compat `AttributeError` | lifecycle/egress | COSMETIC | No money state involved. |
| S13 | `live_trading_system.py:891-894` `_initialize_live_session` | init failure → log, status=ERROR, **re-raise** | COSMETIC | Fail-loud, correct. |
| S14 | `portfolio_handler.py:230,270` add/delete portfolio | publish + **re-raise** | COSMETIC | Admin ops; live seam swallows the re-raise but state is transactional-enough (dict insert/delete). |
| S15 | `portfolio_handler.py:704` `(KeyError, AttributeError)` → default precision 8 | unknown instrument in drift-epsilon resolution | SILENT-DEGRADE | Wrong tolerance for exotic instruments silently; acceptable today (single symbol), keep on the radar with V17-12's multi-symbol arming. |
| S16 | `portfolio_handler.py:962-…` market-value mark loop | mark failure → publish + **re-raise** (WR-08) | **MONEY-adjacent** | Correctly fail-loud per portfolio; live S1 swallow leaves the tick partially marked only at handler granularity (documented in the WR-05 comment `:938-951`). Consequence live: stale valuations feed metrics/drift until next bar. Counted by 3b via S1. |
| S17 | `portfolio_handler.py:1087,1098` config validate/rollback | validation errors → bool | COSMETIC | Interface-visible returns. |

**Census verdict:** the money-mutating set is `{S1, S2, S3, S5, S7-submit, S8, S9}` (+S4 edge).
Every one except **S5** and **S8** at least produces an ErrorEvent today; S8 is the worst
citizen — a *lost settlement* that never even reaches the ERROR route. All of them terminate in
"log/publish and keep running" with **no aggregate view** — which is exactly how V17-01 ran an
entire e2e suite green with zero settlements.

### 3b. ERROR-route circuit-breaker spec (draft — input list from 3a)

**Attach point:** `LiveTradingSystem._publish_and_continue` (S1) — the single seam every
handler failure already crosses — plus a shared counter surface for S8/S9 which bypass S1.

**Route classification at the seam** (from the failing event's `type` + handler qualname):

| Class | Failing route | Policy |
|---|---|---|
| SETTLEMENT | `EventType.FILL` → `PortfolioHandler.on_fill` or `OrderHandler.on_fill`/ReconcileManager | **Halt on FIRST failure** (`halt("fill-settlement-failure")`). A consumed FILL is gone — the failure is never transient, and state is already suspect (S2 partial-mutation). No window needed. |
| ORDER-IO | `EventType.ORDER` → execution/exchange handlers; also S7-submit recovery failures | N=3 failures in rolling W=60s → `halt("order-route-errors")`. Transient transport errors are plausible; repeated ones mean the mirror is diverging. |
| ADMISSION | `EventType.SIGNAL` → order admission | N=3 in W=300s → halt (or CRITICAL alert first). V17-01 arm 1 showed admission can die silently on every signal — this is the dead-man switch for "engine stopped trading and nobody noticed". |
| FILL-TRANSLATION | S8 (`okx.py:651`) | **Prerequisite fix:** emit a counted `ErrorEvent(source="okx_exchange", operation="fill-translation")` instead of log-only, then treat as SETTLEMENT class (halt on first — a lost fill is a lost settlement). |
| LOOP-BACKSTOP | S9 | Increment the same aggregate counter; N=5 in W=60s → halt (unknown failure locus). |
| COSMETIC | ERROR-route consumer, callbacks, lifecycle | Never counted (WR-06 terminal safety preserved). |

**Mechanics:** a small ring of `(monotonic_ts, route_class)` on `LiveTradingSystem`, guarded by
the existing `_stats_lock`; evaluated inside `_publish_and_continue` after the
`errors_count` increment; halt via the existing idempotent `halt(reason)` (freeze-in-place
gate `_dispatch_live` `live_trading_system.py:728-743` then suppresses SIGNAL/ORDER while
draining continues). Counters and last-trip reason surfaced in `get_status()`.

**Hard dependency (→ ARCH-4):** the breaker is inert until V17-03 is fixed — today
`_event_processing_loop`'s unconditional `_update_status(RUNNING)` (`:993`) and the missing
HALTED latch would clobber the breaker's halt exactly as it clobbers the reconciler's.
Land ARCH-4's transition table first (or together).

**Deliberate-swallow constraints to preserve:** WR-06 terminal ERROR-route swallow (S10);
S7's cancel-arm leave-resting semantics; S11's stay-paused-and-retry. The breaker adds an
aggregate tripwire ON TOP of the documented publish-and-continue policy — it does not change
per-event behavior (backtest fail-fast untouched; `.planning/codebase/CONVENTIONS.md`
broad-except policy note stays valid).

---

## AUD-4 — Connector primitive semantics

**Scope covered:** `connectors/okx.py` (`call` :162, `spawn` :168, `disconnect` :195),
`connectors/base.py` (`LiveConnector` Protocol), and every production consumer.

### 4a. Primitive semantics (as implemented)

- **`call(coro)`** (`connectors/okx.py:162-166`): `run_coroutine_threadsafe(...).result(timeout=30)`.
  On timeout the `concurrent.futures` future is abandoned but the **coroutine keeps running on
  the loop** — the operation may still complete at the venue. Under Python 3.13 the raised
  exception is the **builtin `TimeoutError`** (`concurrent.futures.TimeoutError` is an alias
  since 3.11). Calling it **from the connector loop thread self-deadlocks**: the blocking
  `.result()` prevents the loop from ever running the scheduled coroutine → guaranteed 30 s
  stall of the ENTIRE loop, then `TimeoutError`.
- **`spawn(coro)`** (`:168-193`): done-callback is only `self._stream_tasks.discard` (`:182`) —
  **task exceptions are never observed** (V17-07). Raises `TimeoutError` if the loop fails to
  schedule within 30 s (WR-04 guard `:190-192`).
- **`disconnect()`** (`:195-244`): cancel-gather → `client.close()` → loop stop → join, each
  bounded by 30 s; broad `except` logs. WR-06 `finally`: on unclean stop **references are
  retained** for retry — the daemon loop/thread may keep running (streams may keep emitting
  into `global_queue` after the engine loop stopped). Both `call` and `spawn` `assert
  self._loop is not None` — after a clean disconnect they die with a bare `AssertionError`
  (stripped under `python -O`), not a typed StateError.

### 4b. Consumer table

| Consumer (file:line) | Primitive | Trap (a) timeout≠didn't-happen | Trap (b) unobserved task death | Trap (c) unclean stop | Verdict |
|---|---|---|---|---|---|
| `okx.py:310` `_submit_order` create_order | call | **TRAP CONFIRMED** — timeout → boundary swallow → `FillEvent(REFUSED)` → mirror REJECTED + reservation released while the coroutine may still fill (V17-09) | — | — | Fix = V17-09 (in-flight/unknown + reconcile) |
| `okx.py:332` `_cancel_order` | call | Partial — timeout → mirror left resting + ErrorEvent (deliberately conservative, correct default). But the in-flight cancel may STILL succeed later; the mid-session `watch_orders` arm that would reconcile it only logs (`okx.py:662-671`, V17-08) → mirror can stay resting forever | — | — | Depends on V17-08 fix |
| `venue.py:206-207` `snapshot()` | call | Safe — read-only; abandoned coroutine's result is discarded, no stale cache write (write happens after `call` returns, on the calling thread). Startup failure → `start()` fail-loud; resume failure → stay-paused+retry (S11) | — | — | OK |
| `venue_reconciler.py:452` | call | Safe — startup read; failure aborts start() loudly | — | — | OK |
| `okx_provider.py:484,490` `fetch_ohlcv_backfill` — **warmup path** (engine thread, pre-stream: `live_trading_system.py:1100-1101`) | call | Safe thread-wise (engine thread; streams not yet started) | — | — | OK |
| `okx_provider.py:484,490` — **gap path**: `LiveBarFeed.update()` gap branch → `_backfill_gap` (`live_bar_feed.py:298`), and `update()` runs ON the connector loop thread (provider bar-sink, `live_trading_system.py:411`; thread model pinned in `live_bar_feed.py:20-22`) | call | **NEW DEFECT — self-deadlock**: `call()` from the loop thread can never complete → every live bar-gap = 30 s stall of ALL streams (fills/balance/orders) + guaranteed `TimeoutError`; gap never fills; supervisor catches it as transient (`asyncio.TimeoutError` ≡ builtin in 3.13, `okx_provider.py:324-326`) → reconnect → OKX snapshot-on-subscribe re-delivers the gap bar → same stall again → **livelock: BAR delivery stops permanently** | — | — | **V17-15 (appended to v17_bugs.md)** |
| `okx.py:685-686` `_stream_fills`/`_stream_orders` | spawn | — | Supervised for 2 families only; anything else kills the task and spawn never reports (V17-07) | disconnect cancels via handles | V17-07 |
| `venue.py:189-190` `_stream_account`/`_stream_positions` | spawn | — | **NO supervisor at all** — first exception silently kills venue cache updates (V17-07) | cancelled on disconnect | V17-07 |
| `okx_provider.py:217` candle stream | spawn | — | Supervised, same two-family taxonomy holes (V17-07) | cancelled on disconnect | V17-07 |
| `live_trading_system.py:1231` `stop()` | disconnect | — | — | Broad-except + WR-06 retained refs: on unclean stop the daemon loop keeps streaming; OkxExchange may keep `put`ting FillEvents into a queue nobody drains (unbounded growth until process exit) | Acceptable (daemon teardown), document |

### 4c. Required semantics — ready-to-paste `LiveConnector` Protocol docstring spec (NO code edited)

For `connectors/base.py::LiveConnector.call`:

```
CONTRACT — timeout semantics (V17-09/V17-15 lessons):
1. A timeout does NOT cancel the in-flight coroutine. For a MUTATING venue op
   (create_order/cancel_order) a TimeoutError means UNKNOWN OUTCOME — the caller
   MUST treat the operation as in-flight and resolve via query/reconcile, never
   as "did not happen" (no REFUSED, no terminal mirror transition).
2. NEVER invoke call() from the connector loop thread (any code reachable from a
   spawned coroutine, incl. stream sinks). The blocking .result() prevents the
   loop from running the scheduled coroutine: guaranteed full-loop stall for the
   timeout window, then TimeoutError. Loop-thread code must await the client
   coroutine directly instead.
3. call() after disconnect() dies on an assert (not a typed error) — callers
   holding a connector across a reconnect cycle must re-check lifecycle first.
```

For `LiveConnector.spawn`:

```
CONTRACT — supervision (V17-07 lesson): spawn() only tracks the handle for
cancel-on-disconnect; it NEVER observes task exceptions. Every spawned coroutine
MUST either (a) run under a supervisor that classifies ALL exceptions
(unknown ⇒ escalate/halt, never silent death), or (b) attach its own
done-callback that logs task.exception() and escalates. A bare `while True:
await client.watch_*()` coroutine is a latent silent-death defect.
```

For `LiveConnector.disconnect`:

```
CONTRACT — unclean stop: disconnect() is best-effort and bounded; on join
timeout the loop/thread/client references are RETAINED and the daemon loop may
still be running (streams may still emit into sinks/queues). Callers must treat
"disconnect returned" as NOT equivalent to "streams stopped" — check
thread_alive/loop_running (logged) and retry, and must not assume queue
producers have ceased.
```

---

## AUD-5 — LiveBarFeed bar-timing-contract parity

**Scope covered:** `price_handler/feed/live_bar_feed.py` vs the seven rules in
`price_handler/feed/bar_feed.py:10-38` (the contract's single written home), plus the
monotonic guard, gap re-entrancy, and the `backfill_on_resume` wire-or-delete call.

### 5a. Rule-by-rule parity checklist

| Rule (bar_feed.py) | LiveBarFeed behavior | Verdict |
|---|---|---|
| 1 — bars stamped by open time | `t = pd.Timestamp(cb["ts"], ms, UTC)` (`live_bar_feed.py:163`); provider stamps `ts` from the venue candle row open-time, confirm-gated, never wall clock (`okx_provider.py:440-452`) | **PASS** |
| 2 — tick at `T` = bar `T` just closed | delivery is push-on-confirmed-close; `BarEvent.time = bar.time = T` (`:353`) — the arrival IS the tick | **PASS** |
| 3 — same-TF visibility: bars `<= T` | `window()` cutoff degenerates to `asof` when `timeframe == base`; `searchsorted(side="right")` → stamped `<= asof` only; ring holds only delivered closed bars (`:401-416`) | **PASS** |
| 4 — resampled visibility: `B <= T − TF + tf_base` | identical cutoff formula + `label='left', closed='left'` + shared `_AGG`/`_offset_alias` imports (`:46`, `:405-414`) — forming bucket excluded | **PASS** (see caveat C1) |
| 5 — fills at next open | N/A to the feed — live matching is venue-owned (`okx.py:363-369` no-op) | **N/A** |
| 6 — equity at `T` = close of bar `T` | same BAR route/handler as backtest (`update_portfolios_market_value` consumes the emitted BarEvent) | **PASS** |
| 7 — last-bar edge | N/A — no final tick on live | **N/A** |

**Monotonic guard (D-06/D-07, no backtest analog):** the taxonomy at `:139-183` is complete —
first-bar / in-sequence / stale-reject / duplicate-drop / revision-WARN-drop / gap-backfill /
off-grid-reject (WR-01). No rewind path exists; revisions never mutate state. Sound *as
written* — but the gap branch's transport is broken (V17-15), so in practice a live gap today
means BAR delivery stops entirely rather than a look-ahead violation. Look-ahead safety is
preserved even in the failure mode (fail-stalled, not fail-leaky).

### 5b. Caveats (parity-adjacent, not rule violations)

- **C1 — ring-edge partial buckets:** the backtest resamples full store history; live
  resamples a bounded ring (`deque(maxlen=cache_capacity())`, `:327`). The OLDEST bucket in a
  coarse-TF resample can silently aggregate fewer base bars than it covers (left-edge
  eviction), and `cache_capacity()` derives from registered warmup counts that are expressed
  in *strategy-timeframe* bars (`live_trading_system.py:856-861`) with no `TF/tf_base`
  conversion — a coarse-TF live strategy would get both a too-shallow ring AND a partial
  left-edge bucket. Dormant today (SMA_MACD live wiring is same-TF); arm condition = first
  coarse-TF live strategy. Recommend a loud assert in `window()` when
  `max_window * (TF/tf_base) > ring length` rather than silent shallow frames.
- **C2 — `float()` casts in `_base_frame` (`:428-432`)** are analytics-frame casts (indicator
  input), matching the backtest float-frame convention — NOT money-policy violations. Verified
  intentional (D-17 comment).

### 5c. Re-entrancy answer (the audit's explicit question)

**No interleave is possible today.** All three ring writers are sequenced: `warmup()` runs on
the engine thread strictly BEFORE `start_stream()` (`live_trading_system.py:1100-1101`);
mid-session `update()` — including its synchronous in-thread gap replay — runs only on the
connector loop thread (`live_bar_feed.py:20-22`); `backfill_on_resume` is never called. The
single-writer discipline holds by sequencing, not by locks — which means it BREAKS the moment
`backfill_on_resume` is wired onto the engine-thread resume path (second concurrent writer on
`_ring`/`_last_delivered` racing the socket thread).

### 5d. `backfill_on_resume` — wire-or-delete recommendation

**Keep-unwired-and-annotate now; wire loop-natively with the V17-15 fix.** Wiring it as-is is
doubly unsafe: (a) engine-thread call → concurrent-writer race (5c); (b) it funnels into the
same `_backfill_gap` → blocking `call()` transport that V17-15 condemns. The correct landing:
after the V17-15 loop-native backfill redesign, run resume recovery ON the connector loop
(spawned coroutine) where single-writer discipline holds, and call it from the reconnect
callback rather than the engine resume. Until then the cost of NOT wiring it is bounded and
documented: up to one bar-period stall after a reconnect (existing LOW-batch item in
v17_bugs.md). Deleting it outright would discard the only boundary-gated recovery logic
already written and tested — annotation ("dormant until V17-15 fix") is the cheaper reversible
call.

**No new bug entry:** the gap-path defect surfaced here is V17-15 (filed under AUD-4); the
seven-rule contract itself has no violated rule.

---

## AUD-6 — Live order-entry validation strength (D-03a re-examination)

**Scope covered:** the live external order-entry path vs the admission path
(`EnhancedOrderValidator` + sizing + reservation), and the D-03a dual-validator decision.

### 6a. Threshold finding: the premise of the audit item has shifted

1. **`trading_system/trading_interface.py` no longer exists** — deleted in v1.7 Phase 1
   (commit `26b914e3`, "account abstraction"); only a stale `.pyc` remains. CLAUDE.md and
   D-03a still describe it as the live entry bridge. The only remaining external entry
   surface is `LiveTradingSystem.add_event(event)` (`live_trading_system.py:1323`), which
   enqueues ANY event with a single `self._running` check.
2. **`OkxExchange.validate_order` (`okx.py:734-741`, quantity>0) and `validate_symbol`
   (`:743-758`) are NEVER called on the submit path.** `on_order → _submit_order`
   (`okx.py:254-311`) goes straight to `connector.call(create_order)`. Only
   `SimulatedExchange` invokes its own preflight (`simulated.py:202`, `:473`). The
   exchange-side check D-03a leans on for the live path is dead code on the live venue.

### 6b. Validation-gap table (admission path vs live entry path)

Admission path = SIGNAL → `OrderHandler.on_signal` → `AdmissionManager`
(`admission_manager.py:234` `validate_order_pipeline`) + sizing + reservation.
Live entry path = `add_event(OrderEvent)` → ORDER route (`full_event_handler.py:99`,
execution handler only) → `OkxExchange.on_order`.

| Check | Admission path | Live entry path (`add_event` → OKX) |
|---|---|---|
| Critical fields (ids, ticker, action, type) | ✓ `order_validator.py:187` | **✗ none** |
| Exchange support / symbol membership | ✓ `:308` (+ universe membership at signal admission) | **✗** (`validate_symbol` exists, uncalled — venue rejects at submit, cost: one round-trip + REFUSED) |
| Market conditions / hours | ✓ `:287`, `:328` | **✗** |
| Price sanity ranges | ✓ `:353` | **✗** |
| Quantity ranges (incl. >0) | ✓ `:380` | **✗** (`validate_order` qty>0 exists, uncalled; OKX lot rounding `_submit_order` may silently round to 0) |
| Portfolio constraints (position limits) | ✓ `:407` | **✗** |
| Financial risk / funds | ✓ `:466` + cash **reservation** via read-model | **✗ — no funds check, no reservation** |
| Direction policy / leverage clamp | ✓ (admission sizing, LEV-03) | **✗** |
| Order mirror created (fill reconciliation possible) | ✓ (stored order + bracket declaration) | **✗ — mirror-less order**: `_submit_order` registers the clOrdId in the correlation index, so the fill correlates to an order id the `OrderStorage` has never seen → `ReconcileManager.on_fill` lookup fails → fill unreconcilable; no reservation to release |
| Halt/pause gate | ✓ (SIGNAL+ORDER suppressed, `live_trading_system.py:736-743`) | ✓ (same gate — the ONLY check this path has) |

### 6c. Verdict + decision input

The live entry path validates **nothing** — it is not "weaker validation," it is an
unvalidated raw-queue injection surface that produces mirror-less, reservation-less venue
orders. Filed as **V17-16** (v17_bugs.md). Minimum bar for any live external entry:
route external order creation through the admission pipeline (construct a SignalEvent or
call the AdmissionManager directly) so validation+sizing+reservation+mirror all engage —
NOT a parallel validation stack (that is exactly the dual-layer drift D-03a exists to
manage). Additionally, `OkxExchange.on_order` should invoke its own
`validate_order`/`validate_symbol` preflight (defense-in-depth actually wired, mirroring
`simulated.py:202/473`).

### 6d. Proposed D-03a note update (SPEC ONLY — CONVENTIONS.md not edited, per session scope)

Replace the current D-03a paragraph with:

> (4) the **dual-layer order-validator overlap** (`order_validator.py` /
> `simulated.py`) remains justified-by-decision (D-03a, defense-in-depth), but its
> original live-path rationale is stale: `TradingInterface` was deleted in v1.7 Phase 1
> (`26b914e3`), and the live bypass surface is now `LiveTradingSystem.add_event` —
> which (V17-16) currently bypasses BOTH layers, because `OkxExchange` never invokes
> its `validate_order`/`validate_symbol` preflight. The exchange-side layer is only
> real where it is called (`SimulatedExchange`). D-03a therefore stands ONLY on
> condition that (a) every live entry path routes through the admission pipeline, and
> (b) `OkxExchange.on_order` wires its preflight the way `SimulatedExchange` does.
> Until V17-16 is fixed, the "second layer" on the live venue is aspirational.

---

## AUD-7 — Test-double fidelity audit

**Scope covered:** `tests/support/fake_venue_connector.py`,
`tests/support/fixtures/okx_recon_payloads.json`, `test_venue_account_*` payload shapes,
restart-test fixtures.

### 7a. Fidelity gap list — every behavior where the fake is FRIENDLIER than OKX

| # | Fake behavior | Real OKX behavior | What it masks |
|---|---|---|---|
| F1 | `fetch_my_trades` returns the complete canned list on every call, ignoring symbol/`since`/`limit` (`fake_venue_connector.py:99-100`) | `/trade/fills` is a recent-days window, row-capped, paginated | **V17-10** (reconciler completeness assumption) |
| F2 | Every trade/order carries `id`, `clientOrderId`, `order` (fixture throughout) | fills for API-external/manual orders lack the engine's clOrdId; fields can be absent/None | uncorrelated-fill buffer growth (05-13 family), `_relink_bracket` KeyError (LOW), WR-01/WR-02 |
| F3 | `watch_positions`/`fetch_positions` return derivative-shaped entries (`contracts`, `side`, `entryPrice`) for a SPOT symbol; `test_venue_account_drift.py:47` seeds `_venue_positions` directly, bypassing `_extract_positions` entirely | OKX spot returns `[]` from the positions channel | **V17-04** (spot blindness — the e2e tolerance loop iterates an empty map in production, a populated one in tests) |
| F4 | Fixture symbol is `BTC/USDT` and all balance keys are USDT | wired pair is `BTC/USDC` (`live_trading_system.py:51`) while `VenueAccount` is constructed with the USDT default (`:400`, `venue.py:73`) | the wrong-quote wiring bug is INVISIBLE: the fake agrees with the wrong default, so balance parsing tests go green while production tracks the wrong settlement currency (V17-04 related; old IN-04) |
| F5 | `create_order`/`cancel_order` are instant always-successful AsyncMocks (`:103-104`) | latency, timeouts, ambiguous outcomes (submit may succeed after the client gave up) | **V17-09** (timeout≠rejection), **V17-15** (nothing exercises a blocking bridge on a busy loop) |
| F6 | `_CannedStream` yields batches then parks forever (`:70-76`) — never raises | streams die on `ExchangeError`/`BadRequest`/garbage JSON; transient NetworkErrors mid-batch | **V17-07** (supervisor taxonomy holes; unsupervised `_stream_account`/`_stream_positions` death); `test_reconnect_resilience.py` feeds only the two handled families |
| F7 | No re-delivery: each batch exactly once, no snapshot-on-resubscribe | OKX WS pushes snapshot/re-sends on every resubscribe (see memory WR-03); private streams can re-deliver | **V17-06** / WR-03 (dedup-on-redelivery paths untested against realistic replay) |
| F8 | Balance `used` is always `0.0` even with a resting TP order present in `fetch_open_orders` | OKX moves resting-order holds into `used` and shrinks `free` | **V17-13** (pending-overlay double-counts the venue's own hold — the fake cannot express the double-count) |
| F9 | Restart tests hand-stamp `venue_order_id` into fixtures (`test_two_sided_restart.py:123`, `test_bracket_restart_relink.py:118`) | production never writes it on the happy path | **V17-02** (the exact "tests hand-build the state production should produce" pattern) |
| F10 | Streams are mutually coherent (balances exactly reflect the narrated fills, monotonic timestamps) | streams skew: balance snapshot can lag/lead trade delivery | drift-compare timing (the "just-applied engine fill vs stale venue snapshot" spurious-halt arm of V17-04's fix) |

Faithful-by-design (keep): floats everywhere in payloads (Pitfall 2 — forces `to_money(str(...))`
downstream); teardown-safe loop lifecycle mirroring the real connector; `deepcopy` per batch.

### 7b. Fake hardening plan

**Tier 1 — make the DEFAULT fake faithful (these gaps currently hide known production bugs):**
1. Split the fixture by market type: `okx_recon_payloads_spot.json` (wired reality: symbol
   `BTC/USDC`, USDC balance keys, `fetch_positions`/`watch_positions` → `[]`, BASE-currency
   position truth in the balance totals) and keep the current derivative-shaped file as
   `..._swap.json` for the ARCH-2 derivatives arm. The reconciliation cluster's default
   becomes the SPOT file — the shape production actually runs.
2. `fetch_my_trades` honors `symbol`/`since`/`limit` with a windowed, paginated canned
   history (and a "history older than the window" scenario for V17-10's RED test).
3. Balance payloads carry non-zero `used` whenever `fetch_open_orders` has a resting order
   (pins V17-13's fix semantics).
4. Delete fixture hand-stamping of `venue_order_id` from restart tests once the V17-02
   ORDER-ACK writer exists (the v17_bugs Wave-2 item already requires this).

**Tier 2 — a "hostile" opt-in variant for the resilience suites (CONF-A A5–A8):**
`build_hostile_recon_client(payloads, faults)` layered on the same fixture, with injectable
faults: raise mid-stream (`ExchangeError`, garbage-JSON row, one-shot `NetworkError`),
re-deliver the previous batch on "resubscribe" (WR-03/OKX snapshot semantics), drop
`id`/`clientOrderId` on selected trades, delay or hang `create_order` past the call timeout
(V17-09/V17-15), and return trades for an order the engine never placed (external-trade
signal). Default fake stays deterministic-friendly; hostile variant is explicitly chosen by
the resilience/restart suites so existing green tests keep their meaning.

**No new V17 entry:** every fidelity gap maps onto an existing finding (V17-02/04/06/07/09/10/13,
05-13 family); the audit's contribution is the census + the two-tier plan above.

---

## Campaign summary

- **AUD-1:** V17-01's three unguarded sites confirmed as the only ones on the wired run path;
  two more on the serialization path + unchecked `cast()` margin narrowing → **V17-14** filed.
  ARCH-1 Option-A member list narrowed to three true ABC additions (`assert_funds_invariant`,
  `apply_fill_cash_flow`, `reserved_balance`) if `available_balance` reads are re-pointed to
  the existing ABC `available`. Conformance test specified (1d), not committed.
- **AUD-2:** the entire portfolio SQL persistence layer (7 tables) is producer-unwired;
  `portfolio_account_state` has zero callers; `'live'` is never passed to
  `PortfolioStateStorageFactory`. Order + signal stores are the only genuinely wired durable
  paths. This is the ARCH-3 evidence package.
- **AUD-3:** money-mutating swallow set = master seam (`_publish_and_continue`), portfolio/order
  fill handlers, execution/OKX order boundaries, per-trade fill-translation skip (worst — never
  reaches the ERROR route), loop backstop. Circuit-breaker spec drafted (3b); inert until
  ARCH-4/V17-03 lands the HALTED latch.
- **AUD-4:** consumer table for `call`/`spawn`/`disconnect`; **V17-15** filed (gap backfill
  self-deadlocks the connector loop → BAR livelock + 30 s all-stream stalls). Protocol
  docstring contracts spec'd ready-to-paste (4c).
- **AUD-5:** all seven bar-timing rules PASS on `LiveBarFeed` (look-ahead-safe even in failure
  modes); ring-edge/capacity caveat for future coarse-TF strategies; `backfill_on_resume` →
  keep-unwired-and-annotate until the V17-15 loop-native redesign, then wire on the connector
  loop.
- **AUD-6:** `TradingInterface` no longer exists; the live entry surface (`add_event`)
  validates nothing and OKX preflight is dead code → **V17-16** filed; D-03a note update
  spec'd (6d), CONVENTIONS.md untouched.
- **AUD-7:** ten fidelity gaps, each mapped to the defect it masked; two-tier fake hardening
  plan (faithful spot default + hostile opt-in variant).

**New defects filed in v17_bugs.md:** V17-14 (MEDIUM, latent serialization/cast surface),
V17-15 (HIGH, connector-loop backfill deadlock), V17-16 (MEDIUM, unvalidated live order entry).
**ARCH decisions NOT taken** (per session scope): inputs flagged inline as → ARCH-1/2/3/4.
