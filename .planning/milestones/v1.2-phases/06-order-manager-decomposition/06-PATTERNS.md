# Phase 6: Order-Manager Decomposition - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 11 new + 3 modified (1 pure-internal rewire + 2 unchanged-by-mandate barrels)
**Analogs found:** 11 / 11 (every new file mirrors a verified `portfolio_handler/` analog)

> This is a **pure code-motion** phase (D-00/D-13). Every new collaborator file is filled
> with code MOVED VERBATIM from `itrader/order_handler/order_manager.py`. The analogs below
> dictate the *shape of the container* (folder + `__init__.py` re-export + manager-class
> skeleton + injection wiring), NOT the *content* — content is the byte-exact moved code.
>
> **THE LOAD-BEARING DIRECTIVE OF THIS WHOLE PHASE:**
> `order_manager.py` is **TAB-indented** (1159 TAB / 0 SPACE lines, verified). The
> `portfolio_handler/` template `cash_manager.py` is **4-SPACE** (0 TAB / 479 SPACE, verified).
> **Mirror the portfolio LAYOUT, never its WHITESPACE.** Every file holding code moved out of
> `order_manager.py` MUST be **TAB-indented**. Re-indenting moved code to spaces is the single
> worst failure mode in this phase (RESEARCH Pitfall 1) — it turns a clean move into a
> whole-line rewrite and can produce a non-importable mixed-indent Python file.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `order_handler/admission/admission_manager.py` | manager (collaborator) | request-response (signal→order pipeline) | `portfolio_handler/cash/cash_manager.py` | role-match (manager-class shape) | **TAB** |
| `order_handler/admission/__init__.py` | barrel (re-export) | — | `portfolio_handler/cash/__init__.py` | exact | 4-space ok |
| `order_handler/brackets/bracket_manager.py` | manager (collaborator) | transform (bracket assembly) | `portfolio_handler/cash/cash_manager.py` | role-match | **TAB** |
| `order_handler/brackets/bracket_book.py` | model / state-wrapper primitive | CRUD (in-memory map) | `_PendingBracket` (`order_manager.py:34-52`) + `CashOperation` dataclass (`cash_manager.py:23-42`) | role-match (thin value-state wrapper) | **TAB** |
| `order_handler/brackets/levels.py` | utility (stateless helper) | transform (pure function) | `core/money.py` module-level helpers (pure fns + `_`-prefixed module constant) | partial (no exact stateless-helper analog in order/portfolio) | **TAB** |
| `order_handler/brackets/__init__.py` | barrel (re-export) | — | `portfolio_handler/position/__init__.py` (multi-symbol re-export) | exact | 4-space ok |
| `order_handler/reconcile/reconcile_manager.py` | manager (collaborator) | event-driven (FILL reconcile, FRAGILE) | `portfolio_handler/cash/cash_manager.py` | role-match | **TAB** |
| `order_handler/reconcile/__init__.py` | barrel (re-export) | — | `portfolio_handler/cash/__init__.py` | exact | 4-space ok |
| `order_handler/lifecycle/lifecycle_manager.py` | manager (collaborator) | request-response (modify/cancel verbs) | `portfolio_handler/cash/cash_manager.py` | role-match | **TAB** |
| `order_handler/lifecycle/__init__.py` | barrel (re-export) | — | `portfolio_handler/cash/__init__.py` | exact | 4-space ok |
| `tests/unit/order/test_bracket_book.py` | test (new, lean) | — | `tests/unit/order/test_sltp_policy.py` / `test_order_manager.py` | role-match | **4-SPACE** (new test code) |
| `order_handler/order_manager.py` | coordinator (MODIFIED — internals rewired) | orchestration | self (its own `__init__` + read delegators stay) | self | **TAB** (already) |
| `order_handler/__init__.py` | barrel (MODIFIED: **UNCHANGED** per D-12) | — | `portfolio_handler/__init__.py` (managers NOT top-exported) | exact | leave as-is |
| `order_handler/order_handler.py` | handler/facade (UNCHANGED — queue seam) | event-driven | self | self | **TAB** (already) |

