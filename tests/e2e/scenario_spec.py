"""Shared E2E scenario value objects (Phase 6 foundational plan, D-13).

Promoted VERBATIM from the per-leaf ``tests/e2e/smoke/single_market_buy/scenario.py``
so the ``ScenarioSpec``/``PortfolioSpec`` contract — and the new ``actions``
timeline (D-06) — are defined ONCE and imported by every Phase 6-9 leaf, instead
of being re-declared in each ``scenario.py``. The harness (``conftest.py``) reads
these attributes BY NAME, so the existing field names are a consuming contract and
MUST NOT be renamed.

What this module adds over the promoted shape
---------------------------------------------
* ``ScenarioSpec.actions`` — an optional MODIFY/CANCEL timeline (default empty
  tuple). An empty ``actions`` is **oracle-inert**: the harness wires NO ``on_tick``
  hook, so the backtest run is byte-identical to today (D-06 oracle-darkness).
* ``Action`` — a frozen, predicate-resolved MODIFY/CANCEL instruction (D-07). It
  names its target by PREDICATE (ticker + the sole resting/PENDING order), NEVER by
  a literal ``Order.id`` (a non-deterministic UUIDv7). The harness resolves the
  target at the scheduled bar via the existing order-mirror query API and calls the
  REAL ``OrderHandler.modify_order``/``cancel_order`` (D-05 — faithful operator
  round-trip, mirrors live's ``TradingInterface``).

Indentation: 4 spaces (matches ``tests/conftest.py`` / the promoted source).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PortfolioSpec:
    """Minimal portfolio spec the harness reads (``user_id`` / ``name`` / ``cash``).

    The harness consumes these three attributes via ``add_portfolio``
    (``conftest._build_and_run``). A real ``PortfolioConfig`` is the richer Phase 7+
    form; scenarios need only the wiring trio (D-03 — reuse the real shape, no
    parallel sizing/fee schema here). Promoted verbatim from the Phase 4 canary.
    """

    user_id: int
    name: str
    cash: int


@dataclass(frozen=True)
class Action:
    """A scheduled MODIFY/CANCEL the harness plays as the OPERATOR (D-05/D-07).

    Predicate-resolved (D-07): the target is named by ``ticker`` + the sole resting
    (PENDING) order at ``bar_date``, never by a literal ``Order.id`` (UUIDv7 is
    non-deterministic). The harness resolves it via the existing query API and calls
    the REAL ``OrderHandler.modify_order``/``cancel_order`` round-trip — no raw
    ``OrderEvent(MODIFY/CANCEL)`` injection (that would skip ``OrderManager``
    validation, rejected by D-05).

    Parameters
    ----------
    bar_date : str
        ``"YYYY-MM-DD"`` — matched against ``time_event.time`` at the scheduled bar.
    kind : str
        ``"cancel"`` or ``"modify"``.
    ticker : str
        The predicate target (D-07) — the resting order on this ticker is amended.
    new_price, new_quantity : Decimal | None
        New resting price / quantity for a ``"modify"`` (ignored for ``"cancel"``).
    """

    bar_date: str
    kind: str
    ticker: str
    new_price: Decimal | None = None
    new_quantity: Decimal | None = None


@dataclass(frozen=True)
class ScenarioSpec:
    """The per-leaf scenario contract the ``run_scenario`` harness reads.

    Field names match EXACTLY what the harness consumes: ``start``, ``end``,
    ``timeframe``, ``data`` (ticker → CSV path), ``strategies``, ``portfolios``
    (each with ``user_id`` / ``name`` / ``cash``), ``exchange`` (None = zero-fee /
    no-slippage defaults), ``ticker``, ``starting_cash``.

    ``actions`` (D-06) defaults to an empty tuple — an empty timeline wires NO
    ``on_tick`` hook, so the run stays oracle-dark (byte-identical to today).
    """

    start: str
    end: str
    timeframe: str
    ticker: str
    starting_cash: int
    data: dict[str, Any]
    strategies: list[Any]
    portfolios: list[PortfolioSpec]
    exchange: Any = None
    actions: tuple[Action, ...] = field(default_factory=tuple)
