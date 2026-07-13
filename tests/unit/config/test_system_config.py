"""SystemConfig aggregation + import-safety tests (D-02/D-03/D-05/D-06/D-07/D-09).

Pins the cardinality-1 system-config aggregation and its eager-vs-lazy import-safety
split (CFG-01/CFG-02/CFG-04):

  1. runtime EAGER (D-07): ``runtime`` is a pydantic field whose default constructs a
     ``Settings`` instance (reads ``ITRADER_*`` env but builds NO ``SqlSettings``).
  2. sql LAZY register-vs-build (D-05/D-06): ``sql`` is a ``functools.cached_property``,
     NOT a pydantic field — the descriptor is REGISTERED on the class but nothing is
     BUILT until first access.
  3. UNBUILT at import (D-05): importing ``itrader`` runs ``SystemConfig.default()``
     (itrader/__init__.py); the ``cached_property`` stays unresolved, so ``"sql"`` is
     absent from the singleton's ``__dict__`` — zero ``SqlSettings`` at import.
  4. order EXCLUDED (D-03/D-04): ``order`` is reclassified cardinality-N and lives with
     ``OrderHandler`` — it must NOT be a ``SystemConfig`` field.
  5. extra=forbid (D-09): an unknown key raises pydantic ``ValidationError`` (the domain
     YAML is orphaned/dead; nothing feeds extras, so a stray key is a typo caught loudly).
"""

import inspect
from functools import cached_property

import pytest

import pydantic
from itrader.config.settings import Settings
from itrader.config.stream import FeedProviderSettings, StreamSettings
from itrader.config.system import SystemConfig

pytestmark = pytest.mark.unit


def test_runtime_is_eager_settings_field():
    """runtime is a pydantic field whose default constructs a Settings instance (D-07)."""
    assert "runtime" in SystemConfig.model_fields
    assert isinstance(SystemConfig().runtime, Settings)


def test_stream_is_eager_field_with_unchanged_defaults():
    """stream is an eager StreamSettings field carrying the D-08 defaults (IN-01)."""
    assert "stream" in SystemConfig.model_fields
    stream = SystemConfig.default().stream
    assert isinstance(stream, StreamSettings)
    assert stream.okx_stream_symbol == "BTC/USDC"
    assert stream.okx_stream_timeframe == "1d"


def test_feed_provider_is_eager_field_with_unchanged_defaults():
    """feed_provider is an eager FeedProviderSettings field carrying the D-08 defaults (IN-01)."""
    assert "feed_provider" in SystemConfig.model_fields
    feed_provider = SystemConfig.default().feed_provider
    assert isinstance(feed_provider, FeedProviderSettings)
    assert feed_provider.warmup_margin == 5
    assert feed_provider.backfill_page == 1000


def test_adding_eager_fields_keeps_sql_lazy_at_import():
    """Adding stream/feed_provider must NOT resolve the lazy sql cached_property (IN-01)."""
    from itrader import config as c

    assert "sql" not in c.__dict__


def test_sql_is_cached_property_not_a_field():
    """sql is a functools.cached_property REGISTERED on the class, not a pydantic field (D-05/D-06)."""
    assert isinstance(inspect.getattr_static(SystemConfig, "sql"), cached_property)
    assert "sql" not in SystemConfig.model_fields


def test_sql_is_unbuilt_at_import():
    """The imported config singleton has not resolved sql -> no SqlSettings built at import (D-05)."""
    from itrader import config as c

    assert "sql" not in c.__dict__


def test_order_is_not_a_system_config_field():
    """order is reclassified cardinality-N and must stay absent from SystemConfig (D-03/D-04)."""
    assert "order" not in SystemConfig.model_fields


def test_unknown_key_raises_validation_error():
    """extra='forbid' rejects an unknown key, catching config typos loudly (D-09)."""
    with pytest.raises(pydantic.ValidationError):
        SystemConfig.from_dict({"bogus_key": 1})
