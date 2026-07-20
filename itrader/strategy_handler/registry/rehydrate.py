"""The D-01 rehydrate seam: the stored strategy roster becomes live instances at boot.

**D-01 — the load-bearing reframe.** Strategy *types* are CODE: the application hands them
to the engine through the injected catalog (the owner's proprietary strategies live in a
private submodule repo), so ``itrader`` never imports a concrete strategy class. Strategy
*instances* are DATA: the store is their source of truth. Rehydrate therefore INSTANTIATES
from ``store x catalog x codec`` — ``for rec in store.read_all(): cls =
catalog[rec["strategy_type"]]; add_strategy(cls(**params))``. It does NOT re-apply stored
state onto a roster hardcoded in composition code, because that would make code, not the
store, the source of truth for WHAT TRADES.

**CR-01 — the FULL roster loads; ``enabled`` becomes ``is_active``, not a load filter.**
``read_all()`` returns EVERY row (enabled AND disabled). A disabled (``enabled=False``) row
is reconstructed present-but-dark — the rebuilt instance is ``deactivate_strategy()``'d so
it is ``is_active`` False: it owns its open positions and is re-enable-able, rather than
being silently dropped (which would orphan its positions and make the strategy permanently
unreachable across a restart). This is what makes ``disable``-across-restart and the
``remove`` crash-safety guarantee actually hold.

**D-19 — two arms, and they pull in opposite directions.**

* PER-INSTANCE failure (``strategy_type`` retired from the catalog, ``config_json`` that
  will not deserialize after param drift, or a timeframe the feed base cadence cannot serve
  — finer than base or a non-whole-multiple, WR-01 re-review) -> SKIP that instance, fire
  ONE CRITICAL alert, and CONTINUE. The owner's strategy submodule evolves independently of rows already on
  disk, so drift is a certainty rather than a risk; letting one stale row block every
  healthy strategy would turn a data problem into a self-inflicted outage.
* INFRASTRUCTURE failure (rows exist but no catalog was injected; the store is unreadable)
  -> FAIL LOUD. That is a wiring bug, and a live engine that appears healthy while trading
  nothing is worse than one that refuses to boot.

Consequently this module is **NOT** blanket-wrapped in a degrade-clean ``except``: that
pattern is right for the config-layering path next door, but here it would invert the second
arm into exactly the silent boot-with-zero-strategies the first paragraph calls worse.

**"Skip" and "loud" are orthogonal.** Loudness comes from the ``alert_sink`` CRITICAL
channel — the same egress a halt uses — not from halting. A quarantined instance is
reported, not fatal.

**D-19 — the row is NEVER mutated.** Quarantine never flips the row's ``enabled`` flag off,
and writes nothing back at all. The DB holds the operator's declared INTENT; the runtime's
job is to report that it could not load the row, not to rewrite what the operator asked
for. Turning that flag off would silently
convert a transient code-drift problem into a permanent one that SURVIVES THE FIX: repairing
the class and restarting would leave the strategy dark until someone remembered to
re-enable it by hand. This is the decision in this module most likely to be "helpfully"
undone by a later reader — it is deliberate.

**D-02** — ``strategy_name`` is the only restart-stable identity. ``add_strategy``
loud-rejects a duplicate name (a collision would silently overwrite another instance's
persisted state), and each rebuilt instance mints a FRESH ephemeral ``strategy_id`` UUIDv7
per construction; no second durable id exists.

**D-16** — a ``PairStrategy`` row takes the identical path. This module holds no
type-sniffing branch and no pair special case: excluding pairs would mean pairs do not
survive restart. (A pair is ``LONG_SHORT``, so the handler's SHORT-01/D-07 registration
gate still applies to a rebuilt instance exactly as it does to a hand-added one — that
rejection is a system-level misconfiguration, not a bad row, so it is not quarantined.)

**D-21** — an EMPTY registry is a VALID first-start state. A fresh DB means zero strategies:
boot completes, the engine trades nothing and waits. There is no seed-from-config path.

**D-05/GATE-01** — this module is reached only from inside ``build_live_system``'s
``system_store is not None`` gate and is never barrel-exported from ``strategy_handler``, so
the backtest import path stays SQL-free. It imports no store class: the store arrives
injected, as a duck-typed handle.
"""

