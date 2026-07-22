"""
Consolidated PortfolioHandler tests combining legacy and enhanced functionality.
"""

import threading
import uuid
from queue import Queue
from datetime import datetime, UTC
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import pytest

# Import the portfolio classes
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.portfolio import Portfolio, Position
from itrader.portfolio_handler.account import SimulatedMarginAccount
from itrader.core.enums import PortfolioState, PositionSide
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge


def _margin_config(max_leverage: str = "10") -> PortfolioConfig:
    """enable_margin=True config — maintenance_margin / margin_ratio delegate to
    the margin leaf, which 01-03 selects at construction (a spot leaf returns
    Decimal('0') for these); set margin in the constructor config."""
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal(max_leverage)}},
    ))
from itrader.core.exceptions import (
    PortfolioNotFoundError, PortfolioValidationError, StateError,
)
from itrader.events_handler.events import FillEvent, PortfolioErrorEvent
from itrader.core.enums import FillStatus, Side

import uuid_utils.compat as uuid_compat


def _fill_event(ticker, action, price, quantity, commission, portfolio_id, time=None):
    """Construct-complete fill with the D-12 required linkage ids."""
    return FillEvent(
        time=time or datetime.now(), status=FillStatus.EXECUTED, ticker=ticker,
        action=action, price=price, quantity=quantity, commission=commission,
        portfolio_id=portfolio_id, fill_id=uuid_compat.uuid7(),
        order_id=uuid_compat.uuid7(), strategy_id=1,
    )


# Legacy-compatibility test data.
_PORTFOLIO_NAME = "test_pf"
_EXCHANGE = "paper"
_CASH = 150000


@pytest.fixture
def env():
    """A PortfolioHandler (test environment) + its global queue."""
    global_queue = Queue()
    handler = PortfolioHandler(
        global_queue=global_queue,
        config_dir="settings",
        environment="test",
    )
    yield SimpleNamespace(global_queue=global_queue, handler=handler)
    while not global_queue.empty():
        global_queue.get_nowait()


# ===================
# PORTFOLIO CREATION & BASIC OPERATIONS
# ===================


def test_add_portfolio(env):
    """Test basic portfolio creation (legacy compatibility)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Assert if the portfolio has been created (ids are now native UUIDv7)
    assert env.handler.get_portfolio_count() == 1
    assert isinstance(portfolio_id, uuid.UUID)


def test_get_portfolio(env):
    """Test portfolio retrieval (legacy compatibility)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)
    portfolio = env.handler.get_portfolio(portfolio_id)

    assert isinstance(portfolio, Portfolio)
    assert portfolio.portfolio_id == portfolio_id
    assert portfolio.name == _PORTFOLIO_NAME
    assert portfolio.cash == _CASH


def test_portfolio_creation_success(env):
    """Test successful portfolio creation with enhanced features."""
    portfolio_id = env.handler.add_portfolio(
        name="Test Portfolio", exchange="NYSE", cash=10000.0
    )

    assert isinstance(portfolio_id, uuid.UUID)

    portfolio = env.handler.get_portfolio(portfolio_id)
    assert portfolio.name == "Test Portfolio"
    assert portfolio.exchange == "NYSE"
    assert portfolio.cash == 10000.0
    assert portfolio.state == PortfolioState.ACTIVE
    assert portfolio.is_active()
    assert portfolio.can_trade()


def test_portfolio_creation_with_custom_config(env):
    """Test portfolio creation with custom configuration."""
    from itrader.config.portfolio import PortfolioLimits, ValidationSettings

    custom_config = PortfolioConfig(
        name="Custom Config Portfolio",
        limits=PortfolioLimits(max_positions=50, max_position_value=Decimal("500000")),
        validation=ValidationSettings(validate_transactions=True),
    )

    portfolio_id = env.handler.add_portfolio(
        name="Custom Config Portfolio", exchange="NASDAQ",
        cash=25000.0, portfolio_config=custom_config,
    )

    portfolio = env.handler.get_portfolio(portfolio_id)
    assert portfolio.config.limits.max_positions == 50
    assert portfolio.config.limits.max_position_value == Decimal("500000")
    assert portfolio.config.validation.validate_transactions