---

## Pattern Assignments

### `order_handler/admission/__init__.py` (barrel, single-symbol re-export)

**Analog:** `portfolio_handler/cash/__init__.py` — EXACT pattern to copy.

**Re-export excerpt** (`cash/__init__.py:1-10`):
```python
"""
Cash subdomain package.

Re-exports the public cash manager + its CashOperation entity so consumer import
paths stay short after the D-11 subdomain reorg (pure move, no behavior change).
"""

from .cash_manager import CashManager, CashOperation

__all__ = ["CashManager", "CashOperation"]
```

**Apply to `admission/__init__.py`:**
```python
"""
Admission subdomain package.

Re-exports the AdmissionManager (signal->order pipeline) so consumer import
paths stay short after the order-manager decomposition (pure move, D-12/D-13).
"""

from .admission_manager import AdmissionManager

__all__ = ["AdmissionManager"]
```

> **Indentation:** this tiny barrel has no nested blocks beyond the docstring + imports —
> 4-space (like `cash/__init__.py`) is harmless (RESEARCH Pitfall 1, Assumption A1).
> Same template applies verbatim to `reconcile/__init__.py` (→ `ReconcileManager`) and
> `lifecycle/__init__.py` (→ `LifecycleManager`).

---

### `order_handler/brackets/__init__.py` (barrel, MULTI-symbol re-export)

**Analog:** `portfolio_handler/position/__init__.py` — the multi-symbol re-export variant.

**Re-export excerpt** (`position/__init__.py:1-12`):
```python
"""
Position subdomain package.

Re-exports the public position entity + manager so consumer import paths stay
short after the D-11 subdomain reorg (pure move, no behavior change).
"""

from itrader.core.enums import PositionSide
from .position import Position
from .position_manager import PositionManager

__all__ = ["Position", "PositionSide", "PositionManager"]
```

**Apply to `brackets/__init__.py`** (re-exports the manager + the `BracketBook` primitive; `_PendingBracket` stays internal — leading-underscore — so it is NOT in `__all__`):
```python
"""
Brackets subdomain package.

Re-exports the BracketManager + the BracketBook pending-bracket state owner
(D-04/D-05). The stateless levels helper and _PendingBracket stay internal.
"""

from .bracket_manager import BracketManager
from .bracket_book import BracketBook

__all__ = ["BracketManager", "BracketBook"]
```

---

### `order_handler/admission/admission_manager.py` (manager collaborator)

**Analog:** `portfolio_handler/cash/cash_manager.py` — the manager-class skeleton (imports block,
class docstring, `__init__` that receives injected deps + holds them as instance attrs, binds a
component logger, NO queue access).

**Class-shape excerpt** (`cash_manager.py:45-60`):
```python
class CashManager:
    """
    Manages portfolio cash operations with high precision.
    ...
    """

    def __init__(self, portfolio: Any, initial_cash: float | Decimal = 0.0) -> None:
        self.portfolio = portfolio
        # D-19: lock removed — single-writer contract, see Portfolio docstring.
        self.logger = get_itrader_logger().bind(component="CashManager")
```

**The pattern to replicate (NOT the body):** receive injected deps in `__init__`, store as
`self.<dep>`, bind a logger, expose business methods, **never touch `global_queue`**. Per D-09
the injected dep subset for `AdmissionManager` is:
`order_storage`, `logger`, `order_validator`, `sizing_resolver`, `portfolio_handler` (read-model),
`commission_estimator`, the `BracketBook`, and the bracket-assembly seam
(`BracketManager`-or-`levels` import).

