"""Pre-trade safety / throttle domain configuration (Pydantic v2, D-07/D-13/D-14).

Thin config models that give the pre-trade backstop its typed home, following the
``config/stream.py`` convention (``ConfigDict(extra="forbid")`` + a ``default()``
classmethod):

  - ``ThrottleSettings`` holds the static rate + notional caps the ``PreTradeThrottle``
    (Plan 05) enforces on risk-opening ENTRY orders: a sliding-window order cap
    (``max_orders`` per ``window_s``), a per-order notional ceiling
    (``max_notional_per_order``, Decimal — money end-to-end), and the D-09 breach-WARNING
    dedup interval (``warn_min_interval_s``). Conservative defaults are ON by default
    (D-07) — the throttle is armed with 10 orders / 10s + $25k without any opt-in.
  - ``SafetySettings`` is the one-domain container (holds ``throttle``) so the P9
    runtime-config allowlist (D-14) has a single settable object to swap. This plan
    ships STATIC caps only and merely SHAPES that mutation seam; NO runtime
    ``ConfigUpdateEvent`` wiring lands here (that is P9).

Inertness (mirrors ``config/stream.py``, D-13): this module is reachable from
``SystemConfig.default()`` on the backtest import graph, so it imports stdlib + pydantic
ONLY — nothing live/ccxt/async/sql — keeping the OKX import-inertness gate green. Every
cap is inert on the backtest path (the throttle is never constructed in backtest mode).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ThrottleSettings(BaseModel):
    """Static pre-trade throttle caps (D-07/D-13).

    Thin Pydantic model. ``extra`` is forbidden so an unknown key is rejected
    (mass-assignment defense, T-04-01) rather than silently absorbed. Defaults are the
    conservative D-07 caps, ON by default. ``max_notional_per_order`` is ``Decimal``
    (money end-to-end); the rate-window fields stay ``int``/``float`` (non-money
    supervisor tunables read off the injected clock, not wall clock).
    """

    model_config = ConfigDict(extra="forbid")

    # Sliding-window order-rate cap (D-04/D-07): at most ``max_orders`` ENTRY orders
    # per ``window_s`` seconds, pruned off the injected clock.
    max_orders: int = 10
    window_s: float = 10.0
    # Per-order notional ceiling (D-07) — Decimal, money end-to-end.
    max_notional_per_order: Decimal = Decimal("25000")
    # D-09: minimum seconds between de-duped breach-WARNING ErrorEvents (dedup off the
    # injected clock), so a burst of rejects does not flood the ERROR route.
    warn_min_interval_s: float = 5.0

    @classmethod
    def default(cls) -> "ThrottleSettings":
        """The default throttle caps (conservative, ON by default per D-07)."""
        return cls()


class FailureRateSettings(BaseModel):
    """CF-1 aggregate failure-rate tripwire thresholds (D-14/D-15).

    Per-``FailureClass`` ``(threshold, window_s)`` policy the Phase-8 CF-1
    failure-rate tripwire (08-02) reads at construction to build its ``_POLICY``
    map. Modelled on ``ThrottleSettings`` (sliding-window shape, ON by default,
    ``ConfigDict(extra="forbid")`` mass-assignment defense, a ``default()``
    classmethod). Fields are NAMED per class (D-14 discretion — not opaque
    tuples) so the P9 (RTCFG) runtime-config allowlist can target individual
    keys; this is the runtime-tunable seam P9 mutates — STATIC here (no
    ``ConfigUpdateEvent`` wiring lands in P8).

    Defaults are the exact ROADMAP / D-14 values:

      - ``SETTLEMENT``     threshold 1  (halt-on-first — at threshold 1 the
                           window is irrelevant; a nominal window is carried)
      - ``ORDER_IO``       3 / 60s
      - ``ADMISSION``      3 / 300s
      - ``LOOP_BACKSTOP``  5 / 60s

    ``FailureClass.FILL_TRANSLATION`` reuses the ``SETTLEMENT`` threshold/window
    (D-14 — a lost venue fill is a settlement loss, halt-on-first), so it has no
    dedicated field. Thresholds/windows stay ``int``/``float`` (non-money
    supervisor tunables, matching ``ThrottleSettings.window_s`` — NEVER Decimal,
    NEVER float money).
    """

    model_config = ConfigDict(extra="forbid")

    # SETTLEMENT — halt-on-first (threshold 1); FILL_TRANSLATION reuses this pair.
    settlement_threshold: int = 1
    settlement_window_s: float = 60.0
    # ORDER_IO — 3 order-route failures / 60s.
    order_io_threshold: int = 3
    order_io_window_s: float = 60.0
    # ADMISSION — 3 signal-admission failures / 300s.
    admission_threshold: int = 3
    admission_window_s: float = 300.0
    # LOOP_BACKSTOP — 5 unmapped/loop failures / 60s.
    loop_backstop_threshold: int = 5
    loop_backstop_window_s: float = 60.0

    @classmethod
    def default(cls) -> "FailureRateSettings":
        """The default failure-rate tripwire thresholds (D-14 ROADMAP values)."""
        return cls()


class SafetySettings(BaseModel):
    """Pre-trade safety domain container (D-13/D-14).

    The one-domain object the P9 runtime-config allowlist (D-14) will make settable —
    holds the throttle caps and the CF-1 failure-rate thresholds today; SHAPES the
    mutation seam without wiring any runtime ``ConfigUpdateEvent`` mutation (that is P9).
    ``extra`` is forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    throttle: ThrottleSettings = Field(default_factory=ThrottleSettings)
    failure_rate: FailureRateSettings = Field(default_factory=FailureRateSettings)

    @classmethod
    def default(cls) -> "SafetySettings":
        """The default safety settings (default throttle caps + failure-rate thresholds)."""
        return cls()
