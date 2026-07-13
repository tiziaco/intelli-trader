"""Unit tests for the ``resolve_precision`` AbstractExchange capability (VENUE-04 / D-09).

``resolve_precision`` was relocated off the retired ``_OkxPrecisionResolver`` (LTS) onto the
exchange concretions, so precision is now a first-class venue capability beside
``validate_symbol``:

- ``OkxExchange.resolve_precision`` reads the loaded-markets ``precision`` map and builds an
  ``Instrument`` carrying Decimal price/quantity scales via ``core/money.precision_to_scale``
  (D-04 string entry). It returns ``None`` when markets aren't loaded (cold cache — never
  raises, threat T-05-06), the symbol is absent, or a precision entry is unusable, so the
  caller falls to ``Universe.apply``'s ``_DEFAULT_*`` ladder.
- ``SimulatedExchange.resolve_precision`` holds no markets map, so it returns ``None`` (the
  D-09 sensible default) — the caller lands on the default ladder, never a crash.
- Both concretions still satisfy the ``runtime_checkable`` ``AbstractExchange`` Protocol.

Offline only: a minimal fake connector exposes a synthetic ``client.markets`` map; no sockets
and no event loop are opened (``resolve_precision`` is fully synchronous).
"""

from decimal import Decimal
from queue import Queue
from typing import Any

import pytest

from itrader.core.instrument import Instrument
from itrader.execution_handler.exchanges.base import AbstractExchange
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

pytestmark = pytest.mark.unit


class _FakeClient:
    def __init__(self, markets: Any) -> None:
        self.markets = markets


class _FakeConnector:
    """Minimal fake exposing only the ``client.markets`` surface resolve_precision reads."""

    def __init__(self, markets: Any) -> None:
        self._client = _FakeClient(markets)

    @property
    def client(self) -> Any:
        return self._client


def _make_okx(markets: Any) -> OkxExchange:
    return OkxExchange(Queue(), _FakeConnector(markets))


def test_okx_resolve_precision_tick_size_entry_builds_instrument() -> None:
    # ccxt TICK_SIZE mode: precision entries are tick sizes -> Decimal scale directly.
    markets = {
        "BTC/USDT": {"precision": {"price": "0.1", "amount": "0.00000001"}},
    }
    inst = _make_okx(markets).resolve_precision("BTC/USDT")
    assert isinstance(inst, Instrument)
    assert inst.symbol == "BTC/USDT".upper()
    assert inst.price_precision == Decimal("0.1")
    assert inst.quantity_precision == Decimal("0.00000001")


def test_okx_resolve_precision_decimal_places_entry_builds_instrument() -> None:
    # A bare DECIMAL_PLACES count (2 / 8) resolves to a 1e-n scale.
    markets = {
        "ETH/USDT": {"precision": {"price": 2, "amount": 8}},
    }
    inst = _make_okx(markets).resolve_precision("ETH/USDT")
    assert isinstance(inst, Instrument)
    assert inst.price_precision == Decimal("1e-2")
    assert inst.quantity_precision == Decimal("1e-8")


def test_okx_resolve_precision_none_on_unloaded_markets() -> None:
    # Cold markets cache (non-dict) -> None, never raises (T-05-06).
    assert _make_okx(None).resolve_precision("BTC/USDT") is None


def test_okx_resolve_precision_none_on_absent_symbol() -> None:
    assert _make_okx({"BTC/USDT": {"precision": {"price": "0.1", "amount": "0.1"}}}).resolve_precision(
        "DOGE/USDT"
    ) is None


def test_okx_resolve_precision_none_on_unusable_precision_entry() -> None:
    # A non-positive / missing precision value makes the scale unresolvable -> None.
    markets = {"BTC/USDT": {"precision": {"price": "0", "amount": "0.1"}}}
    assert _make_okx(markets).resolve_precision("BTC/USDT") is None


def test_simulated_resolve_precision_returns_none() -> None:
    ex = SimulatedExchange(Queue())
    assert ex.resolve_precision("BTCUSD") is None


def test_both_concretions_satisfy_abstract_exchange_protocol() -> None:
    assert isinstance(SimulatedExchange(Queue()), AbstractExchange)
    assert isinstance(_make_okx({"BTC/USDT": {}}), AbstractExchange)
