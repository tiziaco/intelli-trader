---
status: open
created: "2026-07-28"
source: comment-reduction campaign (45 files, 2026-07-28) — defects surfaced while auditing comments against real code; flagged, never fixed (the campaign is comment-only, AST-verified)
tags: [live, okx, safety, halt-vocabulary, config-reachability, liquidation, encapsulation, dead-parameter, margin, dead-code, reconnect, false-green]
resolves_phase: ""
---

# Code defects surfaced by the comment-reduction campaign

**Origin:** The 2026-07-28 comment-reduction pass over 13 files. Every comment was checked
against the code it described; where the code turned out to be wrong rather than the comment,
it was **flagged and left alone** — that campaign changes no code (`verify.py` asserts the AST
is byte-identical to HEAD after every batch).

All items below were re-verified by grep at HEAD before being written down. Symbol names, not
line numbers — the campaign's single most common finding was decayed line coordinates.

## 1. `TradingRules.liquidation_fee_rate` is unreachable from production (worst of the set)

`SimulatedMarginAccount` prices the liquidation penalty off `instrument.liquidation_fee_rate`
(`portfolio_handler/account/simulated.py`). `Instrument.liquidation_fee_rate` defaults to
`Decimal("0")`. **No production builder ever sets it:**

- `universe/instruments.py::derive_instruments` — builds the field ladder
  (`maintenance_margin_rate`, `max_leverage`, `settles_funding`) and omits `liquidation_fee_rate`
- `execution_handler/exchanges/okx.py::resolve_precision` — omits it
- `universe/universe.py` default-ladder fallback — omits it

So `PortfolioConfig.trading_rules.liquidation_fee_rate` (a real, validated `ge=0` config field,
documented in `core/instrument.py` as the value `Instrument` falls back to) **never reaches an
`Instrument`.** Every production liquidation prices its penalty at zero regardless of config.

**Why the suite is green:** every test that exercises a non-zero rate hand-builds the
`Instrument` and bypasses the builders — `tests/e2e/levered_long_into_liquidation/` constructs
`Instrument(liquidation_fee_rate=_LIQUIDATION_FEE_RATE)` directly, and the unit tests
(`test_liquidation.py`, `test_liquidation_reconcile.py`) set the attribute on a stub. The
penalty maths is proven correct on a value production cannot produce. Textbook false-green:
tested and unreachable.

**Fix:** thread `TradingRules.liquidation_fee_rate` into `derive_instruments` (and decide what
the OKX/default-ladder arms should do), then add a test asserting a configured rate survives
into the built `Instrument` — i.e. cover the wiring, not just the arithmetic.
**Oracle risk:** the spot SMA_MACD oracle never liquidates, so this should be oracle-dark —
confirm before landing.

## 2. `deferred-protective-overflow` is an off-vocabulary halt reason

`SafetyController` defines `_DEFERRED_PROTECTIVE_OVERFLOW_REASON = "deferred-protective-overflow"`
and passes it straight to `self.halt()` from `gate_and_dispatch`. It is **not** a member of
`core/enums/system.py::HaltReason`, which claims in its own docstring: *"Exactly the reasons that
reach `halt()` … one member per live reason, no dead members."*

Either the enum is missing a member or the constant should be `HaltReason.…`.

**Directly continues [[off-vocabulary-halt-reason-baseline-residual-wr04]]** — same defect class
(`baseline-residual`), which that todo fixed for one string in P1 while deferring the
`halt(reason: str) → HaltReason` signature migration. This is a **new** off-vocabulary string
that appeared *after* that todo was written, which is the argument for finishing the migration
rather than patching strings one at a time: nothing structurally prevents the next one.

## 3. `gate_and_dispatch`'s `dispatch_fn` parameter is dead

`SafetyController.gate_and_dispatch` takes a `dispatch_fn` parameter that no caller passes.
`live_runner.py` holds `dispatch_gate=safety.gate_and_dispatch` and calls
`self._dispatch_gate(event)` with **one** argument; all nine test call sites pass the event only.
It always falls through to `self._dispatch_fn`. Dead parameter — delete it, or document why the
override exists.

## 4. `deferred_maxlen` is not operator-tunable

`SafetyController.__init__` takes `deferred_maxlen` (default 1000), but `build_live_system`
passes none and `SafetySettings` (`config/safety.py`, which holds only `throttle` and
`failure_rate`) has no field for it. The only override anywhere is in
`tests/unit/trading_system/test_safety_controller.py`. The deferred-protective-order queue bound
is therefore a hard-coded constant in production despite `SafetySettings` being its obvious home.
Note the overflow path **halts the engine** (item 2), so this bound has real operational weight.

