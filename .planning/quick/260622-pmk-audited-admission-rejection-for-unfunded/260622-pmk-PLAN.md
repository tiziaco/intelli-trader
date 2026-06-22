---
phase: quick-260622-pmk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/order_handler/admission/admission_manager.py
  - tests/unit/order/test_admission_rules.py
autonomous: true
requirements: [WR-03]
must_haves:
  truths:
    - "An unfunded short increase (admitted SELL-add whose post-add margin lock exceeds available buying power) produces exactly ONE audited REJECTED order at admission, mirroring the long arm — NOT a settlement-time InvalidTransactionError that fail-fast aborts the backtest run."
    - "The audited short-increase rejection uses the SAME rejection path the long arm uses (triggered_by=OrderTriggerSource.CASH_RESERVATION via _reject_unsized_signal), with PENDING→REJECTED, persisted to storage, nothing emitted, queue empty."
    - "A FUNDED short increase remains byte-identical to today: admitted, sized through resolve_entry, settles through the side-agnostic SCALE-IN branch — both frozen short-scale-in e2e leaves stay green and unchanged."
    - "The SELL-add still books NO admission-side cash reservation (a SELL credits cash — D-06 reality at admission_manager.py:264 is unchanged); the new gate is a SOLVENCY CHECK emitting an audited rejection, never a reserve."
    - "The long arm (BUY check-and-reserve gate, lines 264-301) and the direction/max_positions gates are byte-exact — no line altered; SMA_MACD spot oracle stays byte-exact 134 / 46189.87730727451."
  artifacts:
    - path: "itrader/order_handler/admission/admission_manager.py"
      provides: "Admission-side margin solvency check for the admitted short SELL-add, emitting an audited CASH_RESERVATION rejection when the prospective post-add aggregate margin lock exceeds available buying power"
      contains: "PositionSide.SHORT"
    - path: "tests/unit/order/test_admission_rules.py"
      provides: "Regression test proving an unfunded short increase yields one audited REJECTED entity, empty queue, unchanged free cash — mirroring test_over_margin_order_is_rejected_via_audited_path; plus a funded-short-increase non-regression assertion"
      contains: "def test_unfunded_short_increase_is_rejected_via_audited_path"
  key_links:
    - from: "itrader/order_handler/admission/admission_manager.py (short SELL-add solvency gate)"
      to: "OrderTriggerSource.CASH_RESERVATION audited rejection"
      via: "_reject_unsized_signal with triggered_by=OrderTriggerSource.CASH_RESERVATION"
      pattern: "_reject_unsized_signal"
    - from: "the new gate"
      to: "available buying power"
      via: "portfolio_handler.available_cash + prospective aggregate margin = (existing short notional + add notional) / effective_leverage"
      pattern: "available_cash"
---

<objective>
Close P05.1 WR-03: make an UNFUNDED short increase produce a clean, AUDITED REJECTED
order at admission — exactly like the long-increase arm — instead of being admitted and
then aborting the whole backtest run at settlement (`assert_lock_fits_buying_power` →
`InvalidTransactionError` → fail-fast `_on_handler_error` re-raise).

The long arm: when a BUY can't be funded, the check-and-reserve gate
(`admission_manager.py:264-301`) catches `InsufficientFundsError`, transitions the order
PENDING→REJECTED with `triggered_by=OrderTriggerSource.CASH_RESERVATION`, stores the
audited entity, returns a failure result, emits nothing — the run CONTINUES.

The admitted short increase (SELL-add against an open SHORT with `allow_increase=True`)
is exempt from that BUY-only reserve gate (a SELL credits cash — D-06). So an unfundable
short add is caught only at SETTLEMENT, which aborts the backtest. This plan adds a
SYMMETRIC admission-side SOLVENCY CHECK for the admitted short add: verify the prospective
post-add margin lock fits available buying power; if NOT, emit an audited
`CASH_RESERVATION` rejection (no reservation booked, no event emitted) so the run continues.

Purpose: symmetric, audited failure mode for unfunded short scale-ins; no run-aborting
exception; funded path byte-identical.
Output: one focused production hunk in `admission_manager.py` + a mirror regression test.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/05.1-short-position-scale-in-margin-increase/05.1-REVIEW.md

# THE file to change — study the BUY check-and-reserve gate (the long arm to mirror)
# at lines 264-301, and the short SELL-add fall-through branch at lines 551-567.
@itrader/order_handler/admission/admission_manager.py

# The long-arm rejection test to MIRROR + the funded short-increase admit test to NOT regress.
@tests/unit/order/test_admission_rules.py

<interfaces>
<!-- Key contracts the executor needs — extracted from the codebase. Use directly. -->

