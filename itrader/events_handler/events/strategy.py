"""
Strategy control-plane command event: THE single typed command carrying
every D-09 verb (D-08/D-09). A frozen ``Event`` subclass (M3-01).
"""

from datetime import datetime
from typing import Any, ClassVar

from itrader.core.enums import EventType

from .base import Event


class StrategyCommandEvent(Event, frozen=True, kw_only=True, gc=False):
    """A control-plane command addressed to one strategy (D-08/D-09).

    The typed engine-command surface routes a roster/membership change to a
    specific strategy as a queue fact (no wrapper method on
    ``LiveTradingSystem`` — the command IS the event, D-09).

    **D-08 — ONE control event carries EVERY verb.** Separate typed events per
    command family were explicitly rejected: they would cost 2-3 new event types
    plus route slots plus bus tiers for marginal typing gain. The verb is a
    string discriminator and the payload rides in ONE optional ``config`` blob.

    The D-09 verb set:

    - ``add`` / ``remove`` — runtime instance lifecycle (dispatch: Plan 07).
    - ``enable`` / ``disable`` — the D-07 ``is_active`` gate.
    - ``reconfigure`` — an authoring-param delta (dispatch: Plan 08).
    - ``subscribe_portfolio`` / ``unsubscribe_portfolio`` — the D-06/D-09
      runtime-mutable portfolio fan-out edge.
    - ``add_ticker`` / ``remove_ticker`` — the original v1.7 membership verbs.

    Payload contract:

    - ``strategy_name`` — the target strategy and the event's SOLE required
      identity anchor. It is the durable per-instance identity (D-02) that every
      one of the nine verbs addresses.
    - ``verb`` — the command discriminator.
    - ``symbol`` — OPTIONAL (``str | None``). Six of the nine verbs carry no
      symbol at all, so a required field would force each of them to pass a
      meaningless sentinel. ``symbol`` is a ticker-verb DETAIL belonging to
      exactly two verbs, not the event's identity — hence the demotion.
    - ``config`` — OPTIONAL payload blob, shaped like a ``config_json`` (D-04).
      Carries the authoring params for ``add``/``reconfigure`` and the
      ``portfolio_id`` for the subscribe verbs.
    - ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``
      (business time, never wall clock — every persist stamps ``at`` from it).

    Both new fields are DEFAULTED, so every pre-existing construction still
    builds and an old-shaped msgspec payload still decodes (``kw_only=True``
    relaxes the defaults-after-non-defaults ordering).

    Construct via the factory classmethods below (the ``FillEvent.new_fill``
    house convention), never by hand.
    """

    type: ClassVar[EventType] = EventType.STRATEGY_COMMAND
    strategy_name: str
    verb: str
    symbol: str | None = None
    config: dict[str, Any] | None = None

    @classmethod
    def add(cls, strategy_name: str, strategy_type: str, config: dict[str, Any],
            *, time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``add`` command (D-08/D-09, construct-complete).

        ``strategy_type`` is folded INTO the ``config`` payload rather than
        carried beside it: the payload IS a ``config_json``-shaped blob and D-04
        specifies ``strategy_type`` as a key of that blob. Folded into a COPY —
        the caller's dict is never mutated.

        ⚠ IN-02 — ``config`` MUST be a full ``config_json``-shaped, VERSION-STAMPED
        blob (as produced by ``encode_strategy_config``, carrying an ``int``
        ``config_version``), NOT a bare authoring-kwargs dict. ``decode_strategy_config``
        hard-requires ``config_version`` and rejects a hand-built dict without it —
        so an ``add`` carrying raw kwargs is a silent loud-no-op at the consumer (the
        FastAPI-era hazard: the client's ``add`` looks accepted but registers nothing).
        """
        payload = {**config, "strategy_type": strategy_type}
        return cls(time=time, strategy_name=strategy_name,
                   verb="add", config=payload)

    @classmethod
    def remove(cls, strategy_name: str, *,
               time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``remove`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name, verb="remove")

    @classmethod
    def enable(cls, strategy_name: str, *,
               time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``enable`` command (D-07/D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name, verb="enable")

    @classmethod
    def disable(cls, strategy_name: str, *,
                time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``disable`` command (D-07/D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name, verb="disable")

    @classmethod
    def reconfigure(cls, strategy_name: str, config: dict[str, Any], *,
                    time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``reconfigure`` command (D-09, construct-complete).

        ⚠ ``config`` is a PARTIAL param delta and its semantics are **MERGE, not
        replace** (WR-04): a field OMITTED from the delta keeps its PRIOR
        INSTANCE VALUE — it does NOT revert to the class default. This is a
        PATCH-shaped payload, and the FastAPI-shaped hazard is assuming
        otherwise: sending ``{"entry_z": "3"}`` does not reset ``exit_z``.
        Named here at the constructor because that is where a caller reasons
        about the shape.
        """
        return cls(time=time, strategy_name=strategy_name,
                   verb="reconfigure", config=config)

    @classmethod
    def subscribe_portfolio(cls, strategy_name: str, portfolio_id: str, *,
                            time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``subscribe_portfolio`` command (D-06/D-09).

        The id rides in the ONE optional ``config`` payload rather than a
        parallel typed field per verb (D-08).
        """
        return cls(time=time, strategy_name=strategy_name,
                   verb="subscribe_portfolio",
                   config={"portfolio_id": portfolio_id})

    @classmethod
    def unsubscribe_portfolio(cls, strategy_name: str, portfolio_id: str, *,
                              time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``unsubscribe_portfolio`` command (D-06/D-09)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="unsubscribe_portfolio",
                   config={"portfolio_id": portfolio_id})

    @classmethod
    def add_ticker(cls, strategy_name: str, symbol: str, *,
                   time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``add_ticker`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="add_ticker", symbol=symbol)

    @classmethod
    def remove_ticker(cls, strategy_name: str, symbol: str, *,
                      time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``remove_ticker`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="remove_ticker", symbol=symbol)

    def __str__(self) -> str:
        # D-08: six of the nine verbs carry no symbol, so render it only when
        # present. `config` is reported by KEY COUNT ONLY, never by content: a
        # payload can be large and can carry operator-supplied values, and
        # __str__ feeds the logs.
        parts = [self.strategy_name, self.verb]
        if self.symbol is not None:
            parts.append(self.symbol)
        if self.config is not None:
            parts.append(f"config={len(self.config)}")
        return f"{self.type} ({', '.join(parts)})"

    def __repr__(self) -> str:
        return str(self)
