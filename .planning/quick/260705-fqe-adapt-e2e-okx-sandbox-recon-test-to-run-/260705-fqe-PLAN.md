---
phase: quick-260705-fqe
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tests/e2e/test_okx_sandbox_recon.py
autonomous: true
requirements: [RECON-01, RECON-03, D-20]
must_haves:
  truths:
    - "The two online start()-driven tests (i test_demo_order_produces_real_fill_event, ii test_venue_account_reconciles_post_fill_within_tolerance) reach SystemStatus.RUNNING against the non-flat OKX demo account instead of halting with halt_reason='baseline-residual'"
    - "The settlement proof asserts the BUY's position DELTA (pos.net_quantity - position_before) within _SETTLE_QTY_FEE_BAND, not the absolute post-fill net_quantity"
    - "On a genuinely flat demo account (venue base total 0/absent) the seed is a no-op and the original flat-start behavior is unchanged"
    - "The module still COLLECTS network-free and credential-free (no import errors); all connector imports in the new helper are lazy (inside the function body)"
  artifacts:
    - path: "tests/e2e/test_okx_sandbox_recon.py"
      provides: "TEST-ONLY seed helper + delta-based settlement assertions"
      contains: "_seed_believed_position_to_venue"
  key_links:
    - from: "tests/e2e/test_okx_sandbox_recon.py::_seed_believed_position_to_venue"
      to: "portfolio.position_manager._storage.set_position"
      via: "Position.open_position(Transaction(BUY, BTC/USDC, venue_qty)) then set_position"
      pattern: "position_manager\\._storage\\.set_position"
    - from: "tests/e2e/test_okx_sandbox_recon.py::_assert_settlement"
      to: "pos.net_quantity - position_before"
      via: "delta_qty assertion band"
      pattern: "position_before"
---

<objective>
Adapt `tests/e2e/test_okx_sandbox_recon.py` so the human-gated online settlement proof runs
against a NON-FLAT OKX demo account (the only kind available — OKX seeds ~1 BTC and the EEA
account cannot be sold flat). Two locked TEST-ONLY changes, no production edits:

1. Seed the engine's believed BTC/USDC position to the LIVE venue BTC balance BEFORE `start()`,
   so `_run_session_baseline_guard` (live_trading_system.py:579) reads `engine_qty == venue_qty`
   and lets `start()` reach RUNNING instead of latching `halt('baseline-residual')`.
2. Assert the BUY's DELTA `(pos.net_quantity - position_before)` in `_assert_settlement` instead
   of the absolute position, so the proof holds on a pre-seeded (non-flat) portfolio.

Purpose: unblock the online RECON-01/RECON-03 + D-20 CONF-B GREEN gate on the demo account that
actually exists. The reconcile test (ii) still passes because engine and venue both move by the
same fill delta from the seeded baseline.

Output: modified `tests/e2e/test_okx_sandbox_recon.py` (the ONLY file touched).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
TEST-ONLY change. NO production source may be modified. If Task work reveals a production change
is genuinely unavoidable, STOP and flag it as a blocker rather than editing `itrader/`.

@tests/e2e/test_okx_sandbox_recon.py

<interfaces>
<!-- Real APIs discovered from the codebase — the executor uses these directly, no exploration. -->

Baseline guard the seed must satisfy — itrader/trading_system/live_trading_system.py:579-627:
- Runs INSIDE `start()` AFTER the connector connects (line ~1249) and AFTER
  `_venue_account.snapshot()` (~1287) + reconcile; BEFORE the engine thread spawns (~1322).
- `symbol = _OKX_STREAM_SYMBOL` == "BTC/USDC" == the test's `_OKX_SYMBOL`.
- `venue_qty = self._venue_account.positions.get(symbol, Decimal('0'))`
- `engine_qty = portfolio.get_open_position(symbol).net_quantity` (or Decimal('0'))
- Halts `halt('baseline-residual')` unless `is_within_single_unit_tolerance(engine_qty, venue_qty, precision)`.
- Consequence: the seed MUST run BEFORE `start()`, and the system connector is NOT yet connected
  pre-start — so the live balance must be read via an independent connector.

Venue spot position derivation — itrader/portfolio_handler/account/venue.py:190-211 (`_extract_spot_position`):
- Reads `balance_payload["total"][BASE]` (BASE = "BTC"), keys it under the wired symbol "BTC/USDC",
  crosses the Decimal edge via `to_money(str(base_raw))`. Zero/absent base total => `{}` (flat).
- So seeding from `fetch_balance()["total"]["BTC"]` via `to_money(str(...))` matches the guard's
  `venue_qty` byte-for-byte.

Read-only balance connector — already in this file at line 280:
- `_build_demo_connector()` -> constructs + `.connect()`s a sandbox `OkxConnector`, asserts
  `connector.sandbox is True`. Reuse it; disconnect in a `finally`.