**Content moved VERBATIM from `order_manager.py` (TAB-indented), per the verified bucket map:**
- `_estimate_commission` (`:128-137`)
- `process_signal` (`:289-466`) — entry point, relocates INTACT (D-07)
- `create_orders_from_signal` (`:468-511`) — entry point, INTACT (D-07)
- `_get_signal_exchange` (`:513-519`)
- `_build_primary_order` (`:521-566`) — D-15 open question RESOLVED to `admission/` (all 3 callers admission)
- `_enforce_direction_admission` (`:808-870`)
- `_enforce_position_admission` (`:872-962`)
- `_resolve_signal_quantity` (`:964-1060`)
- `_reject_unsized_signal` (`:1062-1101`)

**Imports the moved code needs** (carry from `order_manager.py:14-29`): `to_money` (`..core.money`),
`PortfolioReadModel`, `OrderStorage`, `EnhancedOrderValidator`, `SizingResolver`, `Order`,
`OperationResult`, `OrderEvent`/`SignalEvent`, the `core.enums` + `core.sizing` symbols those
methods reference.

> **INDENTATION DIRECTIVE — `admission_manager.py` = TAB.** The source methods are TAB-indented
> (`order_manager.py` is 1159 TAB / 0 SPACE). Paste them TAB-indented. Do NOT copy
> `cash_manager.py`'s 4-space style — that template gives you the class *skeleton shape*, not the
> whitespace for moved bodies.

---

### `order_handler/brackets/bracket_manager.py` (manager collaborator)

**Analog:** `portfolio_handler/cash/cash_manager.py` (same manager-class skeleton as above).

**Injected deps (D-09):** `order_storage`, `logger`, `BracketBook`, `levels` (import).

**Content moved VERBATIM from `order_manager.py` (TAB):**
- `_assemble_bracket_and_emit` (`:568-737`) — arms the book at `:640`, disarms at `:729`, uses `assert_never` (`:650`)
- `_create_fill_anchored_children` (`:755-806`) — built here (bracket concern), **imported by `reconcile/`** per D-08 (see Shared Patterns / cross-bucket seam below)

**Imports to carry:** `assert_never` (`typing`), `to_money`, plus the `_bracket_levels` call now
resolved via `from .levels import _bracket_levels` (D-08).

> **INDENTATION DIRECTIVE — `bracket_manager.py` = TAB.** Moved bodies stay TAB.

---

### `order_handler/brackets/bracket_book.py` (state-wrapper primitive + `_PendingBracket`)

**Analog (container shape):** the `_PendingBracket` frozen dataclass itself (`order_manager.py:34-52`,
moves here verbatim per D-03) plus the `CashOperation` dataclass shape in `cash_manager.py:23-42` —
a thin value type co-located with its manager.

**`_PendingBracket` moves VERBATIM (do NOT retype `action: str` → `Side`; that is W2-02, deferred to
999.5 per D-13).** Source excerpt (`order_manager.py:34-52`, TAB):
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class _PendingBracket:
	"""Context for a PercentFromFill bracket awaiting its parent's fill (D-13).
	...
	"""

	policy: PercentFromFill
	ticker: str
	action: str
	quantity: Decimal
	exchange: str
	strategy_id: StrategyId
	portfolio_id: PortfolioId
```

**`BracketBook` is the genuinely-NEW primitive (D-05).** No existing class is a 1:1 analog — it is a
thin wrapper over `Dict[OrderId, _PendingBracket]` whose methods are **byte-equal to the current dict
ops** at the 8 verified sites. The closest precedent for "thin owner-class around a dict with named
methods" is the manager-owns-its-state pattern in `cash_manager.py` (its `_balance` / storage seam).

**The 8 `_pending_brackets` sites the wrapper must preserve byte-equal** (RESEARCH §site map):

| Current dict op | `BracketBook` method | Semantics |
|-----------------|---------------------|-----------|
| `self._pending_brackets = {}` (`:126`) | `BracketBook()` ctor | empty book |
| `.pop(order_id, None)` (`:240`, `:249`, `:729`, `:1231`) | `consume(order_id)` | read-and-remove, **`None` on miss (idempotent)** |
| `.get(order.id)` (`:1164`) | `get(order_id)` | read, no remove, `None` on miss |
| `[primary.id] = _PendingBracket(...)` (`:640`) | `arm(order_id, bracket)` | write |
| `[order.id] = replace(pending, quantity=...)` (`:1166-67`) | `refresh_quantity(order_id, qty)` | get→replace→set (modify path) |

**CRITICAL — dict-compat dunders (RESEARCH Pitfall 2, A3):** `test_sltp_policy.py` reaches into
`_pending_brackets` as a raw dict at 4 sites (`== {}` ×3 at lines 208/249/272; `order_id in ...` at
265). Since D-14 keeps facade tests untouched and this test is internal-attribute-coupled, the
recommended path is to give `BracketBook` `__eq__` (compares wrapped dict, so `book == {}` works),
`__contains__`, and `__len__` — keeping the test green WITHOUT editing it (move-inherent per D-13).

**Illustrative shape (D-15 discretion on signatures; behavior must be 1:1; TAB-indented):**
```python
# brackets/bracket_book.py — TAB-indented
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Dict, Optional
from ..core.ids import OrderId