import uuid
from typing import Any, Mapping, Optional, Protocol

from itrader.core.enums import ErrorSeverity
from itrader.core.exceptions import MissingParamError, UnknownParamError
from itrader.core.ids import PortfolioId
from itrader.core.policy_codec import PolicyRegistry, default_policy_registry
from itrader.logger import get_itrader_logger
from itrader.price_handler.feed.cache_registration import (
	UnwarmableTimeframeError,
	required_base_depth,
)
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.registry.catalog import (
	StrategyCatalog,
	UnknownStrategyTypeError,
)
from itrader.strategy_handler.registry.config_codec import (
	StrategyConfigError,
	decode_strategy_config,
)

__all__ = [
	"RehydrateInfrastructureError",
	"build_strategy",
	"rehydrate_strategies",
]

# D-19 — the PER-INSTANCE failure set: a bad ROW, not a bad SYSTEM. Each of these means
# "this one instance cannot be reconstructed" and nothing about the health of its siblings,
# so each is quarantined rather than raised.
#
# Enumerated EXPLICITLY rather than caught as a bare ``except`` on the base class: a broad
# catch here would also swallow a genuine infrastructure fault (a store/driver error raised
# mid-loop) and silently quarantine every strategy in turn — reporting a data problem while
# hiding an outage. The narrow tuple keeps the two D-19 arms actually separable.
_QUARANTINABLE: tuple[type[Exception], ...] = (
	UnknownStrategyTypeError,  # the class was retired from the catalog
	StrategyConfigError,       # the blob will not deserialize (version/type/coercion)
	UnknownParamError,         # param drift: the blob names a param the class dropped
	MissingParamError,         # param drift: the class gained a required param
	UnwarmableTimeframeError,  # finer-than-base / non-whole-multiple tf: can never warm from
	                           # the base-bar ring (F-1) — a bad ROW, quarantined not raised (WR-01)
)


class RehydrateInfrastructureError(RuntimeError):
	"""The registry could not be rehydrated at all — a WIRING bug (D-19 loud arm).

	Raised when the registry HAS rows but no ``strategy_catalog`` was injected. This is
	deliberately NOT degrade-cleaned: booting with silently zero strategies would present a
	healthy-looking live engine that trades nothing, which D-19 rates as worse than failing
	to boot. A store that cannot be read propagates its own error for the same reason.
	"""


class StrategyRegistryReader(Protocol):
	"""The read-only slice of ``StrategyRegistryStore`` rehydrate needs (D-05).

	A Protocol, not an import: keeping the store duck-typed means this module pulls no
	SQLAlchemy onto the import graph, and a test can drive it with a plain fake.

	``read_all()`` returns the FULL FK-joined roster — every row, enabled AND disabled,
	each record carrying an inline ``portfolio_ids: list[str]`` (its portfolio fan-out
	joined in). It is NOT a load filter: a row's ``enabled`` column becomes the
	reconstructed instance's ``is_active`` (CR-01), so a disabled row loads present-but-dark
	rather than being dropped.
	"""

	def read_all(self) -> list[Mapping[str, Any]]:
		...


class AlertEgress(Protocol):
	"""The ``alert_sink`` slice used here — the CRITICAL egress (P8's structural seam)."""

	def alert(self, event: Any) -> None:
		...


