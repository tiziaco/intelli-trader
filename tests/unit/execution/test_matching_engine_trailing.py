"""Wave 0 Nyquist scaffolding for Phase 5 — collectible matching-engine trailing stubs.

These are deliberately empty (``pytest.skip``-bodied) placeholders created in plan
05-00 so that EVERY Phase-5 ``-k`` verify selector collects >=1 test BEFORE any
implementation (RED) step exists (project ``workflow.nyquist_validation: true``).
The real assertions land in plan 05-02 (``MatchingEngine`` ratchet logic).

Selector coverage (RESEARCH Test Map):

* ``-k "trailing and long"``     -> ``test_trailing_long_ratchet_favorable_only``
* ``-k "trailing and short"``    -> ``test_trailing_short_ratchet_favorable_only``
* ``-k "trailing and next_bar"`` -> ``test_trailing_next_bar_activation_not_same_bar``
* ``-k "trailing and gap"``      -> the two ``..._gap_through_fills_at_open_*`` tests
* ``-k "trailing and oco"``      -> ``test_trailing_oco_sl_vs_tp_limit``

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no decorator —
``--strict-markers``). No ``backtesting``/``backtrader`` import (Pitfall 3 —
``filterwarnings=["error"]``).
"""

import pytest


def test_trailing_long_ratchet_favorable_only():
    pytest.skip("Wave 0 stub — implemented in 05-02")


def test_trailing_short_ratchet_favorable_only():
    pytest.skip("Wave 0 stub — implemented in 05-02")


def test_trailing_next_bar_activation_not_same_bar():
    pytest.skip("Wave 0 stub — implemented in 05-02")


def test_trailing_gap_through_fills_at_open_long():
    pytest.skip("Wave 0 stub — implemented in 05-02")


def test_trailing_gap_through_fills_at_open_short():
    pytest.skip("Wave 0 stub — implemented in 05-02")


def test_trailing_oco_sl_vs_tp_limit():
    pytest.skip("Wave 0 stub — implemented in 05-02")