class BracketBook:
	def __init__(self) -> None:
		self._pending: Dict[OrderId, "_PendingBracket"] = {}

	def arm(self, order_id: OrderId, bracket: "_PendingBracket") -> None:
		self._pending[order_id] = bracket

	def get(self, order_id: OrderId) -> "Optional[_PendingBracket]":
		return self._pending.get(order_id)

	def consume(self, order_id: OrderId) -> "Optional[_PendingBracket]":
		return self._pending.pop(order_id, None)        # idempotent on miss

	def refresh_quantity(self, order_id: OrderId, quantity: Decimal) -> None:
		pending = self._pending.get(order_id)
		if pending is not None:
			self._pending[order_id] = replace(pending, quantity=quantity)

	def __eq__(self, other: object) -> bool:            # Pitfall 2 — keep test_sltp_policy green
		if isinstance(other, dict):
			return self._pending == other
		if isinstance(other, BracketBook):
			return self._pending == other._pending
		return NotImplemented

	def __contains__(self, order_id: object) -> bool:
		return order_id in self._pending

	def __len__(self) -> int:
		return len(self._pending)
```

> **INDENTATION DIRECTIVE — `bracket_book.py` = TAB.** `_PendingBracket` is moved TAB code; the
> `BracketBook` wrapper sits beside it in the same TAB file. Keep the whole file TAB.

---

### `order_handler/brackets/levels.py` (stateless helper, D-08)

**Analog:** no exact in-domain analog (order/portfolio have no standalone stateless-helper module).
Closest precedent is `core/money.py` — a module of pure functions plus a leading-underscore
module-level constant (`_ONE = Decimal("1")`-style). The pattern: module docstring + the
`_`-prefixed constant + the pure function, no class, no state.

**Content moved VERBATIM from `order_manager.py` (TAB):**
- `_bracket_levels` (`:739-753`) — pure function, called by BOTH `_assemble_bracket_and_emit` (brackets) AND `_create_fill_anchored_children` (also brackets, invoked from reconcile). Extracted stateless so neither `admission` nor `reconcile` needs a `brackets`-collaborator ref (D-08).
- `_ONE = Decimal("1")` (`order_manager.py:31`) — module-private constant used ONLY by `_bracket_levels` (`:752-753`); it MUST travel here.

> **INDENTATION DIRECTIVE — `levels.py` = TAB.** Moved function body stays TAB.

---

### `order_handler/reconcile/reconcile_manager.py` (manager collaborator — FRAGILE, LAST)

**Analog:** `portfolio_handler/cash/cash_manager.py` (manager-class skeleton).

**Injected deps (D-09):** `order_storage`, `logger`, `portfolio_handler` (for `release`), the
`BracketBook`, the `_create_fill_anchored_children` brackets import, and the `cancel_order` lifecycle
seam (see cross-bucket note below).

**Content moved VERBATIM from `order_manager.py` (TAB) — `on_fill` (`:139-287`), as ONE indivisible
unit (D-07, criterion 2).** This is the FRAGILE span. The `should_release`/`try`/`finally` interplay
is byte-for-byte unchanged:

| Concern | Line | Note |
|---------|------|------|
| `should_release = False` (init, before `try`) | `:173` | guards non-terminal early-return |
| `body_raised = False` | `:174` | distinguishes body-raise vs release-raise in `finally` |
| unknown-status early `return` (holds reservation) | `:205` | `should_release` still `False` — INTENTIONAL |
| `should_release = True` (arm, after terminal status) | `:208` | set BEFORE further work so a later raise still releases |
| WR-05 orphaned-child cancel → `self.cancel_order(...)` | `:223-231` | **cross-bucket → lifecycle** |
| `pending = self._pending_brackets.pop(order_id, None)` | `:240` | EXECUTED → `book.consume(order_id)` |
| `self._create_fill_anchored_children(...)` | `:247` | **cross-bucket → brackets import** |
| `self._pending_brackets.pop(order_id, None)` (discard) | `:249` | → `book.consume(order_id)` |
| `finally:` + idempotent `release` (T-05-17) | `:262-273` | the release-in-finally invariant |
| inner release-failure `except`, re-raise only if `not body_raised` (WR-03) | `:274-286` | never mask original |

**The ONLY edits permitted to the moved `on_fill` block** (RESEARCH mandate, line 170):
(a) `self._pending_brackets.pop(...)` → `self._brackets.consume(...)`;
(b) `self.cancel_order(...)` → coordinator-callback delegation (see cross-bucket seam, A2);
(c) `self._create_fill_anchored_children(...)` → injected brackets helper/import.
**No reordering of the `should_release` set/consume. Indentation stays TAB.**

> **INDENTATION DIRECTIVE — `reconcile_manager.py` = TAB.** This is the most-scrutinized move;
> a re-indent here is unrecoverable without the golden oracle. TAB, verbatim.

---

### `order_handler/lifecycle/lifecycle_manager.py` (manager collaborator, D-01 4th bucket)

**Analog:** `portfolio_handler/cash/cash_manager.py` (manager-class skeleton).

**Injected deps (D-09):** `order_storage`, `logger`, `order_validator`, `portfolio_handler` (for
`release`), the `BracketBook`.

**Content moved VERBATIM from `order_manager.py` (TAB):**
- `modify_order` (`:1103-1189`) — uses `BracketBook.get` (`:1164`) + `refresh_quantity` (`:1166-67`, wraps `replace`); needs the `replace` import (`dataclasses`)
- `cancel_order` (`:1191-1263`) — uses `BracketBook.consume` (`:1231`); **called cross-bucket from `on_fill`** (`:227`)

> **INDENTATION DIRECTIVE — `lifecycle_manager.py` = TAB.** Moved bodies stay TAB.

---

### `tests/unit/order/test_bracket_book.py` (NEW lean unit test, D-15)

**Analog:** `tests/unit/order/test_sltp_policy.py` / `test_order_manager.py` — the order unit-test
house style (both **4-SPACE**, verified: 195 / 380 space lines, 0 tabs).

**Assertions (D-15 + RESEARCH Wave 0):** `arm`+`get` round-trip; `consume` returns the entry AND
removes it; `consume` on a missing key returns `None` (idempotent); `refresh_quantity` replaces only
`quantity` and preserves the other `_PendingBracket` fields; and the dict-compat dunders (`== {}`,
`in`, `len`) if the Pitfall-2 option (a) is taken.

> **INDENTATION DIRECTIVE — `test_bracket_book.py` = 4-SPACE.** This is the ONE file that is
> NEW-CODE-not-moved-code, so it follows the `tests/` house style (4-space), NOT the TAB rule that
> governs the moved production code. (RESEARCH Wave 0 note line 434.)

---

### `order_handler/order_manager.py` (MODIFIED — coordinator, internals rewired)

**Analog:** `portfolio_handler/portfolio.py::_init_managers` (`:83-97`) — the coordinator that OWNS
the shared state seam and constructs each manager once, injecting the shared dep.

**Coordinator-injection excerpt** (`portfolio.py:83-97`, note: `portfolio.py` is TAB — matches the
order side, unlike the space-indented `cash_manager.py`):
```python
	def _init_managers(self, initial_cash: float | Decimal) -> None:
		"""Initialize portfolio managers. ..."""
		self.state_storage: PortfolioStateStorage = PortfolioStateStorageFactory.create("backtest")
		self.cash_manager = CashManager(self, initial_cash=initial_cash)
		self.transaction_manager = TransactionManager(self)
		self.position_manager = PositionManager(self)
		self.metrics_manager = MetricsManager(self)
