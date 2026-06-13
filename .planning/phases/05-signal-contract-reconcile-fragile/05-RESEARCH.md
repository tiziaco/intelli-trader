# Phase 5: Signal Contract & Reconcile (FRAGILE) - Research

**Researched:** 2026-06-13
**Domain:** Signal/order authoring contract + FRAGILE fill-reconciliation refactor + external cross-validation
**Confidence:** HIGH (machinery confirmed by code read; cross-validation engine semantics confirmed by source)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Authoring API: distinct factory sugar (SIG-01/SIG-02).** Add `buy_limit` /
  `buy_stop` / `sell_limit` / `sell_stop` sugar to the strategy base. `buy()` / `sell()` stay
  **market-only and byte-exact** (no new params). `SignalIntent` gains `entry_price: Decimal | None`
  and `order_type: OrderType` (set by the factory — `MARKET` for plain `buy()`/`sell()`,
  `LIMIT`/`STOP` for typed factories; never `None` for limit/stop). The price kwarg is **required by
  the limit/stop factory signatures** and **absent from `buy()`/`sell()`** → illegal `(order_type, price)`
  combinations are unrepresentable by construction (Area 4 collapses → D-04). **Retire** the per-instance
  `Strategy.order_type` class attr (`base.py:101`). Blast radius: `base.py:397` `to_dict()` (drop
  `"order_type"`), `SignalRecord.config` consumers, any subclass pinning `order_type`. Plain
  `buy()`/`sell()` hardcode `OrderType.MARKET` (do NOT read `self.order_type`).

- **D-02 — Handler fan-out + audit capture (SIG-01/SIG-02).** `StrategiesHandler.calculate_signals`
  reads `intent.order_type` and `intent.entry_price` (replacing hardwired `strategy.order_type` and,
  for limit/stop, `to_money(bar.close)`). **MARKET keeps `price = to_money(bar.close)` byte-exact.**
  Add `order_type` + `entry_price` to `SignalRecord` (audit read-model; oracle-dark sink).

- **D-03 — SIG-03 typing + snapshot threading (rides the SIG re-baseline).** Retype `Order.action`
  and `_PendingBracket.action` from `str` to `Side`. Thread the position snapshot **ONCE**: capture
  `Optional[Position]` at the top of `admission_manager.process_signal` (before the step-0 direction
  gate, ~line 138) and pass into `_enforce_direction_admission` / `_enforce_position_admission` /
  `_resolve_signal_quantity` (the three current `get_position()` sites at 404/484/583). Byte-exact:
  nothing mutates the position between those sites. Thread the **Position object**. W4-04 validator-overlap
  doc: update **only if** the validator path is actually touched.

- **D-04 — Entry-price validation: accept, no new validation (SIG-01).** No new admission validation in
  v1.3. Marketable limit fills at open with price improvement via existing `MatchingEngine`
  (limit-or-better); wrong-side stop accepts/fills at open. Binance-style rejection → N+4.

- **D-05 — Sizing basis for limit/stop entries (SIG-01).** Sizing + cash reservation use
  `signal_event.price` (already the basis — sizing ~565, reserve line 206). Under the new contract that
  field IS the limit/stop price. **No new sizing logic.** Known edge (document): a BUY stop can gap-fill
  ABOVE its trigger (`max(open, trigger)`), slightly under-reserving on a gap — accepted as same blessed
  class as a MARKET order sized on close.

- **D-06 — RECON-01: clarity cleanup, flow-preserving (RECON-01).** Streamline
  `ReconcileManager.on_fill` by extracting EXECUTED/CANCELLED/REFUSED arms into named helpers + a named
  `_classify(status) → terminal?/transition` and a `_release_reservation(order, should_release, body_raised)`
  helper; improve naming/comments. **Keep the `try`/`finally` exception-safety skeleton BYTE-IDENTICAL.**
  Invariant: idempotent release on EVERY terminal reconciliation; the non-terminal unknown-status
  early-return intentionally HOLDS the reservation.

- **D-07 — Re-baseline + cross-validation (SIG/RECON, owner-gated).** Existing golden stays byte-exact
  (134 / `46189.87730727451`); reference SMAMACD unchanged (MARKET-at-close). Add **ONE owner-signed,
  externally cross-validated (backtesting.py/backtrader)** limit-entry golden, using a **crafted minimal
  deterministic strategy** (e.g. buy_limit at `close*0.98` every N bars + percent SL/TP) on the **same
  BTCUSD golden dataset** — NOT SMAMACD+offset. The scenario MUST: fill on a LATER bar (not immediate),
  exercise the entry-fill→SL/TP-bracket anchor sequence, and include a **marketable-limit case** to pin
  fill-price (open vs limit). Reuse the v1.0 cross-val harness. **Owner sign-off with full attribution
  required before freezing the new golden.**

### Claude's Discretion

- Exact factory signatures / shared `_intent(...)` private helper for sl/tp/exit_fraction/quantity
  across the 6 buy/sell methods (D-01).
- Exact home + names of the `_classify` / `_release_reservation` / per-status arm helpers (D-06).
- The crafted cross-val strategy's exact offset %, cadence N, and SL/TP %, subject to the
  fill-on-later-bar + entry-fill→bracket + marketable-limit-case requirements (D-07).
- `SignalRecord` field names/types for `order_type`/`entry_price` (D-02).

### Deferred Ideas (OUT OF SCOPE)

- Per-venue "stop would trigger immediately" rejection (Binance error -2010 class) → N+4.
- Per-signal `market_execution` (fill-timing) override → future signal-contract phase.
- Margin/liquidation, shorts, leverage, trailing stops → N+2 (builds on this completed SIG surface).
- LIFE-01 run-end TIF / `create_order` second-path gating → Phase 6.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIG-01 | Strategy can specify per-intent limit/stop ENTRY price, threaded `SignalIntent → SignalEvent → Order.new_limit_order`/`new_stop_order` | Order side ALREADY wired (`admission_manager._build_primary_order:337-362`); gap is `SignalIntent` (`sizing.py:212` TODO) + factory sugar (`base.py:434-468`) + fan-out (`strategies_handler.py:143/146`). |
| SIG-02 | Strategy can specify entry `order_type` per intent (MARKET/LIMIT/STOP), incl. the Phase 8 per-bar override unwired in the e2e emitter | `ScriptedEmitter` docstring explicitly documents the per-INSTANCE `order_type` limitation (Pitfall 3) that this requirement removes. Factory carries `order_type` on the intent. |
| SIG-03 | `Order.action` + `_PendingBracket.action` typed `Side`; position snapshot threaded once | Blast radius mapped below (Architecture Patterns). `OrderEvent.action` is ALREADY `Side`; the `str` boundary is `Order.action` (`order.py:49`) + `_PendingBracket.action` (`bracket_book.py:40`) + validator string literals (`order_validator.py:193,414-415`) + bracket child literals (`bracket_manager.py:143/157/245`). |
| RECON-01 | Streamline `on_fill` + `should_release` release-in-`finally`, preserving idempotent-release-on-terminal invariant | Full `reconcile_manager.py:86-234` read; the exception-safety skeleton (WR-03/WR-04/T-05-17) and the cross-bucket seams documented below. |
</phase_requirements>