## 5. Mixed key types in the OKX correlation index

`OkxExchange._submit_order` registers with the **raw** `response.get("id")`, while
`adopt_venue_correlation` and `_handle_order_update` both key on `str(venue_id)` (as does the
emitted `OrderAckEvent`). If ccxt ever yields a non-`str` `id`, a submitted order is indexed
under an `int` while the order-status stream looks it up as a `str` → **silent correlation miss
on the CANCELLED/EXPIRED reconcile path**.

Latent today (ccxt normalises `id` to `str`), but the file is internally inconsistent about it
and the failure is silent rather than loud. Fix: normalise once at the boundary.

## 6. `OkxExchange._active_symbols` is never pruned

Added to on every submit and every adopted rehydrated order; nothing removes a symbol on
terminalization; read by the per-resume missed-fill catch-up. The `__init__` prose correctly
says the *correlation index* state is bounded (release-on-terminal + dedup ring) — but
`_active_symbols` sits outside that and grows monotonically for the process lifetime, widening
the catch-up fan-out over a long live session. Over-inclusion is dedup-safe for *correctness*;
this is an unbounded-growth issue, not a correctness one.

## 7. `OkxExchange.unsubscribe` reaches into `StreamSupervisor` privates

The early-return guard reads `self._supervisor._streams_down` and
`self._supervisor._reconnect_attempts` directly. `StreamSupervisor`'s public surface is
`mark_down` / `mark_up` / `reset_budget` / `is_healthy` / `forget` — there is no membership
predicate, which is why the caller cracked the encapsulation. Behaviour is correct and covered
(`test_unsubscribe_stale_supervisor_state_without_task_still_marshals`); this is coupling only.
Fix: add `StreamSupervisor.tracks(stream_name) -> bool`.

## 8. Four dead assignments in `Portfolio`, two of them on the margin money path

Found in the `portfolio.py` pass. All four pass `mypy --strict` (an unused local is not an
error) and none is covered by a test, so nothing flags them.

The two that matter, both in `Portfolio._process_transaction_margin`:

- **`prior_entry_commission`** — assigned in *both* branches of the `if prior is not None`
  block, then never read. Its own comment says it exists "to avoid double-counting it on
  close", but the close arm computes that credit through
  `_open_commission_credit_for_close(position, closed_qty)` instead. Either it is a leftover
  from before that helper existed, **or the close arm is missing a term.**
- **`fraction`** — assigned in the close arm as `closed_qty / prior_qty`, then never read.
  The method docstring still describes settling `p × realized_PnL`, but `cash_delta` is built
  from `realised_increment + open_commission_credit` with **no `fraction` factor anywhere**.
  Either the docstring describes intended-but-absent behaviour, or the arithmetic is right and
  the docstring is stale.

Both sit on the margin cash-delta path. Resolve what each was meant to do before anyone trusts
that arithmetic — a dead variable whose *name* matches a term in the documented formula is the
signature of a half-applied refactor, not of harmless cruft.

The two harmless ones, in `Portfolio.set_state`: **`old_state`** is assigned and never read,
and the **`reason: str = ""`** parameter is never used in the body — not logged, not recorded
in `_state_transitions`. Every caller passes a reason string that goes nowhere.

## 9. `venue_accounts` is never populated — post-reconnect account refresh is a no-op (worst of the set)

Found in the 29-file sweep. **This is the same false-green shape as item 1, on the safety path.**

`build_live_system` (`trading_system/live_trading_system.py`) declares:

```python
venue_lifecycles: Dict[str, Any] = {}
venue_accounts: Dict[str, Any] = {}
```

with a comment stating *"Both maps are declared here so facade construction,
StreamRecoveryHandler and the halt-signal wiring see them on EVERY path."* The bring-up loop
then fills **only the first**:

```python
for row in venue_manager.read_enabled_for(exchange):
    record = venue_manager.bring_online(row)
    venue_lifecycles[str(row["account_id"])] = record.lifecycle
```

`venue_accounts` is written by **no code path in the repo** — grep finds exactly three
occurrences: the declaration, two comments, and the consumer
`venue_accounts=lambda: list(venue_accounts.values())`. That callable therefore always
returns `[]`.

**Consequence.** `StreamRecoveryHandler.on_reconnect` runs
`for account in _distinct(self._venue_accounts()): account.snapshot()` — a no-op in
production. After a venue stream drops and reconnects, the missed-fill catch-up still runs
(different path, through the exchange), but **the venue-cached account truth is never
re-snapshotted**, so balances/positions cached before the disconnect survive it silently.
`.snapshot()` has exactly three call sites; the other two (`venue_reconciler.py`,
`reconciliation_coordinator.py`) are boot-time reconcile, not reconnect-time. There is no
second path that covers this.