def test_portfolio_creation_invalid_cash(env):
    """Test portfolio creation with invalid cash amount."""
    with pytest.raises(PortfolioValidationError):
        env.handler.add_portfolio(
            name="Invalid Portfolio", exchange="NYSE", cash=-1000.0
        )


def test_portfolio_not_found_error(env):
    """Test getting non-existent portfolio."""
    with pytest.raises(PortfolioNotFoundError):
        env.handler.get_portfolio(99999)


# ===================
# PORTFOLIO STATE MANAGEMENT
# ===================


def test_portfolio_state_management(env):
    """Test portfolio state transitions."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)
    portfolio = env.handler.get_portfolio(portfolio_id)

    # Test initial state
    assert portfolio.state == PortfolioState.ACTIVE

    # Test state transition to INACTIVE
    assert portfolio.set_state(PortfolioState.INACTIVE, "Testing")
    assert portfolio.state == PortfolioState.INACTIVE
    assert not portfolio.is_active()
    assert not portfolio.can_trade()

    # Test state transition back to ACTIVE
    assert portfolio.set_state(PortfolioState.ACTIVE, "Reactivating")
    assert portfolio.state == PortfolioState.ACTIVE

    # Test archiving
    assert portfolio.set_state(PortfolioState.ARCHIVED, "Archiving")
    assert portfolio.state == PortfolioState.ARCHIVED

    # Test that archived portfolios cannot transition
    # FL-01: set_state now raises the typed StateError (was bare ValueError).
    with pytest.raises(StateError):
        portfolio.set_state(PortfolioState.ACTIVE, "Cannot reactivate archived")


def test_portfolio_deletion_with_state_validation(env):
    """Test portfolio deletion with proper state validation."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)

    # Withdraw all cash to allow deletion
    portfolio = env.handler.get_portfolio(portfolio_id)
    portfolio.account.withdraw(portfolio.account.balance, "Test withdrawal")

    # Delete portfolio (should archive first)
    assert env.handler.delete_portfolio(portfolio_id)

    # Verify portfolio is deleted
    with pytest.raises(PortfolioNotFoundError):
        env.handler.get_portfolio(portfolio_id)


def test_active_portfolios_filtering(env):
    """Test filtering active portfolios."""
    p1 = env.handler.add_portfolio("Active1", "NYSE", 10000.0)
    p2 = env.handler.add_portfolio("Active2", "NYSE", 20000.0)
    p3 = env.handler.add_portfolio("Inactive", "NYSE", 15000.0)

    # Make one inactive
    portfolio3 = env.handler.get_portfolio(p3)
    portfolio3.set_state(PortfolioState.INACTIVE)

    active_portfolios = env.handler.get_active_portfolios()
    active_ids = [p.portfolio_id for p in active_portfolios]

    assert len(active_portfolios) == 2
    assert p1 in active_ids
    assert p2 in active_ids
    assert p3 not in active_ids


# ===================
# FILL EVENT PROCESSING
# ===================