- Balance read pattern (established at line 511): `connector.call(connector.client.fetch_balance())`
  then `bal["total"]["BTC"]`.

Position seed seam:
- `Transaction` (itrader/portfolio_handler/transaction/transaction.py) is a `msgspec.Struct`;
  required kwargs: `time, type, ticker, price, quantity, commission, portfolio_id, id, fill_id`.
  `__post_init__` normalizes price/quantity/commission via `to_money` (never Decimal(float)).
- `type=TransactionType.BUY` (from itrader.core.enums); `id=TransactionId(uc.uuid7())`,
  `fill_id=uc.uuid7()` (import uuid_utils.compat as uc); `commission=Decimal("0")`.
- `Position.open_position(transaction)` (position.py:242) -> Position; net_quantity == txn.quantity for a BUY.
- `portfolio = system.portfolio_handler.get_portfolio(portfolio_id)` (portfolio_handler.py:234).
- `portfolio.position_manager._storage.set_position(ticker, position)` (in_memory_storage.py:58) —
  a PURE dict write: `self._positions[ticker] = position`. It does NOT mutate cash (PositionManager
  is cash-agnostic, D-06). So `cash_before` (snapshotted after start()) is unaffected by the seed.
- Read-back for assertions: `system.portfolio_handler.get_position(portfolio_id, ticker)` ->
  PositionView with `.net_quantity` (portfolio_handler.py:302).

Existing module constants to reuse: `_OKX_SYMBOL` ("BTC/USDC"), `_BASE_CCY` ("BTC"),
`_PRICE_ESTIMATE` (Decimal("100000")), `_SETTLE_QTY_FEE_BAND` (Decimal("0.01")).

Convention: 4-space indentation throughout this file. ALL connector/system imports stay LAZY
(inside function bodies) so credential-free collection never touches ccxt.pro.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add the venue-position seed helper and wire it into both online start() tests</name>
  <files>tests/e2e/test_okx_sandbox_recon.py</files>
  <action>
Add a new module-level helper `_seed_believed_position_to_venue(system, portfolio_id)` (place it
alongside the other helpers, e.g. just after `_build_demo_connector` at line ~288). ALL imports go
INSIDE the function body (lazy), matching this file's network-free-collection contract:
`from datetime import datetime, timezone`; `import uuid_utils.compat as uc`;
`from itrader.core.enums import TransactionType`; `from itrader.core.ids import TransactionId`;
`from itrader.core.money import to_money`;
`from itrader.portfolio_handler.position.position import Position`;
`from itrader.portfolio_handler.transaction.transaction import Transaction`.

Helper body:
1. Build a throwaway read-only sandbox connector via the existing `_build_demo_connector()`.
   In a try/finally, read `bal = connector.call(connector.client.fetch_balance())`, then
   `base_raw = bal.get("total", {}).get(_BASE_CCY)` (guard non-dict), and in the `finally`
   `connector.disconnect()` wrapped in its own try/except (clean teardown under
   filterwarnings=["error"] — no leaked authenticated socket).
2. If `base_raw is None`: `return Decimal("0")` (no venue balance key). If
   `venue_qty = to_money(str(base_raw))` (Decimal edge — never Decimal(float)) equals 0:
   `return Decimal("0")` — a genuinely FLAT account, seed is a no-op, original flat-start path intact.
