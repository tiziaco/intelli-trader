---
phase: quick-260623-gao
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tests/unit/portfolio/test_spot_oversell_guard.py
  - itrader/portfolio_handler/portfolio.py
  - tests/unit/order/test_reconcile_orphan_flatten.py
  - itrader/order_handler/reconcile/reconcile_manager.py
autonomous: true
requirements: [OVERSELL-A, OVERSELL-B]
tdd_mode: true

must_haves:
  truths:
    - "A spot LONG_ONLY portfolio holding 1 unit raises InvalidTransactionError when a SELL fill for 5 units settles (over-close fails loud, no silent corruption)"
    - "An exact full-close spot SELL (sell == held qty) still settles to flat without raising"
    - "A partial spot SELL (sell < held qty) still settles and keeps the position open"
    - "When an EXECUTED fill flattens a portfolio+ticker position, that portfolio+ticker's resting bracket children are cancelled (orphaned SL/TP removed)"
    - "Bracket children for OTHER tickers / OTHER portfolios are never cancelled by a flatten (scope precise)"
    - "The SMA_MACD spot oracle stays byte-exact: 134 trades / final_equity 46189.87730727451 (both guards are oracle-dark)"
  artifacts:
    - path: "itrader/portfolio_handler/portfolio.py"
      provides: "CR-02 over-close guard mirrored into _process_transaction_spot, before net_delta/funds/mutation/cash steps"
      contains: "is_increase"
    - path: "itrader/order_handler/reconcile/reconcile_manager.py"
      provides: "Orphaned-bracket cancel on flatten: EXECUTED fill that leaves position flat cancels resting bracket children for that portfolio+ticker"
      contains: "get_position"
    - path: "tests/unit/portfolio/test_spot_oversell_guard.py"
      provides: "Fix A regression test: spot over-close raises; exact/partial close still pass"
    - path: "tests/unit/order/test_reconcile_orphan_flatten.py"
      provides: "Fix B regression test: flatten-by-fill cancels this portfolio+ticker bracket children only"
  key_links:
    - from: "itrader/portfolio_handler/portfolio.py::_process_transaction_spot"
      to: "InvalidTransactionError"
      via: "if not is_increase and transaction.quantity > prior_qty: raise"
      pattern: "transaction\\.quantity > prior_qty"
    - from: "itrader/order_handler/reconcile/reconcile_manager.py::on_fill"
      to: "self._cancel_order"
      via: "portfolio_handler.get_position(...) is None -> cancel resting bracket children for portfolio+ticker"
      pattern: "get_position"
---

<objective>
Implement TWO engine guards for the spot LONG_ONLY over-sell / phantom-equity bug
(fully diagnosed in `.planning/debug/spot-long-only-oversell.md`):

- **Fix A — SPOT SETTLEMENT OVER-CLOSE GUARD:** mirror the existing CR-02 margin guard
  into the spot settlement path so a reducing SELL that exceeds held quantity fails
  loud (`InvalidTransactionError`) BEFORE any mutation, converting silent accounting
  corruption into a clean abort.
