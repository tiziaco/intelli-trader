"""Leaf test for the single-market-buy canary (D-01).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns the build → run → read → assemble →
diff-what's-frozen contract (Plan 02); the leaf adds NO assert/diff logic of its
own. This is the copy-template Phase 6-9 authors clone per scenario.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_single_market_buy(run_scenario):
    run_scenario(HERE)