3. Construct `Transaction(time=datetime.now(timezone.utc), type=TransactionType.BUY,
   ticker=_OKX_SYMBOL, price=_PRICE_ESTIMATE, quantity=venue_qty, commission=Decimal("0"),
   portfolio_id=portfolio_id, id=TransactionId(uc.uuid7()), fill_id=uc.uuid7())`. Then
   `position = Position.open_position(txn)`,
   `portfolio = system.portfolio_handler.get_portfolio(portfolio_id)`,
   `portfolio.position_manager._storage.set_position(_OKX_SYMBOL, position)`. Return `venue_qty`.
   Docstring: explain the non-flat-demo constraint (OKX seeds ~1 BTC, EEA can't sell flat), that
   the read is READ-ONLY (no order), and that set_position is position-only / cash-neutral.

Wire the call into BOTH online start()-driven tests, immediately AFTER `_assert_sandbox_routed(system)`
and BEFORE `system.start()`:
- `test_demo_order_produces_real_fill_event` (line ~583-585)
- `test_venue_account_reconciles_post_fill_within_tolerance` (line ~635-637)
Call it as `_seed_believed_position_to_venue(system, portfolio_id)` (test (i) will also read
position_before separately in Task 2; the return value is not required at the call site). Do NOT add
a seed to `test_restart_rehydrate_then_venue_reconcile_no_spurious_halt` — that test never calls
`system.start()` (it drives a standalone connector + reconciler) and does not hit the baseline guard.
  </action>
  <verify>
  <automated>poetry run python -c "import ast; ast.parse(open('tests/e2e/test_okx_sandbox_recon.py').read())"</automated>
  </verify>
  <done>Helper exists with lazy imports; both start()-driven tests call it between the sandbox
  guard and start(); test (iii) untouched; file parses cleanly.</done>
</task>

<task type="auto">
  <name>Task 2: Switch _assert_settlement to DELTA position assertions and thread position_before</name>
  <files>tests/e2e/test_okx_sandbox_recon.py</files>
  <action>
Change `_assert_settlement` (line ~392) signature from
`(system, portfolio_id, order, emitted, cash_before)` to
`(system, portfolio_id, order, emitted, cash_before, position_before)`.

Inside `_assert_settlement`, keep the `pos = system.portfolio_handler.get_position(...)` fetch and
the `pos is not None` assertion. REPLACE the three absolute assertions (lines ~416-420):
`assert pos.net_quantity > 0`;
`assert pos.net_quantity <= filled_qty`;
`assert pos.net_quantity >= filled_qty * (Decimal("1") - _SETTLE_QTY_FEE_BAND)`
with DELTA assertions on `delta_qty = pos.net_quantity - position_before`:
`assert delta_qty > 0` (the BUY grew the believed position);
`assert delta_qty <= filled_qty` (an OKX spot BUY may take the fee from the base received);
`assert delta_qty >= filled_qty * (Decimal("1") - _SETTLE_QTY_FEE_BAND)` (fee-band floor on the delta).
Keep the exact failure-message style. Leave the CASH assertions (delta = cash_before - cash_after,
band cost..cost*(1+band)) UNCHANGED — they already operate as a delta and cash_before is snapshotted
after start()/after the (cash-neutral) seed. Keep assertions (3) not-HALTED and (4) spot
fetch_positions()==[] unchanged. Add `"position_before": position_before` and
`"position_delta": delta_qty` to the returned dict (so the ARCH-3 capture can record the delta).

In `test_demo_order_produces_real_fill_event`, snapshot `position_before` right where `cash_before`
is taken (line ~594, after start(), before submitting the order):
`_pos_before = system.portfolio_handler.get_position(portfolio_id, _OKX_SYMBOL)`;
`position_before = _pos_before.net_quantity if _pos_before is not None else Decimal("0")`.
Update the call site (line ~611) to
`_assert_settlement(system, portfolio_id, order, emitted, cash_before, position_before)`.

Optionally (keep minimal, no new network calls) add two lines to `_capture_arch3_finalization`'s
Wave-1 settlement section printing `settlement['position_before']` and `settlement['position_delta']`;
if it complicates the diff, skip it — the capture already prints `position_qty` and `filled_qty`.
  </action>
  <verify>
  <automated>poetry run python -c "import ast; ast.parse(open('tests/e2e/test_okx_sandbox_recon.py').read())" && poetry run pytest tests/e2e/test_okx_sandbox_recon.py --collect-only -q</automated>
  </verify>
  <done>`_assert_settlement` takes `position_before` and asserts the position DELTA within the
  fee band; test (i) snapshots `position_before` after start() and passes it; cash + status + spot
  assertions unchanged; module COLLECTS cleanly (credential-free skip path intact, no import errors).</done>
</task>

</tasks>

<verification>
Offline only (the suite is `-m live`, network+credential gated, and would place a real demo order —
NEVER run the live test as verification here):
1. `poetry run python -c "import ast; ast.parse(open('tests/e2e/test_okx_sandbox_recon.py').read())"` — parses.
2. `poetry run pytest tests/e2e/test_okx_sandbox_recon.py --collect-only -q` — collects cleanly, no
   import errors (lazy imports keep collection network-free).
No mypy gate: this test module is outside `[tool.mypy] files = ["itrader"]` scope.
</verification>

<success_criteria>
- `tests/e2e/test_okx_sandbox_recon.py` is the ONLY file changed; no `itrader/` edit.
- New `_seed_believed_position_to_venue` helper reads the live venue BTC balance READ-ONLY and seeds
  the believed BTC/USDC position via `Position.open_position` + `set_position` (cash-neutral); flat
  account => no-op.
- Both start()-driven online tests call the seed between the sandbox guard and `start()`; test (iii)
  is untouched.
- `_assert_settlement` asserts the position DELTA against `position_before` within `_SETTLE_QTY_FEE_BAND`;
  cash/status/spot-venue assertions preserved.
- Module parses and collects cleanly offline.
</success_criteria>

<output>
Create `.planning/quick/260705-fqe-adapt-e2e-okx-sandbox-recon-test-to-run-/260705-fqe-SUMMARY.md` when done.
</output>
