"""LiveDataProvider — the uniform surface every live data provider presents (VENUE-05 / D-10).

This module gives every live data provider ONE structural shape so the
``VenueLifecycle`` (05-06) can wire ANY provider unconditionally — no
``if exchange=='okx' … elif =='paper'`` provider-wiring branch, no ``hasattr``
sprinkling. It carries a single symbol:

- ``LiveDataProvider`` — a ``@runtime_checkable`` ``Protocol`` (the mirror shape of
  the ``LiveConnector`` seam in ``connectors/base.py``) declaring the uniform
  provider surface: the REQUIRED ``set_bar_sink`` plus the OPTIONAL
  streaming/wiring seams (``set_global_queue`` / ``set_halt_signal`` /
  ``set_stream_state_listener`` / ``subscribe`` / ``unsubscribe`` /
  ``spawn_warmup`` / ``is_streaming_healthy``). It is a contract, not a base
  class — method bodies are ``...``. A provider that does not stream (e.g. the
  offline ``ReplayDataProvider``) implements those optional seams DIRECTLY as
  no-ops rather than inheriting them, so the lifecycle can call them
  unconditionally.

D-10 (provider uniformity rule): an OPTIONAL method on a PRESENT object → a no-op
implementation on the provider (call unconditionally, kills ``hasattr``). An
ENTIRELY ABSENT component (paper's connector/account) is a different granularity —
that stays an explicit ``None``-guard in ``VenueLifecycle``, not modelled here.

``OkxDataProvider`` already exposes every method on this surface, so it satisfies
``LiveDataProvider`` STRUCTURALLY without inheriting anything and is NOT edited by
this plan (which also avoids a file conflict with 05-01's StreamSupervisor
delegation in ``okx_provider.py``).

Inertness (VENUE-05 / D-10): this module is pure typing/no-op — it imports nothing
``ccxt``/``sqlalchemy``/``async``. Type parameters are kept loose (``Any`` /
``Callable`` under ``TYPE_CHECKING``) so importing it is free and it never touches
the backtest hot-path forbidden-module set.

Indentation: this file is 4-SPACE (the whole ``providers/`` tree is 4-space,
matched to ``okx_provider.py``) — never tabs. ``mypy --strict`` applies (new code).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class LiveDataProvider(Protocol):
    """Structural surface every live data provider presents (VENUE-05 / D-10).

    The swap-a-fake seam the ``VenueLifecycle`` types against so it can wire ANY
    provider (streaming OKX or non-streaming replay) with the SAME calls. Mirrors
    the ``LiveConnector`` Protocol shape (``@runtime_checkable``, ``...`` bodies,
    no ABC). Method bodies are ``...`` — this is a contract, not a base class.

    Surface split (D-10):

    - **Required:** ``set_bar_sink`` — the ONE method a concrete provider MUST
      implement (the feed registers the closed-bar sink through it). A no-op
      default would silently drop every bar, so each concrete provider MUST
      implement it.
    - **Optional streaming/wiring seams:** ``set_global_queue`` /
      ``set_halt_signal`` / ``set_stream_state_listener`` / ``subscribe`` /
      ``unsubscribe`` / ``spawn_warmup`` / ``is_streaming_healthy`` — a streaming
      provider (OKX) implements them for real; a non-streaming provider implements
      them DIRECTLY as no-ops so the lifecycle can call them unconditionally.
    """

    def set_bar_sink(self, sink: Callable[[Any], None]) -> None:
        """REQUIRED: register the closed-bar sink the ``LiveBarFeed`` consumes.

        The provider hands a raw ``ClosedBar`` dict to ``sink``; the feed owns
        ``BarEvent`` construction and the ring buffer. Concrete providers MUST
        implement this — a no-op default would silently drop every bar.
        """
        ...

    def set_global_queue(self, global_queue: Any) -> None:
        """Optional streaming seam: inject the engine queue the async warmup emits on."""
        ...

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Optional streaming seam: inject the freeze-in-place halt entrypoint."""
        ...

    def set_stream_state_listener(
        self,
        on_down: Callable[[str], None],
        on_up: Callable[[str], None],
    ) -> None:
        """Optional streaming seam: inject the pause/resume-on-disconnect callbacks."""
        ...

    def subscribe(self, symbol: str) -> None:
        """Optional streaming seam: dynamically subscribe one symbol's stream."""
        ...

    def unsubscribe(self, symbol: str) -> None:
        """Optional streaming seam: dynamically unsubscribe a symbol's stream."""
        ...

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        """Optional streaming seam: schedule a loop-native REST warmup fetch."""
        ...

    def is_streaming_healthy(self) -> bool:
        """Optional streaming seam: True iff the provider's stream is up.

        A non-streaming provider is trivially healthy — its own no-op implementation
        returns ``True``.
        """
        ...