def _codec_rec(rec: Mapping[str, Any]) -> Mapping[str, Any]:
	"""Normalize a registry record to the key set ``decode_strategy_config`` reads.

	Two shapes exist for one row and they spell the blob differently, which is exactly the
	kind of drift that fails silently if papered over implicitly:

	* the STORE RECORD (``StrategyRegistryStore.list_active()`` / ``get()``) renames the
	  column to ``config`` on the way out — the repo-wide store-record convention shared
	  with ``VenueStore``/``ConfigRouter``;
	* the TABLE ROW (the raw column set, e.g. ``tests.support.strategy_catalog``'s seeded
	  rows) keeps the real column name ``config_json``, which is what the codec reads.

	This is the ONE place the two are reconciled, and it is explicit rather than a tolerant
	``rec.get("config") or rec.get("config_json")`` so that a row carrying NEITHER key still
	reaches the codec and fails loudly there, naming the strategy.
	"""
	if "config_json" in rec:
		return rec
	return {**rec, "config_json": rec.get("config")}


def _resolve_portfolio_id(raw: str) -> PortfolioId | int:
	"""Rebuild a stored portfolio-subscription id into the handle the fan-out expects.

	The ``strategy_portfolio_subscriptions.portfolio_id`` column is a ``String`` (Plan 02:
	``subscribed_portfolios`` is typed ``list[PortfolioId | int]``, and a ``Uuid`` column
	would reject the legal ``int`` arm), and ``to_dict`` writes it out via ``str(pid)``. The
	inverse therefore has to PARSE — handing the raw string on would be a silent
	correctness bug rather than a typing nit: ``on_bar`` fans an intent out over
	``subscribed_portfolios`` and casts each id straight onto ``SignalEvent.portfolio_id``
	(``strategies_handler.py``, FL-02: "the runtime value is always a UUIDv7-backed
	PortfolioId"). A bare ``str`` would sail through that cast and reach the portfolio
	lookup as an id that matches NOTHING — the strategy would rehydrate looking healthy and
	then trade into the void.

	A malformed id raises ``StrategyConfigError`` so the D-19 quarantine claims it: an
	instance whose fan-out cannot be reconstructed must not register half-wired.
	"""
	try:
		return PortfolioId(uuid.UUID(raw))
	except (ValueError, AttributeError, TypeError):
		pass
	# The legacy int arm the union still permits.
	try:
		return int(raw)
	except (ValueError, TypeError) as exc:
		raise StrategyConfigError(
			f"portfolio subscription id {raw!r} is neither a UUID nor an int — the stored "
			f"fan-out cannot be reconstructed"
		) from exc


def build_strategy(
	rec: Mapping[str, Any],
	*,
	catalog: StrategyCatalog,
	policy_registry: Optional[PolicyRegistry] = None,
) -> Strategy:
	"""Reconstruct ONE strategy instance from a registry record (D-01).

	``catalog x row x codec -> Strategy``. ``decode_strategy_config`` resolves the class
	through the injected allowlist and coerces the declared params; the CONSTRUCTOR then runs
	``_apply_params`` -> ``validate()`` -> ``_run_init()``, so validation, unknown/missing
	rejection, and warmup/max_window re-derivation all happen on the real path rather than
	being re-implemented (and drifting) here.

	Errors PROPAGATE deliberately — ``rehydrate_strategies`` owns the D-19 quarantine
	decision, and swallowing here would take that decision away from the only layer that can
	tell a bad row from a bad system.
	"""
	registry = policy_registry if policy_registry is not None else default_policy_registry()
	cls, params = decode_strategy_config(_codec_rec(rec), catalog, registry)
	return cls(**params)


