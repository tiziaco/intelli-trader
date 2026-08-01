"""CF-7 typed fail-loud guard + ReconciliationCoordinator startup sequence (07-02, SAFE-05).

Two concerns pinned here:

* **CF-7** — ``VenueReconciler._relink_bracket`` must raise a typed
  ``ReconciliationError`` (not a silent ``KeyError``/naked coercion) when a matched venue
  resting-order payload carries no coercible ``'id'``. The error message references ONLY
  the leg id, never the full venue payload (ASVS V7 / T-07-09). Tests carry ``cf7`` in
  their name so ``pytest -k cf7`` selects exactly this arm.
* **Coordinator** — ``ReconciliationCoordinator.run_startup_reconcile`` owns the startup
  ``rehydrate -> venue-reconcile -> baseline-guard`` sequence, driven off the account
  manager's ONLINE RECORDS. The discriminator is whether a record carries a live
  connector, NOT ``exchange == 'okx'`` and NOT an account-kind predicate: a record with no
  connector (paper) NEVER constructs a ``VenueReconciler``, while a record with one whose
  account shows an unexplained base-asset residual latches HALT via the injected callable
  with the FIXED literal ``HaltReason.BASELINE_RESIDUAL.value`` (never ``str(exc)``,
  V7 / T-07-01).

Credential-free synchronous doubles (no event loop, no async warnings under
``filterwarnings=["error"]``). 4-space indentation (matches ``tests/unit/*`` + the
``reconcile/`` production siblings); NO ``__init__.py`` in this dir (auto-memory:
same-named-package collision hazard).
"""

import queue
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import HaltReason, OrderStatus, OrderType, Side
from itrader.core.exceptions import ReconciliationError
from itrader.core.exceptions.base import ITraderError
from itrader.core.ids import PortfolioId, StrategyId
from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.order_handler.order import Order
from itrader.portfolio_handler.reconcile import venue_reconciler as vr_module
from itrader.portfolio_handler.reconcile.reconciliation_coordinator import (
    ReconciliationCoordinator,
)
from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

_SYMBOL = "BTC/USDC"
_VENUE = "okx"
_NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- shared doubles