```

**Current `OrderManager.__init__` wiring to preserve + extend** (`order_manager.py:104-126`, TAB):
```python
		self.order_storage = order_storage
		self.logger = logger
		self.market_execution = MarketExecution(market_execution)
		self.portfolio_handler = portfolio_handler
		self.commission_estimator = commission_estimator
		self.order_validator = EnhancedOrderValidator(portfolio_handler) if portfolio_handler else None
		self.sizing_resolver = SizingResolver(portfolio_handler) if portfolio_handler else None
		self._pending_brackets: Dict[OrderId, _PendingBracket] = {}     # → BracketBook()
```

**Rewire to (the D-04 coordinator-owned star):** construct ONE `BracketBook` (replacing `:126`),
then construct the 4 collaborators passing each its dep subset:
```python
		self._brackets = BracketBook()
		self.bracket_manager = BracketManager(order_storage, logger, self._brackets)
		self.admission_manager = AdmissionManager(order_storage, logger, self.order_validator,
		                                          self.sizing_resolver, portfolio_handler,
		                                          commission_estimator, self._brackets, ...)
		self.lifecycle_manager = LifecycleManager(order_storage, logger, self.order_validator,
		                                          portfolio_handler, self._brackets)
		self.reconcile_manager = ReconcileManager(order_storage, logger, portfolio_handler,
		                                          self._brackets, ...)
