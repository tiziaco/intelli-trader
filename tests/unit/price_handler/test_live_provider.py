"""Unit tests for the uniform live-data-provider surface (VENUE-05 / D-10).

Prove three things about ``itrader.price_handler.providers.live_provider``:

1. ``BaseLiveDataProvider`` supplies callable NO-OP defaults for every OPTIONAL
   streaming/wiring seam (``set_global_queue`` / ``set_halt_signal`` /
   ``set_stream_state_listener`` / ``subscribe`` / ``unsubscribe`` /
   ``spawn_warmup`` all return ``None``; ``is_streaming_healthy`` returns
   ``True`` — a non-streaming provider is trivially healthy). This is what lets
   the ``VenueLifecycle`` (05-06) call the streaming seams UNCONDITIONALLY on a
   base-backed provider that does not stream, killing the venue-string branch.

2. ``LiveDataProvider`` is a ``@runtime_checkable`` Protocol: ``isinstance`` is a
   STRUCTURAL check — an object exposing ``set_bar_sink`` PLUS the streaming
   seams conforms. Proven with a fake and with a ``BaseLiveDataProvider``
   subclass that adds the required ``set_bar_sink`` (exactly the shape
   ``ReplayDataProvider`` takes in Task 2 — the base contributes the streaming
   no-ops, the subclass contributes the real sink).

3. ``BaseLiveDataProvider`` deliberately does NOT default ``set_bar_sink`` (a
   concrete provider MUST wire the real sink — a defaulted no-op would silently
   drop every bar), so a bare base is NOT yet a conforming provider; and a
   subclass overriding ``set_bar_sink`` is honoured (the base never clobbers it).

Import-inertness (D-10): the module is pure typing/no-op — it must import
nothing ``ccxt``/``sqlalchemy``/``async``. Proven here import-only for
``OkxDataProvider`` structural conformance and asserted directly on the module
source (no ccxt/sqlalchemy import lines).

No ``__init__.py`` in this dir (package-collision memory — two top-level
``price_handler`` packages break full-suite collection).
"""

from __future__ import annotations

from itrader.price_handler.providers.live_provider import (
    BaseLiveDataProvider,
    LiveDataProvider,
)


class _FakeFullProvider:
    """A hand-rolled test double exposing the FULL LiveDataProvider surface."""

    def set_bar_sink(self, sink: object) -> None:
        self.sink = sink

    def set_global_queue(self, global_queue: object) -> None:
        return None

    def set_halt_signal(self, halt_signal: object) -> None:
        return None

    def set_stream_state_listener(self, on_down: object, on_up: object) -> None:
        return None

    def subscribe(self, symbol: str) -> None:
        return None

    def unsubscribe(self, symbol: str) -> None:
        return None

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        return None

    def is_streaming_healthy(self) -> bool:
        return True


class _BaseBackedProvider(BaseLiveDataProvider):
    """A minimal concrete provider — base's no-op seams + a real ``set_bar_sink``.

    This is exactly the shape ``ReplayDataProvider`` takes in Task 2: it inherits
    the no-op streaming seams and adds the ONE required method the base does not
    default.
    """

    def __init__(self) -> None:
        self.sink: object | None = None

    def set_bar_sink(self, sink: object) -> None:
        self.sink = sink


# -- No-op default seams (a bare BaseLiveDataProvider) ------------------------


def test_base_streaming_seams_are_noops_returning_none() -> None:
    """Every OPTIONAL streaming/wiring seam on a bare base returns None (no raise)."""
    base = BaseLiveDataProvider()
    assert base.set_global_queue(object()) is None
    assert base.set_halt_signal(lambda reason: None) is None
    assert base.set_stream_state_listener(lambda s: None, lambda s: None) is None
    assert base.subscribe("BTCUSD") is None
    assert base.unsubscribe("BTCUSD") is None
    assert base.spawn_warmup("BTCUSD", "1d", 10) is None


def test_base_is_streaming_healthy_returns_true() -> None:
    """A non-streaming provider is trivially healthy (D-10 no-op default)."""
    assert BaseLiveDataProvider().is_streaming_healthy() is True


def test_base_does_not_default_set_bar_sink() -> None:
    """``set_bar_sink`` is intentionally NOT defaulted — concrete providers must wire it."""
    assert not hasattr(BaseLiveDataProvider(), "set_bar_sink")


# -- runtime_checkable structural conformance ---------------------------------


def test_protocol_is_runtime_checkable_fake_conforms() -> None:
    """A fake exposing the full surface is structurally a LiveDataProvider."""
    assert isinstance(_FakeFullProvider(), LiveDataProvider)


def test_base_subclass_with_set_bar_sink_conforms() -> None:
    """Base no-op seams + a real ``set_bar_sink`` = a conforming provider.

    This proves the mechanism ``ReplayDataProvider`` relies on in Task 2.
    """
    assert isinstance(_BaseBackedProvider(), LiveDataProvider)


def test_bare_base_is_not_yet_a_conforming_provider() -> None:
    """A bare base lacks the required ``set_bar_sink`` so it is NOT yet a provider."""
    assert not isinstance(BaseLiveDataProvider(), LiveDataProvider)


def test_set_bar_sink_override_is_honoured() -> None:
    """Overriding ``set_bar_sink`` on a subclass is honoured (base never clobbers it)."""
    provider = _BaseBackedProvider()
    sentinel = object()
    provider.set_bar_sink(sentinel)
    assert provider.sink is sentinel


# -- OkxDataProvider structural conformance (import-only) ---------------------


def test_okx_data_provider_conforms_structurally() -> None:
    """``OkxDataProvider`` already exposes the full surface — conforms without edit.

    Import-only structural check on the CLASS (no instance / no ccxt client): the
    class exposes every LiveDataProvider method as an attribute, which is what the
    runtime_checkable Protocol keys off. Constructing an instance would need a live
    connector, so we assert method presence on the class instead.
    """
    from itrader.price_handler.providers.okx_provider import OkxDataProvider

    for method in (
        "set_bar_sink",
        "set_global_queue",
        "set_halt_signal",
        "set_stream_state_listener",
        "subscribe",
        "unsubscribe",
        "spawn_warmup",
        "is_streaming_healthy",
    ):
        assert callable(getattr(OkxDataProvider, method, None)), (
            f"OkxDataProvider is missing the LiveDataProvider seam {method!r}"
        )


def test_live_provider_module_imports_nothing_heavy() -> None:
    """The module source imports no ccxt/sqlalchemy/async (D-10 inertness)."""
    import itrader.price_handler.providers.live_provider as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "import ccxt" not in source
    assert "sqlalchemy" not in source
    assert "import asyncio" not in source
