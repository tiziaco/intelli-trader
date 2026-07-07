# Phase 1: Account Abstraction + Portfolio/Handler Refactor - Pattern Map

**Mapped:** 2026-06-30
**Files analyzed:** 10 (7 new, 5 modified, 1 deleted — some overlap)
**Analogs found:** 10 / 10 (every new/modified file has an in-repo analog — this is pure code-motion behind the `PortfolioReadModel` seam)

> **Indentation is load-bearing (CLAUDE.md).** Verified per file below. New `account/` and
> `connectors/` files follow the **4-space** convention (newer refactored modules + the
> `CashManager` code-motion source are 4-space). `portfolio.py` is **TABS**; `portfolio_handler.py`
> is **4-space**; `cash_manager.py` is **4-space**; `exchanges/base.py` is **TABS**;
> `fee_model/base.py` is **4-space**. Match the file you edit, never normalize.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/portfolio_handler/account/__init__.py` (NEW) | barrel | n/a | `execution_handler/fee_model/__init__.py` + `portfolio_handler/cash/__init__.py` | exact |
| `itrader/portfolio_handler/account/base.py` (NEW) | model (ABC) | transform | `execution_handler/fee_model/base.py` (`FeeModel(ABC)`) | exact (ABC-on-domain-axis) |
| `itrader/portfolio_handler/account/simulated.py` (NEW) | model (leaf) | CRUD (ledger) | `portfolio_handler/cash/cash_manager.py` (`CashManager`) | exact (verbatim code-motion) |
| `itrader/portfolio_handler/account/venue.py` (NEW, stub) | model (leaf) | event-driven (deferred) | `execution_handler/exchanges/base.py` interface shape | role-match (interface-only) |
| `itrader/connectors/__init__.py` (NEW) | barrel | n/a | `execution_handler/fee_model/__init__.py` | exact |
| `itrader/connectors/base.py` (NEW) | model (Protocol) | event-driven (deferred) | `execution_handler/exchanges/base.py` (`AbstractExchange` Protocol) | exact (Protocol marker) |
| `itrader/portfolio_handler/portfolio.py` (MODIFY) | model | CRUD | self (in-place delegation rewire) | self |
| `itrader/portfolio_handler/cash/cash_manager.py` (MODIFY→MOVE) | manager | CRUD (ledger) | self (becomes `SimulatedCashAccount`) | self |
| `itrader/portfolio_handler/portfolio_handler.py` (MODIFY) | handler (thin, queue-facing) | event-driven | self (math extracted, emission stays) | self |
| `itrader/trading_system/trading_interface.py` (DELETE) | bridge | request-response | n/a (deleted; barrel + test-docstring cleanup) | n/a |

## Pattern Assignments

### `itrader/portfolio_handler/account/base.py` (NEW — Account ABC)

**Analog:** `itrader/execution_handler/fee_model/base.py` (`FeeModel(ABC)`) — **4-space indentation**.

This is the model for the **inheritance axis** (cash-vs-margin, D-01/D-02). Use `abc.ABC` +
`@abstractmethod` exactly like `FeeModel`, NOT a Protocol (the Protocol analog is reserved for
`LiveConnector` / `VenueAccount`'s structural seam). The ABC pins the
`balance / available / reserve(order_id, amount) / release(order_id)` contract (D-05 drops
`portfolio_id` — Account is the single account under LX-04 1:1).

**ABC + abstractmethod shape to copy** (`fee_model/base.py` lines 10-30, 75-83, 112):
```python
from abc import ABC, abstractmethod
from decimal import Decimal

class FeeModel(ABC):
    """Decimal-native ... interface ... Money (D-12): ... Decimal end-to-end."""

    @abstractmethod
    def calculate_fee(self, quantity: Decimal, price: Decimal, ...) -> Decimal:
        """..."""
        raise NotImplementedError("Subclasses must implement calculate_fee()")
