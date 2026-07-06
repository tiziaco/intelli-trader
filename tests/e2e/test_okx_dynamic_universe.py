"""Opt-in gated live-demo dynamic DATA subscribe/unsubscribe suite (Phase 06-05, UNIV-02).

This is the human-observed live proof that the plan-02 dynamic data-plane seam
(``OkxDataProvider.subscribe`` / ``unsubscribe``, driven from membership in plan 05)
works end-to-end against the OKX **demo** venue: after asserting ``sandbox is True``, it
dynamically subscribes ETH/USDC, observes real CLOSED (``confirm=='1'``) candle bars
arrive for the newly-added symbol, then unsubscribes and observes the stream STOP.

Scope — DATA ONLY (RESEARCH §10): this exercises pure market-data subscribe/unsubscribe.
Order settlement stays paper/replay (plan 04) and is NOT touched here — no order is
submitted, no venue-mutating action is taken. ETH/USDC data subscription is NOT gated by
the OKX EEA/MiCA whitelist (only ORDER settlement is, sCode 51155), so a data subscribe
against the demo venue is safe (MEMORY: OKX EEA demo constraints).

Isolation choice (honest, given the plan-02 provider shape): ``OkxDataProvider`` stamps a
SINGLE ``self._symbol`` into every ``ClosedBar['symbol']`` (the ring key) regardless of
which member stream produced it — a single provider therefore cannot distinguish two
co-streamed symbols by the stamp. To get a CLEAN "the ETH/USDC stream stops after
unsubscribe" observation, this test drives a provider DEDICATED to ETH/USDC (its stamp is
ETH/USDC) rather than co-streaming BTC/USDC on the same provider (which would stamp BTC
bars as ETH and pollute the stop-observation). The live system's BTC/USDC wiring default
is the "alongside" baseline the dynamic seam adds to; this test isolates the ETH/USDC
dynamic seam to prove subscribe/observe/unsubscribe/stop cleanly.

Gating: the whole module is ``pytest.mark.live`` + ``pytest.mark.slow`` and SKIPS unless
demo credentials (``OKX_API_KEY`` / ``OKX_API_SECRET`` / ``OKX_API_PASSPHRASE``) are
present. ``make test`` (``-m "not live"``) STRUCTURALLY excludes it — the credential
skip-gate alone is not a network fence once ``.env`` creds are exported, so the ``live``
marker is what keeps the default run off the venue. The single online GREEN run is
human-triggered via ``-m live``. All connector imports are LAZY (inside the test/helper
bodies) so a credential-free collection never touches connector code (``ccxt.pro``).
4-space indentation throughout (matches the ``tests/e2e`` sibling files).
"""

import os
import time

import pytest

_OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
_HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)

# The folder-derived TYPE marker (``e2e``) is auto-applied by the root conftest; ``slow`` +
# ``live`` are added by hand because this suite makes a real network round-trip against OKX
# demo. ``live`` is what makes ``make test`` (``-m "not live"``) STRUCTURALLY exclude it.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.live,
    pytest.mark.skipif(
        not _HAS_OKX_CREDS,
        reason=(
            "OKX demo credentials absent — opt-in gated live-demo dynamic-data suite "
            "skipped (UNIV-02). Set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE "
            "(demo env) to enable."
        ),
    ),
]

# --- Pinned demo-data parameters ---------------------------------------------
# ETH/USDC (not USDT): the OKX EEA entity whitelists ETH/USDC under MiCA; DATA subscription
# is not gated by the whitelist (only order settlement is), so a demo data subscribe is safe.
_DYNAMIC_SYMBOL = "ETH/USDC"    # the symbol added dynamically (the newly-added member)
_BASELINE_SYMBOL = "BTC/USDC"   # the live wiring default this dynamic seam adds "alongside"
# 1-minute candles so a CLOSED (confirm=='1') bar lands within a bounded human-observed
# window (a 1d candle would only close at day boundary — unusable for a live observation).
_TIMEFRAME = "1m"

# Bounded observation windows — a live venue round-trip, never an unbounded blocking wait.
# A closed 1m bar lands at the next minute boundary, so the subscribe window must span > 60s
# to guarantee at least one close; the stop window must likewise span > 60s so a bar that
# WOULD arrive if still subscribed is given the chance to (and its ABSENCE proves the stop).
_SUBSCRIBE_OBSERVE_S = 135.0
_STOP_OBSERVE_S = 75.0
_POLL_S = 1.0


