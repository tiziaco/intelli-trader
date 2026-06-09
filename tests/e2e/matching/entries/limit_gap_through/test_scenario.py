"""Leaf test for MATCH-02 (BUY LIMIT favorable gap-through entry).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_limit_gap_through(run_scenario):
    run_scenario(HERE)
