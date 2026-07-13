"""Unit tests for the uniform live-data-provider surface (VENUE-05 / D-10).

Prove two things about ``itrader.price_handler.providers.live_provider``:

1. ``LiveDataProvider`` is a ``@runtime_checkable`` Protocol: ``isinstance`` is a
   STRUCTURAL check — an object exposing ``set_bar_sink`` PLUS the streaming
   seams conforms. Proven with a fake exposing the full surface, and with
   ``OkxDataProvider`` (import-only, method-presence on the class).

2. Import-inertness (D-10): the module is pure typing/no-op — it must import
   nothing ``ccxt``/``sqlalchemy``/``async``. Asserted directly on the module
   source (no ccxt/sqlalchemy import lines).

No ``__init__.py`` in this dir (package-collision memory — two top-level
``price_handler`` packages break full-suite collection).
"""

from __future__ import annotations

from itrader.price_handler.providers.live_provider import LiveDataProvider


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


# -- runtime_checkable structural conformance ---------------------------------


def test_protocol_is_runtime_checkable_fake_conforms() -> None:
    """A fake exposing the full surface is structurally a LiveDataProvider."""
    assert isinstance(_FakeFullProvider(), LiveDataProvider)


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
    """The module has no ccxt/sqlalchemy/async IMPORT lines (D-10 inertness).

    Scans actual ``import`` / ``from ... import`` statements (not docstring prose,
    which legitimately names the forbidden libraries when explaining the rule).
    """
    import itrader.price_handler.providers.live_provider as mod

    source = open(mod.__file__, encoding="utf-8").read()
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    for forbidden in ("ccxt", "sqlalchemy", "asyncio"):
        assert not any(forbidden in line for line in import_lines), (
            f"live_provider.py must not import {forbidden!r}: {import_lines}"
        )
