# Phase 5: Signal Contract & Reconcile (FRAGILE) - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

**SIG-01, SIG-02, SIG-03, RECON-01 — complete the signal/order *authoring* contract and
streamline the FRAGILE `on_fill` reconcile path, under ONE owner-gated re-baseline.**

A strategy can specify a per-intent **limit or stop ENTRY price** and **entry `order_type`**
(no longer hardwired to the decision-bar close / fixed per strategy instance); `Order.action`
and `_PendingBracket.action` become **`Side`-typed**; the position snapshot is threaded **once**
through admission→sizing (the triple `get_position()` removed); and the `on_fill` /
`should_release` reconciliation flow is **streamlined for clarity while preserving the
financial-integrity invariant** (idempotent release on every terminal reconciliation —
EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED). `reconcile/` + `admission/` are touched
**ONCE** under a single re-baseline + external cross-validation.

**KEY SCOUTING FINDING — this phase is mostly authoring-surface plumbing, NOT new machinery.**
The order/execution side ALREADY supports per-signal `order_type` + entry price:
- `admission_manager._build_primary_order` (lines 337-362) already dispatches MARKET/LIMIT/STOP
  on `signal_event.order_type` and threads `signal_event.price` into
  `Order.new_limit_order`/`new_stop_order`.
- `MatchingEngine._evaluate` (lines 137-180) already rests limit/stop orders and fills them
  "limit-or-better" (marketable limit fills at the bar OPEN with price improvement) — realistic
  and oracle-consistent, already implemented.

The GAP is the **strategy→signal** side only:
- `SignalIntent` (`core/sizing.py:212`) carries a literal `# TODO add order_type and entry_price`.
- `StrategiesHandler.calculate_signals` (lines 143/146) hardwires `order_type=strategy.order_type`
  and `price=to_money(bar.close)`.

**Re-baseline posture (Decision D-B):** the reference `SMAMACD` stays MARKET-at-close so the
existing oracle (**134 trades / `final_equity 46189.87730727451`**) holds **byte-exact** — any
drift is then an unambiguous SIG-03/RECON-01 bug. The new limit/stop path is proven by **ONE new
owner-signed, externally cross-validated limit-entry scenario**, not by re-baselining the existing
number. So the "owner-gated re-baseline" applies to the NEW scenario only; the existing golden is
expected to remain byte-identical.

**Explicitly NOT in this phase:**
- **Per-venue order validation** (Binance-style "stop would trigger immediately" rejection) → N+4.
- **Margin/liquidation, shorts, leverage, trailing stops** → N+2 (builds on this completed surface).
- **Per-signal `market_execution` fill-timing override** (beyond per-intent `order_type`/entry-price) → future signal-contract phase.
- **LIFE-01 run-end TIF / `create_order` second-path gating** → Phase 6.

</domain>

<decisions>
## Implementation Decisions

### D-01 — Authoring API: distinct factory sugar (SIG-01/SIG-02)
- Add **`buy_limit` / `buy_stop` / `sell_limit` / `sell_stop`** sugar to the strategy base.
  `buy()` / `sell()` stay **market-only and byte-exact** (no new params).
- `SignalIntent` gains **`entry_price: Decimal | None`** and **`order_type: OrderType`** (set by
  the factory — `MARKET` for plain `buy()`/`sell()`, `LIMIT`/`STOP` for the typed factories; never
  `None` for limit/stop). The price kwarg is **required by the limit/stop factory signatures** and
  **absent from `buy()`/`sell()`** → illegal `(order_type, price)` combinations are unrepresentable
  by construction (this is why Area 4 collapses — see D-04).
- **Retire** the per-instance `Strategy.order_type` class attribute (added by STRAT-01, `base.py:101`):
  with explicit factories every call states the type, so the strategy-wide default is never read.
  **Blast radius of the retirement:** `base.py:397` `to_dict()` snapshot (drop `"order_type"`),
  `SignalRecord.config` consumers, and any subclass that pins `order_type`. Plain `buy()`/`sell()`
  hardcode `OrderType.MARKET` on the intent (do NOT read `self.order_type`).
- Rationale vs alternatives: symmetric with the existing `Order.new_market/limit/stop_order`
  factories; "make illegal states unrepresentable" (deletes most validation); discoverable
  (`self.buy_<tab>`). Mirrors nautilus / QuantConnect-Lean. (Rejected: opt-2 explicit
  `order_type=`+`entry_price=` — needs a consistency guard; opt-1 inferred `limit=`/`stop=` —
  backtesting.py style, ruled out though it would read closest to the cross-val oracle.)

