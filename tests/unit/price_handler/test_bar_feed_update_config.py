"""Interface-conformance tests for ``BacktestBarFeed.update_config`` (D-10).

The feed has NO Pydantic config model (D-09 forbids inventing a ``FeedConfig``).
``update_config`` exists purely to satisfy COMP-02's uniform
``update_config(self, updates: dict[str, Any]) -> None`` signature and to fail
LOUDLY (Pitfall 3 — never a silent no-op) for changes that cannot be safely
hot-applied mid-run. ``base_timeframe`` is the named unsafe key: it ripples
into ``_base_alias`` and the window cutoff math — a "replace, not a hot-swap"
(the live replace path is N+4).

Covered behaviors:

- ``update_config({"base_timeframe": ...})`` raises ``ConfigurationError``
  (config_key = "base_timeframe");
- the uniform signature ``update_config(self, updates: dict[str, Any]) -> None``;
- the method never silently accepts an unsafe hot-swap — ANY updates dict
  raises (the backtest feed cannot hot-swap mid-run, D-10).
"""

from datetime import timedelta

import pytest

from itrader.core.exceptions import ConfigurationError
from itrader.price_handler.feed import BacktestBarFeed

pytestmark = pytest.mark.unit


class _StubStore:
    """A minimal PriceStore stand-in.

    ``symbols()`` returns an empty list so the construction-time precompute
    loop (``store.read_bars`` per symbol) is a no-op — ``update_config`` raises
    before touching any frame, so no real data is needed to exercise it.
    """

    def symbols(self) -> list[str]:
        return []


def _make_feed() -> BacktestBarFeed:
    return BacktestBarFeed(_StubStore(), timedelta(days=1))


def test_update_config_raises_on_base_timeframe():
    """An unsafe base_timeframe hot-swap raises ConfigurationError."""
    feed = _make_feed()

    with pytest.raises(ConfigurationError) as exc:
        feed.update_config({"base_timeframe": "1h"})

    assert exc.value.config_key == "base_timeframe"


def test_update_config_never_silently_accepts():
    """ANY updates dict raises — the backtest feed cannot hot-swap (D-10)."""
    feed = _make_feed()

    with pytest.raises(ConfigurationError):
        feed.update_config({"anything": 1})


def test_update_config_returns_none_signature():
    """The uniform signature is dict -> None (raises, so never returns)."""
    feed = _make_feed()

    with pytest.raises(ConfigurationError):
        result = feed.update_config({"base_timeframe": "1h"})
        assert result is None
