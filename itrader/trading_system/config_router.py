"""Engine-thread runtime-config router for ``ConfigUpdateEvent``.

Runs entirely on the engine thread: a dequeued ``ConfigUpdateEvent(scope, key, value)`` is
routed by a default-deny scope->owner dispatch, validated by Pydantic ``validate_assignment``
/ ``model_validate``, persisted to the owning module's store, then applied to the live mutable
config sub-model and pushed through the owning handler's ``update_config(...)``. Ordering is
validate -> persist -> apply: a persist failure rejects and applies nothing live, so the store
and the in-memory config can never diverge in the applied-but-not-persisted direction.

There is no standalone allowlist artifact: the FROZEN ``ITraderConfig`` base blocks immutable
determinism/identity keys structurally (they are not fields on any mutable sub-model, so no
routable scope/key exists for them), and each target sub-model's ``model_fields``
(introspected, not hardcoded) IS the per-scope key allowlist — it can never drift from the
model it allows.

Each scope persists to its OWNING module's store, never centralized (see the scope -> store
map in the ``__init__`` Parameters below). The config object itself is a plain engine-thread-
owned mutable value with a single writer and a single live reader, both on this thread, so no
copy-on-write / atomic-swap snapshot machinery is needed.
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
from itrader.config.portfolio import IMMUTABLE_PORTFOLIO_CONFIG_KEYS, PortfolioConfig
from itrader.config.system import SystemSettings
from itrader.config.universe import UniverseConfig
from itrader.core.clock import Clock
from itrader.core.enums import ErrorSeverity
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import (
    ImmutableConfigKeyError,
    PortfolioNotFoundError,
)
from itrader.core.ids import PortfolioId
from itrader.events_handler.events import ConfigUpdateEvent, ErrorEvent
from itrader.logger import get_itrader_logger

# --- Rejection reason categories: fixed literals, never derived from the value --------------
_REASON_UNROUTED_SCOPE = "unrouted-scope"
_REASON_UNKNOWN_KEY = "unknown-key"
_REASON_UNKNOWN_PORTFOLIO = "unknown-portfolio"
_REASON_VALIDATION_FAILED = "validation-failed"
_REASON_VENUE_KIND = "venue-kind-live-fee-slippage"
_REASON_PERSIST_FAILED = "persist-failed"
# A real field on a mutable section that is deliberately not runtime-mutable — distinct
# from ``unknown-key`` (no such field on the model at all).
_REASON_IMMUTABLE_KEY = "immutable-key"
# A store-read / handler-push / model-validate failure that escaped the per-scope guards
# (not a ``_RejectedUpdate``) — surfaced as a deduped WARNING rejection, never an escape.
_REASON_APPLY_FAILED = "apply-failed"

# --- WARNING ErrorEvent fixed egress literals (same dedup pattern as PreTradeThrottle) -------
_ERROR_SOURCE = "config_router"
_ERROR_TYPE = "ConfigUpdateRejected"
_ERROR_MESSAGE = "runtime config update rejected"
_ERROR_OPERATION = "config_update"

# --- Venue-scope allowlist --------------------------------------------------------------------
_VENUE_FEE_SLIPPAGE_KEYS = frozenset({"fee_model", "slippage_model"})
_VENUE_KEYS = frozenset({"fee_model", "slippage_model", "enabled"})

# --- Portfolio-scope mutable sections: the risk limits + sizing defaults ---------------------
_PORTFOLIO_MUTABLE_SECTIONS = ("limits", "risk_management", "trading_rules")


class _RejectedUpdate(Exception):
    """Internal default-deny signal — carries a FIXED reason category (never the value)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ConfigRouter:
    """Engine-thread router: validate -> persist -> apply -> push, default-deny dispatch.

    Each scope's persistence target is its OWNING module store, never centralized into
    SystemStore — see the scope -> store mapping below.

    Parameters
    ----------
    config:
        The process ``ITraderConfig`` singleton — the live mutable apply target. The FROZEN
        base blocks immutable keys structurally; the router setattrs only the mutable
        sub-models.
    system_store:
        ``SystemStore`` — the ``system`` scope persist target ONLY. ``upsert(key, value, at)``
        with a namespaced ``config.<sub>.<field>`` key.
    venue_store:
        ``VenueStore`` — the ``venue:{name}`` scope persist target. ``upsert(venue_name, config,
        enabled, at)`` with a recursive secret-denylist guard.
    order_handler:
        The order handler; ``order_handler.storage.save_config`` is the ``order`` scope persist
        target (the ORDER store, NOT SystemStore) and ``order_handler.update_config`` the push.
    portfolio_handler:
        The portfolio handler; ``get_portfolio(id)`` resolves the target ``Portfolio`` (unknown id
        -> ``PortfolioNotFoundError`` -> default-deny). Each Portfolio owns its bound
        ``state_storage.save_config`` (the portfolio scope persist target) + ``update_config`` push.
    execution_handler:
        The venue-scope push target for fee/slippage on a simulated venue (``update_config`` ->
        the simulated exchange).
    venue_kind:
        A resolver ``(venue_name) -> bool`` — ``True`` when the venue's execution arm is a
        ``SimulatedExchange`` (fee/slippage runtime-mutable), ``False`` for a live venue (reject).
    bus:
        The event bus; only ``.put`` is used, to emit the deduped WARNING ``ErrorEvent`` on
        rejection.
    clock:
        The injected determinism clock (``now()``) — the persist ``at`` + the WARNING dedup read
        (never wall clock).
    warn_min_interval_s:
        The min-interval (seconds) between WARNING ErrorEvent emissions (default 5.0).
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
        # Last WARNING emission time (injected clock) for the min-interval dedup.
        self._last_warn: Optional[datetime] = None
        # Last rejection reason, exposed for read-model / diagnostic access.
        self.last_error: Optional[str] = None

    # -- Public entry ------------------------------------------------------------------------

    def apply(self, event: ConfigUpdateEvent) -> None:
        """Route + apply one ``ConfigUpdateEvent`` (validate -> persist -> apply -> push).

        Scope matching is EXACT-string (no case-folding / no normalization) — a mis-cased or
        differently-encoded scope is unrouted and rejected. Any rejection surfaces a deduped
        WARNING ``ErrorEvent`` and applies nothing live.
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
        except ImmutableConfigKeyError:
            # ``ImmutableConfigKeyError`` is a ``PortfolioError``, not a ``_RejectedUpdate`` —
            # without this arm it would escape ``apply()`` to the engine error boundary, turning
            # a refused operator knob into a handler-error/live ErrorEvent instead of the same
            # deduped WARNING rejection every other default-deny gets.
            self._surface_rejection(event, _REASON_IMMUTABLE_KEY, now)
        except (SQLAlchemyError, ConfigurationError, pydantic.ValidationError) as exc:
            # A known store-read / handler-push / model-validate failure that escaped the
            # per-scope guards is converted into the same deduped WARNING rejection rather than
            # escaping to the engine-boundary error policy. Not a bare ``except Exception`` — a
            # genuine programming error (AttributeError/TypeError) still surfaces.
            self.logger.warning(
                "ConfigUpdate store/push error (scope=%s, key=%s): %s",
                event.scope, event.key, exc)
            self._surface_rejection(event, _REASON_APPLY_FAILED, now)

    # -- Scope handlers (each owns the full validate -> persist -> apply ordering) ------------

    def _apply_system(self, key: str, value: Any, now: datetime) -> None:
        """``system`` scope -> SystemStore. Idle/timeout knobs + universe knobs.

        The owning sub-model is resolved by introspecting the live model structure: a key on
        ``SystemSettings`` owns ``config.system``; a key on ``UniverseConfig`` owns
        ``config.universe``; any other key is default-deny rejected. There is no dedicated
        push handler here — the universe poll timer and lifecycle logic read
        ``config.<sub>.<field>`` live off the single mutable object, so the apply step is the
        ``setattr`` alone.
        """
        if key in SystemSettings.model_fields:
            sub_attr = "system"
        elif key in UniverseConfig.model_fields:
            sub_attr = "universe"
        else:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        sub_model = getattr(self._config, sub_attr)
        coerced = getattr(self._dry_validate_copy(sub_model, key, value), key)

        # PERSIST — namespaced KV key on the SYSTEM store (system-global config only).
        self._persist(
            lambda: self._system_store.upsert(
                f"config.{sub_attr}.{key}", {"value": coerced}, now
            )
        )

        # APPLY — setattr the live mutable sub-model (re-validates; cheap/idempotent).
        setattr(sub_model, key, value)

    def _apply_order(self, key: str, value: Any, now: datetime) -> None:
        """``order`` scope -> the ORDER store, NOT SystemStore.

        ``OrderConfig`` carries ``market_execution`` only; a non-field key is default-deny
        rejected rather than fabricated — no speculative trail/TIF field is invented to widen
        the allowlist. Persists the coerced OrderConfig record via the order store's
        ``save_config`` and pushes the change through ``order_handler.update_config``.
        """
        if key not in OrderConfig.model_fields:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        # Dry-validate a throwaway copy so nothing persists on invalid input.
        candidate = self._dry_validate_copy(self._config.order, key, value)

        # PERSIST — the single global OrderConfig record on the ORDER store.
        self._persist(
            lambda: self._order_handler.storage.save_config(
                candidate.model_dump(mode="json"), now
            )
        )

        # APPLY + PUSH — mutate the live sub-model, then the owning handler's push.
        setattr(self._config.order, key, value)
        self._order_handler.update_config({key: value})

    def _apply_venue(self, venue_name: str, key: str, value: Any, now: datetime) -> None:
        """``venue:{name}`` scope -> VenueStore. Fee/slippage gated by the venue-kind predicate.

        ``fee_model`` / ``slippage_model`` are runtime-mutable only for a simulated venue — a
        live venue's fee/slippage is rejected, since real-venue fees come from actual fills, not
        engine config. ``enabled`` is allowed regardless of venue kind. The secret-scrub is
        enforced inside ``VenueStore.upsert``: a credential-carrying value is rejected at the
        write boundary and surfaces here as a persist failure (nothing applied).
        """
        if key not in _VENUE_KEYS:
            raise _RejectedUpdate(_REASON_UNKNOWN_KEY)

        # ``enabled`` is a real boolean flag, not a truthy coercion: a non-bool value (e.g. the
        # string "false", which ``bool(...)`` would evaluate to True and silently enable a venue
        # the caller meant to disable) is rejected before any persist.
        if key == "enabled" and not isinstance(value, bool):
            raise _RejectedUpdate(_REASON_VALIDATION_FAILED)

        if key in _VENUE_FEE_SLIPPAGE_KEYS and not self._venue_kind(venue_name):
            raise _RejectedUpdate(_REASON_VENUE_KIND)

        # DRY-validate the fee/slippage value before persisting. ``execution_handler.update_config``
        # is the only validator of a venue fee/slippage value; running its dry twin first means
        # an invalid value never lands in VenueStore — a poisoned row would otherwise brick the
        # next boot's config layering.
        if key in _VENUE_FEE_SLIPPAGE_KEYS:
            try:
                self._execution_handler.validate_config({key: value})
            except ConfigurationError as exc:
                raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc

        # Merge onto the existing persisted venue row so a single-field update does not drop
        # the sibling config keys / enabled flag (last-writer-wins per field).
        existing = self._venue_store.get(venue_name)
        config: dict[str, Any] = dict(existing["config"]) if existing else {}
        enabled: bool = bool(existing["enabled"]) if existing else True
        if key == "enabled":
            enabled = value  # already checked to be a real bool
        else:
            config[key] = value

        # PERSIST — VenueStore.upsert runs its recursive secret-denylist guard first.
        self._persist(
            lambda: self._venue_store.upsert(venue_name, config, enabled, now)
        )

        # APPLY + PUSH — a simulated-venue fee/slippage change pushes to the execution handler.
        # ``enabled`` is a persist-only operational flag with no push here.
        if key in _VENUE_FEE_SLIPPAGE_KEYS:
            self._execution_handler.update_config({key: value})

    def _apply_portfolio(self, pid: str, key: str, value: Any, now: datetime) -> None:
        """``portfolio:{id}`` scope -> the resolved Portfolio's OWN bound store, NOT SystemStore.

        Resolves the target ``Portfolio`` via ``portfolio_handler.get_portfolio(id)`` — an unknown
        id raises ``PortfolioNotFoundError`` -> default-deny reject (no persist, no apply). The key
        is resolved to its owning ``PortfolioConfig`` section (``limits`` / ``risk_management`` /
        ``trading_rules``) by introspecting the live model structure. Dry-validates the candidate
        config so nothing persists on invalid input, persists to the Portfolio's own
        ``state_storage.save_config`` (already portfolio_id-scoped), then applies via
        ``portfolio.update_config``.

        A key in ``IMMUTABLE_PORTFOLIO_CONFIG_KEYS`` is refused FIRST — before the id resolves,
        before any store is read, and before any merge — so nothing is even partially applied.
        The check is KEY-scoped, not section-scoped: ``trading_rules`` stays in
        ``_PORTFOLIO_MUTABLE_SECTIONS`` and every other field in it stays routable — banning the
        whole section would freeze fields nobody asked to freeze.
        """
        # Checked before id resolution because immutability is a property of the KEY, not of
        # the addressed portfolio. ``_resolve_portfolio_section`` keeps returning ``None`` for
        # default-deny rather than raising.
        if key in IMMUTABLE_PORTFOLIO_CONFIG_KEYS:
            raise ImmutableConfigKeyError(key=key, scope=f"portfolio:{pid}")

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

        # Dry-validate the merged candidate — nothing persists on invalid input.
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

        # APPLY + PUSH — delegates to ``Portfolio.update_config``.
        portfolio.update_config(update)

    # -- Helpers -----------------------------------------------------------------------------

    @staticmethod
    def _resolve_portfolio_section(config: PortfolioConfig, key: str) -> Optional[str]:
        """The mutable ``PortfolioConfig`` section owning ``key``.

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

        The copy's ``validate_assignment=True`` re-runs the field's coercion and ``Field(...)``
        constraints without touching the live object. Raises
        ``_RejectedUpdate(validation-failed)`` on a bad type/range. Returns the validated
        candidate so callers can read the coerced field (``getattr(candidate, key)``) or dump
        the whole record (``candidate.model_dump(...)``) — the shared setattr-on-copy path for
        the ``system`` and ``order`` scopes (``portfolio`` deliberately uses a whole-model
        merge-validate instead).
        """
        candidate = sub_model.model_copy()
        try:
            setattr(candidate, key, value)
        except pydantic.ValidationError as exc:
            raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc
        return candidate

    @staticmethod
    def _persist(write: Callable[[], None]) -> None:
        """Run the owning store's write; a persist failure rejects so nothing applies live."""
        try:
            write()
        except _RejectedUpdate:
            raise
        except Exception as exc:  # noqa: BLE001 — any store failure is a persist rejection
            raise _RejectedUpdate(_REASON_PERSIST_FAILED) from exc

    def _surface_rejection(
        self, event: ConfigUpdateEvent, reason: str, now: datetime
    ) -> None:
        """Record ``last_error`` and emit a deduped WARNING ``ErrorEvent``. Applies nothing.

        The min-interval dedup throttles a rejected-update flood off the injected clock. Only
        fixed literals and the (non-secret) scope/key are bound — the ``value`` (the sole
        secret-carrying field) is never stringified into the log or the event.
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
