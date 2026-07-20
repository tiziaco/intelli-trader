"""
Strategy-specific exceptions for the iTrader system.

``StrategyAdmissionError`` is the shared ancestor of every strategy-payload
REFUSAL — the single type a caller catches to mean "this strategy payload was
rejected at admission". The two param errors below are its structured members:

- ``UnknownParamError`` — an unknown construction kwarg was supplied (D-06). The
  engine never silently drops a typo'd or stray kwarg; it rejects loudly so an
  author's mistake surfaces at construction, not as a silently-ignored knob.
- ``MissingParamError`` — a required bare-annotation attribute was not supplied
  (D-07). An under-specified strategy is rejected rather than running with a
  missing required parameter.

Both carry BOTH the house ``ValidationError`` structured-field convention
(RESEARCH §Don't Hand-Roll — never a bare ``raise ValueError``) AND the shared
``StrategyAdmissionError`` admission ancestor.
"""

from .base import ITraderError, ValidationError


class StrategyAdmissionError(ITraderError, ValueError):
    """A strategy payload was REFUSED at admission.

    The payload is either an externally-supplied ``STRATEGY_COMMAND`` or a stored
    registry row; either way it describes a strategy that could not be admitted —
    an unknown type, an undeserializable config blob, or param drift in either
    direction. This is the one ancestor a caller names to catch "a bad strategy
    payload".

    BOTH bases are load-bearing; do not "simplify" either away.

    * ``ITraderError`` joins the house hierarchy, consistent with
      ``PortfolioError`` / ``OrderError`` / ``DataError``.
    * ``ValueError`` preserves every pre-existing catch site AND keeps
      plain-message construction working (``ITraderError`` is a bare
      ``Exception`` subclass). That second property is precisely why the
      alternative — rooting the whole family at the house ``ValidationError`` —
      is impossible: ``StrategyConfigError`` is raised roughly 25 times with a
      plain message string, while ``ValidationError.__init__`` takes
      ``(field, value=None, message=None)``.

    Motivating defect — CR-01. Before this base existed, catching "a bad strategy
    payload" meant hand-listing unrelated names across four separate sites. Those
    sets drifted, and one drifted tuple let a bare ``ValueError`` escape a
    never-raise boundary into a live HALT vector. The shared ancestor removes the
    drift surface itself.
    """


class UnknownParamError(ValidationError, StrategyAdmissionError):
    """Raised when a strategy is constructed with an unknown kwarg (D-06).

    The engine rejects any construction/reconfigure kwarg that does not name a
    declared parameter, calling ``UnknownParamError(sorted(kwargs))`` with the
    collection of offending names.
    """

    def __init__(self, names: list[str]):
        self.names = names
        joined = ", ".join(repr(name) for name in names)
        super().__init__(
            field="strategy_params",
            message=f"unknown parameter(s) supplied: {joined}",
        )


class MissingParamError(ValidationError, StrategyAdmissionError):
    """Raised when a required bare-annotation attr is not supplied (D-07).

    The engine rejects an under-specified strategy, calling
    ``MissingParamError(name)`` with the single missing required attribute name.
    """

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            field=name,
            message="required parameter was not supplied",
        )
