"""
Lean unit test for the BracketBook primitive (D-15, Wave 0).

Asserts the BracketBook methods are byte-equal to the raw dict ops they replace
at the 8 verified `order_manager.py` sites:

* arm + get round-trip
* consume returns the entry AND removes it (second get is None)
* consume on a missing key returns None (idempotent — mirrors `pop(.., None)`)
* refresh_quantity replaces ONLY quantity and preserves every other
  _PendingBracket field
* dict-compat dunders (`== {}`, `in`, `len`) — keep test_sltp_policy.py green
  untouched (Pitfall 2 option a)

Entirely oracle-dark — the golden run carries no brackets. 4-space house style.
"""

from decimal import Decimal

from itrader.order_handler.brackets import BracketBook
from itrader.order_handler.brackets.bracket_book import _PendingBracket
from itrader.core.sizing import PercentFromFill


def _make_bracket(quantity=Decimal("1")):
    """Build a valid _PendingBracket mirroring the dataclass signature."""
    return _PendingBracket(
        policy=PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
        ticker="BTCUSDT",
        action="BUY",
        quantity=quantity,
        exchange="binance",
        strategy_id="strat-1",
        portfolio_id=42,
    )


def test_arm_and_get_round_trip():
    book = BracketBook()
    bracket = _make_bracket()

    book.arm("order-1", bracket)

    assert book.get("order-1") is bracket


def test_get_missing_returns_none():
    book = BracketBook()

    assert book.get("nope") is None


def test_consume_returns_entry_and_removes_it():
    book = BracketBook()
    bracket = _make_bracket()
    book.arm("order-1", bracket)

    consumed = book.consume("order-1")

    assert consumed is bracket
    # Read-and-remove: a second consume/get is None.
    assert book.get("order-1") is None
    assert book.consume("order-1") is None


def test_consume_missing_is_idempotent_none():
    book = BracketBook()

    # Mirrors `dict.pop(.., None)` — None on miss, no raise.
    assert book.consume("never-armed") is None


def test_refresh_quantity_replaces_only_quantity():
    book = BracketBook()
    original = _make_bracket(quantity=Decimal("1"))
    book.arm("order-1", original)

    book.refresh_quantity("order-1", Decimal("3"))

    refreshed = book.get("order-1")
    assert refreshed.quantity == Decimal("3")
    # Every other field is preserved.
    assert refreshed.policy == original.policy
    assert refreshed.ticker == original.ticker
    assert refreshed.action == original.action
    assert refreshed.exchange == original.exchange
    assert refreshed.strategy_id == original.strategy_id
    assert refreshed.portfolio_id == original.portfolio_id


def test_refresh_quantity_missing_is_noop():
    book = BracketBook()

    # Guarded `if pending is not None` — no raise, nothing armed.
    book.refresh_quantity("never-armed", Decimal("5"))

    assert book.get("never-armed") is None
    assert len(book) == 0


def test_dict_compat_dunders():
    book = BracketBook()

    # Empty book compares equal to an empty dict.
    assert book == {}
    assert len(book) == 0

    book.arm("order-1", _make_bracket())
    assert "order-1" in book
    assert "missing" not in book
    assert len(book) == 1
    assert book != {}

    book.consume("order-1")
    assert book == {}
    assert len(book) == 0