def _quarantine_alert(strategy_name: str, exc: Exception) -> Any:
	"""Build the D-19 CRITICAL ``ErrorEvent`` for a quarantined instance.

	Binds ``strategy_name`` and the error KIND (the exception's type name) and NOTHING else
	— no ``config_json`` values, no exception message (a codec error's message quotes the
	offending stored value). This follows the P8 declared-fields-only precedent: the alert
	crosses out to an operator channel, so it carries what is needed to find the row and
	nothing that could leak what is in it.

	The events package is imported lazily: it pulls pandas, and this module is on the boot
	path of a gate that must stay import-light.
	"""
	from datetime import UTC, datetime

	from itrader.events_handler.events import ErrorEvent

	return ErrorEvent(
		time=datetime.now(UTC),
		source="strategy_registry",
		error_type=type(exc).__name__,
		error_message=(
			f"Strategy {strategy_name!r} could not be rehydrated and was QUARANTINED "
			f"({type(exc).__name__}); its registry row is unchanged and it will load "
			f"again on the next restart once the cause is fixed"
		),
		operation="rehydrate",
		severity=ErrorSeverity.CRITICAL,
		details={"strategy_name": strategy_name, "error_kind": type(exc).__name__},
	)


def rehydrate_strategies(
	*,
	store: StrategyRegistryReader,
	catalog: Optional[StrategyCatalog],
	strategies_handler: Any,
	alert_sink: AlertEgress,
	policy_registry: Optional[PolicyRegistry] = None,
) -> list[str]:
	"""Register the FULL stored roster onto ``strategies_handler`` (D-01/CR-01).

	The store is the source of truth for the roster. Rows are reconstructed via
	``read_all()`` — the deterministic ``strategy_name`` ASC roster with each record's
	``portfolio_ids`` in ``portfolio_id`` ASC order (IN-01), so registration order — and
	therefore ``min_timeframe`` derivation and universe membership — is reproducible across
	runs and dialects.

	CR-01 — ``read_all()`` loads EVERY row, not just the enabled ones. A row's ``enabled``
	column becomes the reconstructed instance's ``is_active``: a disabled (``enabled=False``)
	row is reconstructed present-but-dark (``deactivate_strategy()``'d after registration) so
	it owns its positions and is re-enable-able. ``enabled`` is NOT a load filter — dropping
	disabled rows would orphan their positions and make the strategy unreachable after a
	restart.

	Returns
	-------
	list[str]
		The quarantined ``strategy_name``s (D-19). Empty on a clean rehydrate. The caller
		surfaces this on the read-model as ``state.quarantined_strategies``.

	Raises
	------
	RehydrateInfrastructureError
		The registry has rows but ``catalog`` is None (D-19 infrastructure arm).
	Exception
		Anything ``store.read_all()`` raises propagates unchanged — an unreadable store
		is infrastructure, not a bad row.
	ValueError
		``add_strategy`` rejects a duplicate ``strategy_name`` (D-02). Not quarantined: a
		collision means the roster is already inconsistent, which is a system-level problem.
	"""
	logger = get_itrader_logger().bind(component="StrategyRehydrator")

	# D-19 infrastructure: NOT wrapped. A store failure must reach the caller.
	rows = store.read_all()

	if not rows:
		# D-21 x D-19: a fresh DB is a valid first-start state, and with nothing to
		# instantiate there is no wiring bug to report even when no catalog was injected.
		# This is the state of every existing live test, which is what makes
		# construction-time rehydrate safe to land.
		logger.info("Strategy registry is empty — booting with zero strategies (D-21)")
		return []

	if catalog is None:
		# D-19 infrastructure arm: rows exist and nothing can instantiate them.
		raise RehydrateInfrastructureError(
			f"the strategy registry holds {len(rows)} row(s) but no strategy_catalog "
			f"was injected into build_live_system — refusing to boot with zero strategies "
			f"(D-19): this is a wiring bug, and an engine that appears healthy while trading "
			f"nothing is worse than one that fails to start"
		)

	registry = policy_registry if policy_registry is not None else default_policy_registry()
	quarantined: list[str] = []

	for rec in rows:
		strategy_name = rec["strategy_name"]
		try:
			# Build the instance AND resolve its fan-out before touching the handler, so
			# the per-instance step is atomic: a quarantine decision must never leave a
			# half-wired strategy registered (one that would trade with no portfolios, or
			# with only the subscriptions that happened to parse before the bad one).
			strategy = build_strategy(rec, catalog=catalog, policy_registry=registry)
			portfolio_ids = [
				_resolve_portfolio_id(raw)
				for raw in rec["portfolio_ids"]
			]
			# F-1 warmability (WR-01 re-review): a finer-than-base / non-whole-multiple
			# timeframe can never warm from the base-bar ring. Keyed on base_timeframe so
			# ONLY the LIVE feed runs the check — the backtest/in-memory feed has no
			# base_timeframe -> None -> skip cleanly (the SAME degrade the add/reconfigure
			# gates use, strategies_handler.py:770/:1005). Called for its RAISE only (the
			# ring sizing stays owned by register_strategy_warmup — discard the return). It
			# runs BEFORE add_strategy, so a raise leaves the instance unregistered and the
			# row unmutated: UnwarmableTimeframeError is now in _QUARANTINABLE, turning a
			# self-inflicted boot outage into a per-instance quarantine.
			#
			# WR-02 — uniform quarantine (do NOT gate on enabled): the check runs over
			# EVERY row regardless of `rec["enabled"]`. Do NOT rewrite the guard below to
			# `if base_timeframe is not None and rec["enabled"]:`. WHY the check must stay
			# ungated on the row's enabled state:
			#   (a) an unwarmable strategy can never reach is_ready, so a disabled row loaded
			#       present-but-dark would only have ILLUSORY position "ownership" — it could
			#       never warm enough to manage those positions out;
			#   (b) quarantine is LOUD (one CRITICAL alert on the halt egress) whereas loading
			#       it present-but-dark is a SILENTLY-inert dark strategy — and D-19 rates
			#       "appears healthy while trading nothing" as worse than failing to start, so
			#       loud-quarantine is the D-19-consistent choice;
			#   (c) the row is NOT mutated, so the quarantine is non-destructive and
			#       self-recovering — fix the base-cadence config and restart and the row
			#       reloads warmable (nothing to un-flip by hand);
			#   (d) consistent with every other _QUARANTINABLE class (codec / param drift /
			#       portfolio-id), none of which get present-but-dark treatment.
			# Load-bearing: once the deactivated-skip is reverted (quick-260718-evz), the
			# warmup ladder AGAIN includes disabled strategies, so a loaded disabled-unwarmable
			# row would crash boot inside register_strategy_warmup. Uniform quarantine here is
			# therefore REQUIRED (not merely acceptable) to stop one stale disabled row
			# becoming a self-inflicted boot outage.
			base_timeframe = getattr(
				getattr(strategies_handler, "feed", None), "base_timeframe", None)
			if base_timeframe is not None:
				required_base_depth(strategy.warmup, strategy.timeframe, base_timeframe)
		except _QUARANTINABLE as exc:
			# D-19 per-instance: skip, alert CRITICAL, CONTINUE. The row is NOT mutated —
			# see the module docstring for why that is load-bearing.
			quarantined.append(strategy_name)
			alert_sink.alert(_quarantine_alert(strategy_name, exc))
			logger.error(
				"Quarantined strategy %s at rehydrate (%s) — row left unchanged, healthy "
				"strategies continue loading",
				strategy_name, type(exc).__name__)
			continue

		# D-02: a duplicate name raises out of here rather than being quarantined.
		strategies_handler.add_strategy(strategy)
		for portfolio_id in portfolio_ids:
			strategy.subscribe_portfolio(portfolio_id)
		# CR-01: honor `enabled` as `is_active`. A disabled row loads present-but-dark —
		# registered (so it owns its positions and is re-enable-able) but deactivated so
		# the D-07 gate stops NEW entries. This is orthogonal to the quarantine try above:
		# it runs only once add_strategy succeeded.
		if not rec["enabled"]:
			strategy.deactivate_strategy()

	logger.info(
		"Rehydrated %d strategy instance(s) from the registry; %d quarantined",
		len(rows) - len(quarantined), len(quarantined))
	return quarantined