## Summary

Phase 5 is **two-thirds authoring-surface plumbing + one-third a genuinely-research-worthy
cross-validation deliverable.** The order/execution machinery that makes per-signal limit/stop entries
work is **already implemented and verified by existing e2e leaves** — `admission_manager._build_primary_order`
(lines 337-362) already dispatches MARKET/LIMIT/STOP on `signal_event.order_type` and threads
`signal_event.price` into the right `Order` factory; `MatchingEngine._evaluate` (137-180) already rests
and fills limit/stop orders with limit-or-better / pessimistic-gap semantics; and `tests/e2e/matching/entries/`
already contains hand-verified `limit_touch`, `stop_gap_up`, `stop_gap_down`, `market_next_open` golden
leaves. The ONLY gap is the **strategy→signal** hop: `SignalIntent` (`core/sizing.py:212`) carries a literal
`# TODO add order_type and entry_price`, and `StrategiesHandler.calculate_signals` (143/146) hardwires
`order_type=strategy.order_type` + `price=to_money(bar.close)`.

SIG-03 (`action`→`Side`) and RECON-01 (`on_fill` clarity cleanup) are co-phased because both touch the
FRAGILE reconcile/admission path. SIG-03 is a mechanical type-narrowing with a bounded, fully-enumerated
blast radius (the `str` action boundary is `Order.action` + `_PendingBracket.action` + ~6 string-literal
comparison sites). RECON-01 is **explicitly a comment/extract-method refactor with the `try`/`finally`
skeleton held byte-identical** — the hard part is irreducible exception-safe resource release, NOT a
transition table, so a state-machine rewrite is a rejected anti-pattern that risks reintroducing the WR-04
bug for a cosmetic dispatch win.

The research-heavy unknown is **D-07's external cross-validation**: a new owner-signed, backtesting.py /
backtrader cross-validated LIMIT-entry golden. The decisive finding here is that **all three engines share
the same fill-price algebra by construction** — backtesting.py's source computes a buy-limit fill as
`min(open, limit)` and a buy-stop fill as `max(open, stop)`, which is *exactly* iTrader's
`MatchingEngine._evaluate` (limit-or-better → `min`; pessimistic stop → `max`). So a crafted strategy that
isolates the entry-fill→bracket mechanic (no fiddly MACD) will reproduce identically across all three
engines, and the marketable-limit case (limit above market → fill at open) is pinned by the same `min`/`max`
rule. The harness to reuse already exists (`scripts/cross_validate.py` + `scripts/crossval/*_run.py`), but
both current engine runners are **MARKET-only** — they will need a new LIMIT-entry runner variant.

**Primary recommendation:** Treat SIG-01/02 as a thin authoring-surface add (factory sugar + 2 new
`SignalIntent`/`SignalRecord` fields + 2 fan-out lines), confirm-don't-rebuild the order/matching machinery,
do SIG-03 as a mechanical `Side` narrowing against the enumerated blast radius, and do RECON-01 as a
pure extract-method/comment refactor with the `try`/`finally` bytes untouched. Invest the real effort in
the D-07 crafted-strategy cross-validation: reuse `ScriptedEmitter` as the strategy template, add a
LIMIT-entry runner to each engine, and lean on the shared `min(open,limit)`/`max(open,stop)` fill rule to
guarantee three-engine agreement.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-intent entry-price/order_type authoring (SIG-01/02) | Strategy (`strategy_handler/base.py`, `core/sizing.py`) | — | The strategy DECIDES the entry; the contract object (`SignalIntent`) is the carrier. This is the only NEW surface. |
| Signal fan-out → `SignalEvent` (SIG-01/02) | Strategy handler (`strategies_handler.py`) | — | The handler is the strategy→order boundary; it reads the intent and constructs the per-portfolio event. |
| Order construction from signal (already wired) | Order admission (`admission/admission_manager.py:337-362`) | — | The order layer owns order-type dispatch; CONFIRM, do not rebuild. |
| Resting-order matching / fill-price (already wired) | Execution (`matching_engine.py:137-180`) | — | The exchange is source of truth for fills; limit-or-better / pessimistic-stop already implemented. |
| `Side`-typing of `action` (SIG-03) | Order entity (`order.py`) + brackets (`bracket_book.py`) | Order validator (`order_validator.py`) | The `str` boundary lives on the persisted entity, not the event (`OrderEvent.action` is already `Side`). |
| Snapshot threading (SIG-03) | Order admission (`admission_manager.process_signal`) | — | Position read-model crossing is owned by admission; thread the snapshot, don't refetch. |
| Fill reconciliation / reservation release (RECON-01) | Order reconcile (`reconcile/reconcile_manager.py`) | Portfolio read-model (`release`) | The FRAGILE financial-integrity invariant lives here; touch once. |
| Cross-validation evidence (D-07) | Script path (`scripts/crossval/`) + golden (`tests/golden/` or new e2e leaf) | — | SCRIPT-ONLY (D-10): never imported under `tests/` (`filterwarnings=["error"]` contract). |

## Standard Stack

No new external libraries. Every dependency this phase needs is already pinned and installed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `Decimal` | 3.13 | Money end-to-end (entry_price, levels) | Locked project decision; `to_money()` is the only entry into the Decimal domain. |
| Python stdlib `enum` (`Side`, `OrderType`) | 3.13 | `action`/`order_type` typing (SIG-02/03) | `Side`/`OrderType` already exist in `core/enums/`; `Side` has a case-insensitive `_missing_` parser. |

