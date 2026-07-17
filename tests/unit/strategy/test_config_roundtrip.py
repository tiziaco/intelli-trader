"""The D-04/D-20 ``config_json`` round-trip contract (D-01/D-05/D-16).

``decode_strategy_config(encode_strategy_config(s))`` must reconstruct an instance equal
to ``s`` **on the declared surface** — for every shipped strategy, through the three
aliasing traps, with the derived fields excluded.

Why the declared surface is the contract (D-04): ``_declared_hints(cls)`` is
``get_type_hints(cls)`` (``base.py:131-133``), which returns the class-body annotations
across the MRO. That set IS the authoring surface — precisely the names ``_apply_params``
accepts as kwargs. Runtime state (``is_active`` / ``subscribed_portfolios`` /
``strategy_id``) is assigned in ``__init__`` with FUNCTION-LOCAL annotations that never
enter ``cls.__annotations__``, so ``_declared_hints`` is structurally blind to it and
D-04's runtime-exclusion requirement holds for free.

The three traps (RESEARCH Item 3), each pinned by a test below:

1. ``timeframe`` is destructively resolved — ``_apply_params`` overwrites ``self.timeframe``
   with a ``timedelta`` (``base.py:318-320``), so ``getattr(s, "timeframe")`` is NOT a valid
   ``timeframe=`` kwarg. The codec serializes ``timeframe_alias``.
2. ``name`` is the authoring kwarg; ``strategy_name`` is the store PK (D-02) — the same
   value under two spellings. The blob carries no ``name``.
3. ``direction`` serializes as ``.value`` and re-coerces through ``_COERCE``.
"""

import json
from decimal import Decimal

import pytest

from itrader.core.policy_codec import default_policy_registry
from itrader.core.sizing import FractionOfCash, PercentFromFill
from itrader.strategy_handler.base import _declared_hints
from itrader.strategy_handler.registry import (
    CONFIG_VERSION,
    UnknownStrategyTypeError,
    decode_strategy_config,
    encode_strategy_config,
    resolve_strategy_class,
)
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import EthBtcPairStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from tests.support.strategy_catalog import build_shipped_strategies, test_catalog

# The runtime fields D-04 excludes. Asserted absent from every blob (Test 2). They are
# excluded structurally (function-local annotations), not by a hand-maintained list.
_RUNTIME_FIELDS = ("is_active", "subscribed_portfolios", "strategy_id")


@pytest.fixture
def catalog():
    return test_catalog()


@pytest.fixture
def policy_registry():
    return default_policy_registry()


def _roundtrip(strategy, catalog, policy_registry):
    """encode -> row -> decode -> construct. The full symmetric cycle (D-05)."""
    blob = encode_strategy_config(strategy)
    rec = {
        "strategy_name": strategy.name,
        "strategy_type": type(strategy).__name__,
        "config_json": blob,
    }
    cls, params = decode_strategy_config(rec, catalog, policy_registry)
    return blob, cls(**params)


def _shipped_ids():
    return [type(s).__name__ for s in build_shipped_strategies()]


@pytest.fixture(params=build_shipped_strategies(), ids=_shipped_ids())
def shipped(request):
    # Rebuild per test: the params list is evaluated once at collection, and a strategy
    # instance carries mutable state (tickers list, indicator handles).
    return type(request.param)(**_ctor_kwargs(request.param))


def _ctor_kwargs(strategy):
    """The required kwargs for a shipped strategy, recovered from the instance."""
    kwargs = {"timeframe": strategy.timeframe_alias}
    if isinstance(strategy, EmptyStrategy):
        kwargs["tickers"] = list(strategy.tickers)
        kwargs["sizing_policy"] = strategy.sizing_policy
    elif isinstance(strategy, SMAMACDStrategy):
        kwargs["tickers"] = list(strategy.tickers)
    return kwargs


# --------------------------------------------------------------------------- Test 1
def test_declared_surface_roundtrips_losslessly(shipped, catalog, policy_registry):
    """D-05: encode -> decode -> construct is lossless on the FULL declared surface.

    This is the load-bearing symmetry test. Every name ``_declared_hints`` reports is an
    authoring param, so every one of them must survive the cycle.
    """
    _blob, rebuilt = _roundtrip(shipped, catalog, policy_registry)

    assert type(rebuilt) is type(shipped)
    for name in _declared_hints(type(shipped)):
        assert getattr(rebuilt, name) == getattr(shipped, name), (
            f"declared param {name!r} did not survive the round-trip: "
            f"{getattr(shipped, name)!r} -> {getattr(rebuilt, name)!r}"
        )


