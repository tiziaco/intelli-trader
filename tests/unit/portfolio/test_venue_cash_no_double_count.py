"""Regression: a venue balance push must not double-count a locally-applied fill.

Root cause ``okx-venue-cash-double-count`` (.planning/debug/): the live cash surface
is ``VenueAccount.balance = _venue_balance + _ledger_delta``. Every fill settles into
the account via ``apply_fill_cash_flow`` (the shared Account-ABC settlement primitive),
which moves ``_ledger_delta``. The async balance stream (``_stream_account`` ->
``_write_balance_stream``) USED TO ALSO refresh ``_venue_balance`` to the venue's
post-fill ``watch_balance`` push — so the SAME fill was counted twice (once in the
stream-pushed venue balance, once in the ledger): a 2x cash debit, while the position
(single-sourced from ``_venue_positions``, no ledger overlay) stayed single-counted.

The exact online symptom (tests/e2e/test_okx_sandbox_recon.py): a single 0.0001 BTC @
59513 demo BUY (notional 5.9513 USDC) debited cash by 11.9026001 (exactly 2x) instead
of ~5.9513.

The fix: the balance stream writes POSITIONS only, never the cash baseline. ``snapshot()``
remains the SOLE cash-reconcile point (D-01) — it re-baselines ``_venue_balance`` AND
resets ``_ledger_delta`` atomically. This is deterministic and OFFLINE (no network, no
demo order): it drives the cache-write helper directly. Folder-derived ``unit`` marker.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from itrader.portfolio_handler.account.venue import VenueAccount


def _spot_account_snapshotted(pre_fill_quote: str) -> VenueAccount:
    """A spot BTC/USDC ``VenueAccount`` snapshotted to a pre-fill quote balance.

    Uses a ``MagicMock`` connector whose ``call(...)`` returns the canned REST balance
    payload ``snapshot()`` reads (``{"total": {"USDC": <pre_fill_quote>}}``). No BTC key
    yet -> a flat pre-fill holding. After ``snapshot()`` the cache baseline is set and
    ``_ledger_delta`` is zero.
    """
    connector = MagicMock(name="connector")
    connector.call.return_value = {"total": {"USDC": float(pre_fill_quote)}}
    account = VenueAccount(
        connector,
        quote_currency="USDC",
        market_type="spot",
        symbol="BTC/USDC", account_id="acct-test"
    )
    account.snapshot()
    return account


def test_balance_push_after_fill_does_not_double_count_cash() -> None:
    """A post-fill balance push must leave cash single-counted (the online 2x bug)."""
    account = _spot_account_snapshotted("100.0")
    assert account.balance == Decimal("100.0")  # baseline, ledger == 0

    # A 0.0001 @ 59513 BUY settles locally exactly as Portfolio.transact_shares does:
    # one signed net-cash delta of -5.9513 through the ABC settlement primitive.
    account.apply_fill_cash_flow(
        amount=Decimal("-5.9513"),
        fee=Decimal("0"),
        description="BUY BTC/USDC",
        reference_id="txn-1",
        timestamp=datetime(2026, 7, 5),
    )
    # Single-counted so far — the ledger holds the one fill.
    assert account.balance == Decimal("94.0487")

    # The venue balance stream now pushes the POST-fill balance: quote already reflects
    # the -5.9513 (94.0487) and the base holding is now 0.0001 BTC. Before the fix this
    # refreshed _venue_balance to 94.0487 while _ledger_delta STILL held -5.9513 ->
    # balance == 88.0974 (the online 11.9026001 == 2x symptom).
    post_fill_push = {"total": {"USDC": 94.0487, "BTC": 0.0001}}
    account._write_balance_stream(post_fill_push)

    # Cash single-counted: the stream did NOT re-debit the fill.
    assert account.balance == Decimal("94.0487"), (
        "venue balance stream double-counted the locally-applied fill "
        f"(got {account.balance}, expected 94.0487) — okx-venue-cash-double-count")


def test_balance_push_still_keeps_spot_position_live() -> None:
    """The stream must still derive spot position liveness from the balance push (D-03)."""
    account = _spot_account_snapshotted("100.0")
    assert account.positions == {}  # flat pre-fill

    # A balance push carrying the base key is authoritative — derives the holding.
    account._write_balance_stream({"total": {"USDC": 94.0487, "BTC": 0.0001}})
    assert account.positions == {"BTC/USDC": Decimal("0.0001")}


def test_balance_push_does_not_touch_cash_baseline() -> None:
    """The stream leaves the cash baseline (``_venue_balance``) to ``snapshot()`` (D-01)."""
    account = _spot_account_snapshotted("100.0")
    baseline = account._venue_balance
    account._write_balance_stream({"total": {"USDC": 777.0, "BTC": 0.5}})
    # The stream pushed a wildly different quote total; the cash baseline is UNCHANGED.
    assert account._venue_balance == baseline
    assert account.balance == Decimal("100.0")