### D-02 — Handler fan-out + audit capture (SIG-01/SIG-02)
- `StrategiesHandler.calculate_signals` reads `intent.order_type` and `intent.entry_price`
  (replacing the hardwired `strategy.order_type` and, for limit/stop, `to_money(bar.close)`).
  **MARKET keeps `price = to_money(bar.close)` byte-exact** (plain `buy()` carries no entry_price).
- **Add `order_type` + `entry_price` to `SignalRecord`** (strategies_handler:121-131). It is the
  audit read-model of "what the strategy decided"; omitting the new fields would misrepresent
  limit/stop decisions. It is an oracle-dark sink (does not affect fills) — low-risk schema add on
  the in-memory backtest store.

### D-03 — SIG-03 typing + snapshot threading (rides the SIG re-baseline)
- Retype **`Order.action`** (`order.py` — `new_stop_order`:199 / `new_limit_order`:232 `action`
  params + the entity field) and **`_PendingBracket.action`** (`brackets/bracket_book.py`, the v1.2
  06-01 marked spot) from `str` to **`Side`**.
- Thread the position snapshot **ONCE**: capture **`Optional[Position]`** at the top of
  `admission_manager.process_signal` (before the step-0 direction gate, ~line 138) and pass it into
  `_enforce_direction_admission` / `_enforce_position_admission` / `_resolve_signal_quantity` (the
  three current `get_position()` sites at lines 404/484/583). **Byte-exact:** nothing mutates the
  position between those sites (the line-208 reserve touches cash; no fill yet), so one snapshot is
  value-identical to three re-fetches. Thread the **Position object** (each site reads existence /
  `net_quantity`), not a lightweight value.
- **W4-04 validator-overlap doc** (`order_validator.py` / `simulated.py`): update **only if** the
  validator path is actually touched by the limit/stop entry work.

### D-04 — Entry-price validation: accept, no new validation (SIG-01)
- **No new admission validation in v1.3.** A marketable limit (buy-limit above market) fills at the
  bar OPEN with price improvement via the existing `MatchingEngine` ("limit-or-better", D-03,
  matching_engine.py:166-180) — already realistic, already implemented, oracle-consistent. A
  wrong-side stop also accepts/fills at open (matches backtesting.py/backtrader).
- Binance-style "stop would trigger immediately" rejection (error -2010 class) is a **per-venue LIVE**
  concern → **deferred to N+4** (adding it now would diverge from the cross-val oracles and undermine
  D-B). Most of this area was pre-collapsed by D-01's unrepresentable-illegal-states design.

### D-05 — Sizing basis for limit/stop entries (SIG-01)
- Sizing + cash reservation **use `signal_event.price`** (already the basis — sizing ~line 565,
  reserve line 206). Under the new contract that field IS the limit/stop price for those orders
  (close for market). **No new sizing logic.** Conservative-correct: a BUY limit fills at-or-below
  its price, so sizing/reserving at the limit yields a safe (≤) quantity + sufficient reservation.
- **Known edge (document it):** a BUY stop can gap-fill ABOVE its trigger (`max(open, trigger)`),
  slightly under-reserving on a gap — accepted as the **same blessed class** as a MARKET order sized
  on close but filling next-bar-open higher.

### D-06 — RECON-01: clarity cleanup, flow-preserving (RECON-01)
- Streamline `ReconcileManager.on_fill` (reconcile_manager.py:86-234) by **extracting the
  EXECUTED/CANCELLED/REFUSED arms into named helpers** + a named `_classify(status) →
  terminal?/transition` and a `_release_reservation(order, should_release, body_raised)` helper;
  improve naming/comments. **Keep the `try`/`finally` exception-safety skeleton BYTE-IDENTICAL.**
- Rationale: the hard part is **irreducible exception-safe resource release** (release-once-on-terminal-
  even-if-the-body-raises — WR-03/WR-04/T-05-17), NOT a transition-table problem. A state-machine
  rewrite risks reintroducing the WR-04 bug (a sequential `apply(); release()` skips release on a
  raise) for a cosmetic dispatch win. The "release-once-obvious" clarity win is captured via the
  named `_release_reservation` helper without a control-flow rewrite. (Rejected: opt-2 explicit
  state-machine restructure; opt-3 doc-only.) The invariant: idempotent release on EVERY terminal
  reconciliation; the non-terminal unknown-status early-return intentionally HOLDS the reservation.

### D-07 — Re-baseline + cross-validation (SIG/RECON, owner-gated)
- **Existing golden stays byte-exact** (134 / `46189.87730727451`); reference SMAMACD unchanged
  (MARKET-at-close). SIG-03 + RECON-01 must hold it byte-exact + determinism double-run identical.
