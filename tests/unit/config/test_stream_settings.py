"""StreamSettings + FeedProviderSettings model tests (CFG-03 / D-08).

Pins the two config models that fold the scattered live-only module constants into a
single typed home (config/stream.py):

  1. DEFAULT EQUIVALENCE (Pitfall 4): each folded default equals its retired module
     constant EXACTLY — a value drift would silently change live-supervisor behaviour
     and the paper-parity window/symbol meaning.
  2. ``extra="forbid"``: an unknown key raises pydantic ``ValidationError``
     (mass-assignment defense, T-04-01).
  3. Both models are importable from the ``itrader.config`` barrel.

The reconnect fields are floats/ints (matching the current live read-site usage), NOT
Decimal — they are non-money supervisor tunables.
"""

import pytest

import pydantic
from itrader.config.stream import FeedProviderSettings, StreamSettings

pytestmark = pytest.mark.unit


def test_stream_settings_defaults_equal_retired_constants():
    """Each StreamSettings default equals its retired module constant byte-for-byte."""
    cfg = StreamSettings.default()
    assert cfg.reconnect_debounce_s == 0.25       # _STREAM_RECONNECT_DEBOUNCE_SECONDS
    assert cfg.reconnect_backoff_base_s == 1.0     # _STREAM_RECONNECT_BACKOFF_BASE_SECONDS
    assert cfg.reconnect_backoff_cap_s == 30.0     # _STREAM_RECONNECT_BACKOFF_CAP_SECONDS
    assert cfg.reconnect_retry_ceiling == 6        # _STREAM_RECONNECT_RETRY_CEILING
    assert cfg.okx_stream_symbol == "BTC/USDC"     # _OKX_STREAM_SYMBOL
    assert cfg.okx_stream_timeframe == "1d"        # _OKX_STREAM_TIMEFRAME


def test_stream_settings_reconnect_fields_are_float_and_int():
    """The reconnect tunables keep their live float/int types (not Decimal)."""
    cfg = StreamSettings()
    assert isinstance(cfg.reconnect_debounce_s, float)
    assert isinstance(cfg.reconnect_backoff_base_s, float)
    assert isinstance(cfg.reconnect_backoff_cap_s, float)
    assert isinstance(cfg.reconnect_retry_ceiling, int)


def test_feed_provider_settings_defaults_equal_retired_constants():
    """Each FeedProviderSettings default equals its retired module constant exactly."""
    cfg = FeedProviderSettings.default()
    assert cfg.warmup_margin == 5        # _WARMUP_MARGIN
    assert cfg.backfill_page == 1000     # _BACKFILL_PAGE


def test_stream_settings_forbids_unknown_key():
    """extra='forbid' rejects an unknown key (mass-assignment defense, T-04-01)."""
    with pytest.raises(pydantic.ValidationError):
        StreamSettings.model_validate({"bogus": 1})


def test_feed_provider_settings_forbids_unknown_key():
    """extra='forbid' rejects an unknown key (mass-assignment defense, T-04-01)."""
    with pytest.raises(pydantic.ValidationError):
        FeedProviderSettings.model_validate({"bogus": 1})


def test_both_models_importable_from_config_barrel():
    """Both models re-export from the itrader.config barrel."""
    from itrader.config import FeedProviderSettings as FPS
    from itrader.config import StreamSettings as SS

    assert SS is StreamSettings
    assert FPS is FeedProviderSettings
