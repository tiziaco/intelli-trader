"""Wave-0 collectible stubs — PairStrategy two-leg dispatch (PAIR-01).

COLLECTIBLE ``pytest.skip`` stubs (real functions, runtime skip in the body — NOT
a module-level skip or skip decorator). The Nyquist contract requires every
06-VALIDATION.md ``-k`` selector to collect ≥1 test before any RED step; these
turn green in a later plan (the dispatch test plan, 06-03).

Selectors stubbed: ``-k both_legs``, ``-k both_present``, ``-k beta_weighted``
(06-VALIDATION.md Per-Task Verification Map). Folder-derived ``unit`` marker only.
"""

import pytest


def test_both_legs_emit_once_per_tick() -> None:
    """Both legs emit a SignalEvent exactly once per tick through _dispatch_pair."""
    pytest.skip("Wave 0 stub — implemented in Plan 06-03")


def test_both_present_guard_skips_when_one_absent() -> None:
    """D-02 both-present guard: one leg's bar absent → skip silently (no forward-fill)."""
    pytest.skip("Wave 0 stub — implemented in Plan 06-03")


def test_beta_weighted_leg_quantities() -> None:
    """The two SignalEvent.quantity values are β-weighted (N vs β·N), D-08."""
    pytest.skip("Wave 0 stub — implemented in Plan 06-03")