```

**WHAT STAYS on `OrderManager` (D-02/D-06/D-07):**
- External ctor signature UNCHANGED (5 args) — `OrderHandler` builds it identically (`order_handler.py:73-79`); `TradingSystem`/`LiveTradingSystem` untouched.
- The 7 read delegators (`:1269-1295`) stay — `OrderHandler.get_X` keeps delegating here (D-18/D-02). No `queries/` folder.
- Public `process_signal` / `create_orders_from_signal` / `on_fill` / `modify_order` / `cancel_order` become **1-line delegations** into the collaborators (so `test_order_manager.py:21`'s direct import stays valid — RESEARCH Pitfall 4).

> **INDENTATION DIRECTIVE — `order_manager.py` stays TAB** (it already is; do not normalize).

---

### `order_handler/__init__.py` (MODIFIED label, but **UNCHANGED** per D-12)

**Analog:** `portfolio_handler/__init__.py` — exports ONLY `PortfolioHandler` / `Portfolio`; the
cash/position/transaction/metrics managers are NOT top-barrel-exported (they are `Portfolio`
internals).

**The directive:** `order_handler/__init__.py` must keep exporting only
`OrderHandler` / `Order` / `OrderType` / `OrderStatus` / `OrderStorage` / storage. The four new
collaborators + `BracketBook` are `OrderManager` implementation details and **MUST NOT** be added to
the top barrel. Leave this file BYTE-UNCHANGED.

---

## Shared Patterns

### Manager-class skeleton (every collaborator)
**Source:** `portfolio_handler/cash/cash_manager.py:45-60`
**Apply to:** `AdmissionManager`, `BracketManager`, `ReconcileManager`, `LifecycleManager`
Receive injected deps in `__init__`, store as `self.<dep>`, bind
`self.logger = get_itrader_logger().bind(component="...")` (or accept the injected `logger` —
`OrderManager` already passes a `logger` ref, mirror what it does), expose business methods, **NO
`global_queue` access** (D-06/D-18). Unprefixed `<Domain>Manager` names (D-12).

### `__init__.py` re-export
**Source:** `portfolio_handler/cash/__init__.py:8` (single) / `position/__init__.py:8-12` (multi)
**Apply to:** all four collaborator barrels — short docstring + `from .X import Y` + `__all__`.

### Coordinator-owned shared-state star (D-04/D-09)
**Source:** `portfolio_handler/portfolio.py:83-97` (`_init_managers`)
**Apply to:** `OrderManager.__init__` — construct ONE `BracketBook`, inject it into the three
collaborators that touch shared bracket state (`brackets`, `reconcile`, `lifecycle`). No collaborator
reaches into another's state; all depend on the coordinator-owned `BracketBook`.

### Cross-bucket seam inside FRAGILE `on_fill` (D-08, RESEARCH Pitfall 3 — the trickiest wiring)
**Source:** `on_fill` calls `self.cancel_order` (`:227`, lifecycle) and
`self._create_fill_anchored_children` (`:247`, brackets).
**Apply to:** `ReconcileManager` MUST NOT hold sibling `LifecycleManager`/`BracketManager` refs
(that is the D-08 red flag + a circular-import risk). Recommended (A2):
- `cancel_order` → route through a **coordinator callback** (`OrderManager` owns all collaborators), preserving the star topology.
- `_create_fill_anchored_children` → place in `brackets/` as an importable helper taking its deps as args; reconcile **imports** it, not the manager.
The planner MUST lock this in the LAST extraction step (D-10 step 5).

### Decision-tag module docstrings (D-13)
**Source convention:** every `order_manager.py` / `portfolio` module opens with a docstring citing
load-bearing decision tags.
**Apply to:** each new collaborator's module docstring cites the tags the moved code carries
(D-13 PercentFromFill, WR-03/WR-04, T-05-17, T-07-15, RESEARCH Pattern 5). Moved methods keep their
existing in-body tag comments verbatim.

### Money entry-point import (carry on every collaborator)
**Source:** `order_manager.py:23` `from ..core.money import to_money`
**Apply to:** admission/brackets/reconcile/lifecycle all reference `to_money` — each new module needs
this import (verified sites: `:185,186,633,772,1005,1152,1153,1167`). NEVER `Decimal(float)`.

---

## No Analog Found

Every new file maps to a `portfolio_handler/` analog for its container shape. The one file with no
*exact* in-repo analog is the genuinely-new primitive:

| File | Role | Data Flow | Reason / Fallback |
|------|------|-----------|-------------------|
| `brackets/bracket_book.py::BracketBook` | model / state-wrapper | CRUD | No existing thin dict-wrapper-with-named-methods class. Use the derived 1:1 wrapper shape (RESEARCH §Code Examples / this doc) — behavior must be byte-equal to the 8 dict-op sites; signatures are D-15 discretion. |
| `brackets/levels.py` | stateless utility | transform | No standalone stateless-helper module in order/portfolio. Closest precedent: pure-function modules like `core/money.py` (pure fns + `_`-prefixed module constant). |

---

## Metadata

**Analog search scope:** `itrader/order_handler/`, `itrader/portfolio_handler/` (+ subdirs), `tests/unit/order/`
**Files scanned (read/grep):** `order_manager.py` (head + `__init__` + `_PendingBracket`),
`order_handler/__init__.py`, `cash/cash_manager.py`, `cash/__init__.py`, `position/__init__.py`,
`portfolio_handler/__init__.py`, `portfolio.py`; indentation grep across 8 source files + 2 test files.
**Indentation facts (verified this session):** `order_manager.py` 1159 TAB / 0 SPACE;
`order_handler.py` 297 TAB / 0 SPACE; `portfolio.py` 415 TAB / 0 SPACE; `cash_manager.py` 0 TAB /
479 SPACE; `base.py`/`order_validator.py`/`sizing_resolver.py` all SPACE;
`test_sltp_policy.py`/`test_order_manager.py` 4-SPACE.
**Pattern extraction date:** 2026-06-11
