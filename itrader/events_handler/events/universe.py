"""
Universe / live control-plane events (D-03/D-04/D-06/D-09).

Four frozen ``Event`` facts that carry Phase-7 live dynamic-universe traffic
on the global queue. All mirror the ``UniverseUpdateEvent`` shape (frozen
msgspec ``Event``, ``ClassVar`` type pin, ``__str__``/``__repr__``) and carry
the inherited business ``time`` (never wall clock — callers supply the
venue/business time, RESEARCH Pitfall 5):

- ``BarsLoaded`` — warmup bars bulk-transported for one symbol/timeframe (D-03).
- ``BarsLoadFailed`` — a warmup backfill errored for one symbol (D-04).
- ``UniversePollEvent`` — control-plane poll tick, no payload (D-06).
- ``StrategyCommandEvent`` — THE single control-plane command carrying every
  D-09 verb (add/remove/enable/disable/reconfigure/subscribe_portfolio/
  unsubscribe_portfolio/add_ticker/remove_ticker), one factory per verb
  (D-08/D-09).

This plan ships NO consumers: the ``_routes`` entries are explicit-empty and
live consumers are wired live-only in Plan 07 (backtest stays inert).
"""

from datetime import datetime
from typing import Any, ClassVar

from itrader.core.bar import Bar
from itrader.core.enums import EventType

from .base import Event


class BarsLoaded(Event, frozen=True, kw_only=True, gc=False):
    """Warmup bars loaded for one ``(symbol, timeframe)`` (D-03).

    Bulk transport for the REST/backfill warmup path: instead of pushing each
    historical bar one at a time, the loader emits ONE ``BarsLoaded`` carrying
    the whole warmup window as an immutable ``tuple[Bar, ...]``.

    Payload contract:

    - ``bars`` is a ``tuple`` of immutable Decimal ``Bar`` structs — reused
      verbatim from ``core.bar.Bar`` (the same struct ``BarEvent`` carries).
      NEVER a pandas frame on the queue (M5-02).
    - ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``
      (business time = the newest fetched bar's time; UUIDv7 identity).
    """

    type: ClassVar[EventType] = EventType.BARS_LOADED
    symbol: str
    timeframe: str
    bars: tuple[Bar, ...]

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)


class BarsLoadFailed(Event, frozen=True, kw_only=True, gc=False):
    """A warmup backfill failed for one ``symbol`` (D-04).

    Emitted when the REST/backfill warmup for a freshly-added universe symbol
    errors, so the readiness gate can move that entry to ``Readiness.FAILED``.

    Security (T-05-27, RESEARCH Security V5): ``reason`` MUST be a SCRUBBED
    exception TYPE / short human message only — NEVER ``str(exc)`` and never a
    secret/credential/URL. The emit site (Plan 07) is responsible for the
    scrub; this struct only carries the already-scrubbed string.

    ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``.
    """

    type: ClassVar[EventType] = EventType.BARS_LOAD_FAILED
    symbol: str
    reason: str

    def __str__(self) -> str:
        return f"{self.type} ({self.symbol})"

    def __repr__(self) -> str:
        return str(self)


class UniversePollEvent(Event, frozen=True, kw_only=True, gc=False):
    """Control-plane universe-poll tick (D-06).

    A pure control signal that the universe poll cadence elapsed — it carries
    NO extra payload beyond the inherited business ``time``. The live poll
    handler (Plan 07) consumes it to re-derive membership; the backtest route
    is explicit-empty, so dispatching one is an inert no-op.
    """

    type: ClassVar[EventType] = EventType.UNIVERSE_POLL

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)


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