### Supporting (cross-validation only, SCRIPT-PATH, already pinned)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `backtesting` (backtesting.py) | 0.6.5 | GATING cross-val engine for the new LIMIT golden (D-07) | Reused via `scripts/crossval/backtesting_py_run.py` — add a LIMIT-entry runner. |
| `backtrader` | 1.9.78.123 | GATING cross-val engine for the new LIMIT golden (D-07) | Reused via `scripts/crossval/backtrader_run.py` — add a LIMIT-entry runner with `buy_bracket`. |
| `nautilus-trader` | 1.227.0 | NON-GATING corroboration (D-12) | Optional, behind a try-guard; degrades to "not reconciled" on failure. |

**Installation:** None required — all three engines are already in `pyproject.toml` and installed in `.venv`.

**Version verification:**
```
backtesting.py 0.6.5  (confirmed installed: poetry run python -c "import backtesting; print(backtesting.__version__)")
backtrader     1.9.78.123  (confirmed installed)
```
[VERIFIED: poetry run import]

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Crafted minimal strategy on the BTCUSD golden dataset (D-07) | SMAMACD + a price offset | REJECTED in D-07: declared-indicator MACD is too fiddly to replicate identically across 3 engines; a minimal strategy isolates the discrepancy surface to the entry-fill→bracket mechanic. |
| Reuse `tests/golden/` cross-val harness (`scripts/cross_validate.py`) | A new bespoke harness | The existing harness already loads the golden CSV once, recomputes apples-to-apples metrics via `itrader.reporting.metrics`, and emits a committed evidence report. Extend it, don't replace it. |
| D-01 distinct factories (`buy_limit`/...) | Inferred `limit=`/`stop=` kwargs (backtesting.py style) | REJECTED in D-01 even though it reads closest to the cross-val oracle — distinct factories make illegal `(order_type, price)` states unrepresentable. |

## Package Legitimacy Audit

> No external packages are installed by this phase. All cross-validation engines are pre-existing,
> pinned dependencies committed since v1.0 (M5-10) and exercised by the existing
> `tests/golden/CROSS-VALIDATION.md` evidence run.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| backtesting | PyPI | mature (0.6.5) | high | github.com/kernc/backtesting.py | N/A (pre-installed, pinned) | Approved — no install |
| backtrader | PyPI | mature (1.9.x) | high | github.com/mementum/backtrader | N/A (pre-installed, pinned) | Approved — no install |
| nautilus-trader | PyPI | mature (1.227.0) | high | github.com/nautechsystems/nautilus_trader | N/A (pre-installed, pinned) | Approved — no install |

**Packages removed due to slopcheck [SLOP] verdict:** none — no packages installed this phase.
**Packages flagged as suspicious [SUS]:** none.

*slopcheck was not run because this phase installs zero new packages; all three engines are committed,
pinned, version-locked dependencies already imported by the existing v1.0 cross-validation harness.*

## Architecture Patterns

### System Architecture Diagram — the SIG-01/02 path (only the first two hops change)

```
STRATEGY                                                          [NEW — the gap]
  buy_limit(ticker, price=...) / buy_stop(...) / sell_limit / sell_stop
  buy() / sell()  (MARKET, byte-exact, no new params)
        |
        v
  SignalIntent  (core/sizing.py:212)            [NEW fields: entry_price, order_type]
        |
        v
STRATEGY HANDLER
  StrategiesHandler.calculate_signals (143/146)  [CHANGED: read intent.order_type / entry_price]
    MARKET  -> price = to_money(bar.close)        [byte-exact preserved]
    LIMIT/STOP -> price = intent.entry_price
    + SignalRecord(order_type, entry_price)        [NEW audit fields — oracle-dark]
        |
        v
  SignalEvent  (events/signal.py)   [NO field change — already carries order_type + price]
        |
        v  ====================== EVERYTHING BELOW IS ALREADY WIRED — CONFIRM ONLY ======================
ORDER ADMISSION
  admission_manager.process_signal (120-249)
    [SIG-03] snapshot = get_position(...) ONCE  -> thread into the 3 gate/sizing methods
    _build_primary_order (337-362)  -> dispatch on signal.order_type:
        MARKET -> Order.new_order          LIMIT -> Order.new_limit_order   STOP -> Order.new_stop_order
    reserve cost basis (206) = price * qty + commission   [price IS the limit/stop price now]
        |
        v
EXECUTION / MATCHING ENGINE  (matching_engine.py:137-180)
    MARKET -> fill at next-bar open
    BUY LIMIT  -> min(open, trigger)   (limit-or-better; marketable limit fills at open)
    BUY STOP   -> max(open, trigger)   (pessimistic gap-up)
        |
        v  FillEvent
ORDER RECONCILE  (reconcile/reconcile_manager.py:86-234)   [RECON-01: clarity cleanup, flow byte-identical]
    EXECUTED -> FILLED ;  CANCELLED -> CANCELLED ;  REFUSED -> REJECTED
    should_release armed AFTER terminal status, released in finally (idempotent)
```

### Pattern 1: Distinct-factory authoring sugar (D-01)

**What:** Add `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop` alongside the existing `buy()`/`sell()`.
**When to use:** SIG-01/02 — the only new strategy-facing surface.
**Example (existing `buy()` is the template — `base.py:434`):**
```python
# Source: itrader/strategy_handler/base.py:434-468 (existing buy() sugar — the template)
def buy(self, ticker: str, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent:
    return SignalIntent(
        ticker=ticker, action=Side.BUY,
        stop_loss=to_money(sl) if sl is not None else None,
        take_profit=to_money(tp) if tp is not None else None,
        exit_fraction=exit_fraction,
    )

# NEW (D-01): price is REQUIRED on the typed factory; order_type/entry_price set on the intent.
# A shared private _intent(...) helper (Claude's discretion) folds the sl/tp/exit_fraction/quantity
# logic across all 6 methods. buy()/sell() pass order_type=OrderType.MARKET, entry_price=None.
def buy_limit(self, ticker: str, *, price, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent:
    return self._intent(ticker, Side.BUY, OrderType.LIMIT, to_money(price), sl, tp, exit_fraction)
```
**Key constraint:** `buy()`/`sell()` must stay BYTE-EXACT (no new params, hardcode `OrderType.MARKET`).
Reading `self.order_type` is DELETED (the class attr is retired). Indentation: **tabs** (`base.py` is a tab file).

### Pattern 2: Snapshot-threading (D-03, W1-11)