```

**Money discipline to preserve** (`fee_model/base.py` docstring lines 24-30): "Decimal end-to-end —
no float casts inside ... no quantization (rounding happens only at money boundaries)." The
`Account` ABC docstring should carry the same Decimal-end-to-end statement plus a `D-01/D-02`
decision tag (decision-anchored docstrings are the house style, CLAUDE.md).

---

### `itrader/portfolio_handler/account/simulated.py` (NEW — SimulatedCashAccount + SimulatedMarginAccount)

**Analog:** `itrader/portfolio_handler/cash/cash_manager.py` (`CashManager`) — **4-space indentation**.
This file IS the destination of the `CashManager` code-motion (D-05). **`SimulatedCashAccount` is
`CashManager` moved verbatim**; `SimulatedMarginAccount(SimulatedCashAccount)` adds the
margin-only methods. Byte-exactness depends on NOT altering this math (the oracle gate
`134 / 46189.87730727451`).

**Cash-leaf methods that code-motion onto `SimulatedCashAccount`** (verbatim from `cash_manager.py`):
- `balance` property (lines 101-104), `available_balance` (lines 106-119), `reserved_balance` (143-146)
- `deposit` (148-197), `withdraw` (199-258), `process_transaction_cash_flow` (260-321)
- `apply_fill_cash_flow` (323-367) — the ONE trade-path cash primitive, full precision, no quantize
- `reserve_cash` (487-532) / `release_reservation` (534-558) → become `Account.reserve`/`release`
- `assert_funds_invariant` (421-442), `_validate_and_convert_amount` (646-666), `_create_operation` (668-695)

**Margin-only methods that code-motion onto `SimulatedMarginAccount`** (the strict superset, D-02):
- `locked_margin_total` (122-129), `get_locked_margin_for` (131-141)
- `lock_margin` (560-579) / `release_margin` (581-601)
- `accrue_borrow_interest` (369-419), `assert_lock_fits_buying_power` (444-485)
- the margin/liquidation math pulled DOWN from `portfolio_handler.py` (see next section)

**Critical full-precision pattern (do NOT route fill/lock money through the 2dp quantize)**
(`cash_manager.py` `apply_fill_cash_flow` docstring lines 325-347):
```python
def apply_fill_cash_flow(self, amount, fee, description, reference_id, timestamp) -> None:
    # Deliberately does NOT route through _validate_and_convert_amount
    # (Pitfall 1: its 2dp HALF_UP quantize would shift the equity curve -> oracle FAIL)
    old_balance = self._balance
    new_balance = old_balance + amount   # signed, full precision
    self._balance = new_balance
```

**Reserve signature change (D-05):** the `Account`-level method **drops `portfolio_id`** —
`reserve(order_id, amount)` / `release(order_id)`. Inside, the body is the existing
`reserve_cash(amount, description, reference_id)` / `release_reservation(reference_id)` mechanics.

**Storage seam to keep:** `CashManager` reads/writes reserved-cash, locked-margin, and cash-ops
through the injected `PortfolioStateStorage` seam (`cash_manager.py` lines 75-88). Preserve this —
the account constructed by a real `Portfolio` shares `portfolio.state_storage` (M2-08 / WR-02).

---

### `itrader/portfolio_handler/account/venue.py` (NEW — VenueAccount stub leaf)

**Analog:** the interface shape of `execution_handler/exchanges/base.py` — but `VenueAccount` is an
**`Account` ABC leaf** (D-11), so its stable contract comes from `account/base.py`, NOT the
connector. Interface-only this phase: implement the ABC's abstract methods as stubs
(`raise NotImplementedError` / `...`) with `Phase 5 (RECON-01)` decision-tag docstrings noting the
connector-coupled body (cached venue balance/margin/position) is deferred. Mirror the
`NotImplementedError` placeholder convention already in the repo
(`order_handler/storage/postgresql_storage.py`). **4-space indentation.**

---

### `itrader/connectors/base.py` (NEW — LiveConnector Protocol)

**Analog:** `itrader/execution_handler/exchanges/base.py` (`AbstractExchange`) — **TABS** in the
source file, but this is a NEW top-level package; use **4-space** (newer-module convention) and copy
the *structure*, not the indentation.

**`runtime_checkable Protocol` marker pattern to copy** (`exchanges/base.py` lines 1-16):
```python
from typing import Any, Dict, Protocol, runtime_checkable

@runtime_checkable
class AbstractExchange(Protocol):
    """
    Structural interface (D-07) for ... operations ...

    This is a ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes
    the swap-a-fake structural seam that both simulated and live ... must satisfy.
    """
    def on_order(self, event: OrderEvent) -> None: ...
```

**Scope (D-10):** thin marker that *names the arm boundaries* — data arm, order arm, lifecycle — so
Phase 2 knows the slots to fill. **Real signatures (async submit→ack→fill, `confirm`-flag,
balances/positions) are deferred to Phase 2 (CONN-*).** Use `...` method bodies and arm-grouping
comment headers exactly like `AbstractExchange` groups `# Core execution methods` /
`# Connection management` / `# Health and monitoring` (lines 18, 39, 52). Cite `D-07` /
`D-10` in the class docstring (structural-seam consistency with `AbstractExchange`).

