"""Regression: a partial spot balance frame must not clobber the holding to flat (WR-02).

On a spot leaf the per-symbol holding is DERIVED from the balance stream's
``total[BASE]`` (OKX spot has no positions channel, D-03). A partial/quote-only
``watch_balance`` push that OMITS the base key must leave the prior derived
position intact — otherwise the cache resets to flat and the next engine-thread
drift sweep reads engine-qty vs venue-qty=0 and spuriously ``halt("drift")``s. A
base key that is PRESENT-but-zero is a real FLAT and correctly clears the holding.

``_spot_positions_from_balance`` encodes that decision: ``None`` means "base key
absent — leave the cache", a dict (possibly empty) means "authoritative, replace".
Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from decimal import Decimal
from unittest.mock import MagicMock

from itrader.portfolio_handler.account.venue import VenueAccount


def _spot_account() -> VenueAccount:
    """A spot ``VenueAccount`` wired to BTC/USDC (no connect / no stream)."""
    return VenueAccount(
        MagicMock(name="connector"),
        quote_currency="USDC",
        market_type="spot",
        symbol="BTC/USDC",
    )


def test_base_present_derives_holding() -> None:
    account = _spot_account()
    frame = {"total": {"BTC": Decimal("0.5"), "USDC": Decimal("1000")}}
    assert account._spot_positions_from_balance(frame) == {"BTC/USDC": Decimal("0.5")}


def test_base_present_but_zero_is_authoritative_flat() -> None:
    account = _spot_account()
    frame = {"total": {"BTC": Decimal("0"), "USDC": Decimal("1000")}}
    # Empty dict (not None) — a real FLAT that WILL clear the cached holding.
    assert account._spot_positions_from_balance(frame) == {}


def test_partial_frame_without_base_key_leaves_cache_intact() -> None:
    account = _spot_account()
    account._venue_positions = {"BTC/USDC": Decimal("0.5")}  # prior derived holding
    # A quote-only partial frame omits BTC — must NOT clobber to flat.
    assert account._spot_positions_from_balance({"total": {"USDC": Decimal("1000")}}) is None
    # No total map at all — likewise leave the cache alone.
    assert account._spot_positions_from_balance({}) is None