PortfolioReadModel (itrader/core/portfolio_read_model.py), available on self.portfolio_handler:
  - available_cash(portfolio_id: PortfolioId) -> Decimal   # buying power (balance − reserved − locked)
  - get_position(portfolio_id, ticker) -> PositionView | None
  - reserve / release / exchange_for / open_position_count / total_equity / maintenance_margin / margin_ratio

PositionView (frozen, slots): ticker:str, side:PositionSide, net_quantity:Decimal (UNSIGNED magnitude), avg_price:Decimal

AdmissionManager helpers already present (admission_manager.py):
  - _effective_leverage(signal_event) -> Decimal   # Decimal("1") when enable_margin off / no universe; floored at 1
  - _estimate_commission(order) -> Decimal          # to_money-normalized; Decimal("0") when no estimator
  - _reject_unsized_signal(signal_event, reason, *, triggered_by, operation_type, error_prefix) -> OperationResult
        # builds the primary Order UNSIZED (qty 0), PENDING→REJECTED via add_state_change, persists, returns failure_result

Enums: OrderTriggerSource.CASH_RESERVATION, OrderOperationType.CASH_RESERVATION, Side.SELL, PositionSide.SHORT
Money: to_money(x) -> Decimal(str(x)); NEVER Decimal(float). Carry full precision; quantize only at money boundaries.

Settlement-side guard this mirrors (portfolio.py:439 / cash_manager.py:449
assert_lock_fits_buying_power): buying_power = available_balance + own_prior_lock;
the new short add re-locks to NEW aggregate_notional / L, releasing the position's OWN
prior lock first — so the admission-side headroom MUST credit back the existing short's
own prior lock too (otherwise the gate double-counts the prior lock and over-rejects a
fundable add).
</interfaces>

<reference_decisions>
- D-06 (admission-gate reality, LOCKED, DO NOT CHANGE): a SELL credits cash, so the
  check-and-reserve gate at admission_manager.py:264 reserves ONLY for `primary.action is
  Side.BUY`. The short SELL-add books NOTHING on the reserve side. This plan adds a
  solvency CHECK that emits an audited rejection on failure — it is NOT a reservation.
- WR-01 (settlement-side guard this mirrors): cash_manager.assert_lock_fits_buying_power
  credits back the position's OWN prior lock (a scale-in replaces its own lock). The
  admission-side headroom computation MUST do the same: available buying power for the
  prospective NEW lock = available_cash + own_prior_lock_being_released.
- Reuse OrderTriggerSource.CASH_RESERVATION (the long-arm trigger) — NO new
  OrderTriggerSource, NO new FillStatus.
</reference_decisions>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Write the unfunded short-increase regression test (RED) mirroring the long arm</name>
  <files>tests/unit/order/test_admission_rules.py</files>
  <behavior>
    - test_unfunded_short_increase_is_rejected_via_audited_path:
      * Enable margin via the existing _enable_margin(harness, max_leverage) helper (it sets
        am._enable_margin=True, am._portfolio_max_leverage, order_validator.enable_margin=True,
        and a Universe with the instrument cap).
      * Open a SHORT via harness.open_short(quantity=N, price=...) sized so the FIRST short's
        margin lock is fundable, but a SECOND same-side SELL-add (allow_increase=True,
        FractionOfCash(0.95) on remaining cash, or an explicit quantity) would push the
        prospective post-add aggregate margin lock ABOVE available buying power. Choose a
        max_leverage low enough (e.g. Decimal("2")) and quantities such that
        (existing_short_notional + add_notional) / L > available_cash + own_prior_lock.
        NOTE: the harness signal factory carries FractionOfCash(0.95); to make the add
        deterministically unfundable prefer an EXPLICIT large quantity on the SELL-add
        signal (explicit quantity skips the admission position gate but MUST still hit the
        new post-sizing solvency check — see Task 2 for placement so explicit-quantity
        short adds are also covered).
      * Record available_cash BEFORE emitting the SELL-add signal.
      * Submit the unfunded SELL-add (direction=LONG_SHORT or SHORT_ONLY, allow_increase=True).
      * Assert: harness.queue.empty() (nothing emitted).
      * Assert: exactly ONE REJECTED order for the ticker (filter via _get_single_rejection
        OR the get_orders_by_ticker REJECTED filter used by the over-margin test); the prior
        FILLED open-short order is excluded from the count.
      * Assert: last_change.from_status == OrderStatus.PENDING, to_status == OrderStatus.REJECTED,
        triggered_by is OrderTriggerSource.CASH_RESERVATION (same as the long arm
        test_over_margin_order_is_rejected_via_audited_path).
      * Assert: available_cash AFTER == available_cash BEFORE (no reservation booked — free
        cash / buying power UNCHANGED).
    - test_funded_short_increase_still_admits (non-regression):
      * Same margin setup but with a fundable second SELL-add (small quantity / ample leverage):
        assert the SELL-add IS emitted (queue.get returns a Side.SELL OrderEvent with qty>0) —
        proving the new gate does NOT over-reject a funded scale-in. (This may overlap the
        existing test_allow_increase_true_sizes_short_increase_on_remaining_cash_and_reserves
        which runs margin-OFF; the NEW test exercises the margin-ON funded path explicitly.)
  </behavior>
  <action>Add both tests to tests/unit/order/test_admission_rules.py near the existing short