**What:** Capture `Optional[Position]` once at the top of `process_signal`; pass it into the three
methods that currently each call `get_position()`.
**When to use:** SIG-03 — removes the triple `get_position()` (sites 404/484/583).
**Byte-exactness rationale:** The single-writer backtest contract guarantees nothing mutates the position
between those sites within one `process_signal` (the line-208 reserve touches cash only; no fill yet), so
one snapshot is value-identical to three re-fetches.
**Example (target shape from CONTEXT specifics):**
```python
# Source: CONTEXT.md D-03 specifics
def process_signal(self, signal_event):
    snap: Position | None = self.portfolio_handler.get_position(...)  # ONCE, up front
    gate = self._enforce_direction_admission(signal_event, snap)
    gate = self._enforce_position_admission(signal_event, snap)
    resolved = self._resolve_signal_quantity(signal_event, snap)
```
**Caution:** the three current methods each independently null-check `self.portfolio_handler` before
calling `get_position()`. The single capture must preserve the "no read-model → fall through to the
sizing failure" semantics each method relies on (admission_manager:398-401, 478-481, 573-580). Thread
the **Position object** (each site reads existence / `net_quantity`), not a lightweight value.

### Pattern 3: RECON-01 extract-method with byte-identical control flow (D-06)

**What:** Extract the EXECUTED/CANCELLED/REFUSED arms into named helpers + `_classify(status) →
(terminal?, transition)` + `_release_reservation(order, should_release, body_raised)`. **Do NOT touch
the `try`/`finally` skeleton.**
**When to use:** RECON-01 — the clarity win.
**Example (target shape from CONTEXT specifics — note the `finally` stays):**
```python
# Source: CONTEXT.md D-06 specifics + reconcile_manager.py:86-234
def on_fill(self, fill_event):
    terminal, transition = self._classify(fill_event.status)
    try:
        # named per-status arm (_apply_executed / _apply_cancelled / _apply_refused)
        should_release = terminal
        # orphan-child cancel / fill-anchored children (unchanged)
    finally:
        self._release_reservation(order, should_release, body_raised)  # try/finally byte-identical
```
**Indentation: tabs** (`reconcile_manager.py` is a tab file).

### Recommended approach (not a folder change — this phase adds no new packages/dirs)

```
itrader/
├── core/sizing.py                         # + SignalIntent.entry_price, .order_type  (4 spaces)
├── strategy_handler/
│   ├── base.py                            # + buy_limit/buy_stop/sell_limit/sell_stop; - order_type attr  (TABS)
│   ├── signal_record.py                   # + order_type, entry_price audit fields  (4 spaces)
│   └── strategies_handler.py              # fan-out: read intent.order_type/entry_price  (TABS)
├── order_handler/
│   ├── order.py                           # Order.action: str -> Side  (TABS)
│   ├── order_validator.py                 # action string-literal sites -> Side  (TABS, only if touched -> W4-04 doc)
│   ├── admission/admission_manager.py     # snapshot threading  (TABS)
│   ├── brackets/bracket_book.py           # _PendingBracket.action: str -> Side  (TABS, 4-space? verify — it imports 4-space siblings)
│   ├── brackets/bracket_manager.py        # child-action 'BUY'/'SELL' literals -> Side  (TABS)
│   ├── brackets/levels.py                 # _bracket_levels action compare -> Side  (TABS)
│   └── reconcile/reconcile_manager.py     # on_fill clarity extract-method  (TABS)
scripts/crossval/
│   ├── <new>_limit_run.py (or extend)     # backtesting.py + backtrader LIMIT-entry runners  (4 spaces)
tests/
│   ├── e2e/... (new limit-entry leaf)     # crafted-strategy golden  (4 spaces)
│   └── golden/ or new evidence file       # owner-signed cross-val report
```

### Anti-Patterns to Avoid
- **State-machine rewrite of `on_fill` (D-06 rejected opt-2):** risks reintroducing the WR-04 bug (a
  sequential `apply(); release()` skips release on a raise) for a cosmetic dispatch win. The release-in-`finally`
  is irreducible.
- **Refetching the position in each gate (the current triple `get_position()`):** SIG-03 explicitly
  removes this; do not leave it.
- **Reading `self.order_type` in `buy()`/`sell()`:** the class attr is retired (D-01); plain factories
  hardcode `OrderType.MARKET`.
- **Adding entry-price admission validation (D-04 rejected):** no new validation in v1.3; a marketable
  limit/wrong-side stop accepts and fills at open by design (matches the cross-val oracles).
- **Re-baselining the existing 134/`46189.87730727451` golden:** SMAMACD stays MARKET-at-close;
  the existing oracle MUST stay byte-exact. Only the NEW limit-entry golden is owner-gated.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Limit/stop fill-price logic | A new matching path | `MatchingEngine._evaluate` (137-180) | ALREADY implements limit-or-better (`min`) + pessimistic stop (`max`); marketable-limit-at-open is already there. |
| Order-type dispatch from signal | A new branch in the handler | `admission_manager._build_primary_order` (337-362) | ALREADY dispatches MARKET/LIMIT/STOP on `signal.order_type`. |
| Cross-validation report/tables/reconcile | A bespoke comparison script | `scripts/cross_validate.py` + `scripts/crossval/reconcile.py` | ALREADY loads golden once, aligns trades, recomputes apples-to-apples metrics, emits committed evidence. |
| A crafted deterministic strategy fixture | A new strategy class | `tests/e2e/strategies/scripted_emitter.py` (`ScriptedEmitter`) | Date-keyed scripted BUY/SELL with sl/tp + `order_type=OrderType.LIMIT` — the EXACT D-07 template; its docstring even names the SIG-02 limitation. |
| Exception-safe reservation release | A try/except/release rewrite | The existing `try`/`finally` skeleton (reconcile_manager.py:122-233) | The release-once-on-terminal-even-if-body-raises invariant is already correct (WR-03/WR-04/T-05-17); only rename/extract around it. |
| `str` ↔ `Side` parsing | Manual `.upper()`/`== "BUY"` | `Side(value)` (has case-insensitive `_missing_`) | The `Side` enum already parses strings; SIG-03 narrows the type so this parsing moves to fewer boundaries. |

**Key insight:** This phase's risk is NOT building new machinery — it is touching the FRAGILE reconcile
path without drifting the byte-exact golden, and correctly enumerating the SIG-03 `Side` blast radius. The
machinery is done; the discipline is "confirm, narrow, refactor-in-place, cross-validate."

