"""Leaf test for the D-07 crafted LIMIT-entry cross-val scenario.

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.

GOLDEN FROZEN (D-07 owner gate — Plan 05-04 Task 3): the owner signed off on the
verified, externally cross-validated LIMIT-entry run (2026-06-13, tiziaco — see the
sign-off block in ``tests/golden/CROSS-VALIDATION-LIMIT.md``), explicitly accepting the
dispositioned same-bar protective-SL LEGITIMATE-DIFFERENCE (A1). The ``golden/``
(trades.csv + summary.json) is now FROZEN and the former ``xfail`` pending-golden marker
is removed, so this leaf is a live, green regression lock that DIFFS exact (D-08) and
fails on any drift (D-13).
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_limit_entry_crossval(run_scenario):
    run_scenario(HERE)