- Add **ONE owner-signed, externally cross-validated (backtesting.py/backtrader)** limit-entry
  golden, using a **crafted minimal deterministic strategy** (e.g. buy_limit at `close*0.98` every
  N bars + percent SL/TP) on the **same BTCUSD golden dataset** — NOT SMAMACD+offset (declared-
  indicator MACD is too fiddly to replicate identically across 3 engines; a minimal strategy
  isolates discrepancy to the entry-fill→bracket mechanic). The scenario MUST: fill on a LATER bar
  (not immediate), exercise the entry-fill→SL/TP-bracket anchor sequence, and include a
  **marketable-limit case** to pin fill-price (open vs limit). Reuse the v1.0 cross-val harness
  (`tests/golden/CROSS-VALIDATION.md`). **Owner sign-off with full attribution is required before
  freezing the new golden.**

### Claude's Discretion
- Exact factory signatures / shared `_intent(...)` private helper for sl/tp/exit_fraction/quantity
  across the 6 buy/sell methods (D-01).
- Exact home + names of the `_classify` / `_release_reservation` / per-status arm helpers (D-06).
- The crafted cross-val strategy's exact offset %, cadence N, and SL/TP %, subject to the
  fill-on-later-bar + entry-fill→bracket + marketable-limit-case requirements (D-07).
- `SignalRecord` field names/types for `order_type`/`entry_price` (D-02).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source / requirements / discipline
- `.planning/ROADMAP.md` §"Phase 5: Signal Contract & Reconcile (FRAGILE)" — goal + 5 success
  criteria (the pass/fail contract); §"Phase 6" for the LIFE-01 out-of-scope boundary; §"Backlog
  999.4 (N+2)" for the margin/shorts/trailing surface this phase completes for.
- `.planning/REQUIREMENTS.md` §"Signal Contract (SIG)" + §"Order Reconciliation (RECON)" —
  SIG-01/02/03 + RECON-01 (authoritative); the byte-exact-vs-owner-gated re-baseline tags; the
  co-phasing rationale (`reconcile/` touched once).
- `.planning/STATE.md` §"Milestone Gate" — the FRAGILE-zone rule, owner-gate dependency, and the
  idempotent terminal-release invariant (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED).
- `.planning/notes/v1.3-concerns-triage.md` — W1-11 (snapshot threading), W2-02 (`action`→`Side`),
  W4-04 (validator-overlap doc), 999.5-(a) scope.

### FRAGILE / behavior-risk surfaces (touch once, byte-exact-sensitive)
- `itrader/order_handler/reconcile/reconcile_manager.py:86-234` — `on_fill` /
  `should_release` / `try`/`finally` release-in-finally (RECON-01; D-06). Module docstring
  documents WR-03/WR-04/T-05-17.
- `itrader/order_handler/admission/admission_manager.py` — `process_signal` (120-249);
  `_build_primary_order` order_type dispatch (337-362, ALREADY wired); the three `get_position()`
  sites (404/484/583 → thread once, D-03); the line-206 reserve cost basis (D-05).
- `itrader/order_handler/brackets/bracket_book.py` — `_PendingBracket.action` `str`→`Side` (D-03).
- `itrader/order_handler/order.py:199,232` — `new_stop_order`/`new_limit_order` `action` param
  `str`→`Side` + the `Order.action` entity field (D-03).

### Authoring-surface surfaces (the actual gap)
- `itrader/core/sizing.py:212` — `SignalIntent` (+ the `# TODO add order_type and entry_price`); add
  `entry_price`/`order_type` (D-01).
- `itrader/strategy_handler/base.py` — `buy`/`sell` sugar (434-468 → add `buy_limit`/`buy_stop`/
  `sell_limit`/`sell_stop`); `order_type` attr (101 → retire); `to_dict()` (397 → drop order_type).
- `itrader/strategy_handler/strategies_handler.py:121-170` — `SignalRecord` capture (add
  order_type/entry_price, D-02) + the fan-out hardwire (143/146 → per-intent, D-02).
- `itrader/events_handler/events/signal.py` — `SignalEvent` (already carries `order_type`/`price`;
  no field change expected, it is the boundary the handler fills).

### Already-correct machinery (read to confirm, do NOT rebuild)
- `itrader/execution_handler/matching_engine.py:137-180` — limit-or-better fill, marketable-limit
  at open, pessimistic stop gap (D-04/D-05 grounding).
- `tests/golden/CROSS-VALIDATION.md` — the v1.0 backtesting.py/backtrader harness to reuse (D-07).