## Runtime State Inventory

> This is a code/test refactor with one NEW result-changing golden artifact. The "rename" risk here is the
> SIG-03 `str`→`Side` retype touching every site that reads `Order.action` / `_PendingBracket.action` as a
> string. The inventory below enumerates the non-obvious state that a grep-by-field-name alone could miss.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None on the backtest run path.** `SignalRecord`/order mirror use the in-memory backtest store (`order_handler/storage/in_memory_storage.py`); no persisted DB rows carry `action` as a string key. The new `SignalRecord.order_type`/`entry_price` fields are an in-memory schema add (oracle-dark). | Code edit only — no data migration. |
| Live service config | **None.** This phase touches backtest authoring/reconcile; no external service config embeds `action`. (Live PostgreSQL order storage is a `NotImplementedError` placeholder, out of scope.) | None. |
| OS-registered state | **None.** No OS-level registration carries `action`/`order_type`. | None. |
| Secrets/env vars | **None.** No secret/env var references `action` or `order_type`. | None. |
| Build artifacts | **None expected.** No package rename; `pyproject.toml` is untouched (no new deps). The egg-info worktree-shadowing hazard (see MEMORY) is about editable installs, not this phase's edits. | None — but run the full suite under the worktree `.venv` (prepend `PYTHONPATH="$PWD"` if pytest/mypy don't see edits — known worktree shadowing trap). |

**SIG-03 `str`→`Side` blast radius — string-literal action sites that MUST be converted (the real "renamed string" surface):**

| Site | Current (string) | Note |
|------|------------------|------|
| `order.py:49` | `action: str` (entity field) | The root retype → `action: Side`. |
| `order.py:95` | `Side(order.action)` at `to_event` boundary | After retype this re-parse is a no-op / removable (`OrderEvent.action` already `Side`). |
| `order.py:181`, `:214`, `:247` | `signal.action.value` / `action` param passed as str into factories | Factory `action:` params (`new_stop_order:199`, `new_limit_order:232`) retype `str`→`Side` (D-03 named sites). |
| `order_validator.py:193` | `if order.action not in ["BUY", "SELL"]` | String-literal membership check — **if touched, update W4-04 validator-overlap doc (D-03)**. |
| `order_validator.py:414-415` | `order.action == Side.SELL.value` / `== Side.BUY.value` | `.value` comparisons become `is Side.SELL` / `is Side.BUY`. |
| `admission_manager.py:205` | `primary.action == Side.BUY.value` | The reserve gate; becomes `primary.action is Side.BUY`. |
| `admission_manager.py:343`, `:354` | `action=signal_event.action.value` into limit/stop factories | Drop `.value` once factory params are `Side`. |
| `bracket_book.py:40` | `_PendingBracket.action: str` | The D-03 named retype → `Side`. |
| `bracket_manager.py:120,129,143,157` | `signal_event.action.value`; `'BUY' if ... is Side.SELL else 'SELL'` | Child-action string literals → `Side` members. |
| `bracket_manager.py:245` | `child_action = 'BUY' if pending.action == Side.SELL.value else 'SELL'` | Becomes `Side`-typed; depends on `_PendingBracket.action: Side`. |
| `levels.py:38` | `if action == Side.SELL.value` | `_bracket_levels` action compare → `is Side.SELL`. |

**Note:** `OrderEvent.action` (`events/order.py:47`) and `SignalEvent.action` (`signal.py:77`) are ALREADY
`Side`; the simulated exchange reads `event.action.value.lower()` (`simulated.py:207`) off the already-`Side`
`OrderEvent`, so the execution layer is unaffected by the `Order.action` retype. The boundary is entirely
inside `order_handler/`.

## Common Pitfalls

### Pitfall 1: Drifting the existing byte-exact golden while "improving" the MARKET path
**What goes wrong:** A refactor of `calculate_signals` or `SignalIntent` accidentally changes the MARKET
entry price away from `to_money(bar.close)`.
**Why it happens:** SIG-01/02 adds an `entry_price` field; a careless fan-out reads `intent.entry_price`
for MARKET too (it is `None` for plain `buy()`).
**How to avoid:** MARKET MUST keep `price = to_money(bar.close)` (D-02). Only LIMIT/STOP read
`intent.entry_price`. Gate on `intent.order_type`.
**Warning signs:** The integration oracle (`tests/integration/test_backtest_oracle.py`) drifts off
134 / `46189.87730727451`, or `tests/e2e -m e2e` 58/58 breaks. This is the canary — re-run it after every wave.

### Pitfall 2: The `tabs vs 4-spaces` indentation hazard across the touched files
**What goes wrong:** A mixed-indentation diff breaks a tab file (CLAUDE.md hard rule).
**Why it happens:** This phase straddles both: `core/sizing.py`, `signal_record.py`, and
`events_handler/events/` are **4 spaces**; `base.py`, `strategies_handler.py`, `order.py`,
`admission_manager.py`, `reconcile_manager.py`, `brackets/*` are **tabs**.
**How to avoid:** Match the file being edited; never normalize. Verify `bracket_book.py`'s actual
indentation before editing (it imports 4-space `core/sizing` siblings but lives under tab-indented
`order_handler/`).
**Warning signs:** `git diff` shows whitespace-only hunks; Python `TabError`/`IndentationError` at import.

### Pitfall 3: The cross-val engines' fill price diverging from iTrader on a gap
**What goes wrong:** The crafted strategy's LIMIT fill price differs by a few cents across engines,
flipping a borderline trade and breaking three-engine agreement.
**Why it happens:** If the crafted scenario relies on a marketable-limit gap, the three engines must all
apply the same "fill at the better of open vs limit" rule.
**How to avoid:** This is actually a NON-issue by construction: backtesting.py source computes buy-limit
fill as `min(stop_price or open, limit)` and buy-stop as `max(price, stop_price)` — *identical* to
iTrader's `min(open, trigger)` / `max(open, trigger)` (matching_engine.py:161-180). backtrader's bracket
entry Limit "fills at the specified limit price when conditions allow" with default next-bar-open fills.
Pin the crafted scenario so the marketable-limit case fills at OPEN on all three (the `min`/`max` rule
agrees). [VERIFIED: backtesting.py source `_process_orders`]
**Warning signs:** The new cross-val report shows a SHIFT/MISSING row on the entry trade, or a fill-price
metric divergence > 1%.

