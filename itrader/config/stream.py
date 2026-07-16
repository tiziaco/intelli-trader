"""Live stream + feed-provider domain configuration (Pydantic v2, CFG-03 / D-08).

Two thin config models that give the scattered live-only supervisor/feed knobs a
single typed home, following the ``config/order.py`` convention
(``ConfigDict(extra="forbid")`` + a ``default()`` classmethod):

  - ``StreamSettings`` folds the reconnect-supervisor family (debounce / backoff base /
    backoff cap / retry ceiling — triplicated verbatim across
    ``okx_provider``/``account.venue``/``okx`` exchange) plus the single-source OKX
    stream symbol/timeframe hardcodes. The reconnect fields stay ``float``/``int`` —
    matching the current module-constant usage at the live read sites (NOT ``Decimal``;
    these are non-money supervisor tunables, and the naming-collision
    ``config/exchange.py::ConnectionSettings`` — a DIFFERENT concept using ``Decimal``
    time fields — is deliberately not overloaded here, PATTERNS naming-collision note).
  - ``FeedProviderSettings`` folds the warmup safety margin and the REST backfill page
    size.

Pitfall 1 (D-08): this module is reachable from ``ITraderConfig()`` on the
backtest import graph, so it imports stdlib + pydantic ONLY — nothing live/ccxt/async
— keeping the OKX import-inertness gate green. The field defaults equal the retired
module constants byte-for-byte (a value drift would silently change live-supervisor
behaviour and the paper-parity window meaning, Pitfall 4).

Per D-08 the shared ``StreamSupervisor`` that will eventually CONSUME these blocks is
deferred to P5; P1 defines the config home and rewires the direct constant readers to
read a default-constructed instance (the P1 seam) — composition-root injection lands
with the supervisor consolidation.
"""

from pydantic import BaseModel, ConfigDict


class StreamSettings(BaseModel):
    """Live stream reconnect-supervisor + OKX stream-target configuration (D-08).

    Thin Pydantic model. ``extra`` is forbidden so an unknown key is rejected
    (mass-assignment defense, T-04-01) rather than silently absorbed. Defaults equal
    the retired reconnect-supervisor family and the live OKX stream hardcodes.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # Reconnect-supervisor tuning (retired reconnect family, ×3 duplicated).
    reconnect_debounce_s: float = 0.25
    reconnect_backoff_base_s: float = 1.0
    reconnect_backoff_cap_s: float = 30.0
    reconnect_retry_ceiling: int = 6
    # Live OKX stream target (retired stream-symbol/timeframe hardcodes; BTC/USDC not
    # BTC/USDT — the OKX EEA entity restricts USDT spot under MiCA).
    okx_stream_symbol: str = "BTC/USDC"
    okx_stream_timeframe: str = "1d"

    @classmethod
    def default(cls) -> "StreamSettings":
        """The default live stream settings (equal to the retired module constants)."""
        return cls()


class FeedProviderSettings(BaseModel):
    """Feed / provider warmup + backfill configuration (D-08).

    Thin Pydantic model folding the warmup safety margin and the REST backfill page
    size. ``extra`` is forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    warmup_margin: int = 5
    backfill_page: int = 1000

    @classmethod
    def default(cls) -> "FeedProviderSettings":
        """The default feed/provider settings (equal to the retired module constants)."""
        return cls()