def _build_demo_provider():
    """Lazily construct + connect a sandbox-routed connector and an ETH/USDC data provider.

    Returns ``(connector, provider, received)`` un-started beyond ``connect()`` — the TEST
    owns subscribe/unsubscribe + teardown (Pitfall 4 — no leaked authenticated session).
    ``received`` is the list the bar sink appends every CLOSED bar to (``_process_row``
    gates ``confirm=='1'``, so only completed bars ever reach the sink). ALL connector
    imports are LAZY here so a credential-free collection never touches connector code.
    """
    from itrader.config.okx_settings import OkxSettings
    from itrader.connectors.okx import OkxConnector
    from itrader.price_handler.providers.okx_provider import OkxDataProvider

    connector = OkxConnector(OkxSettings())  # type: ignore[call-arg]
    connector.connect()
    # Provider dedicated to the dynamic symbol: its stamp is ETH/USDC (see module docstring
    # for why a single provider cannot co-stream BTC cleanly).
    provider = OkxDataProvider(
        connector, symbol=_DYNAMIC_SYMBOL, timeframe=_TIMEFRAME)
    received: list = []
    provider.set_bar_sink(lambda bar: received.append(bar))
    return connector, provider, received


def _closed_bars_for(received, symbol):
    """Closed bars the sink captured for ``symbol`` (the provider stamps its own _symbol)."""
    return [b for b in received if b.get("symbol") == symbol]


def test_dynamic_data_subscribe_then_unsubscribe_on_okx_demo() -> None:
    """DATA-ONLY: subscribe ETH/USDC -> observe closed bars -> unsubscribe -> observe stop.

    Asserts, in order:
      (0) the connector is sandbox-routed (``sandbox is True``) BEFORE any subscribe — the
          T-06-05-SPOOF mitigation (never stream from the real venue believing it is demo).
      (1) after ``subscribe(ETH/USDC)`` the per-symbol registry holds the stream and at least
          one CLOSED (confirm=='1') ETH/USDC bar arrives within the bounded window.
      (2) after ``unsubscribe(ETH/USDC)`` the registry drops the stream and NO further
          ETH/USDC closed bar arrives within a follow-up window (the stream stopped).

    Touches NO order/settlement path — pure market-data subscribe/unsubscribe (RESEARCH §10).
    """
    connector, provider, received = _build_demo_provider()
    try:
        # (0) T-06-05-SPOOF: demo host only, asserted BEFORE any subscribe/venue read.
        assert connector.sandbox is True, (
            "connector is NOT sandbox-routed — refusing to subscribe against a possibly "
            "real venue (T-06-05-SPOOF)")

        # --- subscribe + observe closed bars arrive for the newly-added symbol --------
        provider.subscribe(_DYNAMIC_SYMBOL)
        assert _DYNAMIC_SYMBOL in provider._streams, (
            "subscribe did not register the ETH/USDC stream in the per-symbol registry")

        deadline = time.monotonic() + _SUBSCRIBE_OBSERVE_S
        while time.monotonic() < deadline:
            if _closed_bars_for(received, _DYNAMIC_SYMBOL):
                break
            time.sleep(_POLL_S)
        arrived = _closed_bars_for(received, _DYNAMIC_SYMBOL)
        assert arrived, (
            f"no CLOSED {_DYNAMIC_SYMBOL} bar arrived within {_SUBSCRIBE_OBSERVE_S}s of "
            f"subscribe — the dynamic data subscription did not stream (baseline "
            f"{_BASELINE_SYMBOL} is the live wiring default this seam adds alongside)")

        # --- unsubscribe + observe the stream STOP ------------------------------------
        count_at_unsubscribe = len(_closed_bars_for(received, _DYNAMIC_SYMBOL))
        provider.unsubscribe(_DYNAMIC_SYMBOL)
        assert _DYNAMIC_SYMBOL not in provider._streams, (
            "unsubscribe did not drop the ETH/USDC stream from the per-symbol registry")

        # Give a bar that WOULD arrive if still subscribed the chance to (window > 60s), then
        # assert the closed-bar count for ETH/USDC did NOT advance — the stream stopped.
        time.sleep(_STOP_OBSERVE_S)
        count_after_stop = len(_closed_bars_for(received, _DYNAMIC_SYMBOL))
        assert count_after_stop == count_at_unsubscribe, (
            f"{_DYNAMIC_SYMBOL} closed bars kept arriving after unsubscribe "
            f"({count_at_unsubscribe} -> {count_after_stop}) — the stream did not stop")
    finally:
        # Teardown-safe: cancel any still-registered stream, then disconnect the connector
        # so no authenticated demo socket leaks under filterwarnings=["error"].
        try:
            provider.unsubscribe(_DYNAMIC_SYMBOL)
        finally:
            try:
                connector.disconnect()
            except Exception:
                pass