def test_buy_fill(env):
    """Test buy fill event processing (legacy compatibility)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Bought 1 BTC over one filled event from the execution handler
    buy_fill = _fill_event("BTCUSDT", Side.BUY, 40000, 1, 0, portfolio_id)
    env.handler.on_fill(buy_fill)
    portfolio = env.handler.get_portfolio(portfolio_id)
    position = portfolio.positions["BTCUSDT"]

    assert len(portfolio.positions) == 1
    assert len(portfolio.closed_positions) == 0
    assert len(portfolio.transactions) == 1
    assert portfolio.cash == 110000
    assert portfolio.total_equity == 150000
    assert portfolio.total_market_value == 40000
    assert portfolio.total_pnl == 0
    assert portfolio.total_realised_pnl == 0
    assert portfolio.total_unrealised_pnl == 0
    assert isinstance(position, Position)
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == portfolio_id
    assert position.is_open is True
    assert position.side == PositionSide.LONG


def test_sell_fill(env):
    """Test sell fill event processing (legacy compatibility - SHORT position)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Sold 1 BTC (short position) over one filled event from the execution handler
    sell_fill = _fill_event("BTCUSDT", Side.SELL, 40000, 1, 0, portfolio_id)
    env.handler.on_fill(sell_fill)
    portfolio = env.handler.get_portfolio(portfolio_id)
    position = portfolio.positions["BTCUSDT"]

    assert len(portfolio.positions) == 1
    assert len(portfolio.closed_positions) == 0
    assert len(portfolio.transactions) == 1
    assert portfolio.cash == 190000  # Started with 150k, sold short for 40k = 190k
    assert portfolio.total_equity == 150000  # Short offsets cash increase
    assert portfolio.total_market_value == -40000  # Negative because short is a liability
    assert portfolio.total_pnl == 0
    assert portfolio.total_realised_pnl == 0
    assert portfolio.total_unrealised_pnl == 0
    assert isinstance(position, Position)
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == portfolio_id
    assert position.is_open is True
    assert position.side == PositionSide.SHORT


def test_fill_event_processing_success(env):
    """Test successful fill event processing (enhanced)."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)

    fill_event = _fill_event("AAPL", Side.BUY, 50.0, 100, 1.0, portfolio_id,
                             time=datetime.now(UTC))

    # D-10: on_fill is raise/None — success means no exception raised.
    env.handler.on_fill(fill_event)

    portfolio = env.handler.get_portfolio(portfolio_id)
    assert portfolio.n_open_positions == 1
    assert portfolio.cash < 10000.0  # Cash should be reduced


def test_on_fill_returns_none(env):
    """D-10 contract propagation: on_fill is raise/None — no bool channel."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 100000.0)
    fill_event = _fill_event("AAPL", Side.BUY, 50.0, 100, 1.0, portfolio_id,
                             time=datetime.now(UTC))

    assert env.handler.on_fill(fill_event) is None


def test_on_fill_transaction_carries_fill_id(env):
    """D-11: the recorded Transaction's fill_id matches the originating
    FillEvent's (fill -> order -> strategy audit chain)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)
    buy_fill = _fill_event("BTCUSDT", Side.BUY, 40000, 1, 0, portfolio_id)

    env.handler.on_fill(buy_fill)

    transaction = env.handler.get_portfolio(portfolio_id).transactions[0]
    assert transaction.fill_id == buy_fill.fill_id


def test_fill_event_processing_inactive_portfolio(env):
    """Test fill event processing with inactive portfolio."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)
    portfolio = env.handler.get_portfolio(portfolio_id)
    portfolio.set_state(PortfolioState.INACTIVE)

    fill_event = _fill_event("AAPL", Side.BUY, 150.0, 100, 1.0, portfolio_id,
                             time=datetime.now(UTC))

    # FL-01: transact on an inactive portfolio now raises the typed StateError
    # (was bare ValueError).
    with pytest.raises(StateError):
        env.handler.on_fill(fill_event)


def test_fill_event_processing_invalid_portfolio(env):
    """Test fill event processing with invalid portfolio ID."""
    fill_event = _fill_event("AAPL", Side.BUY, 150.0, 100, 1.0, "99999",
                             time=datetime.now(UTC))

    with pytest.raises(PortfolioNotFoundError):
        env.handler.on_fill(fill_event)


# ===================
# DICTIONARY CONVERSION & SERIALIZATION
# ===================


def test_portfolios_to_dict(env):
    """Test portfolios to dictionary conversion (legacy compatibility)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Add a transaction to test with data
    buy_fill = _fill_event("BTCUSDT", Side.SELL, 40000, 1, 0, portfolio_id)
    env.handler.on_fill(buy_fill)

    portfolios_dict = env.handler.portfolios_to_dict()

    assert isinstance(portfolios_dict, dict)
    assert len(portfolios_dict) == 1


def test_portfolios_to_dict_thread_safety(env):
    """Test portfolios_to_dict method thread safety."""
    for i in range(3):
        env.handler.add_portfolio(f"Portfolio {i}", "NYSE", 10000.0)

    def get_portfolios_dict():
        return env.handler.portfolios_to_dict()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(get_portfolios_dict) for _ in range(5)]
        results = [future.result() for future in as_completed(futures)]

    assert len(results) == 5
    for result in results:
        assert len(result) == 3
        assert isinstance(result, dict)


# ===================
# VALIDATION & HEALTH CHECKS
# ===================


def test_portfolio_health_validation(env):
    """Test portfolio health validation."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)
    portfolio = env.handler.get_portfolio(portfolio_id)

    health = portfolio.validate_health()
    assert health["is_healthy"]
    assert health["portfolio_id"] == portfolio_id
    assert health["state"] == PortfolioState.ACTIVE.value
    assert len(health["issues"]) == 0


