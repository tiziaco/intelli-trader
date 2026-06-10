"""Leaf test for CASH-02 REJECTED (over-cash BUY rejected at the reservation gate ->
the honest no-orphan negative: an empty cash ledger).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_release_rejected(run_scenario):
    run_scenario(HERE)
