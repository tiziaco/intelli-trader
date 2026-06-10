"""Order-mirror snapshot serializer for the E2E orders golden (Phase 6, D-08).

The opt-in counterpart to ``itrader.reporting.frames`` — for matching scenarios
whose ASSERTION is the final order-mirror state, not a closed trade (OCO
sibling-cancel, MODIFY/CANCEL, never-fill, bracket child states). Joins the same
reporting serializer family: pandas + stdlib only, a DUCK-TYPED ``orders`` input
(``Order``-shaped objects, NO handler import), the same rows→DataFrame→sort→reset
idiom, and ``float(...)`` only at the serialization edge (Decimal stays internal).

Determinism contract (D-08)
---------------------------
Business columns ONLY: ``role``, ``ticker``, ``order_type``, ``action``,
``status``, ``price``, ``quantity``, ``filled_quantity``, ``time``. The UUIDv7
``id``/``event_id`` and wall-clock ``created_at``/``updated_at`` are EXCLUDED
(non-deterministic). Bracket linkage is expressed as a logical ENTRY/SL/TP role
derived from ``parent_order_id``/``child_order_ids`` flags — never the raw UUIDs.
Rows are sorted by a stable business key (not by UUID insertion order).

GAP #1 (load-bearing): there is NO ``OrderStatus.ACTIVE``. A resting / never-filled
order serializes as ``PENDING`` via ``o.status.name`` — the golden + VERIFY note
must write ``PENDING``, never ``ACTIVE``.

Indentation: 4 spaces (reporting package house style).
"""

from typing import Any, Literal

import pandas as pd

from itrader.core.enums.order import OrderType

# IN-01: load-bearing identity label for the orders golden — a serialization-edge
# string (like the sibling ``.name`` columns), not a domain enum. Annotated as a
# Literal so mypy verifies every branch of ``_order_role`` produces a valid label.
OrderRole = Literal["ENTRY", "STANDALONE", "SL", "TP"]

# Deterministic order-snapshot columns (D-08) — business fields only, NO UUID,
# NO wall-clock. ``role`` is the logical bracket linkage (ENTRY/SL/TP/STANDALONE).
ORDER_SNAPSHOT_COLUMNS = [
    "role",
    "ticker",
    "order_type",
    "action",
    "status",
    "price",
    "quantity",
    "filled_quantity",
    "time",
]


def _order_role(order: Any) -> OrderRole:
    """Derive the logical bracket role from linkage flags (D-08).

    A parentless order is an ``ENTRY`` when it declares children (a bracket
    parent) or ``STANDALONE`` otherwise; a child order is the ``SL`` (STOP leg) or
    ``TP`` (LIMIT leg). Uses linkage FLAGS, never the raw UUIDs.

    IN-01: ``role`` is a load-bearing identity column in a TRUSTED regression
    baseline. A child can only be STOP or LIMIT today (both bracket paths use
    ``Order.new_stop_order``/``new_limit_order``), so we map STOP→SL, LIMIT→TP
    explicitly and ``raise`` on anything else — a loud, located failure beats
    silently relabelling an unexpected child type (e.g. a future trailing-stop
    leg) as ``"TP"`` and freezing a wrong row into the golden.
    """
    if order.parent_order_id is None:
        return "ENTRY" if order.child_order_ids else "STANDALONE"
    if order.type is OrderType.STOP:
        return "SL"
    if order.type is OrderType.LIMIT:
        return "TP"
    raise ValueError(
        f"Unexpected child order type {order.type!r} for bracket role "
        f"(id={order.id})")


def build_orders_snapshot(orders: Any) -> pd.DataFrame:
    """Serialize the order mirror to a deterministic business-columns frame (D-08).

    ``orders`` is a duck-typed list of ``Order``-shaped objects (the harness passes
    ``order_handler.get_orders_by_ticker(...)``). Empty-safe; sorted by a stable
    business key so row order is reproducible. Decimal money → ``float`` only here
    at the serialization edge.
    """
    rows = [{
        "role": _order_role(o),
        "ticker": o.ticker,
        "order_type": o.type.name,
        "action": o.action,
        # GAP #1: never-filled => "PENDING" (there is NO OrderStatus.ACTIVE).
        "status": o.status.name,
        "price": float(o.price),
        "quantity": float(o.quantity),
        "filled_quantity": float(o.filled_quantity),
        "time": o.time,
    } for o in orders]
    frame = pd.DataFrame(rows, columns=ORDER_SNAPSHOT_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["role", "order_type", "action", "price"]).reset_index(drop=True)
    return frame
