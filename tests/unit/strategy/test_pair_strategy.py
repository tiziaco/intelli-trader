"""Wave-0 collectible stubs — PairStrategy β-fit / z-score math (PAIR-01).

These are COLLECTIBLE ``pytest.skip`` stubs (real test functions, runtime skip in
the body — NOT a module-level skip or a skip decorator that would prevent
collection). The Nyquist contract requires every 06-VALIDATION.md ``-k`` selector
to collect ≥1 test BEFORE any RED step; these turn green (implemented) in a later
plan (the reference pair strategy / β-z math plan, 06-02/06-03).

Selectors stubbed here: ``-k beta`` and ``-k zscore`` (06-VALIDATION.md
Per-Task Verification Map). Folder-derived ``unit`` marker only — no hand-added
markers (tests/conftest.py applies the type marker from the folder).
"""

import pytest


def test_beta_log_ols_fixture() -> None:
    """β from a log-OLS fit on a hand-computed window yields the expected slope."""
    pytest.skip("Wave 0 stub — implemented in Plan 06-02/06-03")


def test_zscore_rolling_and_crossing() -> None:
    """z-score rolling mean/std + entry/exit crossing detection on a fixture."""
    pytest.skip("Wave 0 stub — implemented in Plan 06-02/06-03")
