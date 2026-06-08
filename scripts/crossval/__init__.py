"""Cross-validation reference-engine harness (08-05+).

Package marker so the per-engine force-match modules can use relative imports.

SCRIPT-ONLY (D-10): the engine modules in this package import the third-party
reference engines (`backtesting`, `backtrader`) which emit warnings at import
(bokeh / numpy-2 deprecations / backtrader SyntaxWarning docstring escapes)
that would trip the repo's ``filterwarnings=["error"]`` test contract. NEVER
import anything from this package under ``tests/`` or in ``itrader/`` — keep it
on the script path only.
"""
