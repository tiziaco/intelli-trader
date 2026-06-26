"""Fill-invalidation tests for the explicit Position.net_quantity / avg_price
cache (Req 2 / D-05, Phase 8).

Position is a hand-written MUTABLE class (excluded from msgspec, D-01). The cache
is two explicit ``Optional[Decimal]`` fields (NOT functools.cached_property, which
D-05 rejected) that are reset to ``None`` at the single input-mutating site
(``update_position``). These tests prove:

- net_quantity / avg_price are cached (computed once, returned from cache on a
  second read with no intervening fill);
- the caches are INVALIDATED (not stale) after a BUY and after a SELL fill;
- market_value stays LIVE on current_price (the cache is only on fill-derived
  quantities/prices, never on current_price);
- cached values stay Decimal (Decimal end-to-end — never coerced).
"""

from datetime import datetime
from decimal import Decimal

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide


_TICKER = "BTCUSDT"
_PORTFOLIO_ID = "portfolio_id"


def _buy(price, quantity, tid):
	return Transaction(
		datetime.now(), TransactionType.BUY, _TICKER, price, quantity, 0,
		_PORTFOLIO_ID, id=tid, fill_id=uuid_compat.uuid7(),
	)


def _sell(price, quantity, tid):
	return Transaction(
		datetime.now(), TransactionType.SELL, _TICKER, price, quantity, 0,
		_PORTFOLIO_ID, id=tid, fill_id=uuid_compat.uuid7(),
	)


def test_net_quantity_cached():
	"""First read computes and stashes; a second read with no fill returns the
	same cached object (identity), proving the recompute path did not run."""
	position = Position.open_position(_buy(42000, 1, 1))

	first = position.net_quantity
	second = position.net_quantity

	assert first == Decimal("1")
	# Identity proves the value was served from the cache field, not recomputed.
	assert first is second
	assert position._net_quantity_cache is not None


def test_avg_price_cached():
	"""avg_price is cached: a second read with no fill returns the cached object."""
	position = Position.open_position(_buy(42000, 1, 1))

	first = position.avg_price
	second = position.avg_price

	assert first is second
	assert position._avg_price_cache is not None


def test_invalidation_on_buy():
	"""After a BUY update_position, net_quantity recomputes to the new
	abs(buy-sell) — the cache was reset, not left stale."""
	position = Position.open_position(_buy(42000, 1, 1))
	# Prime the cache.
	assert position.net_quantity == Decimal("1")

	position.update_position(_buy(50000, 2, 2))

	# Cache was invalidated at the mutation site → fresh recompute.
	assert position._net_quantity_cache is None
	assert position.net_quantity == Decimal("3")


def test_invalidation_on_sell():
	"""After a SELL update_position, both net_quantity and avg_price reflect the
	new inputs (differ correctly from the pre-sell cached values)."""
	position = Position.open_position(_buy(42000, 3, 1))
	# Prime both caches.
	pre_net = position.net_quantity
	pre_avg = position.avg_price
	assert pre_net == Decimal("3")

	position.update_position(_sell(50000, 1, 2))

	# Both caches reset at the mutation site.
	assert position._net_quantity_cache is None
	assert position._avg_price_cache is None
	# net_quantity recomputes to abs(3 - 1) == 2 (differs from cached 3).
	assert position.net_quantity == Decimal("2")
	assert position.net_quantity != pre_net


def test_avg_price_cached_and_invalidated():
	"""avg_price is cached, and after a fill that changes avg_bought/buy_quantity
	it recomputes correctly (not stale)."""
	position = Position.open_position(_buy(42000, 1, 1))
	pre_avg = position.avg_price
	assert pre_avg == Decimal("42000")

	position.update_position(_buy(50000, 1, 2))

	assert position._avg_price_cache is None
	# avg_bought becomes (42000*1 + 50000*1)/2 = 46000; zero commissions →
	# avg_price == avg_bought == 46000 (recomputed, differs from cached 42000).
	assert position.avg_price == Decimal("46000")
	assert position.avg_price != pre_avg


def test_market_value_stays_live():
	"""Changing current_price via update_current_price_time changes market_value
	WITHOUT a fill — the cache is only on fill-derived quantities/prices, not on
	current_price."""
	position = Position.open_position(_buy(42000, 2, 1))
	# Prime net_quantity cache.
	assert position.net_quantity == Decimal("2")
	mv_before = position.market_value
	assert mv_before == Decimal("84000")  # 42000 * 2

	# No fill — only the live current_price moves.
	position.update_current_price_time(45000, datetime.now())

	# market_value reflects the new current_price even though net_quantity is
	# still served from its (un-invalidated) cache.
	assert position.market_value == Decimal("90000")  # 45000 * 2
	assert position.market_value != mv_before
	# net_quantity cache was NOT touched by a price-only update.
	assert position._net_quantity_cache is not None


def test_cached_values_are_decimal():
	"""Cached net_quantity / avg_price stay Decimal (Decimal end-to-end)."""
	position = Position.open_position(_buy(42000, 1, 1))

	assert isinstance(position.net_quantity, Decimal)
	assert isinstance(position.avg_price, Decimal)
	assert isinstance(position._net_quantity_cache, Decimal)
	assert isinstance(position._avg_price_cache, Decimal)
