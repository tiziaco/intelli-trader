# Phase 1: Engine Hygiene - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 8 (1 new-constant add, 1 test rewrite, 1 retype, 4 removal/edit, 1 verify-only)
**Analogs found:** 3 / 3 (only items 1, 4, 6 require an analog; items 2/3/5/7 are removals or doc edits — no analog needed)

> **Phase character:** This is a byte-exact hygiene cleanup. No NEW files are created. Items are edits/removals to existing files, plus one additive public constant. Pattern mapping matters only for items 1, 4, and 6 (where placement/naming/style must match house convention). Items 2, 3, 5, 7 are mechanical removals/doc-softening with no analog to copy.

## File Classification

| File | Item | Role | Data Flow | Edit Kind | Closest Analog | Match Quality |
|------|------|------|-----------|-----------|----------------|---------------|
| `itrader/core/money.py` | 6 | core / money-primitive | transform | add public constant `ONE` | `_DEFAULT_SCALES` / `to_money` (same file) | exact (in-file idiom) |
| `tests/unit/portfolio/test_position_manager.py` | 1 | test | request-response (assert) | rewrite private asserts → public API | sibling asserts already in same file + `PositionManager` public query surface | exact |
| `itrader/portfolio_handler/validators.py` | 4 | validator (dead code) | request-response | retype params + isinstance guards | `core/sizing.py` `_require_positive` (Decimal guard idiom) | role-match |
| `itrader/core/sizing.py` | 6 | core | transform | replace local `_ONE` with import | `to_money` import already present pattern | exact |
| `itrader/order_handler/sizing_resolver.py` | 6 | manager (order) | transform | replace local `_ONE` with import | existing `from itrader.core.money import to_money` (line 37) | exact |
| `itrader/order_handler/brackets/levels.py` | 6 | utility (order) | transform | replace `_ONE` + update docstring | `core/money.py` shape (its own docstring cites this) | exact |
| `itrader/portfolio_handler/portfolio.py` | 3 | handler | — | delete dead constant | — | removal, no analog |
| `pyproject.toml` | 2 | config | — | delete dead mypy override | — | removal, no analog |
| `itrader/order_handler/order_manager.py` | 5 | manager (order) | — | VERIFY-ONLY (already removed in 2ffbeb8) | — | no edit |
| `itrader/order_handler/reconcile/reconcile_manager.py` | 7 | manager (order) | — | soften docstring prose | — | doc-only, no analog |

---

## Pattern Assignments

### Item 6 — `itrader/core/money.py` : add public `ONE` constant (core, transform)

**Analog:** the existing module-level constants in the SAME file. `money.py` is the locked home for money primitives and a pure leaf (imports only `from decimal import Decimal, ROUND_HALF_UP`, line 25 — verified zero `itrader`-internal imports, so no cycle with `core/sizing.py` or `order_handler`).

**Indentation:** 4 SPACES. No `__all__` exists in `money.py` — nothing to update.

**Existing constant-placement pattern** (`core/money.py` lines 25-39):
```python
from decimal import Decimal, ROUND_HALF_UP

_DEFAULT_SCALES: dict[str, Decimal] = {
    "price": Decimal("0.01"),
    "quantity": Decimal("0.00000001"),
    "cash": Decimal("0.01"),
}

_INSTRUMENT_SCALES: dict[str, dict[str, Decimal]] = {
    ...
}
```

**Placement guidance:** add `ONE = Decimal("1")` as a public module constant in this top constant block (after line 25 `from decimal import ...`, alongside `_DEFAULT_SCALES`). Public name (no leading underscore) per D-02 — the `_`-prefix convention marks *module-private*; a cross-module shared constant must be public. String-path literal `Decimal("1")` per D-04 / money policy (never `Decimal(1.0)`).

---

### Item 6 — the three consumer sites: replace local `_ONE` with imported `ONE`

**a) `itrader/core/sizing.py`** (4 SPACES). Currently defines `_ZERO`/`_ONE` locally:

```python
# core/sizing.py lines 58-59 (current)
_ZERO = Decimal("0")
_ONE = Decimal("1")
```
- Add `from itrader.core.money import ONE` to the import block (lines 40-44; module does NOT currently import `core/money.py` — this is a NEW import line, safe, money is a leaf).
- Replace `_ONE` usage at line 72 (`if not (_ZERO < value <= _ONE):`) with `ONE`.
- **D-05: leave `_ZERO` (line 58) untouched** — single copy, no dedup target.

**b) `itrader/order_handler/sizing_resolver.py`** (imports = spaces; function BODIES = TABS). Already imports money:

```python
# sizing_resolver.py line 37 (existing import — ADD ONE here)
from itrader.core.money import to_money
# →  from itrader.core.money import ONE, to_money
```
```python
# sizing_resolver.py line 43 (current — DELETE)
_ONE = Decimal("1")
```
- Just append `ONE` to the existing `from itrader.core.money import to_money` import (line 37) — no new import line needed.
- Replace `_ONE` usage at line 161 with `ONE` (that line is inside a function body → **TABS**, `\t\t` indent — match it).