# ===================
# ERROR HANDLING & EVENTS
# ===================


def test_error_event_publishing(env):
    """Test that error events are published correctly."""
    # Clear the queue first
    while not env.global_queue.empty():
        env.global_queue.get()

    # Process fill event with invalid portfolio to trigger error event
    fill_event = _fill_event("AAPL", Side.BUY, 150.0, 100, 1.0, "99999",
                             time=datetime.now(UTC))

    try:
        env.handler.on_fill(fill_event)
    except PortfolioNotFoundError:
        pass

    # Check that error event was published (if error events are enabled)
    if not env.global_queue.empty():
        error_event = env.global_queue.get()
        assert isinstance(error_event, PortfolioErrorEvent)
        assert error_event.error_type == "PortfolioNotFoundError"
        # The error event carries the id as supplied on the fill (no int
        # coercion now that ids are native UUIDs, not the old integer scheme).
        assert error_event.portfolio_id == "99999"
    else:
        # If no error event was published, that's also acceptable behavior.
        pass


# ===================
# CONCURRENCY & THREAD SAFETY
# ===================


def test_no_concurrency_limiting_single_writer(env):
    """D-19: concurrency-limiting machinery is gone — single-writer contract.

    Regression-locks the deletion of _operations_lock/_active_operations:
    all portfolio state mutations happen on the engine thread; queue.Queue
    is the thread boundary.
    """
    assert not hasattr(env.handler, '_active_operations')
    assert not hasattr(env.handler, '_operations_lock')
    assert not hasattr(env.handler, '_portfolios_lock')


def test_correlation_id_generation(env):
    """Each operation emits a fresh, unique correlation id (public observable).

    The correlation id is observable on the emitted ``PortfolioErrorEvent`` —
    we assert that OBSERVABLE EFFECT through a public path rather than the
    private id-generation helper (D-09 encapsulation hygiene). Driving
    ``on_fill`` twice with an unknown portfolio runs two operation scopes,
    each generating its own correlation id, so the two emitted ids are
    distinct UUIDs.
    """
    while not env.global_queue.empty():
        env.global_queue.get()

    correlation_ids = []
    for _ in range(2):
        fill_event = _fill_event("AAPL", Side.BUY, 150.0, 100, 1.0, "99999",
                                 time=datetime.now(UTC))
        try:
            env.handler.on_fill(fill_event)
        except PortfolioNotFoundError:
            pass
        error_event = env.global_queue.get()
        assert isinstance(error_event, PortfolioErrorEvent)
        correlation_ids.append(error_event.correlation_id)

    id1, id2 = correlation_ids
    assert id1 != id2
    assert isinstance(id1, uuid.UUID)
    assert isinstance(id2, uuid.UUID)