### Pitfall 4: The `should_release` flag semantics shifting under the RECON-01 extract
**What goes wrong:** Extracting `_release_reservation` accidentally moves where `should_release` is armed,
or changes the `body_raised` re-raise gate, causing a stuck reservation (T-05-17) or a masked original
exception (WR-03).
**Why it happens:** The flag is armed AFTER the terminal status is set and BEFORE further work (line 155),
and the inner release-failure re-raises ONLY when `not body_raised` (line 232). Both are load-bearing.
**How to avoid:** Keep the `try`/`finally` skeleton byte-identical (D-06). The extract is for the per-status
arms and the *contents* of the release helper — NOT the control-flow ordering. Verify the non-terminal
unknown-status early-return still leaves `should_release=False` (holds the reservation intentionally).
**Warning signs:** A reconcile unit/integration test that exercises a body-raise asserts the wrong
exception, or buying power leaks across the run.

### Pitfall 5: BUY-stop gap under-reservation (document, don't fix)
**What goes wrong:** A BUY stop sized/reserved at its trigger can gap-fill ABOVE the trigger
(`max(open, trigger)`), so the reservation slightly under-covers.
**Why it happens:** Sizing uses `signal_event.price` = the stop trigger (D-05); the actual fill on a gap
is higher.
**How to avoid:** This is ACCEPTED (D-05) as the same blessed class as a MARKET order sized on close but
filling next-bar-open higher. **Document the edge; do NOT add reservation logic.**
**Warning signs:** A reviewer flags "under-reservation" — point at D-05; it is a locked decision, not a bug.

## Code Examples

### backtesting.py limit/stop entry fill price (the three-engine-agreement anchor)
```python
# Source: github.com/kernc/backtesting.py/blob/master/backtesting/backtesting.py  _process_orders
# BUY (long) limit fill:
price = (min(stop_price or open, order.limit) if order.is_long
         else max(stop_price or open, order.limit))
# BUY stop fill (no limit):
price = max(price, stop_price) if order.is_long else min(price, stop_price)
# => buy-limit fills at min(open, limit) (fill at open if open gaps below limit — marketable);
#    buy-stop fills at max(open, stop). IDENTICAL to iTrader MatchingEngine._evaluate.
```

### iTrader matching engine — the same algebra (confirm-don't-rebuild)
```python
# Source: itrader/execution_handler/matching_engine.py:158-180
if order.order_type == OrderType.STOP:
    if order.action is Side.SELL:                 # stop-loss on a long
        if low <= trigger:  return min(open_, trigger)   # pessimistic gap-down
    else:                                         # BUY stop
        if high >= trigger: return max(open_, trigger)   # pessimistic gap-up
elif order.order_type == OrderType.LIMIT:
    if order.action is Side.SELL:                 # take-profit
        if open_ >= trigger: return open_                # gap-through: better open
        elif high >= trigger: return trigger             # in-bar touch: at limit
    else:                                         # BUY limit
        if open_ <= trigger: return open_                # gap-through: better open
        elif low <= trigger: return trigger              # in-bar touch: at limit
```

### backtrader LIMIT-entry bracket (the D-07 runner shape)
```python
# Source: backtrader.com/docu/order-creation-execution/bracket/bracket/
# buy_bracket: entry Limit + low-side Stop (SL) + high-side Limit (TP), OCO-linked.
self.buy_bracket(
    size=...,
    price=limit_entry_price,      # entry Limit trigger
    exectype=bt.Order.Limit,
    stopprice=sl_price,           # low-side Stop child
    limitprice=tp_price,          # high-side Limit child
)
# Children are inactive until the entry executes; execution/cancel of one child cancels the other.
# Default next-bar-open fills (do NOT enable cheat-on-open/close — matches the existing runner's D-01 knobs).
```

