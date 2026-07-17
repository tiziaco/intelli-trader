"""The D-04/D-20 authoring-param codec: instance <-> ``config_json`` <-> instance.

**D-04 — what a blob is.** ``config_json`` is the FLAT AUTHORING param set: ``strategy_type``,
``config_version``, and every constructor-settable declared param — everything ``cls(**config)``
needs and nothing else. The authoring surface is exactly ``_declared_hints(cls)``
(``get_type_hints`` across the MRO, ``base.py:131-133``), which is precisely the set
``_apply_params`` accepts as kwargs. Runtime state (``is_active`` -> the ``enabled`` column,
``subscribed_portfolios`` -> the child table, ``strategy_id`` -> regenerated per construction)
is assigned in ``__init__`` with FUNCTION-LOCAL annotations that never enter
``cls.__annotations__``, so ``_declared_hints`` is structurally blind to it — D-04's
runtime-exclusion requirement is satisfied for free and needs no exclusion list.

**D-05 — this is the reconstruction-safe counterpart to ``Strategy.to_dict()``, not a
replacement.** ``to_dict()`` is a ONE-WAY observability snapshot: it renders policies through
``repr()`` (``"FractionOfCash(Decimal('0.95'))"``), a form no safe decoder can reconstruct —
which is the whole reason the Plan 01 policy codec exists. ``to_dict()`` STAYS; this is
additive. The two deliberately agree on the aliasing (both skip ``timeframe``/``name`` and
emit ``timeframe_alias``) and diverge only at the policy arm.

**D-16 — pairs need no special case.** The codec dispatches on the resolved declared TYPE, so
a ``PairStrategy`` round-trips its base params plus its own declared extras through the same
path as any other instance. Note that ``entry_z`` / ``exit_z`` / ``leverage`` /
``use_log_prices`` are annotated on ``PairStrategy`` and therefore MERGE into
``_declared_hints(EthBtcPairStrategy)`` across the MRO: they are settable authoring kwargs and
must round-trip like any other param. They are not "unannotated class constants".

**Why decode routes through the constructor.** ``decode_strategy_config`` returns
``(cls, params)`` and the CALLER constructs. ``_apply_params`` already loud-rejects unknown and
missing-required params and already coerces the two ``_COERCE`` enum fields; routing through it
gets that validation for free and makes drift impossible. Re-implementing those checks here is
exactly how the two would drift apart, so this module does neither.
"""

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin

from itrader.core.money import to_money
from itrader.core.policy_codec import PolicyRegistry, decode_policy, encode_policy
from itrader.core.sizing import SizingPolicy, SLTPPolicy
from itrader.strategy_handler.base import _COERCE, Strategy, _declared_hints
from itrader.strategy_handler.registry.catalog import StrategyCatalog, resolve_strategy_class

__all__ = [
	"CONFIG_VERSION",
	"StrategyConfigError",
	"decode_strategy_config",
	"encode_strategy_config",
]

# D-20: the blob's shape version, stamped into EVERY blob and living INSIDE the blob — not
# in a column. It describes the blob's shape, and D-06 reserves columns for runtime state
# (``enabled``) that must be queryable without a JSON scan. An int because integers compare
# trivially and a future migration hangs off a ``<`` comparison.
#
# P10 builds NO migration mechanism — the version exists so that when class-vs-row drift
# bites, it tells you WHAT you are looking at. It is stamped NOW because a version cannot be
# added retroactively to rows already on disk: a blob written without one is indistinguishable
# from a v1 blob forever after, so the stamp has to precede the first durable write or the
# capability is permanently lost.
CONFIG_VERSION: int = 1