**Why the suite is green:** all eight call sites in
`tests/unit/trading_system/test_stream_recovery_handler.py` inject their own
`venue_accounts=lambda: [_FakeAccount(...)]`. The refresh logic is proven correct on a
collection production cannot produce — identical to item 1's hand-built `Instrument`.

**Fix:** populate `venue_accounts` in the `bring_online` loop (the account is reachable from
the record the loop already holds), then add a test that asserts the callable handed to
`StreamRecoveryHandler` is non-empty after a boot with at least one enabled venue row — i.e.
cover the wiring, not just the refresh.

## 10. Dead public surface and cross-collaborator private reaches

Eleven lower-severity defects from the same sweep, grouped by kind. All verified at HEAD.

**Dead code / unreachable:**

- `ExecutionHandler.get_exchange_health` — zero callers, zero tests, anywhere. Carries ~25
  lines of Parameters/Returns contract for a shape nothing consumes, and defaults
  `'connected': True` on `AttributeError` — an unknown health state reported as healthy.
  Harmless while dead; a safety defect the moment it acquires a caller.
- `OrderHandler.__init__` assigns `self.order_validator = EnhancedOrderValidator(portfolio_handler)`
  and nothing ever reads it. It is a **second** validator built *without* `enable_margin`,
  diverging from the one `OrderManager` builds. A future caller reaching for the facade's
  validator would silently get spot-mode full-notional cash checks.
- `core/enums/execution.py::ExecutionStatus` — entire enum unused outside its own definition
  and the barrel re-export. `ExecutionErrorCode.TIMEOUT` likewise, and the comment justifying
  it cites a nonexistent `ExecutionTimeoutError`.
- `venues/bundles.py` imports `DEFAULT_ACCOUNT_ID` at module scope; its only two occurrences
  were inside the (now-corrected) docstring prose. No linter is configured and
  `mypy --strict` does not flag unused imports, so nothing catches it.

**Cross-boundary private reaches** (behaviour correct, coupling only):

- `ReconcileManager.on_fill` → `self.bracket_manager._create_fill_anchored_children(...)`.
  `BracketManager` publishes no seam for this, so the module docstring's "injection, no
  sibling edges" claim is crossed through a private.
- `ReconciliationCoordinator._run_session_baseline_guard` →
  `self._portfolio_handler._drift_precision(symbol)`. Its only external caller. The
  dust-epsilon contract this safety guard depends on is unpublished and can be retuned with
  no compile-time signal — and `portfolio_handler` is typed `Any` there, so mypy sees nothing.

**Cosmetic:**

- `ExecutionHandler.update_config` / `validate_config` are byte-identical apart from the final
  delegate call, including a shared `'no paper exchange wired to update'` message that is wrong
  wording for the dry-validate path (`validate_config` applies nothing).
- `ErrorPolicy.on_handler_error` hardcodes `source='live_trading_system'`, but the policy now
  lives in `events_handler/error_policy.py` and is the dispatcher's generic seam — it is
  injected in replay wiring with no live facade present. The field is wire-visible
  (`ErrorHandler` logs it, `classify_failure` keys on `(source, operation)`), so changing it is
  a behaviour change, not a comment fix.
- `ReconciliationCoordinator.run_startup_reconcile` dedups accounts with a
  `List[int]` of `id(account)` and an `in` test — O(n²), and `id()` is a valid key only while
  every account stays alive. Safe as written; a set keyed on `account_id` would be neither.

## Suggested handling

Item 9 is the one to schedule first: it is a live safety-path no-op, it has a two-line fix,
and its test gap is the same false-green pattern as item 1 — which is the argument for
treating "does a production builder ever produce this value?" as a checklist question rather
than two separate bugs.

Item 8's first two are the only ones here that could mean wrong money; treat them as an
investigation, not a cleanup — decide what the close arm *should* compute, then either delete
the variables or restore the missing term. The `set_state` pair is a trivial tidy.

Items 2–4 are one coherent `SafetyController` cleanup and pair naturally with finishing
[[off-vocabulary-halt-reason-baseline-residual-wr04]]. Items 5–7 are one OKX-exchange cleanup.
Item 1 is independent, is the only one with a real behavioural consequence today, and should be
scoped on its own — it needs an oracle check and a decision about the OKX/default-ladder arms.

**Related:** [[comment-campaign-dead-symbol-citations]] (documentation defects from the same
campaign), [[comment-campaign-untested-safety-claims]] (test gaps from the same campaign).