### ScriptedEmitter — the crafted-strategy template (already exists)
```python
# Source: tests/e2e/strategies/scripted_emitter.py + tests/e2e/matching/entries/limit_touch/scenario.py
# Date-keyed BUY/SELL with sl/tp; order_type currently per-INSTANCE (the SIG-02 limitation).
_SCRIPT = {"2020-01-02": {"side": "BUY", "sl": None, "tp": None},
           "2020-01-04": {"side": "SELL", "exit_fraction": Decimal("1")}}
ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT, order_type=OrderType.LIMIT)
# For D-07: a similar crafted strategy on the BTCUSD golden window emitting a buy_limit at close*0.98
# every N bars + percent SL/TP, plus one marketable-limit (price above market) bar.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `order_type` fixed per strategy INSTANCE (`ScriptedEmitter` Pitfall 3) | Per-intent `order_type` on `SignalIntent` | This phase (SIG-02) | A single strategy can now mix MARKET/LIMIT/STOP per signal. |
| `Order.action` / `_PendingBracket.action` as `str` (deferred from v1.2 06-01 / W2-02) | `Side`-typed | This phase (SIG-03) | mypy-checked side handling; removes `.value`/string-literal compares. |
| Triple `get_position()` in admission (W1-11) | One threaded `Position` snapshot | This phase (SIG-03) | Fewer read-model crossings; byte-exact under the single-writer contract. |
| `on_fill` as one ~150-line method | Same flow, extracted helpers + `_classify` | This phase (RECON-01) | Clarity only — `try`/`finally` bytes unchanged. |

**Deprecated/outdated:**
- `Strategy.order_type` class attribute (added by STRAT-01, `base.py:101`): RETIRED by D-01. `to_dict()`
  (`base.py:397`) drops `"order_type"`.
- The `Side(order.action)` re-parse at `order.py:95`: becomes a no-op once `Order.action` is `Side`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | backtrader's bracket Limit entry fills at the limit price (or open on a favorable gap) consistently with iTrader's `min(open,limit)`. backtrader docs confirm "Limit fills at the specified limit price when conditions allow" + default next-bar-open, but do NOT explicitly document the gap-through-fills-at-open case. | Code Examples / Pitfall 3 | If backtrader fills a marketable limit AT the limit (not the better open), the marketable-limit case diverges by the gap amount on that engine. MITIGATION: craft the marketable-limit bar so the gap is small/controlled, or root-cause+disposition per the existing cross-val D-05 discipline (the harness already supports LEGITIMATE-DIFFERENCE dispositions). |
| A2 | The new LIMIT-entry cross-val scenario can reuse `scripts/cross_validate.py` by adding a parallel LIMIT runner without disturbing the existing SMAMACD report. | Don't Hand-Roll / Standard Stack | If the orchestrator is too SMAMACD-specific, a small new orchestrator entry (still SCRIPT-ONLY, D-10) is needed — low risk, the reconcile helpers (`align_trades`/`build_metric_table`) are generic. |
| A3 | `bracket_book.py` uses tabs (it lives under tab-indented `order_handler/` but imports 4-space `core/sizing` siblings). | Architecture / Pitfall 2 | Editing with the wrong indentation breaks the file. MITIGATION: verify the file's actual indentation before the first edit (cheap). |
| A4 | No persisted/DB state carries `action` as a string key on the backtest path (in-memory store only). | Runtime State Inventory | If a golden artifact (`trades.csv`) serializes `action` as a string column, the column VALUE stays "LONG"/"BUY" text regardless of the in-memory type — verify the reporting serialization edge emits the same string after the `Side` retype (it reads `.value`/`.name` at the edge). |

## Open Questions

1. **Will the D-07 marketable-limit case agree on all three engines to the cent?**
   - What we know: backtesting.py source uses `min(open, limit)` (identical to iTrader). iTrader's
     `MatchingEngine` is the same.
   - What's unclear: backtrader's exact gap-through fill price for a Limit entry (A1).
   - Recommendation: design the marketable-limit bar with a controlled gap; if backtrader diverges,
     disposition it via the existing LEGITIMATE-DIFFERENCE machinery (the cross-val report already supports
     this) and surface it in the owner sign-off.

2. **Should the new LIMIT golden live under `tests/golden/` (a 2nd top-level oracle) or as a new
   `tests/e2e/matching/entries/` leaf?**
   - What we know: the existing e2e harness already has limit_touch/stop_gap leaves (pure-fill, hand-verified);
     `tests/golden/` holds the single SMAMACD oracle + cross-val evidence.
   - What's unclear: whether the owner wants the new cross-validated golden as a standalone
     `CROSS-VALIDATION-LIMIT.md` evidence artifact + frozen golden, or folded into an e2e leaf.
   - Recommendation: planner should treat this as a planning decision; the D-07 wording ("ONE owner-signed
     ... golden ... reuse the v1.0 cross-val harness") leans toward a `tests/golden/`-style evidence artifact
     + frozen golden, owner-signed like the existing `CROSS-VALIDATION.md`.

3. **Does the SIG-02 "Phase 8 per-bar `order_type` override left unwired in the e2e emitter" mean
   `ScriptedEmitter` should also gain per-bar `order_type` in its script?**
   - What we know: REQUIREMENTS SIG-02 explicitly names "the Phase 8 per-bar `order_type` override left
     unwired in the e2e emitter"; `ScriptedEmitter`'s docstring documents the per-INSTANCE limitation.
   - What's unclear: whether wiring per-bar `order_type` into the script is in-scope for THIS phase or only
     the `SignalIntent` carrier is.
   - Recommendation: the carrier (`SignalIntent.order_type` + factories) is the requirement; wiring
     `ScriptedEmitter`'s script to set per-bar `order_type` is a natural same-phase follow-on (it is the
     test fixture that proves SIG-02). Plan it as part of the SIG-02 verification surface.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 + Poetry `.venv` | All code/tests | ✓ | 3.13 | — |
| `backtesting` | D-07 cross-val (gating) | ✓ | 0.6.5 | — |
| `backtrader` | D-07 cross-val (gating) | ✓ | 1.9.78.123 | — |
| `nautilus-trader` | D-07 cross-val (non-gating) | ✓ | 1.227.0 | Degrade to "not reconciled" (D-12 try-guard, already in `cross_validate.py`). |
| BTCUSD golden CSV | D-07 scenario data | ✓ | `data/BTCUSD_1d_ohlcv_2018_2026.csv` | — |
| Owner (human) sign-off | D-07 golden freeze | ✗ (gate) | — | NONE — owner-gated; the new golden CANNOT freeze without explicit sign-off + full attribution. Plan a `checkpoint:human-verify`. |

**Missing dependencies with no fallback:**
- **Owner sign-off** is a hard gate (not a tool): Phases 5 cannot freeze the new golden without it. The
  plan must fully attribute the result (the new limit-entry numbers + cross-val verdict) BEFORE re-baseline.

**Missing dependencies with fallback:**
- nautilus-trader failure degrades gracefully (non-gating, already handled by the harness try-guard).

## Validation Architecture

> `workflow.nyquist_validation` not explicitly false (config has no such override observed) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov, pytest-html); `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`); `testpaths=["tests"]`; markers: `unit`, `integration`, `slow`, `e2e` |
| Quick run command | `poetry run pytest tests/unit/order tests/unit/strategy -x` (touched-domain fast loop) |
| Full suite command | `make test` (full suite, green required) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIG-01 | `buy_limit`/`sell_stop` etc. produce a `SignalIntent` with `entry_price`+`order_type`; threads to `Order.new_limit_order` | unit | `poetry run pytest tests/unit/strategy -k "factory or limit or stop" -x` | ❌ Wave 0 — new factory tests |
| SIG-01 | LIMIT/STOP entry fills on a LATER bar at the right price (limit-or-better / pessimistic stop) | e2e | `poetry run pytest tests/e2e -m e2e -k "limit or stop"` | ✅ existing `entries/limit_touch`, `stop_gap_up/down` leaves cover the matching; ❌ a strategy-driven (not ScriptedEmitter-instance) limit-entry leaf is Wave 0 |
| SIG-02 | Per-intent `order_type` (a single strategy mixes MARKET/LIMIT/STOP); MARKET stays `to_money(bar.close)` | unit + e2e | `poetry run pytest tests/unit/strategy tests/e2e -m e2e -k "order_type"` | ❌ Wave 0 — per-intent order_type test |
| SIG-03 | `Order.action`/`_PendingBracket.action` are `Side`; admission threads one snapshot | unit + mypy | `poetry run pytest tests/unit/order -x && poetry run mypy --strict` | ✅ existing order/admission unit tests; mypy is the type gate |
| SIG-03 | Byte-exact: existing oracle unchanged after the `Side` retype + snapshot threading | integration | `poetry run pytest tests/integration/test_backtest_oracle.py` (expect 134 / `46189.87730727451`) | ✅ exists |
| RECON-01 | `on_fill` idempotent release on EVERY terminal (EXECUTED/CANCELLED/REFUSED); release-on-body-raise; non-terminal holds reservation | unit | `poetry run pytest tests/unit/order -k "reconcile or fill or release" -x` | ✅/❌ — verify coverage of the body-raise + unknown-status branches exists; add Wave 0 if missing |
| D-07 | New LIMIT golden reproduces across backtesting.py + backtrader; owner-signed | manual + script | `poetry run python scripts/cross_validate.py` (or a new LIMIT orchestrator entry) | ❌ Wave 0 — new LIMIT runner(s) + evidence artifact |
| Determinism | Double-run byte-identical (both existing oracle and new golden) | integration | run twice, diff `trades.csv`/`equity.csv`/`summary.json` | ✅ pattern exists (run_backtest.py determinism) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/<touched-domain> -x` + `poetry run mypy --strict`.
- **Per wave merge:** `make test` (full suite) + `poetry run pytest tests/integration/test_backtest_oracle.py`
  (the byte-exact canary) + `tests/e2e -m e2e` (58/58).
