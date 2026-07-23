"""Live-only venue-selection spec + its single shared builder (SEAM-03, D-11).

After D-04 made ``compose_engine`` SPEC-FREE, the ONLY "spec" the live path still
needs is the venue-selection trio that ``assemble_venue`` reads:
``execution_venue`` / ``data_provider`` / ``account_id``. This module promotes that
duck-typed ``SimpleNamespace`` into a small typed value object.

Locked decision for this module:

* **D-11 — a small live-only ``VenueSpec`` for ``assemble_venue``, NOT a compose
  spec.** A frozen ``VenueSpec`` carrying exactly ``execution_venue`` /
  ``data_provider`` / ``account_id`` (3 fields, genuinely venue-scoped, not
  backtest-shaped) feeds ``assemble_venue`` ONLY — it NEVER crosses into
  ``compose_engine`` (compose is spec-free since D-04). ONE shared builder
  (``build_venue_spec``) produces it and is the SOLE home of the
  ``{'okx':'okx','paper':'okx'}`` default-provider map; BOTH ``for_exchange`` and
  ``build_live_system`` call it, killing the twice-written ``SimpleNamespace`` +
  default-map. A typed dataclass (frozen ``__eq__``) is preferred over the
  duck-typed ``SimpleNamespace`` — mypy-friendly, self-documenting, and the free
  equality lets the SEAM-03 unit test prove ``for_exchange`` and
  ``build_live_system`` produce IDENTICAL specs.

Import-inert by construction: this module is PURE (strings + a dataclass) — it
imports NO venue substrate / ccxt / SQL, so it never touches the backtest import
graph and stays ``mypy --strict`` clean.

Indentation: TABS (``trading_system/`` package convention; mirrors the sibling
``system_spec.py``).
"""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class VenueSpec:
	"""The live venue-selection trio ``assemble_venue`` reads (D-11).

	Exactly the three fields ``assemble_venue`` consumes off ``spec`` —
	``execution_venue`` (selects the ``ExecutionVenueRegistry`` plugin),
	``data_provider`` (selects the ``DataProviderRegistry`` plugin), and
	``account_id`` (keys the ``ConnectorProvider`` memo). Frozen so equality is
	free — two specs built from the same inputs compare equal, which is the
	load-bearing SEAM-03 invariant (``for_exchange`` == ``build_live_system``).

	It feeds ``assemble_venue`` ONLY — never ``compose_engine`` (spec-free since
	D-04).

	Beside that selection trio it CARRIES (does not select on) the per-account
	values read off the account's own ``venue_accounts`` row: ``secret_ref`` (D-02)
	and, since 11.2-06, the three allowlisted ``config_json`` knobs ``sandbox`` /
	``region`` / ``market_type`` (D-38). Those are read by the venue PLUGINS the
	trio selects, not by ``assemble_venue`` itself — the spec is simply the one
	object already travelling from the row to both of them.
	"""

	execution_venue: str
	data_provider: str
	account_id: Optional[str] = None
	# 11-04 (D-02/MPORT-06): a POINTER at wherever this ACCOUNT's credentials live
	# (``env:<PREFIX>`` today), read off the durable ``venue_accounts`` row. NEVER a
	# credential itself. The connector plugin resolves it through the injected
	# ``CredentialResolver`` inside ``build``, which is what makes two ``account_id``s
	# connect with DIFFERENT keys instead of the one global ``OKX_API_*`` set (the
	# D-12 caveat). ``None`` = the pre-MPORT-06 single-account deployment.
	secret_ref: Optional[str] = None
	# 11.2-06 (D-38/D-12): the three ACCOUNT-LEVEL, NON-SECRET knobs an account's own
	# ``venue_accounts.config_json`` may carry. ``VenueAccountManager.bring_online``
	# merges them onto the spec through an explicit allowlist; they are carried HERE
	# because the spec is the one object that already travels from that row to both
	# consumers — ``ConnectorProvider.get(venue, account_id, spec)`` ->
	# ``OkxConnectorPlugin.build`` (``sandbox`` / ``region``) and
	# ``VenuePlugin.build_bundle`` (``market_type``).
	#
	# ``None`` on any of them means "this account names no override", leaving the
	# venue/bundle default in force. That is deliberately NOT a concrete default: a
	# real value here would be a SECOND home for each venue's own default and the two
	# would drift, and absence must stay distinguishable from an explicit value or the
	# merge would invent overrides the operator never wrote.
	#
	# ``sandbox`` and ``region`` decide WHICH HOST a live order reaches (an EEA key
	# answers 50119 on the global host); ``market_type`` reaches ``VenueAccount``,
	# where ``_cash_stream_nets_holds = market_type != "spot"`` changes CASH
	# ACCOUNTING. Both are why an unrecognised ``config_json`` key RAISES upstream
	# rather than being dropped.
	sandbox: Optional[bool] = None
	# Left an unconstrained ``str`` ON PURPOSE: the legal region vocabulary is the
	# VENUE's (``OkxSettings.region`` is a ``Literal["global", "eea"]`` that fails loud
	# on anything else), and pinning it here would bake OKX's entity list into a
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
	"""Build the live ``VenueSpec``, applying the default-provider map (D-11).

	The SOLE home of the ``{'okx':'okx','paper':'okx'}`` default-provider map: when
	``data_provider`` is not given, it is derived from ``execution_venue`` (``okx``
	for the okx venue, the OKX live feed for paper (D-21), else ``okx``). An explicit
	``data_provider`` override is honored verbatim. BOTH ``for_exchange`` and
	``build_live_system`` call this builder so the map + spec construction exist in
	exactly ONE location.

	Parameters
	----------
	execution_venue :
		The venue-name string selecting the execution plugin.
	data_provider :
		An explicit data-provider override; when ``None`` the default-provider map
		is applied over ``execution_venue``.
	account_id :
		The connector-memo key; ``None`` defers to the plugins' ``"default"``
		fallback (``assemble_venue`` does NOT re-default it).
	secret_ref :
		The account's credential POINTER off its ``venue_accounts`` row (D-02).
		``None`` = no per-account credentials (paper, or a pre-MPORT-06 deployment).
	sandbox, region, market_type :
		11.2-06 (D-38): the account-level ``config_json`` overrides, threaded through
		this builder rather than assigned onto the spec afterwards. Threading them
		HERE is what keeps the SEAM-03 identity invariant true — a spec re-built from
		its own fields must still compare EQUAL, and a knob the builder dropped would
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
