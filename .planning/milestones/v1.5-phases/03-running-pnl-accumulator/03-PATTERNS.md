# Phase 3: Running PnL Accumulator - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 3 (2 modified, 1 new)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/portfolio_handler/position/position_manager.py` (MODIFY, **4-space indent**) | manager | transform / running-accumulate | self (`get_total_market_value` :289, the WR-05 `_open_commission` accumulator pattern in `portfolio.py`) | exact (same file, sibling re-sum methods) |
| `itrader/portfolio_handler/portfolio.py` (MODIFY, **TAB indent**) | facade | event-driven settle / request-response | self — the existing `cash_manager`/`position_manager` calls on the same close funnel (`process_transaction`, lines 460–546) | exact (same method, same path) |
| `tests/unit/portfolio/test_<accumulator-equivalence>.py` (NEW) | test | request-response | `tests/unit/portfolio/test_portfolio.py` (`test_partial_closure` :121, `test_multiple_buys_followed_by_sell` :64) + `tests/unit/order/test_order_storage.py::test_active_queries_match_full_scan_equivalence` :310 (oracle-vs-fast equivalence shape) | exact role-match |

**CRITICAL indentation hazard (CLAUDE.md):** `position_manager.py` = **4 spaces**; `portfolio.py` = **TABS**. Match each file exactly. A tab/space mixed diff in the tab file breaks it. New test file: 4 spaces (mirror `test_portfolio.py`).

---

## Pattern Assignments

### `itrader/portfolio_handler/position/position_manager.py` (manager, transform → running-accumulate) — 4 SPACES

**Analog A — accumulator field in `__init__`, seeded `Decimal('0.00')`:** sibling Decimal config/precision fields already live in `__init__` (lines 80–88). Add the running accumulator alongside them with the same `Decimal('0.00')` seed used by the read methods below (D-05 byte-exactness).

```python
# position_manager.py:80-88 (4-space indent) — existing Decimal fields the
# accumulator joins. Seed the new field Decimal('0.00') to match
# get_total_realized_pnl's current seed (line 312) — byte-identical, not just ==.
        self.max_position_value = Decimal('1000000.00')  # Max value per position
        self.min_position_value = Decimal('10.00')       # Min value per position

        # Risk management
        self.max_concentration_pct = Decimal('0.20')  # Max 20% of portfolio in one position

        # Calculation precision
        self.precision = Decimal('0.00000001')  # 8 decimal places for calculations
        self.tolerance = Decimal('0.00001')     # Tolerance for position closure
```

**Analog B — the re-sum to REPLACE (`get_total_realized_pnl`, lines 310–323):** rewrite to `return` the accumulator field; the dual open+closed loop is the intrinsic dead-loop collapse called out in D-04 (intrinsic to the change, not a separate cleanup). Keep the same `Decimal('0.00')` seed semantics for an empty portfolio.

```python
# position_manager.py:310-323 (4-space) — REPLACE the two loops with `return self.<accumulator>`.
    def get_total_realized_pnl(self) -> Decimal:
        """Calculate total realized P&L from open and closed positions."""
        total_pnl = Decimal('0.00')

        # Add realized P&L from open positions
        # W1-08: position.realised_pnl is already -> Decimal at source.
        for position in self._storage.get_positions().values():
            total_pnl += position.realised_pnl

        # Add realized P&L from closed positions
        for position in self._storage.get_closed_positions():
            total_pnl += position.realised_pnl

        return total_pnl
```

**Analog C — the apply-increment method to ADD (mirror `get_total_*` method shape):** add a small public method that the Portfolio facade calls to fold the already-computed `realised_increment` into the accumulator. NO `quantize`, NO mid-sum rounding (D-05). Type signature `-> None`, takes a `Decimal`. Mirror the one-line-docstring + Decimal-typed style of the sibling getters.

```python
# Shape to mirror (existing sibling, position_manager.py:289-298, 4-space):
    def get_total_market_value(self) -> Decimal:
        """Calculate total market value of all positions."""
        total_value = Decimal('0.00')
        for position in self._storage.get_positions().values():
            total_value += position.market_value
        return total_value
# New method: e.g. `def apply_realised_increment(self, increment: Decimal) -> None:`
#   `self.<accumulator> += increment` — full precision, no quantize (D-05).
```