scale-in tests (after test_allow_increase_true_sizes_short_increase_on_remaining_cash_and_reserves).
Reuse the existing _AdmissionHarness, _enable_margin(harness, max_leverage), open_short, and the
_get_single_rejection / REJECTED-filter helpers. Mirror test_over_margin_order_is_rejected_via_audited_path
exactly for the rejection assertions (triggered_by CASH_RESERVATION, available_cash unchanged, queue
empty, one REJECTED entity). 4-SPACE indentation (this is a test file — spaces, per CLAUDE.md). Decimal
end-to-end: str(x)==str(expected) for any computed quantity; == only for identity (unchanged available_cash).
Run RED first: the unfunded test MUST currently FAIL by raising InvalidTransactionError at settlement
(the fail-fast abort the fix replaces) OR by admitting+emitting — confirm the RED reason is the current
buggy behavior before writing Task 2.</action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_admission_rules.py -k "unfunded_short_increase or funded_short_increase" -q 2>&1 | tail -20</automated>
  </verify>
  <done>Both new tests exist and are collected; the unfunded test FAILS RED on the current
code (settlement-side InvalidTransactionError abort or an admitted+emitted order), confirming
the bug is reproduced before the fix.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add the admission-side short-add margin solvency check (GREEN)</name>
  <files>itrader/order_handler/admission/admission_manager.py</files>
  <action>
Add a SYMMETRIC admission-side margin solvency check for the admitted short SELL-add, mirroring
the long arm's BUY check-and-reserve gate (lines 264-301) WITHOUT booking a reservation.

PLACEMENT (critical): the check must run AFTER sizing resolves (so the add notional = resolved
quantity × price is known) and BEFORE bracket assembly/emit — the same window as the long
check-and-reserve gate at lines 264-301. Add it as a sibling branch in that gate region (inside
process_signal, after validation at step 3, alongside the `primary.action is Side.BUY` reserve
block). This placement also covers explicit-quantity short adds (the position admission gate is
skipped for explicit quantity, but this post-sizing solvency check still runs).

