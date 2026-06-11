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
from itrader.core.enums import PortfolioState, PositionSide
from itrader.config import PortfolioConfig
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
_USER_ID = 1
_PORTFOLIO_NAME = "test_pf"
_EXCHANGE = "simulated"
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
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Assert if the portfolio has been created (ids are now native UUIDv7)
    assert env.handler.get_portfolio_count() == 1
    assert isinstance(portfolio_id, uuid.UUID)


def test_get_portfolio(env):
    """Test portfolio retrieval (legacy compatibility)."""
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)
    portfolio = env.handler.get_portfolio(portfolio_id)

    assert isinstance(portfolio, Portfolio)
    assert portfolio.portfolio_id == portfolio_id
    assert portfolio.name == _PORTFOLIO_NAME
    assert portfolio.cash == _CASH


def test_portfolio_creation_success(env):
    """Test successful portfolio creation with enhanced features."""
    portfolio_id = env.handler.add_portfolio(
        user_id=1, name="Test Portfolio", exchange="NYSE", cash=10000.0
    )

    assert isinstance(portfolio_id, uuid.UUID)

    portfolio = env.handler.get_portfolio(portfolio_id)
    assert portfolio.user_id == 1
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
        user_id=2, name="Custom Config Portfolio", exchange="NASDAQ",
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
            user_id=1, name="Invalid Portfolio", exchange="NYSE", cash=-1000.0
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
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
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
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)

    # Withdraw all cash to allow deletion
    portfolio = env.handler.get_portfolio(portfolio_id)
    portfolio.cash_manager.withdraw(portfolio.cash_manager.balance, "Test withdrawal")

    # Delete portfolio (should archive first)
    assert env.handler.delete_portfolio(portfolio_id)

    # Verify portfolio is deleted
    with pytest.raises(PortfolioNotFoundError):
        env.handler.get_portfolio(portfolio_id)


def test_active_portfolios_filtering(env):
    """Test filtering active portfolios."""
    p1 = env.handler.add_portfolio(1, "Active1", "NYSE", 10000.0)
    p2 = env.handler.add_portfolio(2, "Active2", "NYSE", 20000.0)
    p3 = env.handler.add_portfolio(3, "Inactive", "NYSE", 15000.0)

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
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)

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
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)

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
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)

    fill_event = _fill_event("AAPL", Side.BUY, 50.0, 100, 1.0, portfolio_id,
                             time=datetime.now(UTC))

    # D-10: on_fill is raise/None — success means no exception raised.
    env.handler.on_fill(fill_event)

    portfolio = env.handler.get_portfolio(portfolio_id)
    assert portfolio.n_open_positions == 1
    assert portfolio.cash < 10000.0  # Cash should be reduced


def test_on_fill_returns_none(env):
    """D-10 contract propagation: on_fill is raise/None — no bool channel."""
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 100000.0)
    fill_event = _fill_event("AAPL", Side.BUY, 50.0, 100, 1.0, portfolio_id,
                             time=datetime.now(UTC))

    assert env.handler.on_fill(fill_event) is None


def test_on_fill_transaction_carries_fill_id(env):
    """D-11: the recorded Transaction's fill_id matches the originating
    FillEvent's (fill -> order -> strategy audit chain)."""
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)
    buy_fill = _fill_event("BTCUSDT", Side.BUY, 40000, 1, 0, portfolio_id)

    env.handler.on_fill(buy_fill)

    transaction = env.handler.get_portfolio(portfolio_id).transactions[0]
    assert transaction.fill_id == buy_fill.fill_id


def test_fill_event_processing_inactive_portfolio(env):
    """Test fill event processing with inactive portfolio."""
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
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
    portfolio_id = env.handler.add_portfolio(_USER_ID, _PORTFOLIO_NAME, _EXCHANGE, _CASH)

    # Add a transaction to test with data
    buy_fill = _fill_event("BTCUSDT", Side.SELL, 40000, 1, 0, portfolio_id)
    env.handler.on_fill(buy_fill)

    portfolios_dict = env.handler.portfolios_to_dict()

    assert isinstance(portfolios_dict, dict)
    assert len(portfolios_dict) == 1


def test_portfolios_to_dict_thread_safety(env):
    """Test portfolios_to_dict method thread safety."""
    for i in range(3):
        env.handler.add_portfolio(i, f"Portfolio {i}", "NYSE", 10000.0)

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
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
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

    def create_portfolio(user_id):
        try:
            portfolio_id = env.handler.add_portfolio(
                user_id=user_id, name=f"Portfolio {user_id}", exchange="NYSE", cash=10000.0
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
    portfolio_id = env.handler.add_portfolio(1, "Test", "NYSE", 10000.0)

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

    ok = handler.update_config({"limits": {"max_portfolios": 7}})

    assert ok is True
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
        user_id=1, name="Test Portfolio", exchange="NYSE",
        cash=10000.0, time=datetime.now(UTC),
    )


def test_portfolio_configuration_management(portfolio):
    """Test portfolio configuration management."""
    # Test default configuration (check actual default from config)
    assert portfolio.config.limits.max_positions == 50  # Matches the test environment config
    assert portfolio.config.limits.max_position_value == Decimal("1000000")

    # Test configuration update
    portfolio.update_config(max_positions=75, max_position_value=Decimal("500000"))
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
        "portfolio_id", "user_id", "name", "exchange", "creation_time",
        "current_time", "state", "cash", "total_market_value", "total_equity",
        "n_open_positions", "config", "health_metrics", "last_activity",
    ]

    for field in required_fields:
        assert field in portfolio_dict

    assert portfolio_dict["user_id"] == 1
    assert portfolio_dict["name"] == "Test Portfolio"
    assert portfolio_dict["state"] == PortfolioState.ACTIVE.value
    assert portfolio_dict["cash"] == 10000.0
