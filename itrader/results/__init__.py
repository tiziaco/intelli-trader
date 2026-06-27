"""The results-store package — home of the ``ResultsStore`` ABC (SPINE-02, Phase 2 impl).

Re-exports the narrow ``ResultsStore`` abstract base class: the spine's fourth composable
concern. The concrete ``Sql``-backed implementation (and its ``runs`` / ``run_artifacts``
schema) lands in Phase 2; this package ships only the composition seam.
"""

from itrader.results.base import ResultsStore

__all__ = ["ResultsStore"]
