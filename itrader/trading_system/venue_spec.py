"""Live-only venue-selection spec + its single shared builder.

Carries the fields consumed at live wiring: ``execution_venue`` and ``account_id``
select the execution bundle via ``assemble_venue``; ``data_provider`` selects the
data-provider plugin at the composition root's own build call, not inside
``assemble_venue``. A frozen dataclass is preferred over a duck-typed namespace
here: free equality lets two independently-built specs be compared directly.

Pure module: imports no venue substrate / ccxt / SQL, so it never touches the
backtest import graph.

Indentation: tabs (matches the sibling ``system_spec.py``).
"""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class VenueSpec:
	"""The live venue-selection fields read at assembly + composition.

	``execution_venue`` and ``account_id`` select the execution bundle via
	``assemble_venue`` (``execution_venue`` picks the ``ExecutionVenueRegistry``
	plugin, ``account_id`` keys the ``ConnectorProvider`` memo). ``data_provider``
	selects the ``DataProviderRegistry`` plugin at the composition root's own
	build call, not inside ``assemble_venue``. Frozen so equality is free — two
	specs built from the same inputs compare equal.

	It feeds ``assemble_venue`` ONLY — never ``compose_engine``.

	Beside that trio it also carries the per-account values read off the
	account's own ``venue_accounts`` row: ``secret_ref``, and the three
	allowlisted ``config_json`` knobs ``sandbox`` / ``region`` / ``market_type``.
	Those are read by the venue plugins the trio selects, not by
	``assemble_venue`` itself.
	"""

	execution_venue: str
	data_provider: str
	account_id: Optional[str] = None
	# A POINTER at wherever this account's credentials live (``env:<PREFIX>`` today),
	# read off the durable ``venue_accounts`` row — NEVER a credential itself. The
	# connector plugin's ``build`` resolves it through the injected
	# ``CredentialResolver``, which is what lets two ``account_id``s connect with
	# DIFFERENT keys instead of sharing one global credential set. ``None`` means no
	# per-account credentials.
	secret_ref: Optional[str] = None
	# Account-level, non-secret knobs an account's own ``venue_accounts.config_json``
	# may carry. ``VenueAccountManager.bring_online`` merges them onto the spec
	# through an explicit allowlist so the spec is the one object travelling from
	# that row to both ``OkxConnectorPlugin.build`` (sandbox/region) and
	# ``VenuePlugin.build_bundle`` (market_type).
	#
	# ``None`` means "no override, venue/bundle default stands" rather than a
	# concrete default: a real default here would be a second home for each venue's
	# own default, and the two would drift out of sync.
	#
	# sandbox/region decide which host a live order reaches (an EEA key answers
	# 50119 on the global host); market_type reaches ``VenueAccount``, where
	# ``_cash_stream_nets_holds = market_type != "spot"`` changes cash accounting —
	# why an unrecognised config_json key raises rather than being silently dropped.
	sandbox: Optional[bool] = None
	# Left an unconstrained str on purpose: the legal region vocabulary is the
	# venue's own (``OkxSettings.region`` is a ``Literal["global", "eea"]`` that fails
	# loud on anything else), and pinning it here would bake OKX's entity list into a
	# venue-agnostic value object. ``market_type`` is the opposite case — its
	# vocabulary is shared across venues (``VenueAccountConfig``) and a wrong value
	# silently inverts cash accounting rather than failing loud — so it IS constrained.
	region: Optional[str] = None
	market_type: Optional[Literal["spot", "derivative"]] = None


def build_venue_spec(
	execution_venue: str,
	*,
	data_provider: Optional[str] = None,
	account_id: Optional[str] = None,
	secret_ref: Optional[str] = None,
	sandbox: Optional[bool] = None,
	region: Optional[str] = None,
	market_type: Optional[Literal["spot", "derivative"]] = None,
) -> VenueSpec:
	"""Build the live ``VenueSpec``, applying the default-provider map.

	The sole home of the ``{'okx':'okx','paper':'okx'}`` default-provider map: when
	``data_provider`` is not given, it is derived from ``execution_venue`` (``okx``
	for the okx venue, the OKX live feed for paper, else ``okx``). An explicit
	``data_provider`` override is honored verbatim. Both ``for_exchange`` and
	``build_live_system`` call this builder so the map + spec construction exist in
	exactly one location.

	Parameters
	----------
	execution_venue :
		The venue-name string selecting the execution plugin.
	data_provider :
		An explicit data-provider override; when ``None`` the default-provider map
		is applied over ``execution_venue``.
	account_id :
		The connector-memo key; ``None`` makes ``assemble_venue`` raise
		``ValidationError`` rather than default it — a live spec must always name
		an account.
	secret_ref :
		The account's credential POINTER off its ``venue_accounts`` row.
		``None`` = no per-account credentials.
	sandbox, region, market_type :
		The account-level ``config_json`` overrides, threaded through this builder
		rather than assigned onto the spec afterwards: a spec re-built from its own
		fields must still compare EQUAL, and a knob the builder dropped would
		silently make the two live entry points produce specs that route to two
		different hosts. ``None`` on any of them = no override (the default stands).
	"""
	resolved_provider = data_provider or {
		'okx': 'okx', 'paper': 'okx'}.get(execution_venue, 'okx')
	return VenueSpec(
		execution_venue=execution_venue,
		data_provider=resolved_provider,
		account_id=account_id,
		secret_ref=secret_ref,
		sandbox=sandbox,
		region=region,
		market_type=market_type,
	)