# --------------------------------------------------------------------------- Test 2
def test_blob_stamps_type_and_version_and_excludes_derived_and_runtime(shipped):
    """D-04/D-20: the blob carries the type + version and excludes derived/runtime state."""
    blob = encode_strategy_config(shipped)

    assert blob["strategy_type"] == type(shipped).__name__
    assert blob["config_version"] == CONFIG_VERSION == 1
    assert isinstance(blob["config_version"], int)

    # D-04 / F-2: the derived fields are excluded (see Test 6 for why it is correctness).
    assert "warmup" not in blob
    assert "max_window" not in blob
    # Trap 2: name lives in the row PK, never the blob.
    assert "name" not in blob
    # D-04: runtime state never enters the blob.
    for field in _RUNTIME_FIELDS:
        assert field not in blob


# --------------------------------------------------------------------------- Test 3
def test_trap1_timeframe_serializes_as_alias_string(shipped, catalog, policy_registry):
    """Trap 1: the blob holds the ALIAS str, never the resolved timedelta or the enum."""
    blob, rebuilt = _roundtrip(shipped, catalog, policy_registry)

    assert blob["timeframe"] == shipped.timeframe_alias
    assert isinstance(blob["timeframe"], str)

    # The resolved runtime value is a timedelta — proving the blob did NOT store it.
    from datetime import timedelta

    assert isinstance(shipped.timeframe, timedelta)
    assert not isinstance(blob["timeframe"], timedelta)

    assert rebuilt.timeframe_alias == shipped.timeframe_alias
    assert rebuilt.timeframe == shipped.timeframe
    assert isinstance(rebuilt.timeframe, timedelta)


# --------------------------------------------------------------------------- Test 4
def test_trap2_name_comes_from_the_row_pk_not_the_blob(shipped, catalog, policy_registry):
    """Trap 2 (D-02): a row whose PK and blob disagree is UNREPRESENTABLE.

    Not merely "we prefer the PK" — the blob carries no name to disagree with, so the
    disagreement has no way to be expressed.
    """
    blob = encode_strategy_config(shipped)
    assert "name" not in blob

    rec = {
        "strategy_name": "renamed_by_the_row",
        "strategy_type": type(shipped).__name__,
        "config_json": blob,
    }
    cls, params = decode_strategy_config(rec, catalog, policy_registry)

    assert params["name"] == "renamed_by_the_row"
    assert cls(**params).name == rec["strategy_name"]


# --------------------------------------------------------------------------- Test 5
def test_trap3_direction_serializes_as_enum_value(shipped, catalog, policy_registry):
    """Trap 3: direction crosses as ``.value`` and re-coerces via ``_COERCE``."""
    from itrader.core.sizing import TradingDirection

    blob, rebuilt = _roundtrip(shipped, catalog, policy_registry)

    assert blob["direction"] == shipped.direction.value
    assert isinstance(blob["direction"], str)
    assert not isinstance(blob["direction"], TradingDirection)

    assert isinstance(rebuilt.direction, TradingDirection)
    assert rebuilt.direction is shipped.direction


# --------------------------------------------------------------------------- Test 6
@pytest.mark.parametrize(
    "factory, expected_max_window",
    [
        # class max_window unset (base default 0), handle-derived 100 -> max(100, 0)
        (lambda: SMAMACDStrategy(timeframe="1d", tickers=["BTCUSD"]), 100),
        # class max_window = 1, handle-derived 0 -> max(0, 1). The exclusion-correctness
        # case: storing the derived 0 would SHRINK it below author intent.
        (
            lambda: EmptyStrategy(
                timeframe="1h",
                tickers=["BTCUSD"],
                sizing_policy=FractionOfCash(Decimal("0.5")),
            ),
            1,
        ),
        # class max_window = 280 (hand-set: beta_warmup 250 + z_lookback 30)
        (lambda: EthBtcPairStrategy(timeframe="1d"), 280),
    ],
    ids=["SMAMACDStrategy", "EmptyStrategy", "EthBtcPairStrategy"],
)
def test_f2_derived_max_window_is_reproduced_and_never_ratchets(
    factory, expected_max_window, catalog, policy_registry
):
    """F-2: excluding ``max_window`` reproduces author intent AND prevents the ratchet.

    ``_run_init`` re-derives ``max_window = max(handle-derived, hand-set class value)`` on
    every construction, so the exclusion is lossless. Storing it instead would replay a
    DERIVED value as an AUTHORED one — ratcheting it monotonically upward across
    reconfigures with no way to shrink, silently defeating D-14's window-shrank-stays-warm
    case. Three successive round-trips assert no growth.
    """
    strategy = factory()
    assert strategy.max_window == expected_max_window

    for cycle in range(3):
        _blob, strategy = _roundtrip(strategy, catalog, policy_registry)
        assert strategy.max_window == expected_max_window, (
            f"max_window ratcheted on cycle {cycle}: "
            f"{strategy.max_window} != {expected_max_window}"
        )
        # warmup is unconditionally re-derived by _run_init — it must also be stable.
        assert "warmup" not in _blob


