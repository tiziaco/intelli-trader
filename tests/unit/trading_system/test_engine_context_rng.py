"""Unit contract for the REQUIRED ``EngineContext.rng`` determinism field.

Proves:

- **VENUE-06 / D-07** — ``rng`` is a REQUIRED field on ``EngineContext``: omitting it
  raises ``TypeError`` rather than silently defaulting. A default would mint a SECOND,
  unseeded ``random.Random`` on a wiring omission, and a second instance is not an
  error state — it is a silently non-reproducible run.
- **D-07 field placement** — ``rng`` is listed BEFORE the defaulted ``store`` /
  ``sql_engine``, mechanically enforcing the dataclass's own stated ordering invariant
  ("required before defaulted"). A reader-facing docstring rule is not a guard; the
  ``dataclasses.fields`` assertion is.
- **VENUE-06 rng identity** — the ctx carries the CALLER'S instance (``is``), not an
  equal-seeded copy. Two ``random.Random(42)`` objects look identical and diverge the
  moment either is drawn from, so equality of seed proves nothing.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is auto-applied
by folder. 4-space indentation (tests house style).
"""

import dataclasses
import random

import pytest

from itrader.trading_system.engine_context import EngineContext


def _ctx_kwargs() -> dict:
    """The REQUIRED fields other than ``rng``.

    ``EngineContext`` is a plain frozen dataclass with no validation, so opaque
    stand-ins are sufficient here and keep this a true unit test (no CSV store, no
    feed construction, no database).
    """
    return {
        "bus": object(),
        "config": object(),
        "environment": "backtest",
        "feed": object(),
    }


def test_rng_is_required_and_precedes_the_defaulted_fields() -> None:
    """``rng`` is required (D-07) and sits before the defaulted fields."""
    # Required: omitting it is a construction-time TypeError, never a silent default.
    with pytest.raises(TypeError):
        EngineContext(**_ctx_kwargs())

    names = [f.name for f in dataclasses.fields(EngineContext)]
    assert "rng" in names
    # The dataclass's own invariant: required fields precede defaulted ones. Appending
    # `rng` after `store` would raise "non-default argument follows default argument",
    # so this ordering is load-bearing, not cosmetic.
    assert names.index("rng") < names.index("store")
    assert names.index("rng") < names.index("sql_engine")


def test_engine_context_carries_the_caller_s_rng_instance() -> None:
    """The ctx holds the caller's object itself — asserted by identity, not equality."""
    shared = random.Random(42)
    ctx = EngineContext(rng=shared, **_ctx_kwargs())
    assert ctx.rng is shared
