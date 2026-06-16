"""Liquidation forced-close mirror reconcile (LIQ-03) — Wave 0 stubs.

================================ WAVE 0 STUB — NOT YET IMPLEMENTED ================================
COLLECTIBLE skipped stubs satisfying the Nyquist sampling contract: the LIQ-03 mirror
selector must resolve >=1 test BEFORE the implementation RED step. The forced-close
order-mirror reconcile is implemented in plan 04-03; each test below is bodied with
`pytest.skip(...)` until then.

Test-only change — ZERO production code, so the SMA_MACD spot oracle stays byte-exact
(D-11, 134 / 46189.87730727451).

Selector this file satisfies (04-VALIDATION Per-Task Verification Map):
* `poetry run pytest tests/unit/order -k "liquidation"`  (LIQ-03 mirror reconcile)

LOCKED design these stubs pin (PROJECT.md / STATE.md Decisions):
* NO new `FillStatus` — the liquidation engine reuses `FillStatus.EXECUTED`; the forced
  close mints a real `strategy_id`/`order_id` order that bypasses admission, tagged
  `OrderTriggerSource.LIQUIDATION`, reconciling EXECUTED → FILLED through the existing path.
==================================================================================================

Folder-derived `unit` marker (tests/conftest.py applies it; no decorator here). Must
collect cleanly under `filterwarnings=["error"]` / `--strict-markers` — no reference-engine
import (NEVER `backtesting`/`backtrader`).
"""

import pytest

_SKIP = "Wave 0 stub — implemented in 04-03"


def test_liquidation_reconcile_executed_to_filled():
    """LIQ-03: a forced-close fill reconciles the order mirror EXECUTED → FILLED through
    the existing reconcile path (no new FillStatus — reuse EXECUTED)."""
    pytest.skip(_SKIP)


def test_liquidation_trigger_source():
    """LIQ-03: the minted forced-close order is tagged `OrderTriggerSource.LIQUIDATION`
    so the trade log distinguishes it from a strategy-driven close."""
    pytest.skip(_SKIP)


def test_no_new_fill_status():
    """LIQ-03 (LOCKED design): liquidation introduces NO new `FillStatus` member — the
    forced close rides `FillStatus.EXECUTED`."""
    pytest.skip(_SKIP)


def test_unregistered_order_no_ops_mirror():
    """LIQ-03 (Pitfall 4 guard): a forced-close fill for an order absent from the mirror
    must no-op the reconcile rather than raise / corrupt state."""
    pytest.skip(_SKIP)