**Out of scope — DO NOT TOUCH (D-06):** `get_total_unrealized_pnl` (lines 300–308) and `get_total_market_value` (lines 289–298) must keep re-summing (price-dependent per bar). The `float(...)` casts in `get_positions_summary` (lines 420–422) are a legitimate serialization edge — leave them (D-04).

**D-02 audit anchor — the single open→closed move + single per-fill entry:** `_close_position` (lines 207–214) is the one open→closed move site; `process_position_update` (lines 95–115) is the one per-fill entry. The audit must confirm `position.realised_pnl` changes ONLY via the close funnel below.

---

### `itrader/portfolio_handler/portfolio.py` (facade, settle funnel) — TABS

**Analog — the increment already computed + the existing manager-call pattern on the same path.** `realised_increment` is computed at line 529 inside `process_transaction`'s CLOSE arm; the surrounding code already makes manager calls (`cash_manager.release_margin`, `cash_manager.lock_margin`, `apply_fill_cash_flow`, `transaction_manager.record`). Add ONE `position_manager.apply_realised_increment(realised_increment)` call on this same path — no new event, handler, or ABC (D-01/D-02). The facade→manager direction is preserved (manager keeps no back-reference).

```python
# portfolio.py:529-546 (TAB indent) — realised_increment is the EXACT value the
# accumulator reuses (D-02). Insert the PositionManager call alongside the
# existing cash/transaction manager calls on this path. partial AND full close
# both flow here (the else-branch is "PARTIAL or FULL CLOSE", line 488).
			realised_increment = position.realised_pnl - prior_realised
			open_commission_credit = self._open_commission_credit_for_close(
				position, closed_qty
			)
			cash_delta = realised_increment + open_commission_credit

		# ONE ledger entry: signed cash delta + the commission fee field +
		# event-derived timestamp (D-06, Pitfalls 1/5).
		self.cash_manager.apply_fill_cash_flow(
			amount=cash_delta, fee=commission, ...
		)
		# Record — the applied Transaction entity IS the audit record (D-11).
		self.transaction_manager.record(transaction)
```

**Note:** `prior_realised` is captured pre-mutation at line 406 (`prior.realised_pnl if prior is not None else Decimal("0")`). The increment is only computed in the CLOSE arm (`is_increase` False); the OPEN/SCALE-IN arm (lines 468–487) does NOT change `realised_pnl` — confirms the D-02 single-funnel invariant. Apply the increment only in the close arm.

**Consumers unchanged (must see byte-identical Decimal):** read-properties `total_realised_pnl` (line 243 → `position_manager.get_total_realized_pnl()`) and `total_pnl` (line 248). `metrics_manager._get_realized_pnl` reads `portfolio.total_realised_pnl` — signature and value identical (D-05).

---

### `tests/unit/portfolio/test_<accumulator-equivalence>.py` (test, equivalence drift-lock) — 4 SPACES

**Primary analog — `tests/unit/portfolio/test_portfolio.py`** (drives the FULL settle funnel through `Portfolio.process_transaction`, which is the ONLY path that feeds the accumulator). NOTE: `tests/unit/portfolio/test_position_manager.py` drives `process_position_update` DIRECTLY, bypassing the Portfolio funnel — so the accumulator is NOT fed there. The equivalence test MUST go through `Portfolio`, not bare `PositionManager`.

**Fixture pattern (test_portfolio.py:17-20):**
```python
@pytest.fixture
def portfolio():
    """A fresh simulated portfolio funded with $150000."""
    return Portfolio(1, "test_pf", "simulated", 150000, datetime.now())
```

**Transaction + settle + assert-realised pattern — partial close (test_portfolio.py:121-133) and full close (test_portfolio.py:64-82):**
```python
def test_partial_closure(portfolio):
    # Buy 3 ... then Sell 2 units of BTC at $45000 (partial closure)
    # ... portfolio.process_transaction(buy_txn) / process_transaction(sell_txn)
    assert portfolio.total_realised_pnl == 10000  # closed portion only

def test_multiple_buys_followed_by_sell(portfolio):
    # scale-in then full close via process_transaction
    assert portfolio.total_realised_pnl == pytest.approx(19000, abs=0.01)
```

