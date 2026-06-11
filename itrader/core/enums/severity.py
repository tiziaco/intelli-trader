"""
Error-severity enum for the iTrader system (D-05).

Replaces the comment-as-enum ``severity: str = "ERROR"  # ERROR, CRITICAL,
WARNING`` affordance on ``ErrorEvent`` with a real class-based, string-valued
enum following the ``FillStatus`` house pattern (explicit UPPERCASE string
values + a case-insensitive ``_missing_`` parser raising a clear f-string
``ValueError``). The ERROR-route log consumer keys its severity-to-logger map
on these members instead of bare strings.
"""

from enum import Enum


class ErrorSeverity(Enum):
    """Severity of an ``ErrorEvent`` (D-05).

    Member values are explicit uppercase strings, matching the exact string
    vocabulary the legacy comment-as-enum documented ('ERROR', 'CRITICAL',
    'WARNING'). No code relies on the ``.value`` being an int, so explicit
    string values are safe and clearer.
    """
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"

    @classmethod
    def _missing_(cls, value: object) -> "ErrorSeverity":
        """Case-insensitive string parse; raise a clear f-string error.

        Invoked by ``ErrorSeverity(value)`` on lookup failure, mirroring the
        ``FillStatus._missing_`` shape. Never the buggy
        ``raise ValueError('Value %s', x)`` printf-tuple form (D-03).
        """
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown ErrorSeverity: {value!r}")
