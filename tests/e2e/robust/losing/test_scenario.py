"""Leaf test for ROBUST-03c losing (net-negative round-trip -> all-finite metrics).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_losing(run_scenario):
    run_scenario(HERE)
