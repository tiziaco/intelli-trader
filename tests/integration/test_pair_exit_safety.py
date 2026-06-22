"""Wave-0 collectible stub — pair close-only / safe-when-flat exit (PAIR-01, D-12).

COLLECTIBLE ``pytest.skip`` stub (a real function, runtime skip in the body — NOT
a module-level skip or skip decorator). The Nyquist contract requires the
06-VALIDATION.md selector to collect ≥1 test before any RED step; this turns green
in a later plan (the exit-safety plan).

The live-test form of the D-12 trace: a quantity-free ``exit_fraction=1.0`` exit
(a cover) clamps-to-flat and no-ops when the position is already flat — an
explicit quantity on an exit would instead open a NEW position (the D-12 hazard).
Folder-derived ``integration`` marker only.
"""

import pytest


def test_close_only_exit_noop_when_flat() -> None:
    """A quantity-free exit_fraction=1.0 exit clamps-to-flat and no-ops when flat (D-12)."""
    pytest.skip("Wave 0 stub — implemented in a later Phase 6 plan")