# --------------------------------------------------------------------------- Test 7
def test_d16_pair_roundtrips_with_no_special_case(catalog, policy_registry):
    """D-16: a pair encodes/decodes like any other instance — no special case.

    The pair's declared extras are annotated on ``PairStrategy`` and therefore merge into
    ``_declared_hints(EthBtcPairStrategy)`` across the MRO. They ARE authoring params (each
    is a settable kwarg), so they ride the same declared-hints path as any base param and
    MUST round-trip. A NON-DEFAULT value is used deliberately: a codec that silently
    dropped these would still pass a defaults-only test while losing author intent.
    """
    strategy = EthBtcPairStrategy(
        timeframe="1d",
        entry_z=Decimal("3"),
        exit_z=Decimal("0.25"),
        z_lookback=30,
        beta_warmup=250,
        entry_units=Decimal("2"),
    )
    blob, rebuilt = _roundtrip(strategy, catalog, policy_registry)

    # The pair's declared extras are present in the blob and survive the cycle.
    for name in ("entry_z", "exit_z", "leverage", "z_lookback", "beta_warmup",
                 "entry_units", "use_log_prices"):
        assert name in blob, f"declared pair param {name!r} missing from the blob"

    assert rebuilt.entry_z == Decimal("3")
    assert rebuilt.exit_z == Decimal("0.25")
    assert rebuilt.entry_units == Decimal("2")
    # Decimals must come back as Decimals, not the strings they crossed JSON as.
    assert isinstance(rebuilt.entry_z, Decimal)
    assert isinstance(rebuilt.entry_units, Decimal)


# --------------------------------------------------------------------------- Test 8
def test_blob_is_json_dumpable_with_no_default_hook(shipped, catalog, policy_registry):
    """The blob is JSON-native: ``json.dumps`` needs no ``default=`` hook.

    Every Decimal already crossed as a string (the money boundary — via the Plan 01 policy
    codec for policy fields, and the declared-Decimal arm for knobs like ``entry_z``).
    """
    blob = encode_strategy_config(shipped)

    dumped = json.dumps(blob)  # no default= — a raw Decimal/timedelta would raise here
    cycled = json.loads(dumped)

    rec = {
        "strategy_name": shipped.name,
        "strategy_type": type(shipped).__name__,
        "config_json": cycled,
    }
    cls, params = decode_strategy_config(rec, catalog, policy_registry)
    rebuilt = cls(**params)

    for name in _declared_hints(type(shipped)):
        assert getattr(rebuilt, name) == getattr(shipped, name)


# --------------------------------------------------------------------------- Test 9
def test_none_sltp_policy_encodes_as_null_and_decodes_back_to_none(
    catalog, policy_registry
):
    """An optional policy is never silently DROPPED from the blob — it is JSON null."""
    strategy = EmptyStrategy(
        timeframe="1h",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.5")),
        sltp_policy=None,
    )
    blob, rebuilt = _roundtrip(strategy, catalog, policy_registry)

    assert "sltp_policy" in blob, "an optional policy must be present as null, not dropped"
    assert blob["sltp_policy"] is None
    assert json.loads(json.dumps(blob))["sltp_policy"] is None
    assert rebuilt.sltp_policy is None