---

### `itrader/portfolio_handler/portfolio.py` (MODIFY — TABS)

**Self-analog (in-place rewire).** Three changes, all behind unchanged public surface:

1. **`cash` property → `account.balance` delegation** (current lines 198-206):
```python
@property
def cash(self) -> Decimal:
    return self.cash_manager.balance        # -> self.account.balance
```

2. **Construct the account leaf in `_init_managers`** (current lines 83-97) the same way the four
   managers are built; choose the leaf by `enable_margin` at wiring (D-03 — runtime branch becomes
   leaf selection):
```python
def _init_managers(self, initial_cash) -> None:
    self.state_storage = PortfolioStateStorageFactory.create("backtest")
    self.cash_manager = CashManager(self, initial_cash=initial_cash)   # -> self.account = Simulated{Cash,Margin}Account(...)
    self.transaction_manager = TransactionManager(self)
    ...
```
   D-03 leaf selection input is `self.config.trading_rules.enable_margin` (the same flag that
   today branches `_process_transaction_spot` vs `_margin` at line 303).

3. **`user_id` strip** (constructor line 46, assignment line 52, `get_info` dict line 850). It is
   app-layer (FastAPI owns the `user_id → portfolio` map; CONTEXT canonical-refs); it must NOT
   relocate onto `Account`. Ripple: `add_portfolio` signature (below) + golden wiring.

4. **Settlement sites** (`_process_transaction_spot` lines 308-389, `_process_transaction_margin`
   391-558) call `self.cash_manager.<method>` ~12 times (lines 364, 380, 471, 498-525, 556, 806).
   Re-point these to `self.account.<method>`. The spot/margin branch math is **byte-exact site #2 /
   verbatim code-motion** — do not alter, only re-point the receiver.

---

### `itrader/portfolio_handler/portfolio_handler.py` (MODIFY — 4-space; thin queue-facing handler)

**Self-analog.** This is the `*_handler` thin layer — it keeps the queue and the emission; only the
**math moves down to `Account`** (ACCT-02). The convention from CLAUDE.md: `*_handler` = thin
queue-facing interface; managers/accounts have NO queue.

**Reserve/release seam re-points but signature is FROZEN** (current lines 276-284):
```python
def reserve(self, portfolio_id, order_id, amount) -> None:
    self.get_portfolio(portfolio_id).cash_manager.reserve_cash(   # -> .account.reserve(order_id, amount)
        amount, "order cash reservation", str(order_id))

def release(self, portfolio_id, order_id) -> None:
    self.get_portfolio(portfolio_id).cash_manager.release_reservation(str(order_id))  # -> .account.release(order_id)
```
The `PortfolioReadModel.reserve(portfolio_id, order_id, amount)` / `release(portfolio_id, order_id)`
Protocol seam (`core/portfolio_read_model.py` lines 127, 146) stays **unchanged** (D-06/D-07 —
keyed by `portfolio_id`, which `Account` has no notion of). Zero ripple into the order domain.

**Margin/liquidation math MOVES to `SimulatedMarginAccount`** (math only — these are pure Decimal
functions today):
- `maintenance_margin` (339-372), `margin_ratio` (374-388)
- `_isolated_liq_price` (399-421, `@staticmethod`), `_is_breached` (423-433),
  `_liquidation_penalty` (435-442), `_liq_inputs` (444-460)

**Emission STAYS in the handler (queue-only rule preserved, ACCT-02).** The `global_queue.put` in
`_liquidate_position` (line 538) and the surrounding `OrderEvent`/`FillEvent` mint + shared-mirror
write + log do NOT move:
```python
self._order_storage.add_order(order)                       # shared mirror (Pitfall 4)
order_event = OrderEvent.new_order_event(order)
fill_event = FillEvent.new_fill("EXECUTED", order_event, price=..., commission=penalty, time=bar_time)
self.global_queue.put(fill_event)                          # <-- STAYS in the handler
```
`_liquidate_position` (462-555) and `_run_liquidation_pass` (557-…) keep their event-minting/emitting
shell; they call DOWN into the account for the math (`_isolated_liq_price`, `_liquidation_penalty`).

**`add_portfolio` signature ripple from user_id strip** (current line 152):
```python
def add_portfolio(self, user_id, name, exchange, cash, portfolio_config=None) -> PortfolioId:
    ...
    portfolio = Portfolio(user_id=user_id, name=name, ...)   # drop user_id arg + Portfolio kwarg
```
Touches golden-master wiring (`backtest_trading_system.py:466`, `system_spec.py`, `validators.py`).
Do deliberately; re-confirm byte-exact.