# D-04: the derived-field exclusion set.
#
# EXHAUSTIVENESS: ``_run_init`` (``base.py:382-406``) is the ONLY post-``_apply_params``
# mutator of declared fields, and it touches exactly these two — so this set is complete by
# construction, not by inspection.
#
# - ``warmup`` is UNCONDITIONALLY overwritten from the registered indicators' ``min_period``
#   (the WR-03 footgun fix, D-08), so storing it is pointless: the stored value could never
#   be read back.
# - ``max_window`` is ``max(handle-derived, hand-set class value)``, so excluding it
#   reproduces author intent EXACTLY for all three shipped strategies (SMA_MACD: max(100, 0)
#   = 100; Empty: max(0, 1) = 1; EthBtcPair: max(0, 280) = 280).
#
# Excluding ``max_window`` is a CORRECTNESS requirement, not merely tidier (F-2). Storing it
# would replay a DERIVED value as an AUTHORED one, and ``_apply_params``' reconfigure fallback
# (``base.py:252-255``) reads the prior instance value — which after ``_run_init`` is the
# post-``max()`` derived value. It would therefore ratchet monotonically upward across
# reconfigures and could never shrink, silently defeating D-14's window-shrank-stays-warm case.
_DERIVED_FIELDS: frozenset[str] = frozenset({"warmup", "max_window"})

# Trap 2 (D-02): ``name`` is the authoring kwarg; ``strategy_name`` is the store PK — the same
# value under two spellings. Storing it in the blob would permit a row whose PK and blob
# disagree; omitting it makes that disagreement UNREPRESENTABLE. ``decode`` sources the name
# from ``rec["strategy_name"]``.
_SKIPPED_FIELDS: frozenset[str] = _DERIVED_FIELDS | {"name"}

# Trap 1: ``_apply_params`` OVERWRITES ``self.timeframe`` with a ``timedelta``
# (``base.py:318-320``), stashing the enum on ``self._timeframe`` and the string on
# ``self.timeframe_alias``. So ``getattr(strategy, "timeframe")`` is NOT a valid ``timeframe=``
# kwarg. The codec emits ``timeframe_alias`` under the key ``timeframe`` — exactly what
# ``to_dict`` already does at ``base.py:766-772``, and for exactly the same reason.
_TIMEFRAME_FIELD = "timeframe"

_TYPE_KEY = "strategy_type"
_VERSION_KEY = "config_version"

# The blob's two envelope keys are not declared params — they must never reach ``cls(**params)``.
_ENVELOPE_KEYS: frozenset[str] = frozenset({_TYPE_KEY, _VERSION_KEY})

# The policy classes, derived from both union aliases (never hand-listed — the Plan 01
# rationale: hand-listing is how ``PercentFromDecision`` got omitted once).
_POLICY_ARMS: frozenset[Any] = frozenset(get_args(SizingPolicy)) | frozenset(get_args(SLTPPolicy))

# Declared types that cross JSON unchanged.
_PASSTHROUGH: tuple[type, ...] = (bool, int, str)


class StrategyConfigError(ValueError):
	"""A ``config_json`` blob could not be encoded or decoded (D-04 fail-loud)."""


def _unwrap_optional(declared: Any) -> tuple[Any, bool]:
	"""Split ``X | None`` into ``(X, True)``; a non-union declared type is ``(X, False)``.

	Only a single non-None arm is supported — a genuine multi-arm union has no unambiguous
	coercion and is refused rather than guessed at. (Policy unions are multi-arm and are
	dispatched BEFORE this, by ``_policy_annotation``.)
	"""
	origin = get_origin(declared)
	if origin is not UnionType and origin is not Union:
		return declared, False

	arms = get_args(declared)
	non_none = [arm for arm in arms if arm is not NoneType]
	if len(non_none) != 1:
		raise StrategyConfigError(
			f"unsupported union type {declared!r}: expected exactly one non-None arm, "
			f"got {len(non_none)}"
		)
	return non_none[0], len(non_none) != len(arms)