- **Fix B — ORPHANED-BRACKET CANCEL ON FLATTEN:** when an EXECUTED fill flattens a
  portfolio+ticker position, cancel that portfolio+ticker's resting bracket children
  (the SL/TP the matching engine's OCO only cancels for its own sibling), removing the
  seed channel that bypasses admission.

Purpose: make the over-sell impossible AND loud, while keeping the SMA_MACD spot oracle
byte-exact (both guards are expected oracle-dark: the golden strategy never over-sells
and declares no brackets).

Output: two new regression test files + two small, decision-anchored source edits.

OUT OF SCOPE (do NOT implement): Fix C (sign-aware net_quantity / market_value) — it is
owner-gated and result-changing. No changes to sizing/admission/matching beyond the
precise bracket-cancel seam for B.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<execution_env_critical>
This plan edits the INSTALLED `itrader/` package. pytest MUST see the edited source.

- Run on the MAIN checkout, OR prepend `PYTHONPATH="$PWD"` to every pytest call — the
  editable `.venv` install otherwise shadows in-tree edits (see MEMORY:
  worktree-venv-shadowing).
- Do NOT use `make test` (it aborts on a missing `.env` in some environments). Call
  `poetry run pytest ...` directly.
- `mypy` reads files directly and is unaffected by the shadowing.
- Strict pytest config (`pyproject.toml`): `filterwarnings = ["error", ...]`,
  `--strict-markers`, `--strict-config`. Only `unit`/`integration`/`slow`/`e2e` markers
  are declared; the type marker is folder-derived by `tests/conftest.py` (put unit tests
  under `tests/unit/...` — do NOT add an explicit marker). Any stray warning fails the suite.
- Money is Decimal end-to-end (never `Decimal(float)`; enter via `to_money`/`Decimal(str(x))`).
- Indentation: `itrader/portfolio_handler/` and `itrader/order_handler/` handler/manager
  modules use TABS. `portfolio.py` and `reconcile_manager.py` are both TAB files — match
  exactly, never normalize (a mixed-indentation diff breaks a tab file).
</execution_env_critical>

<context>
@.planning/debug/spot-long-only-oversell.md
@.planning/STATE.md
@itrader/portfolio_handler/portfolio.py
@itrader/order_handler/reconcile/reconcile_manager.py
@itrader/core/portfolio_read_model.py

<interfaces>
<!-- Contracts the executor needs — extracted from the codebase. No exploration required. -->

The margin guard to MIRROR (itrader/portfolio_handler/portfolio.py, _process_transaction_margin,
lines 367-404 — TAB indented):

  prior = self.position_manager.get_position(ticker)          # live Position | None
  prior_qty = abs(prior.net_quantity) if prior is not None else Decimal("0")
  # is_increase: a fill that moves in the position's OWN side
  if prior is None:
      is_increase = True
  else:
      is_increase = (
          (prior.side == PositionSide.LONG  and transaction.type == TransactionType.BUY)
          or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
      )
  # CR-02 over-close guard:
  if not is_increase and transaction.quantity > prior_qty:
      raise InvalidTransactionError(
          "Margin close fill exceeds open quantity (...)",
          {"closed": str(transaction.quantity), "open": str(prior_qty)},
      )

NOTE: `self.position_manager.get_position(ticker)` returns the LIVE `Position` (not the
read-model `PositionView`) inside the portfolio. `Position.net_quantity` = abs(buy-sell),
`Position.side` is `PositionSide`. `InvalidTransactionError`, `PositionSide`, `TransactionType`,
`Decimal` are ALL already imported in portfolio.py (lines 11, 24, 3). The spot method
`_process_transaction_spot(self, transaction)` is at lines 308-338; its first real step is
`net_delta = transaction.net_cash_delta` (line 319).

For Fix B — the reconcile seam (itrader/order_handler/reconcile/reconcile_manager.py):
  - on_fill(fill_event) -> List[OrderEvent]; the EXECUTED arm is reached at ~line 242,
    after `should_release = True` (line 259) and `self.order_storage.update_order(order)`
    (line 265). The existing WR-05 block (lines 266-282) cancels children of a PARENT that
    terminated WITHOUT a fill — a DIFFERENT case from Fix B (which is a flatten by a
    SEPARATE order's EXECUTED fill).
  - self.portfolio_handler is a PortfolioReadModel | None. Its
    get_position(portfolio_id, ticker) -> PositionView | None — returns None when FLAT.
  - self.order_storage.get_active_orders(portfolio_id) -> List[Order]; each Order has
    .ticker (str), .parent_order_id (OrderId | None), .child_order_ids (List[OrderId]),
    .id (OrderId), .portfolio_id (PortfolioId), .is_active() -> bool.
  - self._cancel_order(order_id, portfolio_id, reason=...) -> OperationResult; an
    OperationResult has .success (bool) and .order_events (List[OrderEvent]). The existing
    WR-05 block shows the exact call+collect idiom.
  - FillEvent carries .ticker (str), .portfolio_id (PortfolioId), .order_id (OrderId),
    .status (FillStatus), .quantity, .price, .time. FillStatus.EXECUTED is the flatten-by-fill case.

Test fakes already in tests/unit/order/test_reconcile_manager.py to MIRROR for Fix B:
  - _FakeOrder(id, portfolio_id) with .child_order_ids, .filled_quantity, add_fill/cancel/reject.
  - _FakeStorage(order) with get_order_by_id, update_order. (Extend with get_active_orders.)
  - _RecordingPortfolio with release(); (extend with get_position).
  - _FakeFill(status, order_id, portfolio_id); (extend with .ticker).
  - _make_manager(order, portfolio, storage) wires the ReconcileManager with cancel_order=Mock().

Test helpers in tests/unit/portfolio/test_portfolio.py to MIRROR for Fix A:
  - `portfolio` fixture: Portfolio(1, "test_pf", "simulated", 150000, datetime.now()) — SPOT
    (enable_margin defaults False).
  - Transaction(datetime.now(), TransactionType.BUY/SELL, "BTCUSDT", price, qty, commission,
    None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7()).
  - The CR-02 margin analog tests (test_portfolio.py:426-509) are the structural template:
    over-close raises; exact full-close and partial-close still pass.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix A regression test [RED] — spot over-close guard</name>
  <files>tests/unit/portfolio/test_spot_oversell_guard.py</files>
  <behavior>
    - test_spot_over_close_fill_fails_loud: a SPOT LONG_ONLY portfolio opens 1 unit
      (BUY 1 @ 89591), then a SELL 5 @ 89591 MUST raise InvalidTransactionError
      (this is the silent over-sell from the debug repro — RED today, GREEN after Task 2).
    - test_spot_exact_full_close_still_succeeds: BUY 1 then SELL 1 settles to flat
      (len(positions)==0, len(closed_positions)==1) without raising (non-regression).
    - test_spot_partial_close_still_succeeds: BUY 4 then SELL 1 keeps the position open
      with net_quantity == Decimal("3") (non-regression).
    - test_spot_scale_in_still_succeeds: BUY 1 then BUY 2 (same-side increase) does NOT
      raise and yields net_quantity == Decimal("3") (the guard only fires on reductions).
  </behavior>
  <action>
    Create the test mirroring the CR-02 margin analog tests at
    tests/unit/portfolio/test_portfolio.py:426-509 but for the SPOT path. Use a SPOT
    portfolio: `Portfolio(1, "spot_pf", "simulated", 150000, datetime.now())` (enable_margin
    defaults False). Build transactions with the same idiom as test_portfolio.py:
    `Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 89591, 1, 0, None,
    idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())`. Import
    InvalidTransactionError from itrader.core.exceptions (as test_portfolio.py does).
    Assert the over-close raises via `with pytest.raises(InvalidTransactionError):`.
    Use Decimal for quantity assertions (net_quantity is Decimal). File lives under
    tests/unit/portfolio/ so conftest auto-applies the `unit` marker — do NOT add an
    explicit marker. Adapt the mechanism from the scratchpad repro_oversell.py (BUY 1 →
    SELL 5) but do NOT import or depend on the scratchpad file at runtime.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/portfolio/test_spot_oversell_guard.py -x 2>&1 | tail -20</automated>
  </verify>
  <done>
    The file exists with 4 tests. test_spot_over_close_fill_fails_loud FAILS (RED — the
    guard does not exist yet, so SELL 5 settles silently and pytest.raises does not catch).
    The three non-regression tests PASS. Confirm RED is the over-close test specifically
    (not an import/collection error).
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Fix A implementation [GREEN] — port CR-02 guard into spot path</name>
  <files>itrader/portfolio_handler/portfolio.py</files>
  <action>
    In `_process_transaction_spot` (lines 308-338), BEFORE the existing first step
    `net_delta = transaction.net_cash_delta` (line 319), insert the over-close guard
    mirrored from `_process_transaction_margin` (lines 367-404), per OVERSELL-A / CR-02:

      ticker = transaction.ticker
      prior = self.position_manager.get_position(ticker)
      prior_qty = abs(prior.net_quantity) if prior is not None else Decimal("0")
      if prior is None:
          is_increase = True
      else:
          is_increase = (
              (prior.side == PositionSide.LONG and transaction.type == TransactionType.BUY)
              or (prior.side == PositionSide.SHORT and transaction.type == TransactionType.SELL)
          )
      if not is_increase and transaction.quantity > prior_qty:
          raise InvalidTransactionError(...)

    Use TAB indentation (portfolio.py is a TAB file — match the margin method exactly).
    Add a decision-anchored comment in the established style citing CR-02 and this debug
    session (.planning/debug/spot-long-only-oversell.md): note that the spot path is the
    documented "byte-exact site #2" and the guard is DARK on the SMA_MACD golden path
    (which never over-sells — exits are clamped to net_quantity), so the oracle stays
    byte-exact. InvalidTransactionError / PositionSide / TransactionType / Decimal are all
    already imported (lines 11, 24, 3) — do NOT add imports. The guard MUST run BEFORE the
    net_delta/funds-invariant/position-mutation/cash-apply steps (fail loud before any mutation),
    exactly as the margin guard runs before its mutation. Do NOT introduce a clamp — match the
    margin path's fail-fast semantics (raise, never silently truncate). Do NOT touch
    net_quantity / market_value / avg_price (that is owner-gated Fix C, out of scope).
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/portfolio/test_spot_oversell_guard.py tests/unit/portfolio/test_portfolio.py -x 2>&1 | tail -20</automated>
  </verify>
  <done>
    All 4 tests in test_spot_oversell_guard.py PASS (over-close now GREEN). The full
    test_portfolio.py suite (including the CR-02 margin analogs) still passes — the spot guard
    did not regress the margin path or any existing spot settlement test.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Fix B regression test [RED] — cancel orphaned bracket children on flatten</name>
  <files>tests/unit/order/test_reconcile_orphan_flatten.py</files>
  <behavior>
    - test_flatten_by_fill_cancels_resting_bracket_children: an EXECUTED fill on a
      discretionary SELL order for (portfolio P, ticker BTCUSDT) where the portfolio
      read-model reports get_position(P, "BTCUSDT") is None (now FLAT) MUST trigger a
      _cancel_order call for each resting bracket child (active orders with a non-None
      parent_order_id) of that portfolio+ticker. Returned CANCEL order_events are collected
      into on_fill's return list. RED today (no flatten-cancel logic exists), GREEN after Task 4.
    - test_flatten_does_not_cancel_other_ticker_children: a resting bracket child for a
      DIFFERENT ticker (ETHUSDT) in the same portfolio is NOT cancelled (scope precise).
    - test_flatten_does_not_cancel_when_position_still_open: an EXECUTED fill where
      get_position(...) returns a non-None PositionView (still open / partial) cancels
      NOTHING.
    - test_non_executed_fill_does_not_trigger_flatten_cancel: a CANCELLED/REFUSED fill
      does NOT invoke the new flatten-cancel path (it is the existing WR-05 case, kept distinct).
  </behavior>
  <action>
    Mirror the fakes in tests/unit/order/test_reconcile_manager.py. EXTEND them:
    - _FakeFill gains a `ticker` attribute (e.g. "BTCUSDT").
    - the portfolio read-model fake gains `get_position(self, portfolio_id, ticker)`
      returning None (flat) or a PositionView (open) per the test. Import PositionView from
      itrader.core.portfolio_read_model and PositionSide from itrader.core.enums when an open
      view is needed.
    - the storage fake gains `get_active_orders(self, portfolio_id)` returning a list of fake
      resting child orders (objects with .id, .portfolio_id, .ticker, .parent_order_id set to a
      non-None parent id, .child_order_ids, .filled_quantity, is_active()->True). Include one
      BTCUSDT child, one ETHUSDT child, and a NON-bracket order (parent_order_id=None) to prove
      scope.
    - cancel_order is a Mock; assert it was called with the BTCUSDT child id(s) and NOT the
      ETHUSDT child id nor the non-bracket order. Make the Mock return an object with
      .success=True and .order_events=[] (or a sentinel) so on_fill's collect step runs cleanly.
    File lives under tests/unit/order/ → conftest auto-applies the `unit` marker (no explicit
    marker). Keep money Decimal. No stray warnings (filterwarnings=error).
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_reconcile_orphan_flatten.py -x 2>&1 | tail -25</automated>
  </verify>
  <done>
    The file exists with 4 tests. test_flatten_by_fill_cancels_resting_bracket_children FAILS
    (RED — no flatten-cancel logic yet, so cancel_order is never called for the orphaned child).
    The scope/negative tests are written and the RED is specifically the missing-cancel assertion
    (not an import/collection error).
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Fix B implementation [GREEN] — flatten-cancel in ReconcileManager.on_fill</name>
  <files>itrader/order_handler/reconcile/reconcile_manager.py</files>
  <action>
    In `ReconcileManager.on_fill`, in the EXECUTED-fill path AFTER the mirror update
    (`self.order_storage.update_order(order)` ~line 265) and the existing WR-05 /
    PercentFromFill blocks, add an orphaned-bracket-cancel-on-flatten step (OVERSELL-B):

    Only when `fill_event.status == FillStatus.EXECUTED` and `self.portfolio_handler is not None`:
      - read `self.portfolio_handler.get_position(fill_event.portfolio_id, fill_event.ticker)`;
      - if it is None (the position is now FLAT — the fill closed it), find this portfolio+ticker's
        resting bracket children: iterate `self.order_storage.get_active_orders(fill_event.portfolio_id)`,
        select orders where `o.ticker == fill_event.ticker` AND `o.parent_order_id is not None`
        AND `o.id != order.id` (never the just-filled order itself);
      - for each, call `self._cancel_order(child.id, fill_event.portfolio_id,
        reason=f"position {fill_event.ticker} flattened by fill {order.id}")`, and if
        `child_result.success and child_result.order_events` extend `out_events` with them
        (mirror the existing WR-05 collect idiom at lines 274-282).

    Scope the cancel PRECISELY to (fill_event.portfolio_id, fill_event.ticker) — NEVER cancel
    unrelated resting orders (other tickers, other portfolios, or non-bracket orders with
    parent_order_id is None). RESPECT the queue-only / read-model architecture: this stays in the
    ORDER domain, reads the portfolio only through the injected `portfolio_handler` read-model, and
    cancels only through the injected `_cancel_order` coordinator callback — the portfolio NEVER
    reaches across domains (D-04 star / D-08). Use TAB indentation (reconcile_manager.py is a TAB
    file). Add a decision-anchored docstring/comment in the established style citing OVERSELL-B and
    the debug session, noting this is the SEED fix (an orphaned SL/TP child surviving a discretionary
    flatten), distinct from the WR-05 parent-terminal-without-fill case, and that it is oracle-dark
    (SMA_MACD declares no brackets). Update the `on_fill` Returns docstring to mention flatten-cancel
    CANCEL events join the returned list. Do NOT change the WR-04 should_release/finally skeleton or
    the existing WR-05 block. Keep money Decimal.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_reconcile_orphan_flatten.py tests/unit/order/test_reconcile_manager.py -x 2>&1 | tail -25</automated>
  </verify>
  <done>
    All 4 tests in test_reconcile_orphan_flatten.py PASS (flatten-cancel now GREEN, scope precise,
    non-EXECUTED and still-open cases cancel nothing). The full test_reconcile_manager.py suite still
    passes (the existing WR-05 / release / fill-anchored-children behavior did not regress).
  </done>
</task>

<task type="auto">
  <name>Task 5: Full-suite + oracle + mypy verification gate</name>
  <files>(verification only — no source edits)</files>
  <action>
    Run the full verification gate. ALL must be green and the oracle MUST stay byte-exact.
    If the oracle drifts AT ALL: STOP — do NOT proceed or patch. Both guards are designed
    oracle-dark (SMA_MACD never over-sells and declares no brackets); any drift means a real
    problem and is an owner-gated, result-changing decision to surface to the developer (per the
    constraints and the milestone gate in .planning/STATE.md). Do not attempt to make the oracle
    pass by changing its baseline.
  </action>
  <verify>
    <automated>cd "$PWD" && PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py 2>&1 | tail -15 && echo "--- E2E ---" && PYTHONPATH="$PWD" poetry run pytest tests/e2e -m e2e 2>&1 | tail -8 && echo "--- FULL SUITE ---" && PYTHONPATH="$PWD" poetry run pytest tests 2>&1 | tail -12 && echo "--- MYPY ---" && poetry run mypy itrader 2>&1 | tail -8</automated>
  </verify>
  <done>
    - tests/integration/test_backtest_oracle.py passes byte-exact: 134 trades /
      final_equity 46189.87730727451 (NO drift).
    - tests/e2e -m e2e passes green.
    - Full suite `poetry run pytest tests` passes green (no failures, no stray-warning errors
      under filterwarnings=error).
    - `poetry run mypy itrader` is clean under --strict.
    If the oracle drifts, the task STOPS and the SUMMARY records it as an owner-gated
    result-changing finding rather than a completion.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| exchange fill → Portfolio.process_transaction | A resting bracket child fill bypasses order-domain admission and settles directly; untrusted (over-sized) quantity crosses here |
| exchange fill → ReconcileManager.on_fill | The order domain learns a position flattened only via the fill; the cancel decision crosses the read-model boundary |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-gao-01 | Tampering | _process_transaction_spot (silent over-close corrupts position/cash accounting) | mitigate | Fix A: fail-loud CR-02 over-close guard BEFORE mutation (Task 2); regression-locked by Task 1 |
| T-gao-02 | Tampering | orphaned resting SL/TP child fills against a flat portfolio (seed channel) | mitigate | Fix B: cancel this portfolio+ticker bracket children on flatten (Task 4); regression-locked by Task 3 |
| T-gao-03 | Repudiation | over-cancel of unrelated resting orders (scope creep) | mitigate | Fix B scope strictly (fill_event.portfolio_id, fill_event.ticker, parent_order_id is not None); negative-scope tests in Task 3 |
| T-gao-04 | Denial of Service | a guard mis-fire / oracle drift aborts the golden run | accept (verified) | Both guards designed oracle-dark; Task 5 verifies 134/46189.87730727451 byte-exact and STOPS on any drift (owner-gated) |
</threat_model>

<verification>
Encoded as Task 5. The gate:
1. Fix-A and Fix-B regression tests RED before, GREEN after (Tasks 1-4).
2. Oracle byte-exact: `tests/integration/test_backtest_oracle.py` → 134 trades / final_equity 46189.87730727451.
3. `tests/e2e -m e2e` green; full `tests` suite green (no failures, no filterwarnings=error tripwires).
4. `mypy itrader` clean under --strict.
5. Oracle drift ⇒ STOP, surface as owner-gated result-changing decision (do not re-baseline).
</verification>

<success_criteria>
- Spot LONG_ONLY over-close raises InvalidTransactionError before any mutation; exact/partial/scale-in
  spot settlements unchanged.
- A flatten-by-fill cancels exactly that portfolio+ticker's resting bracket children, nothing else.
- SMA_MACD spot oracle byte-exact (134 / 46189.87730727451); e2e + full suite green; mypy --strict clean.
- No source change to net_quantity / market_value / avg_price (Fix C remains out of scope).
- All edits respect TAB indentation, Decimal money, queue-only / read-model architecture.
</success_criteria>

<output>
Create `.planning/quick/260623-gao-engine-over-sell-protection-a-b-spot-set/260623-gao-SUMMARY.md` when done.
</output>