def test_present_sltp_policy_roundtrips_through_the_d03_codec(catalog, policy_registry):
    """A present policy delegates to the Plan 01 tagged-union codec (D-03), not repr()."""
    policy = PercentFromFill(sl_pct=Decimal("0.02"), tp_pct=Decimal("0.05"))
    strategy = EmptyStrategy(
        timeframe="1h",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.5")),
        sltp_policy=policy,
    )
    blob, rebuilt = _roundtrip(strategy, catalog, policy_registry)

    # The tagged form — NOT the one-way repr() to_dict() emits.
    assert blob["sltp_policy"]["kind"] == "PercentFromFill"
    assert blob["sltp_policy"]["sl_pct"] == "0.02"
    assert rebuilt.sltp_policy == policy


# --------------------------------------------------------------------------- Test 10
def test_unknown_strategy_type_is_a_loud_reject(catalog):
    """D-01: an unknown type is a LOUD reject naming the type and the known keys."""
    with pytest.raises(UnknownStrategyTypeError) as exc:
        resolve_strategy_class(catalog, "NoSuchStrategy")

    message = str(exc.value)
    assert "NoSuchStrategy" in message
    for known in catalog:
        assert known in message, f"the reject must list the known key {known!r}"


def test_decode_rejects_an_unknown_strategy_type(catalog, policy_registry):
    """The catalog IS the access control — decode cannot instantiate an off-list type."""
    rec = {
        "strategy_name": "x",
        "strategy_type": "NoSuchStrategy",
        "config_json": {"strategy_type": "NoSuchStrategy", "config_version": 1},
    }
    with pytest.raises(UnknownStrategyTypeError):
        decode_strategy_config(rec, catalog, policy_registry)


# --------------------------------------------------------------------------- Test 11
def test_unknown_param_in_blob_is_rejected_by_the_constructor(catalog, policy_registry):
    """T-10-20: the codec routes rejection THROUGH the constructor; it never re-implements it.

    ``_apply_params`` already loud-rejects unknown params. The codec returning
    ``(cls, params)`` means that validator owns the rejection — a duplicate check inside the
    codec would drift from it.
    """
    from itrader.core.exceptions.strategy import UnknownParamError

    strategy = SMAMACDStrategy(timeframe="1d", tickers=["BTCUSD"])
    blob = encode_strategy_config(strategy)
    blob["smuggled_param"] = "malicious"

    rec = {
        "strategy_name": strategy.name,
        "strategy_type": type(strategy).__name__,
        "config_json": blob,
    }
    cls, params = decode_strategy_config(rec, catalog, policy_registry)

    assert "smuggled_param" in params, "the codec must not silently drop the unknown key"
    with pytest.raises(UnknownParamError):
        cls(**params)


# --------------------------------------------------------------------------- Test 12
def test_encode_is_stable_across_repeated_calls(shipped):
    """Backstop: repeated encodes of an unchanged instance produce EQUAL blobs.

    No set/dict iteration order leaks into the blob, so an unchanged strategy never
    produces a spurious row update.
    """
    first = encode_strategy_config(shipped)
    second = encode_strategy_config(shipped)

    assert first == second
    assert list(first) == list(second), "key ORDER must be stable, not just the key set"
    assert json.dumps(first) == json.dumps(second)


# ------------------------------------------------------- D-20 version enforcement
def test_missing_config_version_is_rejected(shipped, catalog, policy_registry):
    """D-20: P10 does not migrate — it REPORTS. A version cannot be added retroactively."""
    from itrader.strategy_handler.registry import StrategyConfigError

    blob = encode_strategy_config(shipped)
    del blob["config_version"]
    rec = {
        "strategy_name": shipped.name,
        "strategy_type": type(shipped).__name__,
        "config_json": blob,
    }
    with pytest.raises(StrategyConfigError):
        decode_strategy_config(rec, catalog, policy_registry)


def test_newer_config_version_is_rejected_naming_both_versions(
    shipped, catalog, policy_registry
):
    from itrader.strategy_handler.registry import StrategyConfigError

    blob = encode_strategy_config(shipped)
    blob["config_version"] = CONFIG_VERSION + 1
    rec = {
        "strategy_name": shipped.name,
        "strategy_type": type(shipped).__name__,
        "config_json": blob,
    }
    with pytest.raises(StrategyConfigError) as exc:
        decode_strategy_config(rec, catalog, policy_registry)

    message = str(exc.value)
    assert str(CONFIG_VERSION + 1) in message
    assert str(CONFIG_VERSION) in message
