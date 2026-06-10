"""Leaf test for MATCH-03 (SELL STOP pessimistic gap-down stop-loss exit leg of a long).

IN-03: under the LONG_ONLY v1.1 guard the SELL STOP is the stop-loss EXIT leg of a
long position, NOT a short entry — see this leaf's scenario.py for the accurate
explanation.

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_stop_gap_down(run_scenario):
    run_scenario(HERE)
