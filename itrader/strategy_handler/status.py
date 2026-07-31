"""The strategy-status vocabulary: durable INTENT x in-process ROSTER.

The direct analog of ``venues/accounts.py``'s ``AccountState``/``AccountStatus``, and for
the same reason: two independent facts decide whether a strategy trades — what the registry
row says (``enabled`` / disabled / no row at all) and whether an instance is actually
registered on the handler in THIS process. A read that reports only the roster cannot see
the two anomalies below, which are precisely the states an operator has to act on.

Where the account analog reads its runtime fact from ``bring_online``, this one reads it
from rehydrate: a row that could not be reconstructed (retired ``strategy_type``,
undeserializable blob, param drift, unwarmable timeframe) is SKIPPED, and D-19 leaves the
row untouched — so a quarantined strategy presents exactly as "row present, no instance".

Import-light by construction: it names no store and no ``Strategy``, taking both halves as
plain data, so it stays off the GATE-01 SQL import graph.

4-space indentation (a new module, matching ``venues/accounts.py`` which it mirrors).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

__all__ = [
    "StrategyState",
    "StrategyStatus",
]


class StrategyState(Enum):
    """The four reachable combinations of registry row and in-process instance.

    Named as one closed vocabulary because each combination needs a different operator
    action, and two of them are invisible to any read that lists only the roster.
    """

    #: Row enabled, instance registered and live. The only state that generates signals.
    ACTIVE = "active"
    #: Instance registered but dark — a disabled row loaded present-but-dark (CR-01), or a
    #: ``deactivate`` verb applied at runtime. It still OWNS its open positions and is
    #: re-enable-able, which is why the instance is kept rather than dropped.
    INACTIVE = "inactive"
    #: Row present, NO instance — rehydrate quarantined it (D-19), or the boot that would
    #: have loaded it has not run. The row is never rewritten on a quarantine (the database
    #: holds operator INTENT), so this is how a quarantined strategy presents. It is
    #: self-recovering: fix the cause, restart, and the same row loads clean.
    QUARANTINED = "quarantined"
    #: Instance with NO row behind it — a hand-registered strategy on a run with no durable
    #: registry (every backtest instance is this), or a row deleted underneath a live
    #: process. Nothing rehydrates this instance on restart.
    UNTRACKED = "untracked"


@dataclass(frozen=True)
class StrategyStatus:
    """One ``strategy_name``'s durable intent AND roster reality.

    Carries the RAW facts rather than a label alone — ``enabled`` (``None`` when there is no
    row) and ``registered`` — and derives ``state`` from them so the two can never disagree.

    Frozen, and a SNAPSHOT: what was true when the roster was read, not a live view.
    """

    strategy_name: str
    #: ``None`` means NO registry row — distinct from ``False`` (a row that says disabled).
    enabled: Optional[bool]
    #: Whether an instance is on the handler's roster in this process.
    registered: bool
    #: The instance's own ``is_active`` flag; always ``False`` when not registered, since
    #: there is no instance to read it off.
    is_active: bool
    #: The error KIND that quarantined this row (the exception's type name), or ``None``.
    #: Never the exception MESSAGE — a codec error's message quotes the stored config value,
    #: and this surface crosses out to an operator channel (the ``_quarantine_alert``
    #: declared-fields-only precedent).
    quarantine_reason: Optional[str] = None

    def __post_init__(self) -> None:
        """Refuse the one combination that names nothing: no row AND no instance.

        A name with neither is not a strategy in any state — it is a name nothing knows
        about — so it has no member in ``StrategyState`` and must not be constructible.
        Rejecting it here is what keeps ``state`` TOTAL rather than returning a lie for an
        input it cannot label.
        """
        if self.enabled is None and not self.registered:
            raise ValueError(
                f"strategy {self.strategy_name!r} has no registry row and no registered "
                "instance — that name does not exist, so it has no status")

    @property
    def state(self) -> StrategyState:
        """The label the raw facts imply."""
        if not self.registered:
            return StrategyState.QUARANTINED
        if self.enabled is None:
            return StrategyState.UNTRACKED
        return StrategyState.ACTIVE if self.is_active else StrategyState.INACTIVE
