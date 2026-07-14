"""ThrottleSettings + SafetySettings model tests (D-07/D-13/D-14).

Pins the pre-trade safety config home (config/safety.py):

  1. STATIC CAPS ON BY DEFAULT (D-07): 10 orders / 10s + $25k notional, plus the D-09
     dedup interval.
  2. ``max_notional_per_order`` is Decimal (money end-to-end), rate fields int/float.
  3. ``extra="forbid"`` on both models: an unknown key raises pydantic ValidationError
     (mass-assignment defense, T-04-01).
  4. ``SystemConfig.default().safety.throttle`` is reachable (eager inertness-safe field).
  5. Both models are importable from the ``itrader.config`` barrel.
"""

from decimal import Decimal

import pydantic
import pytest

from itrader.config import SafetySettings, ThrottleSettings
from itrader.config.system import SystemConfig

pytestmark = pytest.mark.unit


def test_throttle_defaults_are_conservative_and_on():
    """D-07: the static caps are ON by default at 10/10s + $25k + 5s dedup."""
    t = ThrottleSettings.default()
    assert t.max_orders == 10
    assert t.window_s == 10.0
    assert t.max_notional_per_order == Decimal("25000")
    assert t.warn_min_interval_s == 5.0


def test_max_notional_is_decimal():
    """max_notional_per_order is Decimal (money end-to-end); rate fields int/float."""
    t = ThrottleSettings()
    assert isinstance(t.max_notional_per_order, Decimal)
    assert isinstance(t.max_orders, int)
    assert isinstance(t.window_s, float)
    assert isinstance(t.warn_min_interval_s, float)


def test_throttle_extra_forbid():
    """extra=forbid: an unknown key raises pydantic ValidationError (T-04-01)."""
    with pytest.raises(pydantic.ValidationError):
        ThrottleSettings(extra_key=1)


def test_safety_settings_holds_throttle_and_forbids_extra():
    """SafetySettings is the one-domain container (holds throttle) and forbids extras."""
    s = SafetySettings.default()
    assert isinstance(s.throttle, ThrottleSettings)
    assert s.throttle.max_orders == 10
    with pytest.raises(pydantic.ValidationError):
        SafetySettings(extra_key=1)


def test_system_config_safety_field_reachable():
    """SystemConfig.default().safety.throttle is an eager, reachable field."""
    cfg = SystemConfig.default()
    assert cfg.safety.throttle.max_orders == 10
    assert cfg.safety.throttle.max_notional_per_order == Decimal("25000")