- **Phase gate:** Full suite green; existing oracle byte-exact (134 / `46189.87730727451`); e2e 58/58;
  `mypy --strict` clean; determinism double-run identical; **NEW limit golden owner-signed +
  cross-validated** (backtesting.py + backtrader gating; nautilus non-gating).

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_*factory*.py` — `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop` produce the
      right `SignalIntent` (order_type, entry_price, sl/tp/exit_fraction); `buy()`/`sell()` stay MARKET-only.
- [ ] Per-intent `order_type` fan-out test — MARKET keeps `to_money(bar.close)`; LIMIT/STOP read `entry_price`.
- [ ] `SignalRecord` schema test — new `order_type`/`entry_price` fields captured (oracle-dark).
- [ ] Reconcile branch coverage — confirm a test exercises body-raise-still-releases (WR-04) and
      unknown-status-holds-reservation; add if absent (RECON-01 must not regress these).
- [ ] New cross-val LIMIT runner(s) under `scripts/crossval/` (backtesting.py + backtrader) + a crafted
      BTCUSD limit-entry strategy + the owner-signed evidence artifact (D-07).
- [ ] mypy is already the strict type gate (no install needed) — ensure the `Side` retype is mypy-clean.

## Sources

### Primary (HIGH confidence)
- iTrader source (read this session): `reconcile/reconcile_manager.py:86-234`,
  `admission/admission_manager.py`, `execution_handler/matching_engine.py:137-208`,
  `strategy_handler/base.py:90-108,380-489`, `core/sizing.py:180-247`,
  `strategy_handler/strategies_handler.py:100-172`, `events_handler/events/signal.py`,
  `events_handler/events/order.py:80-114`, `order_handler/order.py:40-262`,
  `order_handler/brackets/bracket_book.py:1-90`, `order_handler/brackets/bracket_manager.py` (grep),
  `order_handler/order_validator.py:185-199`, `strategy_handler/signal_record.py`,
  `tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/matching/entries/limit_touch/scenario.py`,
  `scripts/cross_validate.py`, `scripts/crossval/backtesting_py_run.py`, `scripts/crossval/backtrader_run.py`,
  `tests/golden/CROSS-VALIDATION.md`.
- backtesting.py source `_process_orders` (limit fill `min(open,limit)` / stop `max(open,stop)`):
  github.com/kernc/backtesting.py/blob/master/backtesting/backtesting.py
- backtrader bracket docs: backtrader.com/docu/order-creation-execution/bracket/bracket/
- Engine versions confirmed installed: `poetry run python -c "import backtesting, backtrader; ..."`
  → backtesting.py 0.6.5, backtrader 1.9.78.123.

### Secondary (MEDIUM confidence)
- backtesting.py order-fill discussion (next-bar fill / gap behavior): kernc.github.io API docs +
  GitHub discussions #989, #1015, #1127.
- backtrader order-creation/execution + buy_bracket signature: backtrader.com/docu/order-creation-execution/.

### Tertiary (LOW confidence)
- backtrader gap-through-fills-at-open for a Limit entry — not explicitly documented (A1; mitigated by the
  existing LEGITIMATE-DIFFERENCE disposition machinery).

## Project Constraints (from CLAUDE.md)

- **Money = Decimal end-to-end** via `to_money(x)`; NEVER `Decimal(float)`. `entry_price`/levels enter the
  Decimal domain only through `to_money` (the `Decimal(str(x))` string path).
- **Indentation:** tabs in `order_handler/`/`strategy_handler/` handler modules; **4 spaces** in `core/`
  (`sizing.py`), `events_handler/events/`, and storage-seam modules (`signal_record.py`). Match the file;
  never normalize (a mixed-indentation diff breaks a tab file).
- **Test strictness:** `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; only `unit`,
  `integration`, `slow`, `e2e` markers declared. Cross-val engine imports stay SCRIPT-ONLY (never under
  `tests/`) to avoid tripping `filterwarnings=["error"]`.
- **Determinism:** seeded `random.Random` (`performance.rng_seed`, default 42) + injected `BacktestClock`;
  runs reproducible; double-run byte-identical.
- **IDs:** single UUIDv7 via `idgen` (`uuid-utils`); no second scheme.
- **mypy `--strict`** over `itrader` is the only static gate — the SIG-03 `Side` retype must be mypy-clean.
- **Queue-only cross-domain writes:** handlers emit events; read-model seams (`PortfolioReadModel`) are the
  only cross-domain read path. The snapshot threading (D-03) reads through the injected read-model — keep it
  that way.
- **Worktree `.venv` shadowing (MEMORY):** an editable install can hide worktree edits from pytest/mypy —
  prepend `PYTHONPATH="$PWD"` when verifying if edits don't appear.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all engines pre-installed and version-confirmed.
- Architecture (already-wired machinery): HIGH — confirmed by direct source read + existing e2e leaves.
- SIG-03 blast radius: HIGH — every string-literal `action` site enumerated by grep.
- RECON-01 invariant: HIGH — full `reconcile_manager.py` read; the WR-03/WR-04/T-05-17 skeleton documented.
- Cross-val fill-price agreement: HIGH for backtesting.py (source-confirmed `min`/`max`); MEDIUM for
  backtrader gap-through (A1).
- Pitfalls: HIGH — grounded in CLAUDE.md hard rules + the existing cross-val LEGITIMATE-DIFFERENCE record.

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (stable — internal codebase + pinned engines; re-check only if engine versions
bump or the reconcile/admission modules move).
