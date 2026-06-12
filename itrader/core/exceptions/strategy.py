"""
Strategy-specific exceptions for the iTrader system.

These are the loud-rejection errors the Strategy param-introspection engine raises
when a strategy is constructed (or reconfigured) with a contract violation:

- ``UnknownParamError`` — an unknown construction kwarg was supplied (D-06). The
  engine never silently drops a typo'd or stray kwarg; it rejects loudly so an
  author's mistake surfaces at construction, not as a silently-ignored knob.
- ``MissingParamError`` — a required bare-annotation attribute was not supplied
  (D-07). An under-specified strategy is rejected rather than running with a
  missing required parameter.

Both subclass the house ``ValidationError`` (RESEARCH §Don't Hand-Roll — never a
bare ``raise ValueError``) so they carry the structured-field convention.
"""

from .base import ValidationError


class UnknownParamError(ValidationError):
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


class MissingParamError(ValidationError):
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
