"""Engine-thread runtime-config router — validate -> persist -> apply -> push (RTCFG-02/04/05).

The single-writer CONTROL-plane consumer of ``ConfigUpdateEvent`` (D-23). Runs ENTIRELY on the
engine thread (LR-12 single-writer contract): a dequeued ``ConfigUpdateEvent(scope, key, value)``
is routed by a default-deny scope->owner dispatch (D-11/D-21), validated by Pydantic
``validate_assignment`` / ``model_validate`` (D-13), persisted to the OWNING module store (D-25),
then applied to the live mutable config sub-model + pushed through the owning handler's existing
``update_config(...)`` (D-01). Ordering is validate -> persist -> apply (D-15): a persist failure
rejects and applies NOTHING live, so the DB and the in-memory config never diverge in the
applied-but-not-persisted direction.

There is NO standalone allowlist artifact (D-11). The mutation boundary IS the config structure:
  * the FROZEN ``ITraderConfig`` base blocks immutable determinism/identity keys (rng_seed,
    environment, IDs) — they are not fields on any mutable sub-model, so no routable (scope,key)
    exists for them and default-deny rejects them STRUCTURALLY (RTCFG-04);
  * the router's scope->owner map is the routable-scope set; and
  * the target sub-model's ``model_fields`` (introspected, NOT hardcoded) IS the per-scope key
    allowlist — a key that is not a real field on the owning sub-model is default-deny rejected
    (D-12). Because the allowlist is the live model structure, it can never drift from the model.

D-21/D-25 — each MODULE owns its config; config is NEVER centralized into SystemStore:
  * ``system``          -> SystemStore  (system-global lifecycle + universe knobs)
  * ``order``           -> the ORDER store via ``order_handler.storage.save_config`` (one global
                          singleton OrderConfig record, NOT SystemStore)
  * ``venue:{name}``    -> VenueStore    (per-venue config + enabled; secret-scrub guarded)
  * ``portfolio:{id}``  -> the resolved Portfolio's OWN bound ``PortfolioStateStorage.save_config``
                          (already portfolio_id-scoped, NOT SystemStore)

Inventory pass (WARNING-2 / D-12, A1-style re-grep 2026-07-16 — the router routes ONLY to fields
that actually exist on the target sub-models; every other (scope,key) is default-deny rejected):
  * ``system`` scope keys -> resolve dynamically against ``SystemSettings.model_fields``
    (``enable_auto_restart`` / ``auto_restart_delay_seconds`` / ``enable_graceful_shutdown`` /
    ``shutdown_timeout_seconds`` — the idle/timeout knobs) AND ``UniverseConfig.model_fields``
    (``poll_cadence_s`` / ``remove_policy`` — the universe poll cadence + remove policy). Per
    RTCFG-02 both the system idle/timeout knobs AND the universe poll_cadence/remove_policy live
    under the single ``system`` scope (scopes are locked to {system, order, venue, portfolio}, D-21).
  * ``order`` scope keys  -> ``OrderConfig.model_fields`` == {``market_execution``} ONLY today. The
    RTCFG-02 "order trail/TIF defaults" fields do NOT exist on ``OrderConfig`` and the D-08/D-09
    restructure does NOT add them — so the router routes the order scope to ``market_execution`` and
    lets default-deny reject the rest. NOT fabricated (no speculative trail/TIF field is invented),
    NOT dropped (the order scope stays fully routable). Making trail/TIF runtime-mutable would be a
    config-model addition surfaced as a finding, out of P9's locked restructure (WARNING-2 / D-12).
  * ``venue:{name}`` keys -> {``fee_model``, ``slippage_model``, ``enabled``}; ``fee_model`` /
    ``slippage_model`` are gated by the venue-kind predicate (D-14/RTCFG-05 — simulated-only).
  * ``portfolio:{id}`` keys -> resolve dynamically against the mutable sections of ``PortfolioConfig``
    (``limits`` / ``risk_management`` / ``trading_rules``) — the risk limits + sizing defaults.

Rejection surfacing (D-16): any rejection (unrouted scope, non-field key, unknown portfolio id,
validation failure, live-venue fee/slippage, persist failure) emits a deduped/rate-limited
WARNING-severity ``ErrorEvent`` (the P7 ``warn_min_interval_s`` min-interval dedup pattern, reused)
and records ``self.last_error`` — nothing is applied live. Only FIXED literals + the (non-secret)
scope/key are bound to the ErrorEvent; the ``value`` (the sole secret-carrying field, V7) is NEVER
stringified into a log or an event.

No copy-on-write / atomic-swap snapshot machinery (D-03): the config is a plain engine-thread-owned
mutable object (single writer + single live reader, both on this thread). 4-space indentation
(matches ``route_registrar.py`` / the live CONTROL-plane siblings this router is wired alongside).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Optional

import pydantic
from sqlalchemy.exc import SQLAlchemyError

from itrader.config.itrader_config import ITraderConfig
from itrader.outils.dict_merge import recursive_merge
from itrader.config.order import OrderConfig
from itrader.config.portfolio import PortfolioConfig
from itrader.config.system import SystemSettings
from itrader.config.universe import UniverseConfig
from itrader.core.clock import Clock
from itrader.core.enums import ErrorSeverity
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.core.ids import PortfolioId
from itrader.events_handler.events import ConfigUpdateEvent, ErrorEvent
from itrader.logger import get_itrader_logger

# --- Rejection reason categories (fixed literals — never derived from the value, V7) ---------
_REASON_UNROUTED_SCOPE = "unrouted-scope"
_REASON_UNKNOWN_KEY = "unknown-key"
_REASON_UNKNOWN_PORTFOLIO = "unknown-portfolio"
_REASON_VALIDATION_FAILED = "validation-failed"
_REASON_VENUE_KIND = "venue-kind-live-fee-slippage"
_REASON_PERSIST_FAILED = "persist-failed"
# WR-02: a store read / handler push / model-validate failure that escaped the per-scope
# guards (NOT a _RejectedUpdate) — surfaced as a deduped WARNING rejection, never an escape.
_REASON_APPLY_FAILED = "apply-failed"

# --- WARNING ErrorEvent fixed egress literals (mirrors the PreTradeThrottle D-09 pattern) ----
_ERROR_SOURCE = "config_router"
_ERROR_TYPE = "ConfigUpdateRejected"
_ERROR_MESSAGE = "runtime config update rejected"
_ERROR_OPERATION = "config_update"

# --- Venue-scope allowlist (D-14/RTCFG-05) ---------------------------------------------------
_VENUE_FEE_SLIPPAGE_KEYS = frozenset({"fee_model", "slippage_model"})
_VENUE_KEYS = frozenset({"fee_model", "slippage_model", "enabled"})

# --- Portfolio-scope mutable sections (D-21 — the risk limits + sizing defaults) -------------
_PORTFOLIO_MUTABLE_SECTIONS = ("limits", "risk_management", "trading_rules")


class _RejectedUpdate(Exception):
    """Internal default-deny signal — carries a FIXED reason category (never the value)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ConfigRouter:
    """Engine-thread router: validate -> persist -> apply -> push, default-deny dispatch.

    Constructed with the deps it needs (all injected by ``build_live_system`` in Wave 3), each
    MODULE'S OWN store per D-21/D-25 — the persistence target is the owning module store, NEVER
    centralized into SystemStore. The collaborators are typed ``Any`` where their config surface
    (``save_config`` on the order/portfolio stores) is finalized in Wave 3.

    Parameters
    ----------
    config:
        The process ``ITraderConfig`` singleton — the live mutable apply target (D-06/D-07). The
        FROZEN base blocks immutable keys structurally (RTCFG-04); the router setattrs only the
        mutable sub-models.
    system_store:
        ``SystemStore`` — the ``system`` scope persist target ONLY (D-21/D-25). ``upsert(key,
        value, at)`` with a namespaced ``config.<sub>.<field>`` key.
    venue_store:
        ``VenueStore`` — the ``venue:{name}`` scope persist target. ``upsert(venue_name, config,
        enabled, at)`` with the recursive secret-denylist guard (V7).
    order_handler:
        The order handler; ``order_handler.storage.save_config`` is the ``order`` scope persist
        target (the ORDER store, NOT SystemStore) and ``order_handler.update_config`` the push.
    portfolio_handler:
        The portfolio handler; ``get_portfolio(id)`` resolves the target ``Portfolio`` (unknown id
        -> ``PortfolioNotFoundError`` -> default-deny). Each Portfolio owns its bound
        ``state_storage.save_config`` (the portfolio scope persist target) + ``update_config`` push.
    execution_handler:
        The venue-scope push target for fee/slippage on a simulated venue (``update_config`` ->
        the simulated exchange, D-01).
    venue_kind:
        A resolver ``(venue_name) -> bool`` — ``True`` when the venue's execution arm is a
        ``SimulatedExchange`` (fee/slippage runtime-mutable), ``False`` for a live venue (reject).
    bus:
        The event bus; only ``.put`` is used — the deduped WARNING ``ErrorEvent`` egress (D-16).
    clock:
        The injected determinism clock (``now()``) — the persist ``at`` + the WARNING dedup read
        (never wall clock).
    warn_min_interval_s:
        The min-interval (seconds) between WARNING ErrorEvent emissions (P7 dedup, default 5.0).
    """

    def __init__(
        self,
        *,
        config: ITraderConfig,
        system_store: Any,
        venue_store: Any,
        order_handler: Any,
        portfolio_handler: Any,
        execution_handler: Any,
        venue_kind: Callable[[str], bool],
        bus: Any,
        clock: Clock,
        warn_min_interval_s: float = 5.0,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="ConfigRouter")
        self._config = config
        self._system_store = system_store
        self._venue_store = venue_store
        self._order_handler = order_handler
        self._portfolio_handler = portfolio_handler
        self._execution_handler = execution_handler
        self._venue_kind = venue_kind
        self._bus = bus
        self._clock = clock
        self._warn_min_interval_s = warn_min_interval_s
        # D-16: last WARNING emission time (injected clock) for the min-interval dedup.
        self._last_warn: Optional[datetime] = None
        # D-19: the last rejection reason (Plan 04's read-model reads state.last_error; here the
        # router just exposes it — the state-store write lands in Wave 3).
        self.last_error: Optional[str] = None

    # -- Public entry ------------------------------------------------------------------------

    def apply(self, event: ConfigUpdateEvent) -> None:
        """Route + apply one ``ConfigUpdateEvent`` (validate -> persist -> apply -> push, D-15).

        Default-deny scope dispatch (D-11): scope matching is EXACT-string (no case-folding / no
        normalization) — a mis-cased or differently-encoded scope is unrouted -> rejected. Any
        rejection surfaces a deduped WARNING ``ErrorEvent`` and applies NOTHING live (D-16).
        """
        now = self._clock.now()
        scope = event.scope
        try:
            if scope == "system":
                self._apply_system(event.key, event.value, now)
            elif scope == "order":
                self._apply_order(event.key, event.value, now)
            elif scope.startswith("venue:"):
                venue_name = scope[len("venue:"):]
                if not venue_name:
                    raise _RejectedUpdate(_REASON_UNROUTED_SCOPE)
                self._apply_venue(venue_name, event.key, event.value, now)
            elif scope.startswith("portfolio:"):
                pid = scope[len("portfolio:"):]
                if not pid:
                    raise _RejectedUpdate(_REASON_UNROUTED_SCOPE)
                self._apply_portfolio(pid, event.key, event.value, now)
            else:
                raise _RejectedUpdate(_REASON_UNROUTED_SCOPE)
        except _RejectedUpdate as rejected:
            self._surface_rejection(event, rejected.reason, now)
        except (SQLAlchemyError, ConfigurationError, pydantic.ValidationError) as exc:
            # WR-02/D-16: a KNOWN store-read / handler-push / model-validate failure that
            # escaped the per-scope guards (e.g. an out-of-``_persist`` venue ``get``, a
            # portfolio-store read error, a post-persist push raise) is converted into the
            # SAME deduped WARNING rejection rather than escaping ``apply()`` to the
            # engine-boundary error policy. NOT a bare ``except Exception`` — a genuine
            # programming error (AttributeError/TypeError) still surfaces.
            self.logger.warning(
                "ConfigUpdate store/push error (scope=%s, key=%s): %s",
                event.scope, event.key, exc)
            self._surface_rejection(event, _REASON_APPLY_FAILED, now)

    # -- Scope handlers (each owns the full validate -> persist -> apply D-15 ordering) -------

    def _apply_system(self, key: str, value: Any, now: datetime) -> None:
        """``system`` scope -> SystemStore (D-21/D-25). Idle/timeout knobs + universe knobs.

        The owning sub-model is resolved by introspecting the live model structure (D-12 — the
        structure IS the allowlist): a key on ``SystemSettings`` owns ``config.system``; a key on
        ``UniverseConfig`` owns ``config.universe``; any other key is default-deny rejected. There
        is no dedicated ``update_config`` push handler for system-global config — the universe poll
        timer + lifecycle logic read ``config.<sub>.<field>`` live off the single mutable object
        (D-03), so the apply step is the ``setattr`` alone.
        """
        if key in SystemSettings.model_fields:
            sub_attr = "system"
        elif key in UniverseConfig.model_fields:
            sub_attr = "universe"
        else:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        sub_model = getattr(self._config, sub_attr)
        coerced = getattr(self._dry_validate_copy(sub_model, key, value), key)

        # PERSIST (D-15) — namespaced KV key on the SYSTEM store (system-global config only).
        self._persist(
            lambda: self._system_store.upsert(
                f"config.{sub_attr}.{key}", {"value": coerced}, now
            )
        )

        # APPLY — setattr the live mutable sub-model (re-validates; cheap/idempotent).
        setattr(sub_model, key, value)

    def _apply_order(self, key: str, value: Any, now: datetime) -> None:
        """``order`` scope -> the ORDER store (D-21/D-25), NOT SystemStore.

        ``OrderConfig`` carries ``market_execution`` only today; a non-field key is default-deny
        rejected (WARNING-2 / D-12 — the order trail/TIF fields do not exist and are not
        fabricated). Persists the coerced single-global OrderConfig record via the order store's
        ``save_config`` and pushes the change through ``order_handler.update_config`` (D-01).
        """
        if key not in OrderConfig.model_fields:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        # Dry-validate a throwaway copy so nothing persists on invalid input (D-15 ordering).
        candidate = self._dry_validate_copy(self._config.order, key, value)

        # PERSIST — the single global OrderConfig record on the ORDER store (D-25).
        self._persist(
            lambda: self._order_handler.storage.save_config(
                candidate.model_dump(mode="json"), now
            )
        )

        # APPLY + PUSH (D-01) — mutate the live sub-model, then the owning handler's push.
        setattr(self._config.order, key, value)
        self._order_handler.update_config({key: value})

    def _apply_venue(self, venue_name: str, key: str, value: Any, now: datetime) -> None:
        """``venue:{name}`` scope -> VenueStore. Fee/slippage gated by the venue-kind predicate.

        RTCFG-05/D-14: ``fee_model`` / ``slippage_model`` are runtime-mutable ONLY for a simulated
        venue — a live venue's fee/slippage is rejected (real-venue fees come from actual fills,
        not engine config). ``enabled`` is allowed regardless of venue kind. The secret-scrub is
        enforced inside ``VenueStore.upsert`` (V7) — a credential-carrying value is rejected at the
        write boundary and surfaces here as a persist failure (nothing applied).
        """
        if key not in _VENUE_KEYS:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        # WR-01: ``enabled`` is a REAL boolean flag, not a truthy coercion. A non-bool value
        # (e.g. the string "false", which ``bool(...)`` would evaluate to True and silently
        # ENABLE a venue the caller meant to disable) is rejected BEFORE any persist.
        if key == "enabled" and not isinstance(value, bool):
            raise _RejectedUpdate(_REASON_VALIDATION_FAILED)

        # Venue-kind predicate (D-14) — checked at apply time on the venue's execution arm.
        if key in _VENUE_FEE_SLIPPAGE_KEYS and not self._venue_kind(venue_name):
            raise _RejectedUpdate(_REASON_VENUE_KIND)

        # CR-02/D-15 — DRY-validate the fee/slippage value BEFORE persisting (restores the
        # validate -> persist -> apply -> push ordering the venue scope was missing). The
        # push (``execution_handler.update_config``) is the ONLY validator of a venue
        # fee/slippage value; running its dry twin FIRST means an invalid value NEVER lands
        # in VenueStore (a poisoned row would otherwise brick the next boot's layering).
        if key in _VENUE_FEE_SLIPPAGE_KEYS:
            try:
                self._execution_handler.validate_config({key: value})
            except ConfigurationError as exc:
                raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc

        # Merge onto the existing persisted venue row so a single-field update does not drop the
        # sibling config keys / enabled flag (last-writer-wins per field, D-15 arrival order).
        existing = self._venue_store.get(venue_name)
        config: dict[str, Any] = dict(existing["config"]) if existing else {}
        enabled: bool = bool(existing["enabled"]) if existing else True
        if key == "enabled":
            enabled = value  # already checked to be a real bool (WR-01)
        else:
            config[key] = value

        # PERSIST — VenueStore.upsert runs its recursive secret-denylist guard FIRST (V7).
        self._persist(
            lambda: self._venue_store.upsert(venue_name, config, enabled, now)
        )

        # APPLY + PUSH — a simulated-venue fee/slippage change pushes to the execution handler
        # (-> the simulated exchange, D-01). ``enabled`` is a persist-only operational flag here.
        if key in _VENUE_FEE_SLIPPAGE_KEYS:
            self._execution_handler.update_config({key: value})

    def _apply_portfolio(self, pid: str, key: str, value: Any, now: datetime) -> None:
        """``portfolio:{id}`` scope -> the resolved Portfolio's OWN bound store (D-21/D-25).

        Resolves the target ``Portfolio`` via ``portfolio_handler.get_portfolio(id)`` — an unknown
        id raises ``PortfolioNotFoundError`` -> default-deny reject (no persist, no apply). The key
        is resolved to its owning ``PortfolioConfig`` section (``limits`` / ``risk_management`` /
        ``trading_rules``) by introspecting the live model structure (D-12). Dry-validates the
        candidate config (mirrors ``Portfolio.update_config``) so nothing persists on invalid
        input, persists to the Portfolio's OWN ``state_storage.save_config`` (already
        portfolio_id-scoped — NOT SystemStore, NO id-keying), then applies via
        ``portfolio.update_config`` (recursive_merge -> validate -> atomic-swap push, D-01).
        """
        try:
            portfolio_id = PortfolioId(uuid.UUID(pid))
        except (ValueError, AttributeError, TypeError) as exc:
            raise _RejectedUpdate(_REASON_UNKNOWN_PORTFOLIO) from exc

        try:
            portfolio = self._portfolio_handler.get_portfolio(portfolio_id)
        except PortfolioNotFoundError as exc:
            raise _RejectedUpdate(_REASON_UNKNOWN_PORTFOLIO) from exc

        section = self._resolve_portfolio_section(portfolio.config, key)
        if section is None:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)
        update = {section: {key: value}}

        # Dry-validate the merged candidate (D-13/D-15) — nothing persists on invalid input.
        try:
            validated = PortfolioConfig.model_validate(
                recursive_merge(portfolio.config.model_dump(), update)
            )
        except pydantic.ValidationError as exc:
            raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc

        # PERSIST — the Portfolio's OWN bound portfolio store (already portfolio_id-scoped).
        self._persist(
            lambda: portfolio.state_storage.save_config(
                validated.model_dump(mode="json"), now
            )
        )

        # APPLY + PUSH — Portfolio.update_config does recursive_merge -> validate -> atomic swap (D-01).
        portfolio.update_config(update)

    # -- Helpers -----------------------------------------------------------------------------

    @staticmethod
    def _resolve_portfolio_section(config: PortfolioConfig, key: str) -> Optional[str]:
        """The mutable ``PortfolioConfig`` section owning ``key`` (D-12 structural allowlist).

        Introspects the live sub-model ``model_fields`` so the routable-key set can never drift
        from the model. Returns ``None`` (default-deny) when no mutable section owns the key.
        """
        for section in _PORTFOLIO_MUTABLE_SECTIONS:
            section_model = getattr(config, section)
            if key in type(section_model).model_fields:
                return section
        return None

    @staticmethod
    def _dry_validate_copy(sub_model: Any, key: str, value: Any) -> Any:
        """Dry-validate ``value`` against ``sub_model.key`` on a throwaway copy; return the copy.

        The copy's ``validate_assignment=True`` re-runs the field's coercion + ``Field(...)``
        constraints WITHOUT touching the live object (D-13/D-15 — validate before persist). Raises
        ``_RejectedUpdate(validation-failed)`` on a bad type/range. Returns the validated candidate
        copy so callers can read the coerced field (``getattr(candidate, key)``) or dump the whole
        record (``candidate.model_dump(...)``) — the shared setattr-on-copy path for the ``system``
        and ``order`` scopes (``portfolio`` deliberately uses a whole-model merge-validate instead).
        """
        candidate = sub_model.model_copy()
        try:
            setattr(candidate, key, value)
        except pydantic.ValidationError as exc:
            raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc
        return candidate

    @staticmethod
    def _persist(write: Callable[[], None]) -> None:
        """Run the owning store's write; a persist failure rejects (D-15 — apply NOTHING live)."""
        try:
            write()
        except _RejectedUpdate:
            raise
        except Exception as exc:  # noqa: BLE001 — any store failure is a persist rejection (D-15)
            raise _RejectedUpdate(_REASON_PERSIST_FAILED) from exc

    def _surface_rejection(
        self, event: ConfigUpdateEvent, reason: str, now: datetime
    ) -> None:
        """Record ``last_error`` + emit a deduped WARNING ``ErrorEvent`` (D-16). Applies nothing.

        The min-interval dedup (P7 ``warn_min_interval_s`` pattern) throttles a rejected-update
        flood off the injected clock. Only FIXED literals + the (non-secret) scope/key are bound —
        the ``value`` (the sole secret-carrying field, V7) is NEVER stringified into the log/event.
        """
        self.last_error = reason
        self.logger.warning(
            "ConfigUpdate rejected (scope=%s, key=%s, reason=%s)",
            event.scope,
            event.key,
            reason,
        )
        if (
            self._last_warn is not None
            and (now - self._last_warn).total_seconds() < self._warn_min_interval_s
        ):
            return
        self._last_warn = now
        self._bus.put(
            ErrorEvent(
                time=now,
                source=_ERROR_SOURCE,
                error_type=_ERROR_TYPE,
                error_message=_ERROR_MESSAGE,
                operation=_ERROR_OPERATION,
                severity=ErrorSeverity.WARNING,
                details={"scope": event.scope, "key": event.key, "reason": reason},
            )
        )