def _policy_annotation(declared: Any) -> tuple[bool, bool]:
	"""Classify ``declared`` as a policy annotation -> ``(is_policy, optional)``.

	``sizing_policy: SizingPolicy`` is a 4-arm union and ``sltp_policy: SLTPPolicy | None`` is a
	2-arm union plus None, so neither survives ``_unwrap_optional``. Recognise them by union
	membership against the DERIVED ``_POLICY_ARMS`` rather than by field name: a subclass
	declaring a second policy-typed knob then rides the same path with no change here.
	"""
	arms = get_args(declared)
	if not arms:
		return False, False
	non_none = [arm for arm in arms if arm is not NoneType]
	if not non_none or not all(arm in _POLICY_ARMS for arm in non_none):
		return False, False
	return True, len(non_none) != len(arms)


def _encode_value(owner: str, field: str, declared: Any, value: Any) -> Any:
	"""Coerce one declared param OUT, dispatching on its resolved declared type."""
	is_policy, policy_optional = _policy_annotation(declared)
	if is_policy:
		if value is None:
			if not policy_optional:
				raise StrategyConfigError(f"{owner}.{field} is not optional but holds None")
			# An optional policy is JSON null — never DROPPED from the blob. A dropped key
			# would be indistinguishable from "author never declared it" on the way back.
			return None
		return encode_policy(value)

	inner, optional = _unwrap_optional(declared)
	if value is None:
		if not optional:
			raise StrategyConfigError(f"{owner}.{field} is not optional but holds None")
		return None

	if inner is Decimal:
		# The money boundary (D-04/money.py): a Decimal crosses JSON as a STRING. JSON has no
		# Decimal token, so a raw Decimal would make json.dumps raise and a float would
		# silently corrupt the value.
		if not isinstance(value, Decimal):
			raise StrategyConfigError(
				f"{owner}.{field} is declared Decimal but holds "
				f"{type(value).__name__}: {value!r}"
			)
		if not value.is_finite():
			raise StrategyConfigError(
				f"{owner}.{field} is not finite ({value!r}): a NaN/Infinity Decimal has no "
				f"safe JSON round-trip"
			)
		return str(value)

	if isinstance(inner, type) and issubclass(inner, Enum):
		return value.value

	if get_origin(inner) is list:
		# Emit a COPY, never the live list object — ``tickers`` is mutated in place by the
		# ticker verbs, so handing out the live list would let a later mutation retroactively
		# alter an already-encoded blob.
		return [_encode_scalar(owner, field, item) for item in value]

	if inner in _PASSTHROUGH:
		return value

	# Fail loud: a silent pass-through would put a non-JSON-native value in the blob and only
	# surface at the json.dumps boundary, far from the declaration site.
	raise StrategyConfigError(
		f"{owner}.{field}: unsupported declared type {inner!r} — the codec encodes Decimal, "
		f"Enum, bool, int, str, list, and the sizing/SLTP policies (optionally None-unioned)"
	)


def _encode_scalar(owner: str, field: str, item: Any) -> Any:
	"""Encode one element of a declared list (``tickers`` is ``list[str]``)."""
	if isinstance(item, Decimal):
		return str(item)
	if isinstance(item, Enum):
		return item.value
	if item is None or isinstance(item, _PASSTHROUGH):
		return item
	raise StrategyConfigError(
		f"{owner}.{field}: list element of unsupported type {type(item).__name__}: {item!r}"
	)