**Equivalence-oracle shape — `tests/unit/order/test_order_storage.py:294-353`** (Phase 2 D-09 precedent this phase reuses as D-03). Define an independent oracle that reproduces the PRIOR full re-sum, then assert the fast path equals it byte-for-byte:
```python
# test_order_storage.py:297-307 — independent oracle reproducing prior full-scan.
def _active_oracle(storage, portfolio_id=None):
    """Independent oracle: scan ... Reproduces the prior full-scan semantics so
    index-backed output can be asserted byte-equal against it (D-09)."""
    return [o for o in storage._by_id.values() if o.is_active and ...]

def test_active_queries_match_full_scan_equivalence(store):
    """D-09: index-backed query order == prior full-scan order."""
    ... assert [fast] == [oracle]
```

**Equivalence test recipe (D-03):**
1. Build a `Portfolio` (mirror the `portfolio` fixture).
2. Drive a non-trivial mix through `portfolio.process_transaction(...)`: at least one open, one scale-in, one PARTIAL close (open + closed-list both carry realised terms), and one FULL close (moves a position to `_closed_positions`). Mirror the txn-construction calls in test_portfolio.py:29-75.
3. Define an oracle `_resum_realised(pm)` that reproduces the prior dual-loop sum exactly: `sum(p.realised_pnl for open) + sum(p.realised_pnl for closed)` — same `Decimal('0.00')` seed.
4. Assert `pm.<accumulator> == _resum_realised(pm)` (value-equality `==`, criterion #2's contract, D-05) at each step after a closing fill — across partial and full closes.
5. Reach the manager via `portfolio.position_manager` (the facade exposes it; portfolio.py:245 reads through it).

---

## Shared Patterns

### Decimal-end-to-end, no mid-sum quantize (D-05)
**Source:** `position_manager.py:291-298, 302-308, 312-323` (every `get_total_*` seeds `Decimal('0.00')` and accumulates raw `Decimal` terms — NO `quantize` until a money boundary).
**Apply to:** the new accumulator field + apply method + equivalence test. Seed `Decimal('0.00')`; never quantize the running total.

### Facade→manager layering, no back-reference (D-01)
**Source:** `portfolio.py:460-546` — `Portfolio.process_transaction` calls `self.position_manager.*` and `self.cash_manager.*`; managers never call back into the portfolio.
**Apply to:** the new `apply_realised_increment` call goes Portfolio→PositionManager only. The accumulator method takes a plain `Decimal` and stores it; it does NOT read back from the portfolio.

### Audit-the-invariant + dedicated equivalence test, NO hot-path runtime guard (Phase 2 D-04/D-09 precedent)
**Source:** `tests/unit/order/test_order_storage.py:294-353` (oracle-vs-fast equivalence as a drift lock); 02-CONTEXT.md D-04/D-09.
**Apply to:** prove correctness via (1) the written D-02 single-funnel audit, (2) the byte-exact oracle + determinism double-run, (3) the new equivalence regression test. Do NOT add a per-bar assert that re-sums on the hot path (re-introduces the O(positions) cost this phase removes).

### Logging / module style
**Source:** `position_manager.py:54, 90-93` — `self.logger = get_itrader_logger().bind(component="PositionManager")`; methods carry one-line docstrings; decision tags (D-NN, W1-08, WR-NN) anchor comments.
**Apply to:** new method gets a one-line docstring; anchor the accumulator comments to `D-01`/`D-02`/`D-05`. No new log line on the hot read path.

---

## No Analog Found

None — every file has a strong in-codebase analog (same file for the two modifications; `test_portfolio.py` + the Phase 2 equivalence test for the new test).

## Metadata

**Analog search scope:** `itrader/portfolio_handler/position/`, `itrader/portfolio_handler/`, `tests/unit/portfolio/`, `tests/unit/order/`
**Files scanned:** `position_manager.py`, `portfolio.py` (settle path + read-properties), `test_position_manager.py`, `test_portfolio.py`, `test_order_storage.py`, `03-CONTEXT.md`
**Pattern extraction date:** 2026-06-24