THE CHECK (Decimal end-to-end, match TABS in this file):
  - Guard: only run when self.portfolio_handler is not None AND primary.action is Side.SELL AND
    there is an OPEN SHORT for the ticker (re-read snap or get_position; an open short for the
    portfolio_id/ticker with side PositionSide.SHORT). A SELL with no open short (first short
    entry) or a SELL-on-long (exit) is NOT a short increase — skip the check (those paths are
    unchanged and must stay byte-exact). DO NOT run this for BUYs (the long arm already owns them).
  - Compute the prospective post-add aggregate margin lock:
      effective_leverage = self._effective_leverage(signal_event)   # Decimal("1") on the spot/no-margin arm
      existing_notional   = open_short.net_quantity * open_short.avg_price   # PositionView magnitude × avg
      add_notional        = primary.price * primary.quantity
      prospective_lock    = (existing_notional + add_notional) / effective_leverage
    Use a real if-branch on self._enable_margin for the division (Pitfall 4: never route the spot
    arm through `/ 1` — Decimal division is context-sensitive and a /1 can shift the exponent;
    when enable_margin is off the short-increase path is oracle-dark, but keep the spot arm
    division-free for safety and parity with the existing reserve-gate branch at lines 277-281).
  - Compute available buying power, CREDITING BACK the existing short's OWN prior lock (mirroring
    cash_manager.assert_lock_fits_buying_power / WR-01): the settlement re-lock RELEASES this
    position's prior lock then re-locks the new aggregate, so the admission headroom must add the
    existing short's own prior locked margin back to available_cash. Read available_cash via the
    read-model; obtain the existing position's prior lock through the read boundary. If the
    read-model does not expose per-position locked margin on the narrow Protocol, compute the
    existing short's own prior lock as existing_notional / effective_leverage (it equals the lock
    the settlement path holds today: aggregate_notional / L) — this is the value cash_manager
    credits back. Prefer this derived value to avoid widening the PortfolioReadModel Protocol.
      buying_power = self.portfolio_handler.available_cash(portfolio_id) + existing_own_prior_lock
  - If prospective_lock > buying_power → emit an audited rejection via _reject_unsized_signal
    with triggered_by=OrderTriggerSource.CASH_RESERVATION,
    operation_type=OrderOperationType.CASH_RESERVATION, a reason naming the insufficient margin
    (e.g. f"insufficient margin for short increase: required {prospective_lock} > buying power
    {buying_power} for {ticker}"), error_prefix consistent with the long-arm style. Return that
    failure result (do NOT emit, do NOT reserve). NOTE: _reject_unsized_signal builds its own
    UNSIZED audit entity and persists it — this yields exactly ONE audited REJECTED order, queue
    untouched, available_cash unchanged (no reserve booked). Do not also store `primary`.
  - If prospective_lock <= buying_power → fall through unchanged (funded path byte-identical:
    the add proceeds to bracket assembly/emit and settles through the SCALE-IN branch as today).

CRITICAL constraints:
  - Do NOT alter the BUY check-and-reserve block (lines 264-301), the direction gate, the
    max_positions gate, or the short fall-through comment block in _enforce_position_admission —
    only ADD the new SELL-side solvency check in the post-sizing gate region.
  - Do NOT book any cash reservation for the SELL (D-06 — a SELL credits cash). This is a CHECK
    that rejects, not a reserve.
  - Decimal end-to-end: use to_money / existing Decimal helpers; NEVER Decimal(float); full
    precision through the intermediate; no quantize needed (a comparison, not a ledger write).
  - TABS — match admission_manager.py exactly; never normalize.
  - Update the relevant docstring/comment for the short fall-through to note that an admitted
    short add now passes through a symmetric admission-side margin solvency check (closing WR-03),
    keeping the decision-anchored docstring honest (CLAUDE.md: these are load-bearing).
  - Optionally close IN-01 by adding the short SELL-add clause to the process_signal step-0
    docstring (descriptive only) — low priority, do if it does not bloat the hunk.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_admission_rules.py -q 2>&1 | tail -25</automated>
  </verify>
  <done>The full test_admission_rules.py suite passes including both new tests; the unfunded
short increase now yields ONE audited CASH_RESERVATION REJECTED order with queue empty and
available_cash unchanged (no settlement-time InvalidTransactionError, no run abort); the funded
short increase still admits and emits; the long-arm over-margin BUY test and all direction/
max_positions/increase tests remain green (unaltered).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| signal → admission gate | unsized/explicit SELL-add crosses into the order domain; solvency must be enforced here, not deferred to settlement fail-fast |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-pmk-01 | Denial of Service | admitted unfunded short add → settlement InvalidTransactionError → backtest fail-fast abort | mitigate | add admission-side margin solvency check emitting an audited CASH_RESERVATION rejection so the run continues (this plan) |
| T-pmk-02 | Tampering | over-rejection of a FUNDED short add (admission headroom miscounts the existing short's own prior lock) | mitigate | credit back the existing short's own prior lock (mirror cash_manager.assert_lock_fits_buying_power / WR-01); funded-short-increase non-regression test + frozen e2e leaves prove no over-rejection |
| T-pmk-SC | Tampering | npm/pip/cargo installs | accept | no package installs in this change (pure logic + test edit) |
</threat_model>

<verification>
Run from the MAIN checkout (a worktree may abort `make test` on missing .env; prefer the
explicit pytest invocations below):

1. New regression + non-regression (the WR-03 close):
   `PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_admission_rules.py -q`
2. Funded short-scale-in e2e MUST stay green and unchanged (frozen leaves):
   `PYTHONPATH="$PWD" poetry run pytest tests/e2e/short_scale_in tests/e2e/short_scale_in_partial_cover -q`
3. SMA_MACD spot oracle byte-exact (134 trades / final_equity 46189.87730727451):
   `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -q`
4. mypy --strict clean across itrader:
   `poetry run mypy --strict itrader`
</verification>

<success_criteria>
- An unfunded short increase yields exactly ONE audited REJECTED entity in order storage
  (triggered_by=OrderTriggerSource.CASH_RESERVATION, PENDING→REJECTED), the queue is EMPTY
  (nothing emitted), and free cash / available buying power is UNCHANGED — mirroring
  test_over_margin_order_is_rejected_via_audited_path. No InvalidTransactionError, no run abort.
- A funded short increase remains byte-identical: admitted, sized through resolve_entry, settles
  through the SCALE-IN branch; both frozen short-scale-in e2e leaves green and unchanged.
- The long arm (BUY check-and-reserve), direction gate, and max_positions gate are byte-exact.
- SMA_MACD spot oracle byte-exact 134 / 46189.87730727451; full test_admission_rules.py green.
- mypy --strict clean across itrader.
- admission_manager.py edits are TABS; test edits are 4-SPACE; no Decimal(float) introduced.
</success_criteria>

<output>
Create `.planning/quick/260622-pmk-audited-admission-rejection-for-unfunded/260622-pmk-SUMMARY.md` when done.
</output>
