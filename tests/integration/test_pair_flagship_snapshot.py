"""Wave-0 collectible stubs — pair flagship STABILITY snapshot + determinism (PAIR-01).

This is a STABILITY lock, NOT a correctness oracle (D-11). The ETH/BTC pair-trading
run output is regression-locked as a GENERATED snapshot (not hand-verified) — a
two-leg market-neutral strategy partially cancels its own sign errors, so it is a
weak correctness oracle. The correctness oracle for this milestone is the crafted
short/leveraged/liquidation scenarios cross-validated under XVAL-01 (Phase 4), NOT
pair trading. This phase does NOT re-baseline the SMA_MACD golden master
(tests/golden/{trades,equity}.csv is untouched); the pair snapshot lives in its
own NEW artifact directory.

COLLECTIBLE ``pytest.skip`` stubs (real functions, runtime skip in the body — NOT
a module-level skip or skip decorator). The Nyquist contract requires every
06-VALIDATION.md selector — including ``-k determinism`` — to collect ≥1 test
before any RED step; these turn green in a later plan (the flagship snapshot plan).
Folder-derived ``integration`` marker only.
"""

import pytest


def test_pair_flagship_snapshot_matches() -> None:
    """Full ETH/BTC run output matches the committed STABILITY snapshot (NOT an oracle, D-11)."""
    pytest.skip("Wave 0 stub — implemented in a later Phase 6 plan")


def test_pair_flagship_determinism_double_run() -> None:
    """Two runs of the ETH/BTC flagship are byte-identical (determinism, D-11)."""
    pytest.skip("Wave 0 stub — implemented in a later Phase 6 plan")