class _SyncConnector:
    """Minimal ``LiveConnector`` double: ``call`` returns its (already-computed) arg."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def call(self, value: Any) -> Any:
        return value


class _FakeStore:
    """Minimal rehydratable store double exposing the reconcile working set."""

    def __init__(self, orders: Optional[List[Order]] = None) -> None:
        self._orders = orders if orders is not None else []
        self.updated: List[Order] = []

    def rehydrate(self) -> None:
        pass

    def get_active_orders(self, _portfolio_id: Any) -> List[Order]:
        return [o for o in self._orders if o.is_active]

    def get_order_by_id(self, order_id: Any, *_args: Any) -> Optional[Order]:
        for order in self._orders:
            if order.id == order_id:
                return order
        return None

    def update_order(self, order: Order) -> bool:
        self.updated.append(order)
        return True


def _make_order(**overrides: Any) -> Order:
    """Build an active BTC/USDC ``Order`` (overridable per field)."""
    base: Dict[str, Any] = dict(
        time=_NOW,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker=_SYMBOL,
        action=Side.BUY,
        price=Decimal("42000"),
        quantity=Decimal("1.0"),
        exchange="okx",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=PortfolioId(uc.uuid7()),
    )
    base.update(overrides)
    return Order(**base)


def _relink_reconciler(orders: List[Order]) -> VenueReconciler:
    """A VenueReconciler over synchronous fakes for the _relink_bracket CF-7 path.

    ``adapter=None`` is a legitimate value (the correlation-map adopt guard-clauses on
    it) and ``_relink_bracket`` reads only the store and the handed-in venue payload, so
    no venue read is reachable from this arm.
    """
    return VenueReconciler(
        store=_FakeStore(orders),
        adapter=None,
        connector=_SyncConnector(),
        global_queue=queue.Queue(),
        halt_signal=lambda _reason: None,
    )


# ================================================================ CF-7 guard


def test_cf7_reconciliation_error_is_itrader_error():
    """ReconciliationError subclasses the ITraderError root (typed, catchable domain error)."""
    assert issubclass(ReconciliationError, ITraderError)


def test_cf7_relink_bracket_raises_on_missing_id():
    """A matched venue resting payload with no 'id' fails loud with ReconciliationError."""
    child = _make_order()
    parent = _make_order(child_order_ids=[child.id])
    reconciler = _relink_reconciler([parent, child])
    # Resting order matches the leg on symbol+side+price+qty but carries NO 'id' key —
    # the fallback attribute match returns it, and the CF-7 guard must trip.
    resting = [{"symbol": _SYMBOL, "side": "buy", "price": 42000, "amount": 1.0}]

    with pytest.raises(ReconciliationError) as exc_info:
        reconciler._relink_bracket(parent, resting, {})

    # The message references the leg id, NEVER the full venue payload (V7 scrub).
    message = str(exc_info.value)
    assert str(child.id) in message
    assert "amount" not in message and "price" not in message


def test_cf7_relink_bracket_succeeds_with_id():
    """A matched resting payload WITH an 'id' re-links cleanly (no false positive)."""
    child = _make_order()
    parent = _make_order(child_order_ids=[child.id])
    reconciler = _relink_reconciler([parent, child])
    resting = [{"id": "venue-123", "symbol": _SYMBOL, "side": "buy",
                "price": 42000, "amount": 1.0}]

    assert reconciler._relink_bracket(parent, resting, {}) is True
    assert child.venue_order_id == "venue-123"


# ================================================================ coordinator


class _FakeAdapter:
    """Execution-adapter double — the ONE object that can read its account's venue truth.

    ``snapshot()`` answers a real ``AccountSnapshot`` and counts its calls, which is what
    makes "one venue read per account, hoisted out of the per-symbol loop" observable:
    the read is a REST round trip now, so a per-symbol re-read would both multiply the
    request count and let two symbols be judged against two different pictures of the
    venue. FLAT is an ABSENT key here, matching the snapshot contract.
    """

    def __init__(self, positions: Optional[Dict[str, Decimal]] = None) -> None:
        self._positions = dict(positions) if positions else {}
        self.snapshot_calls = 0

    def snapshot(self) -> AccountSnapshot:
        self.snapshot_calls += 1
        return AccountSnapshot(balances={}, positions=dict(self._positions))

    def adopt_venue_correlation(self, _order: Order) -> None:
        pass


def _record(*, adapter: Any, connector: Any = None,
            venue: str = _VENUE, account_id: str = "acct-1") -> Any:
    """One ``OnlineAccount``-shaped record: a spec pair, its adapter and its session.

    ``connector=None`` is the PAPER shape — a record with no venue session behind it.
    That is the discriminator the coordinator keys off, so the paper/live distinction is
    expressed here exactly as the account manager expresses it.
    """
    return SimpleNamespace(
        spec=SimpleNamespace(venue_name=venue, account_id=account_id),
        adapter=adapter,
        connector=connector,
    )


def _live_record(*, positions: Optional[Dict[str, Decimal]] = None,
                 account_id: str = "acct-1") -> Any:
    """A record with a live connector; returns it with its own adapter attached."""
    return _record(adapter=_FakeAdapter(positions),
                   connector=_SyncConnector(),
                   account_id=account_id)


class _FakePortfolio:
    """Minimal portfolio double: the record-pair identity + canned open positions."""

    def __init__(self, open_qty: Decimal = Decimal("0"),
                 open_positions: Optional[Dict[str, Decimal]] = None,
                 account_id: str = "acct-1",
                 name: str = "pf") -> None:
        self.name = name
        self.portfolio_id = name
        self.account_id = account_id
        self.venue_name = _VENUE
        self.exchange = _VENUE
        self._open = (
            open_positions if open_positions is not None
            else ({_SYMBOL: open_qty} if open_qty else {}))

    def get_open_position(self, ticker: str) -> Any:
        qty = self._open.get(ticker, Decimal("0"))
        if qty == 0:
            return None
        return type("_Pos", (), {"net_quantity": qty})()


class _FakePortfolioHandler:
    """Portfolio-handler double: active portfolios + drift precision + rehydrate spy."""

    def __init__(self, portfolios: List[_FakePortfolio],
                 precisions: Optional[Dict[str, int]] = None) -> None:
        self._portfolios = portfolios
        self.rehydrate_calls = 0
        # A per-symbol precision map, not a flat constant. A double that returns the same
        # precision for every symbol cannot observe whether the resolution moved INSIDE
        # the per-symbol loop, so that gate would be unfalsifiable against it.
        self._precisions = precisions or {}

    def get_active_portfolios(self) -> List[_FakePortfolio]:
        return self._portfolios

    def _drift_precision(self, ticker: str) -> int:
        return self._precisions.get(ticker, 8)

    def rehydrate(self, _seed_hook: Any) -> None:
        self.rehydrate_calls += 1


class _FakeExecutionHandler:
    """Pair-keyed exchange registry double — ``exchanges[(venue, account_id)]``."""

    def __init__(self, exchanges: Optional[Dict[Any, Any]] = None) -> None:
        self.exchanges: Dict[Any, Any] = exchanges or {}


def _build_coordinator(*, portfolios: List[_FakePortfolio],
                       halt_calls: List[str],
                       records: Optional[List[Any]] = None,
                       precisions: Optional[Dict[str, int]] = None,
                       exchanges: Optional[Dict[Any, Any]] = None,
                       ) -> ReconciliationCoordinator:
    """Construct the coordinator on its records-driven signature.

    ``records`` is a CALLABLE read at use time (accounts come online at runtime), and it
    is the only source of accounts. Note what is absent: no ``venue_account``, no
    ``connector``, no ``exchange`` scalar — each record carries its own adapter and its
    own connector.
    """
    handler = _FakePortfolioHandler(portfolios, precisions)
    supplied = list(records) if records else []
    return ReconciliationCoordinator(
        portfolio_handler=handler,
        seed_applied_trades=lambda _keys: None,
        order_storage=_FakeStore(),
        global_queue=queue.Queue(),
        halt=halt_calls.append,
        records=lambda: supplied,
    )


def _spy_reconciler(monkeypatch) -> List[Dict[str, Any]]:
    """Patch ``VenueReconciler`` with a spy; return the list of constructor kwargs."""
    constructed: List[Dict[str, Any]] = []

    class _SpyReconciler:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

        def reconcile(self) -> None:
            pass

    monkeypatch.setattr(vr_module, "VenueReconciler", _SpyReconciler)
    return constructed


# ---------------------------------------------------------------- no scalar collaborators


def test_coordinator_refuses_a_scalar_venue_account_parameter():
    """The scalar ``venue_account`` parameter is GONE — passing one is a TypeError.

    Asserted executably rather than by grep. A ``grep -c 'venue_account'`` over the
    module can never reach 0 (prose in the docstring alone would keep it non-zero), so a
    count-based criterion would be permanently false-red or, worse, tuned until it was
    false-green. A TypeError is unambiguous.
    """
    with pytest.raises(TypeError):
        ReconciliationCoordinator(
            portfolio_handler=_FakePortfolioHandler([]),
            seed_applied_trades=lambda _keys: None,
            order_storage=_FakeStore(),
            global_queue=queue.Queue(),
            halt=lambda _r: None,
            venue_account=object(),
        )


def test_coordinator_refuses_scalar_connector_and_exchange_parameters():
    """``connector`` and ``exchange`` are refused too — all THREE per-account scalars.

    ``exchange`` matters as much as the other two: it used to feed the reconciler's
    correlation-map repopulation, so leaving it would make portfolio B's reconcile write
    into account **A's** correlation map — the exact cross-account write the records-keyed
    shape makes unexpressible.
    """
    for kwarg in ("connector", "exchange"):
        with pytest.raises(TypeError):
            ReconciliationCoordinator(
                portfolio_handler=_FakePortfolioHandler([]),
                seed_applied_trades=lambda _keys: None,
                order_storage=_FakeStore(),
                global_queue=queue.Queue(),
                halt=lambda _r: None,
                **{kwarg: object()},
            )


def test_coordinator_paper_record_skips_venue_reconcile(monkeypatch):
    """A record with NO connector (paper) runs rehydrate but constructs NO VenueReconciler.

    The discriminator is the presence of a venue session, so a durable paper engine still
    gets its ledger restored while nothing tries to reconcile it against a venue that
    does not exist — and its adapter is never asked for a snapshot it cannot take.
    """
    constructed = _spy_reconciler(monkeypatch)

    adapter = _FakeAdapter()
    record = _record(adapter=adapter, connector=None)
    portfolio = _FakePortfolio()
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    coordinator.run_startup_reconcile()

    assert coordinator._portfolio_handler.rehydrate_calls == 1
    assert constructed == []          # no VenueReconciler behind a connector-less record
    assert adapter.snapshot_calls == 0
    assert halt_calls == []           # no baseline halt on the paper path


def test_coordinator_live_record_runs_reconcile(monkeypatch):
    """A record with a live connector constructs exactly one VenueReconciler over ITS pair."""
    constructed = _spy_reconciler(monkeypatch)

    # Venue flat (an absent key) AND engine flat → the baseline guard is a clean no-op.
    record = _live_record(positions={})
    portfolio = _FakePortfolio(open_qty=Decimal("0"))
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    coordinator.run_startup_reconcile()

    assert len(constructed) == 1                 # exactly one VenueReconciler
    # The reconciler reads THIS record's adapter and THIS record's connector.
    assert constructed[0]["adapter"] is record.adapter
    assert constructed[0]["connector"] is record.connector
    # The baseline guard took the account's ONE venue read.
    assert record.adapter.snapshot_calls == 1
    assert halt_calls == []                      # flat/flat → no residual halt


def test_coordinator_no_online_records_is_a_clean_noop(monkeypatch):
    """The empty edge: nothing online, so nothing reconciled, nothing reported, no halt.

    This is the backtest/paper answer as well as the pre-first-account live answer — the
    default records source reports nothing, and reporting nothing must never halt.
    """
    constructed = _spy_reconciler(monkeypatch)
    halt_calls: List[str] = []
    coordinator = _build_coordinator(portfolios=[], halt_calls=halt_calls)

    coordinator.run_startup_reconcile()

    assert coordinator._portfolio_handler.rehydrate_calls == 1
    assert constructed == []
    assert halt_calls == []


def test_coordinator_never_compares_portfolio_a_against_account_b(monkeypatch):
    """THE cross-account gate: each portfolio is judged against ITS OWN account's truth.

    The explicit negative. With a scalar account collaborator, portfolio B was compared
    against account A's positions — and it looked completely healthy, because the
    reconcile ran, the halt fired or did not, and nothing named which account had been
    read. Here account A is flat while account B holds 1.0, and each portfolio's engine
    belief MATCHES ITS OWN account. A cross-comparison would report two residuals; a
    correct per-record scan reports none.
    """
    constructed = _spy_reconciler(monkeypatch)

    record_a = _live_record(positions={}, account_id="acct-a")
    record_b = _live_record(
        positions={_SYMBOL: Decimal("1.0")}, account_id="acct-b")
    pf_a = _FakePortfolio(open_qty=Decimal("0"), account_id="acct-a", name="pf-a")
    pf_b = _FakePortfolio(open_qty=Decimal("1.0"), account_id="acct-b", name="pf-b")

    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[pf_a, pf_b], halt_calls=halt_calls,
        records=[record_a, record_b])

    coordinator.run_startup_reconcile()

    # Each record was reconciled exactly once, with its own adapter and its own connector.
    assert [k["adapter"] for k in constructed] == [
        record_a.adapter, record_b.adapter]
    assert [k["connector"] for k in constructed] == [
        record_a.connector, record_b.connector]
    # Every portfolio matches its OWN account, so nothing is unexplained. Compare
    # portfolio A against account B and BOTH would look like residuals.
    assert halt_calls == []


def test_coordinator_reconciles_with_the_records_own_adapter(monkeypatch):
    """The reconcile target comes from the RECORD, never from a second lookup.

    The pair-keyed exchange registry here maps this record's pair to a DIFFERENT object.
    Resolving the adapter through the registry instead of off the record reintroduces a
    second source of truth for "which adapter owns this account's session", and the two
    disagreeing is a silent cross-account write rather than a visible failure.
    """
    constructed = _spy_reconciler(monkeypatch)

    record = _live_record(account_id="acct-a")
    registry_impostor = _FakeAdapter()
    portfolio = _FakePortfolio(account_id="acct-a", name="pf-a")
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=[], records=[record],
        exchanges={(_VENUE, "acct-a"): registry_impostor})

    coordinator.run_startup_reconcile()

    assert [k["adapter"] for k in constructed] == [record.adapter]
    assert registry_impostor.snapshot_calls == 0


# ------------------------------------------------- the baseline guard scan


def test_coordinator_baseline_residual_halts_with_fixed_literal(monkeypatch):
    """An unexplained base-asset residual latches HALT with the FIXED literal reason (V7)."""
    _spy_reconciler(monkeypatch)

    # Venue holds 1.0 BTC but the engine believes it holds 0 → unexplained residual.
    record = _live_record(positions={_SYMBOL: Decimal("1.0")})
    portfolio = _FakePortfolio(open_qty=Decimal("0"))
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    coordinator.run_startup_reconcile()

    assert halt_calls == [HaltReason.BASELINE_RESIDUAL.value]
    assert halt_calls[0] == "baseline-residual"
    # The reason is a FIXED literal — no venue payload, no stringified exception (V7).
    assert "BTC" not in halt_calls[0] and "1.0" not in halt_calls[0]


def test_baseline_guard_scans_every_symbol_the_account_holds(monkeypatch):
    """Three held symbols → all three checked, off ONE venue read, not one configured symbol."""
    _spy_reconciler(monkeypatch)

    record = _live_record(positions={
        "BTC/USDC": Decimal("1.0"),
        "ETH/USDC": Decimal("2.0"),
        "SOL/USDC": Decimal("3.0"),
    })
    portfolio = _FakePortfolio(open_positions={})   # engine believes it holds nothing
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=[], records=[record])

    residuals = coordinator._run_session_baseline_guard()

    assert [r.symbol for r in residuals] == ["BTC/USDC", "ETH/USDC", "SOL/USDC"]
    # ONE snapshot for the three symbols: the venue read is a REST round trip, and two
    # symbols judged against two different pictures of the venue is not one comparison.
    assert record.adapter.snapshot_calls == 1


def test_baseline_guard_reports_a_residual_in_an_unsubscribed_symbol(monkeypatch):
    """The closed blind spot — a residual in a symbol the system never streams.

    The guard used to read ONE globally configured symbol
    (``config.stream.okx_stream_symbol``), so an unexplained holding in any other symbol
    was invisible. That is arguably the exposure most worth knowing about, which is why
    the narrower union-of-subscribed-symbols scope was rejected.
    """
    _spy_reconciler(monkeypatch)

    unsubscribed = "DOGE/USDC"
    assert unsubscribed != _SYMBOL
    record = _live_record(positions={unsubscribed: Decimal("500")})
    portfolio = _FakePortfolio(open_positions={})
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    residuals = coordinator._run_session_baseline_guard()

    assert [r.symbol for r in residuals] == [unsubscribed]
    assert halt_calls == [HaltReason.BASELINE_RESIDUAL.value]


def test_baseline_guard_resolves_precision_per_instrument_inside_the_loop(monkeypatch):
    """A per-symbol epsilon, not one loop-invariant value.

    The construction is the point. Both symbols carry the SAME 0.001 delta. At precision
    3 the band is 0.001 and the delta is reconciled; at precision 8 the band is 1e-8 and
    the same delta is drift. Hoisting the resolution outside the loop applies whichever
    symbol happens to be first to BOTH — producing either a false reconciliation of ETH
    or a false drift report on BTC, depending on iteration order.
    """
    _spy_reconciler(monkeypatch)

    record = _live_record(positions={
        "BTC/USDC": Decimal("1.001"),   # precision 3 → band 0.001 → RECONCILED
        "ETH/USDC": Decimal("2.001"),   # precision 8 → band 1e-8  → DRIFT
    })
    portfolio = _FakePortfolio(open_positions={
        "BTC/USDC": Decimal("1.000"),
        "ETH/USDC": Decimal("2.000"),
    })
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=[], records=[record],
        precisions={"BTC/USDC": 3, "ETH/USDC": 8})

    residuals = coordinator._run_session_baseline_guard()

    assert [r.symbol for r in residuals] == ["ETH/USDC"]


def test_baseline_guard_evaluates_every_account_before_deciding(monkeypatch):
    """Three accounts, the FIRST and THIRD mismatch — BOTH are reported.

    The scan used to ``return`` right after the first halt call. This cannot be observed
    through ``halt_calls``: halt takes a fixed literal, so one halt looks exactly like one
    halt whether the scan stopped early or ran to completion. The collected result record
    is what makes the fix falsifiable at all.
    """
    _spy_reconciler(monkeypatch)

    def _pair(name: str, venue_qty: Decimal, engine_qty: Decimal) -> tuple:
        # FLAT is an absent key, so a clean account reports no position at all.
        positions = {_SYMBOL: venue_qty} if venue_qty else {}
        record = _live_record(positions=positions, account_id=name)
        portfolio = _FakePortfolio(
            open_positions=({_SYMBOL: engine_qty} if engine_qty else {}),
            account_id=name, name=name)
        return record, portfolio

    first = _pair("pf-1", Decimal("1.0"), Decimal("0"))     # mismatch
    second = _pair("pf-2", Decimal("0"), Decimal("0"))      # clean
    third = _pair("pf-3", Decimal("5.0"), Decimal("0"))     # mismatch
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[first[1], second[1], third[1]], halt_calls=halt_calls,
        records=[first[0], second[0], third[0]])

    residuals = coordinator._run_session_baseline_guard()

    assert [r.portfolio_id for r in residuals] == ["pf-1", "pf-3"]
    assert [r.account_id for r in residuals] == ["pf-1", "pf-3"]
    # One latched halt for the completed scan — halt is engine-wide, so N calls would be
    # N writes of one state. What matters is that the SCAN saw both.
    assert halt_calls == [HaltReason.BASELINE_RESIDUAL.value]


def test_baseline_guard_treats_exactly_equal_as_reconciled(monkeypatch):
    """Adjacency edge: engine == venue is reconciled, documented not incidental."""
    _spy_reconciler(monkeypatch)

    record = _live_record(positions={_SYMBOL: Decimal("1.25")})
    portfolio = _FakePortfolio(open_positions={_SYMBOL: Decimal("1.25")})
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    assert coordinator._run_session_baseline_guard() == []
    assert halt_calls == []


def test_baseline_guard_tolerance_boundary_is_inclusive(monkeypatch):
    """Adjacency edge: exactly AT the band is reconciled; one ulp beyond is not.

    ``is_within_single_unit_tolerance`` uses ``<=``, so the boundary is INCLUSIVE. Both
    sides are asserted — an exclusive implementation would pass the second assertion
    alone, so testing only the drift side would not pin the boundary at all.
    """
    _spy_reconciler(monkeypatch)

    def _residuals(venue_qty: str) -> List[Any]:
        record = _live_record(positions={_SYMBOL: Decimal(venue_qty)})
        portfolio = _FakePortfolio(open_positions={_SYMBOL: Decimal("1.00")})
        coordinator = _build_coordinator(
            portfolios=[portfolio], halt_calls=[], records=[record],
            precisions={_SYMBOL: 2})
        return coordinator._run_session_baseline_guard()

    # precision 2 → band 0.01. Exactly at the band: reconciled (inclusive).
    assert _residuals("1.01") == []
    # One least-significant unit beyond the band: a residual.
    assert len(_residuals("1.02")) == 1


def test_baseline_guard_zero_positions_is_a_benign_noop(monkeypatch):
    """Empty edge: an account holding nothing reports nothing, halts nothing."""
    _spy_reconciler(monkeypatch)

    record = _live_record(positions={})
    portfolio = _FakePortfolio()
    halt_calls: List[str] = []
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=halt_calls, records=[record])

    assert coordinator._run_session_baseline_guard() == []
    assert halt_calls == []


def test_baseline_guard_reads_no_global_configuration(monkeypatch):
    """The global ``config.stream`` read is absent from this per-account path.

    Pinned behaviourally rather than by grep: the guard must find a residual in a symbol
    the global configuration does not name, using an account whose positions map does not
    contain the configured symbol at all. An implementation still reading
    ``config.stream.okx_stream_symbol`` would look up a symbol the account never holds,
    default it to 0, and report nothing.
    """
    from itrader import config as _system_config

    _spy_reconciler(monkeypatch)
    configured = _system_config.stream.okx_stream_symbol

    held = {"XRP/USDC": Decimal("7")}
    assert configured not in held
    record = _live_record(positions=held)
    portfolio = _FakePortfolio(open_positions={})
    coordinator = _build_coordinator(
        portfolios=[portfolio], halt_calls=[], records=[record])

    assert [r.symbol for r in coordinator._run_session_baseline_guard()] == ["XRP/USDC"]