def _decode_value(
	owner: str, field: str, declared: Any, raw: Any, policy_registry: PolicyRegistry
) -> Any:
	"""Coerce one declared param IN, dispatching on its resolved declared type."""
	is_policy, policy_optional = _policy_annotation(declared)
	if is_policy:
		if raw is None:
			if not policy_optional:
				raise StrategyConfigError(
					f"{owner}.{field} is not optional but the blob holds null"
				)
			return None
		if not isinstance(raw, Mapping):
			raise StrategyConfigError(
				f"{owner}.{field}: expected a tagged policy blob, got "
				f"{type(raw).__name__}: {raw!r}"
			)
		return decode_policy(raw, policy_registry)

	inner, optional = _unwrap_optional(declared)
	if raw is None:
		if not optional:
			raise StrategyConfigError(f"{owner}.{field} is not optional but the blob holds null")
		return None

	if inner is Decimal:
		# Re-enter the Decimal domain via to_money (the Decimal(str(x)) string path) — never
		# the binary-float constructor. A JSON float is refused rather than silently rounded.
		if isinstance(raw, float):
			raise StrategyConfigError(
				f"{owner}.{field}: a JSON float cannot back a Decimal param (float for money "
				f"is a correctness defect) — encode Decimals as strings"
			)
		if isinstance(raw, bool) or not isinstance(raw, (str, int)):
			raise StrategyConfigError(
				f"{owner}.{field}: expected a Decimal string, got "
				f"{type(raw).__name__}: {raw!r}"
			)
		value = to_money(raw)
		if not value.is_finite():
			raise StrategyConfigError(f"{owner}.{field}: refusing a non-finite Decimal: {raw!r}")
		return value

	if isinstance(inner, type) and issubclass(inner, Enum):
		# Reached only for an Enum field OUTSIDE _COERCE (the _COERCE fields are passed through
		# untouched by the caller so the constructor coerces them). A hypothetical future enum
		# knob would otherwise land on the instance as a bare str, silently: _apply_params
		# coerces ONLY the _COERCE names ("D-08: ONLY these three engine fields coerce a str").
		try:
			return inner(raw)
		except ValueError as exc:
			raise StrategyConfigError(
				f"{owner}.{field}: {raw!r} is not a valid {inner.__name__}"
			) from exc

	if get_origin(inner) is list:
		if not isinstance(raw, list):
			raise StrategyConfigError(
				f"{owner}.{field}: expected a list, got {type(raw).__name__}: {raw!r}"
			)
		# A copy, so the caller cannot alias the blob's list onto the instance (the ticker
		# verbs mutate ``tickers`` in place). The base's IN-02 guard validates the contents.
		return list(raw)

	if inner in _PASSTHROUGH:
		if not isinstance(raw, inner):
			raise StrategyConfigError(
				f"{owner}.{field}: expected {inner.__name__}, got "
				f"{type(raw).__name__}: {raw!r}"
			)
		return raw

	raise StrategyConfigError(
		f"{owner}.{field}: unsupported declared type {inner!r} — the codec decodes Decimal, "
		f"Enum, bool, int, str, list, and the sizing/SLTP policies (optionally None-unioned)"
	)


def encode_strategy_config(strategy: Strategy) -> dict[str, Any]:
	"""Serialize ``strategy``'s authoring params to a JSON-native ``config_json`` blob (D-04).

	The blob is exactly ``_declared_hints(type(strategy))`` minus ``_DERIVED_FIELDS`` and
	``name``, with ``timeframe`` aliased (trap 1), enums as ``.value`` (trap 3), and policies
	delegated to the Plan 01 tagged-union codec — plus the ``strategy_type`` and
	``config_version`` envelope keys.

	``json.dumps(blob)`` needs no ``default=`` hook: every Decimal has already crossed as a
	string.
	"""
	cls = type(strategy)
	hints = _declared_hints(cls)
	blob: dict[str, Any] = {}
	# Sorted, so repeated encodes of an unchanged instance produce EQUAL blobs (byte-equal
	# under json.dumps) and never trigger a spurious row update. _declared_hints walks the MRO,
	# whose order is stable but incidental — sorting makes the blob's key order a property of
	# the NAMES rather than of the class hierarchy's shape.
	for name in sorted(hints):
		if name in _SKIPPED_FIELDS:
			continue
		if name == _TIMEFRAME_FIELD:
			blob[name] = strategy.timeframe_alias
			continue
		blob[name] = _encode_value(cls.__name__, name, hints[name], getattr(strategy, name))
	blob[_TYPE_KEY] = cls.__name__
	blob[_VERSION_KEY] = CONFIG_VERSION
	return blob