### Conventions (must match)
- `CLAUDE.md` + `.planning/codebase/CONVENTIONS.md` — **tabs** in `order_handler/`/`strategy_handler/`
  (this phase's modules); **4 spaces** in `core/` (`sizing.py`) + `events_handler/events/`; Decimal
  money via `to_money` (NEVER `Decimal(float)`); the broad-`except` run-mode policy; the W4-04
  dual-layer validator justified-by-decision.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Order.new_limit_order` / `new_stop_order`** (`order.py:199,232`) — already exist; admission
  already calls them. SIG-01/02 just feeds them per-intent values instead of strategy-fixed ones.
- **`MatchingEngine._evaluate`** (137-180) — already rests + fills limit/stop with realistic
  limit-or-better / pessimistic-gap semantics. No matching work needed.
- **`SignalIntent.buy()/sell()` sugar** (`base.py:434-468`) — the template the new `buy_limit`/
  `buy_stop`/`sell_limit`/`sell_stop` factories extend (shared sl/tp/exit_fraction/quantity logic).
- **v1.0 cross-validation harness** (`tests/golden/CROSS-VALIDATION.md`) — reuse for the D-07
  limit-entry scenario.
- **`ReconcileManager` (`reconcile/`)** — the clean, bounded enabling surface the v1.2 Phase-6
  intact-move created specifically so RECON-01 can refactor it here.

### Established Patterns
- **Per-signal `order_type` dispatch is already the admission contract** (`_build_primary_order`) —
  the strategy side just wasn't feeding it. The phase is asymmetric: order side done, strategy side new.
- **Next-bar-open, no immediate-execution** (matching_engine docstring) — every order rests and fills
  next bar at earliest; marketable limits fill next-bar-open, look-ahead-safe.
- **Idempotent terminal release in `finally`** (WR-03/WR-04/T-05-17) — the invariant RECON-01 must
  preserve byte-for-byte; `should_release` armed AFTER terminal status, BEFORE further work.
- **Single-writer backtest contract** — no position mutation within one `process_signal`, which is
  what makes the D-03 one-snapshot threading byte-exact.
- **SignalRecord is an oracle-dark sink** (D-12) — augmenting it never affects fills.

### Integration Points
- `SignalIntent` (`core/`) → `SignalEvent` (handler fan-out) → `Order` (admission) → `MatchingEngine`
  (execution) → `FillEvent` → `ReconcileManager.on_fill` (mirror) — the full path SIG-01/02 + RECON-01
  thread through; only the first two hops change.
- `OrderManager.on_fill` is a 1-line delegation to `ReconcileManager.on_fill` — the public surface
  stays byte-equal through the RECON-01 cleanup.

</code_context>

<specifics>
## Specific Ideas

- Crafted cross-val strategy (D-07), illustrative shape:
  ```python
  # every N bars: place a buy-limit below close + percent SL/TP
  self.buy_limit(ticker, price=to_money(close * Decimal("0.98")), sl=..., tp=...)
  # plus one bar that places a MARKETABLE buy-limit (price above market) to pin
  # the open-vs-limit fill price against backtesting.py / backtrader
  ```
- Snapshot threading (D-03), target shape:
  ```python
  def process_signal(self, signal_event):
      snap: Position | None = self.portfolio_handler.get_position(...)  # ONCE, up front
      gate = self._enforce_direction_admission(signal_event, snap)
      gate = self._enforce_position_admission(signal_event, snap)
      resolved = self._resolve_signal_quantity(signal_event, snap)
  ```
- RECON-01 cleanup (D-06), target shape:
  ```python
  def on_fill(self, fill_event):
      terminal, transition = self._classify(fill_event.status)
      try:
          # named per-status arm (_apply_executed/_cancelled/_refused)
          should_release = terminal
          # orphan-child cancel / fill-anchored children (unchanged)
      finally:
          self._release_reservation(order, should_release, body_raised)  # try/finally byte-identical
  ```

</specifics>

<deferred>
## Deferred Ideas

- **Per-venue "stop would trigger immediately" rejection (N+4 Live Readiness)** — Binance-style
  error -2010 class; per-venue order validation, alongside the trailing-stop native-vs-synthetic
  venue-capability seam already noted for N+2/N+4. Adding it in v1.3 would diverge from the
  backtesting.py/backtrader cross-val oracles.
- **Per-signal `market_execution` (fill-timing) override** — beyond SIG-02's per-intent
  `order_type`/entry-price; a finer extension for a future signal-contract phase (carried from
  Phase 4 deferred).
- **N+2 (margin/shorts/leverage/trailing) builds directly on this completed SIG surface** — the
  cross-validated limit-entry golden (D-07) becomes its regression anchor.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 5-signal-contract-reconcile-fragile*
*Context gathered: 2026-06-13*