---

### `itrader/trading_system/trading_interface.py` (DELETE) + barrel + test docstring

**D-08:** delete the file (dead code; referenced only by the barrel export and a test *docstring*;
carries a `quantity: float` live-path float-money leak — `trading_interface.py` lines 41-43, 94-96).
Deleting helps the `mypy --strict` / no-float-money gate.

Three-part deletion scope:
1. Delete `itrader/trading_system/trading_interface.py`.
2. Remove from barrel `itrader/trading_system/__init__.py` — drop the `from .trading_interface import
   TradingInterface` line (line 6) and the `'TradingInterface'` `__all__` entry (line 12).
3. Fix the test **docstring** mention in `tests/unit/order/test_admission_rules.py` (the
   `test_long_short_direction_passes_the_gate` docstring at line ~267 reads "e.g. from
   TradingInterface" — reword; it is a comment, not a code reference, so no test logic changes).

## Shared Patterns

### ABC + sibling-leaf folder convention
**Source:** `execution_handler/fee_model/` (`base.py` ABC + `{zero,percent,maker_taker}_fee_model.py`
leaves + `__init__.py` barrel), mirrored by `slippage_model/` and `exchanges/`.
**Apply to:** `account/` becomes the **fifth peer** under `portfolio_handler/` next to
`cash/ position/ transaction/ metrics/` (D-12). NOT a top-level `account_handler/` (Account has no
queue). Layout: `account/{__init__,base,simulated,venue}.py`.

### Barrel re-export
**Source:** `fee_model/__init__.py` (lines 8-18) and `cash/__init__.py` (lines 8-10).
**Apply to:** `account/__init__.py` and `connectors/__init__.py`.
```python
from .base import Account
from .simulated import SimulatedCashAccount, SimulatedMarginAccount
from .venue import VenueAccount
__all__ = ["Account", "SimulatedCashAccount", "SimulatedMarginAccount", "VenueAccount"]
```

### Decimal-end-to-end money (correctness-critical)
**Source:** `cash_manager.py` (`to_money`, full-precision fill path vs 2dp quantize boundary) +
`fee_model/base.py` docstring.
**Apply to:** every `account/` file. Enter Decimal via `to_money(x)`; carry full precision; quantize
ONLY at ledger boundaries (`quantize(..., ROUND_HALF_UP)`). The fill/lock/carry paths
(`apply_fill_cash_flow`, `lock_margin`, `accrue_borrow_interest`) deliberately skip the 2dp quantize
(Pitfall 1 — a quantize there shifts the equity curve and FAILS the byte-exact oracle).

### Decision-anchored docstrings + indentation match
**Source:** every file read (e.g. `# D-19`, `Pitfall 5`, `M2-08`, `D-01-CORR`).
**Apply to:** all new/modified files. Open modules/classes with a docstring citing the relevant
decision tag (`D-01..D-13`, `ACCT-01..06`). Match indentation of the file edited — `portfolio.py`
TABS, `portfolio_handler.py`/`cash_manager.py`/new `account/`+`connectors/` 4-space.

### Structural-seam Protocol (vs ABC)
**Source:** `exchanges/base.py` (`@runtime_checkable class AbstractExchange(Protocol)`).
**Apply to:** `connectors/base.py` `LiveConnector` (and the conceptual venue seam). Use a
`runtime_checkable Protocol` marker for the swap-a-fake live/sim boundary; use `abc.ABC`
(`fee_model` style) for the `Account` family inheritance axis. The two patterns are intentionally
split: ABC where there is shared implementation to inherit (cash→margin superset), Protocol where
there is only a structural contract (connector / venue caching seam).

## No Analog Found

None. Every file maps to an in-repo analog — this phase is deliberately pure code-motion behind the
existing `PortfolioReadModel` seam and reuses the established `fee_model`/`slippage_model`/`exchanges`
ABC+leaf and four-manager-subdir precedents. (RESEARCH was correctly flagged SKIP.)

## Metadata

**Analog search scope:** `itrader/portfolio_handler/` (cash/position/transaction/metrics, portfolio,
portfolio_handler), `itrader/execution_handler/` (fee_model, slippage_model, exchanges),
`itrader/core/portfolio_read_model.py`, `itrader/trading_system/`, `tests/unit/order/`.
**Files scanned:** ~12 read in full or targeted; indentation verified on 6.
**Pattern extraction date:** 2026-06-30