**c) `itrader/order_handler/brackets/levels.py`** (imports/constant = column 0; function body = TABS):

```python
# levels.py lines 19-23 (current)
from decimal import Decimal
from ...core.enums import Side
from ...core.sizing import SLTPPolicy

_ONE = Decimal("1")
```
- Add NEW import `from ...core.money import ONE` (file does not import money today).
- Delete the local `_ONE = Decimal("1")` (line 23).
- Replace four `_ONE` usages at lines 39-40 (`anchor * (_ONE + ...)` etc.) with `ONE` — these are inside the `_bracket_levels` function body → **TABS** (`\t\t`).

**LOAD-BEARING docstring residue (part of item 6, not optional — Pitfall 5):** the `levels.py` module docstring asserts `_ONE` is module-private and lives here. After consolidation this is false and re-introduces an item-7-style misleading doc. Update these lines:
```python
# levels.py lines 11-13 (current — now FALSE after consolidation)
`_ONE = Decimal("1")` is the module-private constant used ONLY by
`_bracket_levels`; it travels here with its sole consumer. ...

# levels.py lines 15-16 (current — now FALSE)
This module mirrors the `core/money.py` shape — a pure-function module plus a
leading-underscore module-level constant, no class, no state.
```
Soften to reflect that `ONE` now lives in `core/money.py` and is imported (exact prose = planner discretion).

---

### Item 1 — `tests/unit/portfolio/test_position_manager.py` : private asserts → public API (test)

**Analog A (house assertion style):** the file's OWN passing asserts. The test already mixes public-attribute asserts (`pm.max_total_positions == 100`, `position.ticker == "BTCUSDT"`) with the private `pm._storage.*` reaches — so the public-API target style is already demonstrated in-file. Indentation: 4 SPACES (test file).

**Current private pattern** (lines 62-63, 79-80 shown):
```python
assert len(pm._storage.get_positions()) == 0
assert len(pm._storage.get_closed_positions()) == 0
...
assert len(pm._storage.get_positions()) == 1
assert "BTCUSDT" in pm._storage.get_positions()
```

**Analog B (the public surface to copy):** `PositionManager` query methods, `position_manager.py` lines 257-270:
```python
def get_all_positions(self) -> Dict[str, Position]:
    """Get all active positions."""
    return self._storage.get_positions()

def get_closed_positions(self, limit: Optional[int] = None) -> List[Position]:
    """Get closed positions history."""
    ...

def get_position_count(self) -> int:
    """Get count of active positions."""
    return len(self._storage.get_positions())
```

**Substitution map (uniform, semantics-identical):**
| Private call | Public replacement |
|--------------|--------------------|
| `pm._storage.get_positions()` | `pm.get_all_positions()` |
| `pm._storage.get_closed_positions()` | `pm.get_closed_positions()` |

**Recommendation (RESEARCH-confirmed):** use `get_all_positions()` UNIFORMLY for the open-positions dict — it returns `Dict[str, Position]`, so it supports BOTH `len(...)` AND the membership assert on line 80 (`"BTCUSDT" in pm.get_all_positions()`). Do NOT substitute `get_position_count()` for line 80 — an `int` does not support `in`. The 14 occurrences across 11 assert lines (62, 63, 79, 80, 118, 135, 136, 148, 149, 354, 361, 362, 393, 426) all map mechanically. No test logic changes; no new assertions. Test-only → cannot move the golden master.

---

### Item 4 — `itrader/portfolio_handler/validators.py` : retype `validate_transaction_data` (validator, dead code)

**Analog (the Decimal-guard idiom):** `core/sizing.py` `_require_positive` (lines 62-67) shows the project's "validate a Decimal is positive" shape — but the closest *structural* analog is the method's own sibling guards, retyped. Indentation: **4 SPACES** (verified — predates the tab convention for `portfolio_handler/`).

**Current signature + guards** (`validators.py` lines 20-43):
```python
@staticmethod
def validate_transaction_data(
    ticker: str,
    price: float,
    quantity: float,
    commission: float,
    transaction_type: str
) -> None:
    ...
    if not isinstance(price, (int, float)) or price <= 0:
        raise InvalidTransactionError(f"Price must be positive, got {price}")

    if not isinstance(quantity, (int, float)) or quantity <= 0:
        raise InvalidTransactionError(f"Quantity must be positive, got {quantity}")

    if not isinstance(commission, (int, float)) or commission < 0:
        raise InvalidTransactionError(f"Commission must be non-negative, got {commission}")
```

**Required change (signature AND body — Pitfall 1):** retype `price`/`quantity`/`commission` to strict `Decimal` (D-06) AND change the three `isinstance(..., (int, float))` guards to `isinstance(..., Decimal)`. An annotation-only change that leaves the `(int, float)` guards would make a real `Decimal` arg fail and raise `InvalidTransactionError` — a latent trap.

**Style match:** the module already uses `import decimal` (line 5) and writes `decimal.Decimal('...')` (lines 13-14). Prefer `decimal.Decimal` for the annotations and guards to keep the diff stylistically consistent with the file (rather than adding `from decimal import Decimal`).

