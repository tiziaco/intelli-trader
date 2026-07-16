"""ITraderConfig frozen-base + mutable-sub-model behavior tests (RTCFG-01/04, D-04..D-13).

Pins the load-bearing runtime-config foundation: the new ``frozen=True``
``ITraderConfig`` root whose immutable determinism/identity base params reject runtime
``setattr`` while its domain sub-models mutate in place under ``validate_assignment``.

  1. Frozen base blocks (RTCFG-04, D-04/D-07): ``setattr`` on ``rng_seed``/``environment``
     raises ``pydantic.ValidationError`` — immutable-at-runtime by field placement.
  2. Sub-model mutate (RTCFG-01, D-07/D-12): ``config.<sub>.<field> = X`` succeeds and is
     visible on re-read — the runtime-config mutation surface.
  3. validate_assignment (D-13): a coercible str coerces on assign; a wrong-type /
     out-of-range value raises ``ValidationError`` (``Field(...)`` constraints re-run).
  4. Top-level sub-model reassignment blocked (Pitfall 5): ``config.stream = X`` raises —
     the frozen guard blocks a whole-sub-model reference swap (field-level mutation only).
  5. Unhashable gotcha (Pitfall 4): ``hash(config)`` raises ``TypeError`` — ``config`` can
     never be a dict/set key or a cache key (frozen base hashes unhashable sub-models).

Every test builds a fresh ``ITraderConfig()`` — the process singleton is never mutated.
"""

import pytest

import pydantic

from itrader.config.itrader_config import ITraderConfig
from itrader.config.stream import StreamSettings
from itrader.config.system import Environment

pytestmark = pytest.mark.unit


def test_rng_seed_defaults_to_42_on_frozen_base():
    """rng_seed reads 42 off the frozen base (moved off config.performance.rng_seed)."""
    assert ITraderConfig().rng_seed == 42


def test_frozen_base_rejects_rng_seed_setattr():
    """setattr on the frozen base rng_seed raises ValidationError (RTCFG-04)."""
    config = ITraderConfig()
    with pytest.raises(pydantic.ValidationError):
        config.rng_seed = 1
    assert config.rng_seed == 42


def test_frozen_base_rejects_environment_setattr():
    """setattr on the frozen base environment raises ValidationError (RTCFG-04)."""
    config = ITraderConfig()
    with pytest.raises(pydantic.ValidationError):
        config.environment = Environment.PRODUCTION
    assert config.environment == Environment.DEVELOPMENT


def test_frozen_base_rejection_is_thread_agnostic():
    """A base-param setattr raises regardless of which thread performs it (RTCFG-04 edge).

    The frozen guard is a structural pydantic property of the model, not a thread-local
    latch — a worker thread hits the same ``ValidationError`` as the main thread.
    """
    import threading

    config = ITraderConfig()
    outcome: dict[str, object] = {}

    def _mutate() -> None:
        try:
            config.rng_seed = 99
            outcome["raised"] = False
        except pydantic.ValidationError:
            outcome["raised"] = True

    worker = threading.Thread(target=_mutate)
    worker.start()
    worker.join()
    assert outcome["raised"] is True
    assert config.rng_seed == 42


def test_sub_model_field_mutates_in_place():
    """config.<sub>.<field> = X mutates in place and is visible on re-read (RTCFG-01)."""
    config = ITraderConfig()
    config.stream.reconnect_retry_ceiling = 9
    assert config.stream.reconnect_retry_ceiling == 9
    config.universe.remove_policy = "force-close"
    assert config.universe.remove_policy == "force-close"


def test_validate_assignment_coerces_str_to_int():
    """A coercible str assigned to an int sub-model field coerces (validate_assignment, D-13)."""
    config = ITraderConfig()
    config.stream.reconnect_retry_ceiling = "12"
    assert config.stream.reconnect_retry_ceiling == 12
    assert isinstance(config.stream.reconnect_retry_ceiling, int)


def test_validate_assignment_enforces_field_constraint():
    """An out-of-range value raises ValidationError on assign (Field(gt=0) re-runs, D-13)."""
    config = ITraderConfig()
    with pytest.raises(pydantic.ValidationError):
        config.universe.poll_cadence_s = -1.0
    assert config.universe.poll_cadence_s == 60.0


def test_validate_assignment_rejects_unknown_sub_model_key():
    """extra='forbid' rejects an unknown key on a sub-model setattr (mass-assignment, D-11)."""
    config = ITraderConfig()
    with pytest.raises(pydantic.ValidationError):
        config.stream.bogus_field = 1


def test_top_level_sub_model_reassignment_blocked():
    """config.stream = StreamSettings() raises — frozen blocks a sub-model swap (Pitfall 5)."""
    config = ITraderConfig()
    with pytest.raises(pydantic.ValidationError):
        config.stream = StreamSettings()


def test_unknown_base_key_rejected_at_construction():
    """extra='forbid' on the frozen root rejects an unknown construction key (D-06/D-11)."""
    with pytest.raises(pydantic.ValidationError):
        ITraderConfig(bogus_key=1)


def test_config_is_unhashable():
    """hash(config) raises TypeError — config is never a dict/set/cache key (Pitfall 4)."""
    config = ITraderConfig()
    with pytest.raises(TypeError):
        hash(config)
