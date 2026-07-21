"""Unit tests for the declarative system spec value objects (D-01/D-02, MPORT-05).

Plan 11-05 created this file: there was NO existing test for ``system_spec.py`` or
``PortfolioSpec`` anywhere under ``tests/unit/`` before it, so the plan's original
"extend the existing spec unit tests" instruction had no target and running
``pytest tests/unit/trading_system`` would have reported a FALSE GREEN.

MPORT-05: ``PortfolioSpec`` gains ``account_id`` so a composition-time spec can name
each portfolio's venue account. It must DEFAULT so every existing construction site —
including the byte-exact backtest composition root — is untouched.
"""

import dataclasses

import pytest

from itrader.trading_system.system_spec import PortfolioSpec


def test_legacy_two_field_construction_still_works():
    """The field defaults, so every existing construction site is untouched."""
    spec = PortfolioSpec(name="a", cash=1000)
    assert spec.name == "a"
    assert spec.cash == 1000


def test_account_id_defaults_to_none():
    """MPORT-05: naming an account is optional at the spec layer; plan 11-08's
    composition-time invariant is what requires it for a live portfolio."""
    assert PortfolioSpec(name="a", cash=1000).account_id is None


def test_account_id_is_carried_when_supplied():
    """MPORT-05: a composition-supplied portfolio names its venue account here."""
    assert PortfolioSpec(name="a", cash=1000, account_id="acct_a").account_id == "acct_a"


def test_spec_remains_frozen():
    """The spec is a frozen value object — a later mutation must not be possible."""
    spec = PortfolioSpec(name="a", cash=1000, account_id="acct_a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.account_id = "acct_b"


def test_account_id_is_the_last_field():
    """Appended LAST so existing positional construction sites stay valid."""
    field_names = [f.name for f in dataclasses.fields(PortfolioSpec)]
    assert field_names == ["name", "cash", "account_id"]