**Numeric-limit checks unchanged:** `price > 1_000_000` / `quantity > 1_000_000` (lines 49-52) compare `Decimal > int` — valid Python, no change.

**Scope discipline (D-07):** sibling methods (`validate_portfolio_data`'s `cash: float`, `PositionValidator.validate_position_consistency`'s float params, `to_decimal`/`from_decimal` helpers) are OUT OF SCOPE — item 4 names only `validate_transaction_data`. Method has zero callers → provably inert / byte-exact.

---

## Removal / Verify-Only Items (no analog needed)

### Item 2 — `pyproject.toml` : remove stale `screener_event_handler` mypy override
Removal only. Delete the `"itrader.events_handler.screener_event_handler"` entry + its 2 trailing comment-continuation lines (block lines 86-100, the entry near line 96). **Protect line 95** `"itrader.screeners_handler.*"` — still-live wildcard, different override (Pitfall 4). Config-only, no runtime effect.

### Item 3 — `itrader/portfolio_handler/portfolio.py` : delete `TOLERANCE = 1e-3`
Removal only. Line 26 (column-0 constant), repo-wide grep confirms sole hit / zero readers. File is TABS (handler module) but the deleted line is at column 0 — whole-line removal, no indentation hazard.

### Item 5 — `itrader/order_handler/order_manager.py` : dead `StrategyId` import
**VERIFY-ONLY — already removed in commit `2ffbeb8`.** Do NOT create an edit task (will no-op/error). Confirm `grep -n "StrategyId" order_manager.py` returns nothing. **Protect** `order.py` and `brackets/bracket_book.py` where `StrategyId` is still legitimately used (Pitfall 3).

### Item 7 — `itrader/order_handler/reconcile/reconcile_manager.py` : soften `TYPE_CHECKING` doc
Docstring prose only (module docstring lines ~23-26). No code change. State that the runtime `BracketBook` import (line 41) already pulls in the `brackets` package — so `BracketManager` loads at runtime regardless — and the `TYPE_CHECKING` guard only keeps the annotation NAME off runtime bindings, not the class load. Exact wording = planner discretion (D, IN-01). File is TABS; docstring prose lines are flush-left inside `"""..."""`.

---

## Shared Patterns

### Indentation map (CRITICAL — applies to every edited file)
| File | Convention | Note |
|------|-----------|------|
| `core/money.py` | 4 SPACES | item 6 constant add |
| `core/sizing.py` | 4 SPACES | item 6 import/usage |
| `tests/unit/portfolio/test_position_manager.py` | 4 SPACES | item 1 |
| `portfolio_handler/validators.py` | 4 SPACES | item 4 (predates tab convention for the package) |
| `order_handler/sizing_resolver.py` | imports = spaces; function bodies = TABS | item 6 (line 161 usage is `\t\t`) |
| `order_handler/brackets/levels.py` | imports/constant = column 0; function body = TABS | item 6 (lines 39-40 usage is `\t\t`) |
| `portfolio_handler/portfolio.py` | TABS | item 3 (deleted line column 0) |
| `order_handler/reconcile/reconcile_manager.py` | TABS | item 7 (docstring flush-left) |

**Rule:** match each file exactly, never normalize. A mixed-indent diff in a TAB file breaks the file (CLAUDE.md / CONVENTIONS line 46). Import-statement and column-0 constant edits carry no indentation; only wrapped/continued lines and in-body usages do.

### Money-primitive constant convention (item 6)
**Source:** `core/money.py` (`_DEFAULT_SCALES`, `to_money`), `CONVENTIONS.md` money policy.
**Apply to:** the new `ONE` constant.
- String-path literals only: `Decimal("1")`, never `Decimal(1.0)` (D-04).
- Module-private → leading underscore (`_ONE`, `_ZERO`); cross-module shared → public (`ONE`) (D-02).
- `core/money.py` is the locked home for money primitives; consolidate there, do not re-define per module.

### Public-API encapsulation (item 1)
**Source:** `PositionManager` query surface (`position_manager.py:253-270`).
**Apply to:** all `pm._storage.*` reaches in the test.
Tests assert through the documented public read surface — the entire point of the W3-07/NAME-04 encapsulation fix. Don't hand-roll a storage-reaching test helper.

---

## No Analog Found

| File | Item | Role | Reason |
|------|------|------|--------|
| `pyproject.toml` | 2 | config | mechanical removal — no pattern to copy |
| `portfolio_handler/portfolio.py` | 3 | handler | mechanical dead-constant removal |
| `order_handler/order_manager.py` | 5 | manager | verify-only, no edit |
| `order_handler/reconcile/reconcile_manager.py` | 7 | manager | docstring prose softening, no pattern |

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/portfolio_handler/`, `itrader/order_handler/`, `tests/unit/portfolio/`.
**Files read this session:** `core/money.py` (1-60), `core/sizing.py` (1-75), `portfolio_handler/validators.py` (1-55), `portfolio_handler/position/position_manager.py` (250-289), `tests/unit/portfolio/test_position_manager.py` (55-89), `order_handler/sizing_resolver.py` (35-44), `order_handler/brackets/levels.py` (1-41).
**Pattern extraction date:** 2026-06-12
