---
slug: wr-high-priority-live
status: awaiting_human_verify
trigger: "Phase 5 review WR-01/WR-02/WR-04 — three high-priority live-path warnings, all the CR-01 'promote-a-conflated-concept-to-a-first-class-primitive' pattern"
created: 2026-07-03
updated: 2026-07-03
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
oracle_dark: true
related: cr-01-fill-double-count
---

# Debug Session: wr-high-priority-live

Three Phase-5 code-review warnings, root causes already established during review + a
follow-up code walk with the user (HIGH confidence). All are the same class as CR-01: a
distinct domain concept collapsed into an overloaded representation. Whole surface is
oracle-dark (live/sandbox only) — the frozen SMA_MACD backtest MUST stay byte-exact.

## Symptoms / Root Causes (established)

### WR-01 — failed CANCEL emits FillEvent(REFUSED), wrongly terminalizing a resting order
- **Where:** `OkxExchange.on_order` (okx.py:192-211) — one `except` covers BOTH `_submit_order`
  and `_cancel_order`, emitting `FillEvent("REFUSED", ...)`.
- **Effect:** `ReconcileManager._apply_refused` (reconcile_manager.py:224) moves the mirror to
  REJECTED. Correct for a submit that never reached the venue; WRONG for a transient CANCEL RPC
  failure — the venue order is very likely STILL RESTING, but the mirror is now permanently
  REJECTED → later a real fill arrives against an order the engine believes is dead, or an
  un-cancellable resting order.
- **Root smell (CR-01 family):** a failed cancel is NOT an execution event; forcing it through
  the fill/execution channel conflates a command-ack failure with execution truth.

### WR-02 — one shared VenueAccount assigned to every live portfolio
- **Where:** `live_trading_system.py:1085-1089` — the loop assigns the SAME `self._venue_account`
  instance to every active portfolio.
- **Effect:** with >1 live portfolio they share one venue balance/available/positions cache
  (buying power + positions conflated; `_compare_symbol_drift` reads one venue truth for all),
  and each portfolio's prior `SimulatedAccount` ledger is silently discarded. Latent today
  (single-portfolio live) but a correctness trap the moment a second portfolio exists.
- **Root smell (CR-01 family):** the venue account is a first-class keyed entity (AccountId /
  venue sub-account) but is modeled as a shared singleton.

### WR-04 — clOrdId truncation drops UUID entropy → wrong-order correlation
- **Where:** `OkxExchange._client_order_id` (okx.py:162-172) — `("it" + token)[:32]`, token = 32
  hex chars of the UUIDv7 → 34 truncated to 32, dropping the last 2 hex chars (tail-random bits).
- **Effect:** clOrdId is the fast-fill-race correlation key (`_orders_by_clOrdId`); two orders
  differing only in those bits collide → an echoed fill resolves to the WRONG originating order
  (wrong order_id/strategy_id/portfolio_id on the emitted FillEvent). Low but non-zero, rises
  with order volume.
- **Root smell (CR-01 family):** clOrdId = client order id (FIX ClOrdID(11) / Nautilus
  ClientOrderId), a must-be-unique first-class key, encoded lossily.
- **Clarified with user:** the fix is NOT a type change — the internal `order_id` STAYS a UUIDv7
  (locked single-UUIDv7-scheme decision); the clOrdId is the venue-charset RENDERING of it.
  Venue-ASSIGNED ids (`venue_order_id`, `venue_trade_id`) are correctly opaque `String` /
  `Optional[str]` already — leave those unchanged.

## Agreed Fix Designs (Nautilus/FIX-grounded)

### WR-01 fix
For a failed CANCEL, do NOT synthesize a `FillEvent`. Branch on `event.command` in the
`on_order` except:
- CANCEL failure → leave the mirror in its resting state (do NOT emit REFUSED) and emit an
  `ErrorEvent` (existing operator/dead-letter channel) so there is an auditable trail + optional
  alert; the next reconcile / drift pass reconciles true venue state. (Nautilus:
  `OrderCancelRejected` leaves order state untouched; a first-class OrderCancelRejected event is
  the full-parity option, DEFERRED — ErrorEvent gets correctness now.)
- SUBMIT failure → keep the existing `FillEvent("REFUSED", ...)` behavior (mirror PENDING→REJECTED
  is correct for a submit that never reached the venue).