def decode_strategy_config(
	rec: Mapping[str, Any],
	catalog: StrategyCatalog,
	policy_registry: PolicyRegistry,
) -> tuple[type[Strategy], dict[str, Any]]:
	"""Resolve a registry row to ``(cls, params)`` ready for ``cls(**params)`` (D-01/D-04/D-20).

	``rec`` is a ``strategy_registry`` row: ``strategy_name`` (the natural PK), ``strategy_type``
	(the catalog key) and ``config_json`` (the blob).

	The CALLER constructs. Plan 05's ``build_strategy`` owns the D-19 quarantine of a
	construction failure, so a construction error is deliberately NOT swallowed here — and
	``_apply_params`` owns unknown/missing-param rejection, which is why an unrecognised blob key
	is passed THROUGH to the constructor rather than rejected here.

	Raises
	------
	UnknownStrategyTypeError
		``strategy_type`` is absent from the injected catalog (D-01).
	StrategyConfigError
		The blob's version is absent or newer than ``CONFIG_VERSION``, the blob disagrees with
		the row about the type, or a declared param cannot be coerced.
	"""
	blob = rec.get("config_json")
	if not isinstance(blob, Mapping):
		raise StrategyConfigError(
			f"row {rec.get('strategy_name')!r}: config_json must be a mapping, got "
			f"{type(blob).__name__}: {blob!r}"
		)

	strategy_type = rec.get(_TYPE_KEY)
	if not isinstance(strategy_type, str):
		raise StrategyConfigError(
			f"row {rec.get('strategy_name')!r}: missing a string {_TYPE_KEY!r} column, got "
			f"{strategy_type!r}"
		)

	# D-01: the injected allowlist lookup — the ONLY way a string becomes a class here.
	cls = resolve_strategy_class(catalog, strategy_type)

	# The blob is self-describing (it carries its own strategy_type) AND the row has a
	# strategy_type column. The COLUMN is authoritative — it is what the catalog lookup and the
	# store's queries key on. Cross-check them so a row whose column and blob disagree is
	# reported rather than silently resolved one way (T-10-22/T-10-24: the disagreement is
	# itself the signal that something wrote the row inconsistently).
	blob_type = blob.get(_TYPE_KEY)
	if blob_type is not None and blob_type != strategy_type:
		raise StrategyConfigError(
			f"row {rec.get('strategy_name')!r}: strategy_type disagrees between the row "
			f"({strategy_type!r}) and its config_json ({blob_type!r})"
		)

	# D-20: P10 does not migrate — it REPORTS.
	version = blob.get(_VERSION_KEY)
	if not isinstance(version, int) or isinstance(version, bool):
		raise StrategyConfigError(
			f"row {rec.get('strategy_name')!r}: config_json is missing an int "
			f"{_VERSION_KEY!r} (got {version!r}); expected {CONFIG_VERSION}"
		)
	if version > CONFIG_VERSION:
		raise StrategyConfigError(
			f"row {rec.get('strategy_name')!r}: config_json version {version} is newer than "
			f"the supported version {CONFIG_VERSION} — this build cannot decode it"
		)

	hints = _declared_hints(cls)
	# Trap 2 (D-02): the name comes from the ROW's PK, never the blob (which has none).
	params: dict[str, Any] = {"name": rec["strategy_name"]}
	for key, raw in blob.items():
		if key in _ENVELOPE_KEYS:
			continue
		if key in _COERCE:
			# ``timeframe`` / ``direction``: pass the string STRAIGHT through and let the
			# constructor's _COERCE coerce it (via each enum's case-insensitive _missing_).
			# Coercing here would duplicate _apply_params — and a duplicate drifts.
			params[key] = raw
			continue
		declared = hints.get(key)
		if declared is None:
			# An unrecognised key. Pass it through UNTOUCHED so _apply_params raises
			# UnknownParamError — that validator owns the rejection (T-10-20). Dropping it here
			# would be a silent skip of exactly the smuggling attempt it is meant to catch.
			params[key] = raw
			continue
		params[key] = _decode_value(cls.__name__, key, declared, raw, policy_registry)
	return cls, params