def test_thread_safety_concurrent_creation(env):
    """Test thread safety during concurrent portfolio creation."""
    results = []
    errors = []

    def create_portfolio(idx):
        try:
            portfolio_id = env.handler.add_portfolio(
                name=f"Portfolio {idx}", exchange="NYSE", cash=10000.0
            )
            results.append(portfolio_id)
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(5):
        thread = threading.Thread(target=create_portfolio, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0
    assert len(results) == 5
    assert len(set(results)) == 5  # All unique IDs


def test_thread_safety_concurrent_access(env):
    """Test thread safety during concurrent portfolio access."""
    portfolio_id = env.handler.add_portfolio("Test", "NYSE", 10000.0)

    results = []
    errors = []

    def access_portfolio():
        try:
            portfolio = env.handler.get_portfolio(portfolio_id)
            results.append(portfolio.portfolio_id)
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(10):
        thread = threading.Thread(target=access_portfolio)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0
    assert len(results) == 10
    assert all(r == portfolio_id for r in results)


# ===================
# Handler configuration management
# ===================


def test_update_config_partial_nested_preserves_siblings(env):
    """WR-04: a partial nested update must preserve sibling fields.

    A shallow `{**base, **updates}` merge would REPLACE the whole `limits`
    submodel, silently resetting siblings like `max_positions`. The deep merge
    must keep them.
    """
    handler = env.handler
    before_max_positions = handler.config_data.limits.max_positions

    # D-07/D-08: canonical contract returns None (no longer bool).
    result = handler.update_config({"limits": {"max_portfolios": 7}})

    assert result is None
    # The intended field changed...
    assert handler.config_data.limits.max_portfolios == 7
    assert handler.max_portfolios == 7
    # ...and the sibling field was NOT reset by the partial update.
    assert handler.config_data.limits.max_positions == before_max_positions


# ===================
# Individual portfolio enhancements
# ===================


@pytest.fixture
def portfolio():
    return Portfolio(
        name="Test Portfolio", exchange="NYSE",
        cash=10000.0, time=datetime.now(UTC),
    )


def test_portfolio_configuration_management(portfolio):
    """Test portfolio configuration management."""
    # Test default configuration (check actual default from config)
    assert portfolio.config.limits.max_positions == 50  # Matches the test environment config
    assert portfolio.config.limits.max_position_value == Decimal("1000000")

    # Test configuration update (D-07: canonical dict contract, not **kwargs)
    portfolio.update_config({"limits": {"max_positions": 75, "max_position_value": "500000"}})
    assert portfolio.config.limits.max_positions == 75
    assert portfolio.config.limits.max_position_value == Decimal("500000")

    # Test configuration dictionary (this should maintain backward compatibility)
    config_dict = portfolio.get_config_dict()
    assert config_dict["max_positions"] == 75
    assert config_dict["max_position_value"] == 500000.0


def test_portfolio_enhanced_to_dict(portfolio):
    """Test enhanced to_dict method."""
    portfolio_dict = portfolio.to_dict()

    required_fields = [
        "portfolio_id", "name", "exchange", "creation_time",
        "current_time", "state", "cash", "total_market_value", "total_equity",
        "n_open_positions", "config", "health_metrics", "last_activity",
    ]

    for field in required_fields:
        assert field in portfolio_dict

    assert portfolio_dict["name"] == "Test Portfolio"
    assert portfolio_dict["state"] == PortfolioState.ACTIVE.value
    assert portfolio_dict["cash"] == 10000.0


# ===================
# MAINTENANCE MARGIN / MARGIN RATIO (Plan 02-05, MARGIN-03, D-13/D-16)
# ===================


def _fake_universe(rates):
    """A minimal Universe stand-in exposing instrument(ticker).maintenance_margin_rate.

    ``rates`` maps ticker -> Decimal maintenance_margin_rate. Mirrors the
    Universe.instrument(symbol) -> Instrument surface the handler reads (D-13).
    """
    instruments = {
        ticker: SimpleNamespace(maintenance_margin_rate=rate)
        for ticker, rate in rates.items()
    }
    return SimpleNamespace(instrument=lambda ticker: instruments[ticker])


def test_maintenance_margin_sums_mmr_times_size_times_price(env):
    """maintenance_margin = Σ (mmr × |size| × current_price) over open positions (D-13)."""
    portfolio_id = env.handler.add_portfolio(
        _PORTFOLIO_NAME, _EXCHANGE, _CASH, portfolio_config=_margin_config())
    # Position A: |size| 2 @ 100, mmr 0.01 -> 2 ; Position B: |size| 1 @ 50, mmr 0.02 -> 1
    env.handler.on_fill(_fill_event("AAA", Side.BUY, 100, 2, 0, portfolio_id))
    env.handler.on_fill(_fill_event("BBB", Side.BUY, 50, 1, 0, portfolio_id))
    env.handler.set_universe(_fake_universe({
        "AAA": Decimal("0.01"),
        "BBB": Decimal("0.02"),
    }))

    mm = env.handler.maintenance_margin(portfolio_id)
    assert isinstance(mm, Decimal)
    assert mm == Decimal("3")


def test_maintenance_margin_zero_with_no_open_positions(env):
    """No open positions -> Decimal('0') maintenance margin (no margin required)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)
    env.handler.set_universe(_fake_universe({}))
    assert env.handler.maintenance_margin(portfolio_id) == Decimal("0")


def test_margin_ratio_equals_equity_over_maintenance(env):
    """margin_ratio = total_equity() / maintenance_margin (D-12 mark-to-market)."""
    portfolio_id = env.handler.add_portfolio(
        _PORTFOLIO_NAME, _EXCHANGE, _CASH, portfolio_config=_margin_config())
    env.handler.on_fill(_fill_event("AAA", Side.BUY, 100, 2, 0, portfolio_id))
    env.handler.on_fill(_fill_event("BBB", Side.BUY, 50, 1, 0, portfolio_id))
    env.handler.set_universe(_fake_universe({
        "AAA": Decimal("0.01"),
        "BBB": Decimal("0.02"),
    }))

    equity = env.handler.total_equity(portfolio_id)
    mm = env.handler.maintenance_margin(portfolio_id)
    ratio = env.handler.margin_ratio(portfolio_id)
    assert isinstance(ratio, Decimal)
    assert ratio == equity / mm


def test_margin_ratio_zero_sentinel_when_no_maintenance(env):
    """Zero maintenance (no open positions) -> deterministic Decimal('0') sentinel, no div0."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)
    env.handler.set_universe(_fake_universe({}))
    assert env.handler.margin_ratio(portfolio_id) == Decimal("0")


def test_margin_ratio_reads_honestly_when_breached(env):
    """When equity drops below maintenance, margin_ratio < 1 and is NOT clamped (D-16)."""
    portfolio_id = env.handler.add_portfolio(
        _PORTFOLIO_NAME, _EXCHANGE, 100, portfolio_config=_margin_config())
    # One position whose maintenance margin exceeds tiny equity:
    # |size| 1 @ 50, mmr 0.99 -> maintenance 49.5; with starting cash 100 the
    # mmr is set high enough that equity/maintenance is small but, more directly,
    # we assert no clamp: a deliberately huge mmr forces ratio < 1.
    env.handler.on_fill(_fill_event("AAA", Side.BUY, 50, 1, 0, portfolio_id))
    env.handler.set_universe(_fake_universe({"AAA": Decimal("100")}))

    equity = env.handler.total_equity(portfolio_id)
    mm = env.handler.maintenance_margin(portfolio_id)
    ratio = env.handler.margin_ratio(portfolio_id)
    assert mm > equity  # breached
    assert ratio < Decimal("1")
    assert ratio == equity / mm  # honest, no clamp to 0 or 1


# ---------------------------------------------------------------------------
# Phase 3 WR-02 (universe_unwired) — fail-loud StateError on an unwired universe.
# A maintenance_margin / carry read with OPEN positions but `_universe is None`
# must raise a context-rich `StateError` (universe-unwired), NEVER a bare
# `AttributeError`. Implemented in Plan 03-06.
# ---------------------------------------------------------------------------


def test_universe_unwired_maintenance_margin_raises_state_error(env):
    """WR-02: maintenance_margin with open positions but `_universe is None`
    raises a context-rich StateError, NOT a bare AttributeError."""
    portfolio_id = env.handler.add_portfolio(
        _PORTFOLIO_NAME, _EXCHANGE, _CASH, portfolio_config=_margin_config())
    # Open a position WITHOUT wiring the universe (set_universe never called).
    env.handler.on_fill(_fill_event("AAA", Side.BUY, 100, 2, 0, portfolio_id))

    with pytest.raises(StateError) as exc_info:
        env.handler.maintenance_margin(portfolio_id)
    # Fail-loud with attribution context — not a bare AttributeError.
    assert "universe" in str(exc_info.value).lower()


def test_universe_unwired_no_positions_is_not_an_error(env):
    """WR-02: with NO open positions, an unwired universe is benign — the sum is
    Decimal('0') and no StateError is raised (the guard only fires when there is
    something to read)."""
    portfolio_id = env.handler.add_portfolio(_PORTFOLIO_NAME, _EXCHANGE, _CASH)
    # No positions, no set_universe — must NOT raise.
    assert env.handler.maintenance_margin(portfolio_id) == Decimal("0")


# ---------------------------------------------------------------------------
# D-01 / VENUE-01 (11.1-03) — the Account leaf carries NO reference back to the
# Portfolio that owns it. The object-graph property itself is not directly
# assertable, so the checkable proxy is constructibility-and-exercisability in
# ISOLATION: if the leaf can be built and its margin math driven to a real
# number with no Portfolio object in existence at all, there is no residual
# coupling left to find (no attribute, no closure capture, no getattr fallback).
# ---------------------------------------------------------------------------


def _fake_position(ticker, net_quantity, current_price):
    """A minimal open-position stand-in for the margin sum (D-13).

    Exposes exactly the three reads maintenance_margin performs: ``ticker``
    (universe lookup key), ``net_quantity`` and ``current_price``.
    """
    return SimpleNamespace(
        ticker=ticker,
        net_quantity=net_quantity,
        current_price=current_price,
    )


def test_margin_math_runs_with_no_portfolio_object_in_existence():
    """D-01/VENUE-01: the margin leaf needs no Portfolio — not to construct, and
    not to compute. Built from cash alone, handed positions and an id directly."""
    account = SimulatedMarginAccount(10000)
    account.set_universe(_fake_universe({
        "AAA": Decimal("0.01"),
        "BBB": Decimal("0.02"),
    }))

    # Σ (mmr × |size| × price): 0.01×2×100 = 2 ; 0.02×1×50 = 1 -> 3
    positions = {
        "AAA": _fake_position("AAA", Decimal("2"), Decimal("100")),
        "BBB": _fake_position("BBB", Decimal("1"), Decimal("50")),
    }
    mm = account.maintenance_margin(positions, "pf-no-portfolio")
    assert isinstance(mm, Decimal)
    assert mm == Decimal("3")

    # margin_ratio takes equity as an argument for the same reason — no
    # Portfolio to read total_equity from.
    assert account.margin_ratio(Decimal("30"), positions, "pf-no-portfolio") == Decimal("10")

    # VENUE-01 `empty` edge: an EMPTY positions mapping returns Decimal('0')
    # WITHOUT dereferencing the Universe, so the WR-02 unwired-Universe guard
    # stays unreachable when there is nothing to price. Proved on a SECOND,
    # deliberately unwired account so the assertion cannot free-ride on the
    # set_universe call above.
    unwired = SimulatedMarginAccount(10000)
    assert unwired._universe is None
    assert unwired.maintenance_margin({}, "pf-no-portfolio") == Decimal("0")

    # VENUE-01 boundary edge: zero maintenance returns the Decimal('0') sentinel
    # rather than dividing by zero.
    assert unwired.margin_ratio(Decimal("500"), {}, "pf-no-portfolio") == Decimal("0")


def test_margin_math_with_no_portfolio_still_fails_loud_on_unwired_universe():
    """D-01 must NOT weaken the WR-02 detective control: positions present but no
    Universe still raises a context-rich StateError carrying the portfolio id."""
    account = SimulatedMarginAccount(10000)  # set_universe deliberately not called
    positions = {"AAA": _fake_position("AAA", Decimal("2"), Decimal("100"))}

    with pytest.raises(StateError) as exc_info:
        account.maintenance_margin(positions, "pf-attribution-id")
    message = str(exc_info.value)
    assert "universe" in message.lower()
    # The portfolio-id attribution the caller supplied survives into the error
    # (RESEARCH F-6 — the id is not an optional, droppable argument).
    assert "pf-attribution-id" in message