### WR-02 fix
- Key the venue-account cache by sub-account (AccountId); build/resolve ONE `VenueAccount` per
  portfolio rather than sharing one instance under an exclusivity assumption.
- Until multi-portfolio-live actually exists, assert `len(active_portfolios) == 1` at wiring
  (fail-loud) so a second portfolio can never silently mis-attribute buying power/positions.
  (If two portfolios must ever share one venue sub-account, that needs real position attribution
  by clOrdId/tag — a bigger design, correctly deferred BEHIND the assert.)

### WR-04 fix
- Replace the lossy hex-truncate with a LOSSLESS encoding of the 16 raw UUID bytes: base62 of
  `event.order_id.bytes` → ~22 chars; `"it"` + 22 = ~24 chars, comfortably under OKX's 32-char
  alphanumeric clOrdId limit, full 128-bit entropy preserved. Keep deterministic (venue-echoed
  clOrdId must still map straight back to the pending correlation). Validate output ≤32 chars and
  alphanumeric.

## Scope guards (ALL three)
- Money stays Decimal end-to-end; venue floats cross via `to_money(str(x))` only.
- Match each file's existing indentation — okx.py / live_trading_system.py use TABS; events/ and
  config/ use 4 SPACES. Never normalize.
- Whole surface is oracle-dark. SMA_MACD backtest MUST stay byte-exact (simulated path takes no
  new branch): verify `tests/integration/test_backtest_oracle.py`.
- Do NOT touch `venue_order_id` / `venue_trade_id` types — already correct opaque strings.
- Independent of the open `cr-01-fill-double-count` working-tree changes; do not revert those.

## Current Focus
- hypothesis: Three root causes established (CR-01 family). All three agreed fixes IMPLEMENTED +
  unit-covered; full verification gate GREEN. Awaiting human confirmation.
- next_action: User confirms the three fixes resolve the WR-01/02/04 warnings in their live/sandbox
  review; on "confirmed fixed" -> archive session + append knowledge base.
- deviation_note (WR-02): the guard rejects len(active_portfolios) > 1 (NOT strict == 1). The
  existing Phase-5 test `test_start_spawns_okx_order_arm_fill_stream` starts a system with 0
  portfolios (a legitimate lifecycle — portfolios can be added post-start), which a strict ==1
  assert would REGRESS. The actual defect is sharing ONE VenueAccount across MULTIPLE portfolios;
  0 = benign no-op, 1 = supported single-portfolio-live, >1 = fail-loud RuntimeError. Correctness
  intent (no silent multi-portfolio mis-attribution) fully preserved; ==1 would have broken a valid
  path. Used RuntimeError (not a strippable assert) so the guard holds under `python -O`.
- reasoning_checkpoint:
  - WR-01: a failed-cancel test must leave the mirror ACTIVE (not REJECTED) and emit an
    ErrorEvent; a failed-submit test must still emit REFUSED → REJECTED (unchanged).
  - WR-02: a two-portfolio wiring must fail loud at the assert; single-portfolio wiring unchanged.
  - WR-04: two UUIDs differing only in tail bits must produce DIFFERENT clOrdIds; round-trip
    correlation (submit → echoed clOrdId → pending map) still resolves; all ≤32 chars alnum.
  - oracle byte-exact + existing Phase-5 live tests green.

## Evidence
- timestamp: 2026-07-03 — okx.py:192-211 single except covers submit+cancel, both emit REFUSED;
  reconcile_manager.py:224 _apply_refused → REJECTED. Confirmed WR-01.
- timestamp: 2026-07-03 — live_trading_system.py:1088-1089 assigns shared self._venue_account to
  every active portfolio. Confirmed WR-02.
- timestamp: 2026-07-03 — okx.py:171-172 ("it"+token)[:32] drops 2 hex chars of the UUIDv7.
  Confirmed WR-04. venue_order_id already String (models.py:109) / Optional[str] (order.py:116) —
  NOT to be changed.
- timestamp: 2026-07-03 (FIX) — WR-01 applied: on_order except now branches on event.command. A
  failed CANCEL publishes ErrorEvent(source="okx_exchange", operation="cancel_order", ERROR),
  leaves the mirror resting, no FillEvent; a failed SUBMIT still emits FillEvent(REFUSED). Exception
  TYPE bound only (T-05-27 scrub), never str(exc). ReconcileManager._apply_refused path for submits
  unchanged.
- timestamp: 2026-07-03 (FIX) — WR-02 applied: extracted testable seam
  `_link_venue_account_to_portfolios`; fail-loud RuntimeError on >1 active portfolio (0=no-op,
  1=link). Verified two-portfolio wiring raises, single-portfolio links, and the existing
  0-portfolio start path stays green.
- timestamp: 2026-07-03 (FIX) — WR-04 applied: _client_order_id now base62-encodes the order id's
  128 bits (UUID .bytes; int fallback for test doubles) → "it"+token ≤24 chars, asserted alnum/≤32.
  Lossless: two UUIDs differing only in the tail byte produce DIFFERENT clOrdIds; round-trip
  clOrdId correlation still resolves an echoed fill.
- timestamp: 2026-07-03 (VERIFY) — actual command output:
  * tests/unit/execution/test_okx_exchange.py → 19 passed (incl. WR-01 ErrorEvent test + 3 WR-04)
  * WR-02 wiring + phase-5 live set (okx_wiring, fill_idempotency, reconnect_resilience,
    two_sided_restart, bracket_restart_relink, okx_exchange) → 57 passed
  * tests/unit/portfolio/ + tests/integration/test_backtest_oracle.py → 316 passed (oracle
    byte-exact green — backtest surface unchanged)
  * tests/unit/execution/ (full tree) → 220 passed
  * `mypy itrader` (--strict via pyproject) → Success: no issues found in 225 source files

## Resolution
root_cause: |
  Three CR-01-family conflations on the live path: (WR-01) a failed CANCEL forced through the
  fill/execution channel as FillEvent(REFUSED), wrongly terminalizing a still-resting order to
  REJECTED; (WR-02) one shared VenueAccount assigned to every active portfolio, conflating buying
  power/positions and discarding each SimulatedAccount ledger once >1 portfolio exists; (WR-04)
  clOrdId rendered by lossy hex-truncation ("it"+32hex)[:32], dropping the UUID tail bits so two
  near-identical order ids collided on one correlation key.
fix: |
  WR-01 — okx.py on_order except branches on event.command: CANCEL failure publishes an ErrorEvent
  (operator/dead-letter channel) and leaves the mirror resting for the next reconcile; SUBMIT
  failure keeps FillEvent(REFUSED). WR-02 — extracted _link_venue_account_to_portfolios with a
  fail-loud RuntimeError guard on >1 active portfolio (deferred per-portfolio VenueAccount design
  documented behind it). WR-04 — _client_order_id base62-encodes the order id's full 128 bits
  (lossless, deterministic), "it"-prefixed, asserted alphanumeric and ≤32 chars.
verification: |
  New unit coverage per fix (failed-cancel ErrorEvent vs failed-submit REFUSED; two-portfolio
  fail-loud vs single-portfolio link; base62 no-collision + round-trip correlation). 57 Phase-5
  live tests + 316 portfolio/oracle tests + 220 execution tests all green; oracle byte-exact
  (backtest unchanged); mypy --strict clean over 225 files. Awaiting human confirmation in the
  live/sandbox review.
files_changed:
  - itrader/execution_handler/exchanges/okx.py (imports; _CLORDID_ALPHABET const ~62; _client_order_id ~172-205 WR-04; on_order except ~207-256 WR-01)
  - itrader/trading_system/live_trading_system.py (wiring site ~1085-1088; _link_venue_account_to_portfolios helper WR-02)
  - tests/unit/execution/test_okx_exchange.py (imports; WR-01 cancel ErrorEvent test; 3 WR-04 tests)
  - tests/integration/test_live_system_okx_wiring.py (pytest import; 2 WR-02 wiring tests)

## Eliminated
- hypothesis: WR-04 is fixed by using a string type instead of a UUID for the venue id —
  ELIMINATED: clOrdId is already a string and is CLIENT-generated from our internal UUIDv7; the
  defect is lossy truncation, not the type. Venue-assigned ids are already opaque strings.
- hypothesis: WR-01 minimal fix (branch + bare return, no event) is sufficient — PARTIALLY
  ELIMINATED as the PREFERRED design: bare return leaves no audit trail; emit an ErrorEvent so the
  failed cancel is observable and the mirror-left-resting decision is recorded.
