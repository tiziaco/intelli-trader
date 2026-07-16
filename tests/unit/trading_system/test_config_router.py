"""ConfigRouter runtime-mutation tests (RTCFG-02/04/05, Plan 09-02).

Constructs ``ConfigRouter`` with fakes/doubles (a fresh ``ITraderConfig``, per-module store
doubles capturing every persist, handler doubles spying ``update_config``, a fake
``portfolio_handler`` whose ``get_portfolio`` resolves a fake Portfolio for a known id and raises
``PortfolioNotFoundError`` for an unknown id, a configurable venue-kind resolver, an injected clock,
and a fake bus recording every emitted ``ErrorEvent``) and pins the D-11..D-16 / D-21 / D-25
contract:

  (a) happy path — a known (scope,key) routes validate -> persist -> apply -> push in that order;
  (b) default-deny — an unknown scope and an unknown key each reject with no persist + WARNING;
  (c) ``-k venue_kind`` — a live-venue fee/slippage update rejects, a simulated-venue one applies;
  (d) validation failure — an out-of-range value rejects with no persist (D-13);
  (e) persist failure — a store double that raises rejects and applies NOTHING live (D-15);
  (f) idempotency — applying the same event twice leaves ONE persisted record + the same value;
  (g) immutable-key default-deny — ``rng_seed`` / ``environment`` have no routable key (RTCFG-04);
  (h) ``-k portfolio`` — the portfolio:{id} scope persists to the resolved Portfolio's OWN store +
      pushes ``update_config``; an unknown id is default-deny rejected (D-21/D-25 blocker coverage);
  (i) ``-k scope_owner_table`` — an enumerated walk of the full D-21/D-25 scope->OWNING-store table
      asserting each scope persists into its OWN store, and order/portfolio NEVER into SystemStore.

Fully offline: no ``LiveTradingSystem``, no venue, no network. Package-less test dir (no
``__init__.py``) to avoid the full-suite package collision. Folder-derived ``unit`` marker.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, List, Optional

import pytest
from sqlalchemy.exc import SQLAlchemyError

from itrader.config.itrader_config import ITraderConfig
from itrader.config.merge import deep_merge
from itrader.config.portfolio import PortfolioConfig
from itrader.core.enums import ErrorSeverity, MarketExecution
from itrader.core.exceptions import ValidationError
from itrader.core.exceptions.base import ConfigurationError
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.core.ids import PortfolioId
from itrader.events_handler.events import ConfigUpdateEvent, ErrorEvent
from itrader.trading_system.config_router import ConfigRouter

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------------------------


class _FakeClock:
    """An injected, hand-advanced clock — the determinism seam (never wall clock)."""

    def __init__(self, start: datetime) -> None:
        self._t = start

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)


class _FakeBus:
    """A minimal bus recording every ``put`` (the WARNING ErrorEvent egress)."""

    def __init__(self) -> None:
        self.events: List[Any] = []

    def put(self, event: Any) -> None:
        self.events.append(event)

    @property
    def warnings(self) -> List[ErrorEvent]:
        return [
            e
            for e in self.events
            if isinstance(e, ErrorEvent) and e.severity is ErrorSeverity.WARNING
        ]


class _SystemStoreDouble:
    """SystemStore ``upsert(key, value, at)`` double — cardinality-1 KV by natural key."""

    def __init__(self, call_log: List[str]) -> None:
        self._log = call_log
        self.rows: dict[str, Any] = {}
        self.upsert_count = 0

    def upsert(self, key: str, value: dict[str, Any], at: datetime) -> None:
        self._log.append("persist:system")
        self.rows[key] = value  # delete-then-insert -> one row per key
        self.upsert_count += 1


class _ConfigStoreDouble:
    """A per-module config-store double capturing ``save_config(config, at)`` (order/portfolio)."""

    def __init__(self, call_log: List[str], label: str, *, raises: bool = False) -> None:
        self._log = call_log
        self._label = label
        self._raises = raises
        self.saved: Optional[dict[str, Any]] = None  # single logical row (cardinality-1)
        self.save_count = 0

    def save_config(self, config: dict[str, Any], at: datetime) -> None:
        if self._raises:
            raise RuntimeError("save_config boom")
        self._log.append(f"persist:{self._label}")
        self.saved = config  # upsert -> ONE row (overwrite)
        self.save_count += 1


class _VenueStoreDouble:
    """VenueStore ``get`` / ``upsert`` double with the recursive secret-denylist guard (V7)."""

    _SECRET_KEYS = frozenset({"api_key", "secret", "password", "passphrase", "token"})

    def __init__(self, call_log: List[str]) -> None:
        self._log = call_log
        self.rows: dict[str, dict[str, Any]] = {}
        self.upsert_count = 0

    def get(self, venue_name: str) -> Optional[dict[str, Any]]:
        return self.rows.get(venue_name)

    def _assert_no_secret_keys(self, node: Any) -> None:
        # V7 defensive arm — recursive denylist (mirrors VenueStore._assert_no_secret_keys):
        # a secret-like key at ANY depth (dicts + lists-of-dicts) is rejected before any write.
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.lower() in self._SECRET_KEYS:
                    raise ValidationError(
                        field="config_json",
                        message="secret-like key is not allowed in venue config",
                    )
                self._assert_no_secret_keys(value)
        elif isinstance(node, list):
            for item in node:
                self._assert_no_secret_keys(item)

    def upsert(
        self, venue_name: str, config: dict[str, Any], enabled: bool, at: datetime
    ) -> None:
        self._assert_no_secret_keys(config)  # fires FIRST — a rejected write persists NOTHING
        self._log.append("persist:venue")
        self.rows[venue_name] = {
            "venue_name": venue_name,
            "config": config,
            "enabled": enabled,
        }
        self.upsert_count += 1


class _HandlerSpy:
    """A push-target double spying ``update_config`` (execution / order handlers, D-01).

    Also spies the CR-02 dry-validation twin ``validate_config`` (the pre-persist venue
    fee/slippage validator). ``validate_raises=True`` makes it reject like the real
    ``execution_handler.validate_config`` on a bad value (``ConfigurationError``), so a test
    can assert nothing persists BEFORE the validating push.
    """

    def __init__(self, call_log: List[str], label: str) -> None:
        self._log = call_log
        self._label = label
        self.updates: List[dict[str, Any]] = []
        self.validate_calls: List[dict[str, Any]] = []
        self.validate_raises = False
        self.storage: Any = None  # order handler carries its store here

    def update_config(self, updates: dict[str, Any]) -> None:
        self._log.append(f"push:{self._label}")
        self.updates.append(updates)

    def validate_config(self, updates: dict[str, Any]) -> None:
        # Dry twin (CR-02): recorded but NOT appended to call_log so the ordering
        # assertions on call_log (persist -> push) stay unchanged for the happy path.
        self.validate_calls.append(updates)
        if self.validate_raises:
            raise ConfigurationError(reason="invalid venue config (test)")


class _FakePortfolio:
    """A fake Portfolio carrying its OWN bound config-store double + an update_config push spy.

    ``update_config`` mirrors the real ``Portfolio.update_config`` contract (deep_merge ->
    model_validate -> atomic swap) so the test can assert the field actually mutated.
    """

    def __init__(self, call_log: List[str], state_storage: _ConfigStoreDouble) -> None:
        self._log = call_log
        self.config = PortfolioConfig.default()
        self.state_storage = state_storage
        self.update_calls: List[dict[str, Any]] = []

    def update_config(self, updates: dict[str, Any]) -> None:
        self._log.append("push:portfolio")
        self.update_calls.append(updates)
        merged = deep_merge(self.config.model_dump(), updates)
        self.config = PortfolioConfig.model_validate(merged)


class _FakePortfolioHandler:
    """A portfolio_handler double resolving a fake Portfolio for a KNOWN id only."""

    def __init__(self, known_id: uuid.UUID, portfolio: _FakePortfolio) -> None:
        self._known_id = known_id
        self._portfolio = portfolio

    def get_portfolio(self, portfolio_id: PortfolioId) -> _FakePortfolio:
        if uuid.UUID(str(portfolio_id)) != self._known_id:
            raise PortfolioNotFoundError(portfolio_id)
        return self._portfolio


# --------------------------------------------------------------------------------------------
# Router bundle fixture
# --------------------------------------------------------------------------------------------


class _Bundle:
    """Holds the router + every double so tests can assert against the owning stores/handlers."""

    def __init__(self, *, venue_simulated: bool = True) -> None:
        self.call_log: List[str] = []
        self.clock = _FakeClock(datetime(2026, 7, 16, tzinfo=UTC))
        self.bus = _FakeBus()
        self.config = ITraderConfig()

        self.system_store = _SystemStoreDouble(self.call_log)
        self.venue_store = _VenueStoreDouble(self.call_log)
        self.order_store = _ConfigStoreDouble(self.call_log, "order")
        self.portfolio_store = _ConfigStoreDouble(self.call_log, "portfolio")

        self.order_handler = _HandlerSpy(self.call_log, "order")
        self.order_handler.storage = self.order_store
        self.execution_handler = _HandlerSpy(self.call_log, "execution")

        self.known_id = uuid.uuid4()
        self.portfolio = _FakePortfolio(self.call_log, self.portfolio_store)
        self.portfolio_handler = _FakePortfolioHandler(self.known_id, self.portfolio)

        self._venue_simulated = venue_simulated
        self.router = ConfigRouter(
            config=self.config,
            system_store=self.system_store,
            venue_store=self.venue_store,
            order_handler=self.order_handler,
            portfolio_handler=self.portfolio_handler,
            execution_handler=self.execution_handler,
            venue_kind=lambda name: self._venue_simulated,
            bus=self.bus,
            clock=self.clock,
        )

    def event(self, scope: str, key: str, value: Any) -> ConfigUpdateEvent:
        return ConfigUpdateEvent(
            time=self.clock.now(), scope=scope, key=key, value=value
        )

    def apply(self, scope: str, key: str, value: Any) -> None:
        self.router.apply(self.event(scope, key, value))


# --------------------------------------------------------------------------------------------
# (a) Happy path — validate -> persist -> apply -> push, in order
# --------------------------------------------------------------------------------------------


def test_happy_path_order_scope_persist_then_apply_then_push() -> None:
    b = _Bundle()

    b.apply("order", "market_execution", "next_bar")

    # persist to the OWNING (order) store, then push — persist BEFORE push (D-15).
    assert b.order_store.saved is not None
    assert b.order_store.saved["market_execution"] == "next_bar"
    assert b.call_log == ["persist:order", "push:order"]
    # the live sub-model field actually mutated (coerced str -> enum member).
    assert b.config.order.market_execution is MarketExecution.NEXT_BAR
    assert b.order_handler.updates == [{"market_execution": "next_bar"}]
    # nothing rejected.
    assert b.bus.warnings == []
    assert b.router.last_error is None


def test_happy_path_system_scope_persists_to_system_store() -> None:
    b = _Bundle()

    b.apply("system", "auto_restart_delay_seconds", 30)

    assert b.system_store.rows["config.system.auto_restart_delay_seconds"] == {"value": 30}
    assert b.config.system.auto_restart_delay_seconds == 30
    assert b.bus.warnings == []


def test_happy_path_universe_key_routes_under_system_scope() -> None:
    b = _Bundle()

    b.apply("system", "remove_policy", "force-close")

    # universe knobs live under the `system` scope but own the config.universe sub-model.
    assert b.system_store.rows["config.universe.remove_policy"] == {"value": "force-close"}
    assert b.config.universe.remove_policy == "force-close"
    assert b.bus.warnings == []


# --------------------------------------------------------------------------------------------
# (b) Default-deny — unknown scope + unknown key
# --------------------------------------------------------------------------------------------


def test_default_deny_unknown_scope_rejects_with_warning_and_no_persist() -> None:
    b = _Bundle()

    b.apply("bogus", "whatever", 1)

    assert b.call_log == []  # nothing persisted, nothing pushed
    assert len(b.bus.warnings) == 1
    assert b.bus.warnings[0].details["reason"] == "unrouted-scope"
    assert b.router.last_error == "unrouted-scope"


def test_default_deny_unknown_key_rejects_with_warning_and_no_persist() -> None:
    b = _Bundle()

    b.apply("order", "not_a_real_field", 1)

    assert b.order_store.save_count == 0
    assert b.order_handler.updates == []
    assert len(b.bus.warnings) == 1
    assert b.bus.warnings[0].details["reason"] == "unknown-key"


def test_mis_cased_scope_is_unrouted_exact_string_match() -> None:
    b = _Bundle()

    b.apply("System", "auto_restart_delay_seconds", 30)  # wrong case

    assert b.call_log == []
    assert b.bus.warnings[0].details["reason"] == "unrouted-scope"


# --------------------------------------------------------------------------------------------
# (c) Venue-kind predicate (RTCFG-05/D-14) — -k venue_kind
# --------------------------------------------------------------------------------------------


def test_venue_kind_live_venue_fee_slippage_rejected() -> None:
    b = _Bundle(venue_simulated=False)

    b.apply("venue:okx", "fee_model", {"type": "percent", "rate": "0.001"})

    assert b.venue_store.upsert_count == 0  # nothing persisted
    assert b.execution_handler.updates == []  # nothing applied live
    assert len(b.bus.warnings) == 1
    assert b.bus.warnings[0].details["reason"] == "venue-kind-live-fee-slippage"


def test_venue_kind_simulated_venue_fee_slippage_applies() -> None:
    b = _Bundle(venue_simulated=True)

    b.apply("venue:paper", "fee_model", {"type": "percent", "rate": "0.001"})

    assert b.venue_store.rows["paper"]["config"]["fee_model"] == {
        "type": "percent",
        "rate": "0.001",
    }
    assert b.execution_handler.updates == [
        {"fee_model": {"type": "percent", "rate": "0.001"}}
    ]
    assert b.call_log == ["persist:venue", "push:execution"]
    assert b.bus.warnings == []


def test_venue_kind_enabled_flag_allowed_regardless_of_kind() -> None:
    b = _Bundle(venue_simulated=False)  # even a live venue can be enabled/disabled

    b.apply("venue:okx", "enabled", False)

    assert b.venue_store.rows["okx"]["enabled"] is False
    assert b.execution_handler.updates == []  # enabled is persist-only, no push
    assert b.bus.warnings == []


def test_venue_fee_slippage_dry_validated_before_persist_on_valid_value() -> None:
    # CR-02: a fee/slippage update is dry-validated (execution_handler.validate_config)
    # BEFORE the persist, then persisted, then pushed.
    b = _Bundle(venue_simulated=True)

    b.apply("venue:paper", "fee_model", {"type": "percent", "rate": "0.001"})

    # the dry twin ran, and the value persisted + pushed.
    assert b.execution_handler.validate_calls == [
        {"fee_model": {"type": "percent", "rate": "0.001"}}
    ]
    assert b.venue_store.upsert_count == 1
    assert b.execution_handler.updates == [
        {"fee_model": {"type": "percent", "rate": "0.001"}}
    ]
    assert b.bus.warnings == []


def test_venue_bad_fee_slippage_rejected_before_persist_not_poisoned() -> None:
    # CR-02 BLOCKER: an invalid fee/slippage value is REJECTED at the pre-persist dry-validate
    # so VenueStore is NEVER poisoned (the poisoned row would brick the next boot's layering).
    b = _Bundle(venue_simulated=True)
    b.execution_handler.validate_raises = True  # the real validate_config would raise

    b.apply("venue:paper", "slippage_model", {"type": "bogus"})

    # the dry twin was consulted, then the update was rejected BEFORE any persist/push.
    assert b.execution_handler.validate_calls == [{"slippage_model": {"type": "bogus"}}]
    assert b.venue_store.upsert_count == 0  # NOTHING persisted — store not poisoned
    assert "paper" not in b.venue_store.rows
    assert b.execution_handler.updates == []  # nothing pushed live
    assert b.bus.warnings[0].details["reason"] == "validation-failed"
    assert b.router.last_error == "validation-failed"


def test_venue_enabled_non_bool_string_rejected_not_truthy_enabled() -> None:
    # WR-01: bool("false") is True — a non-bool ``enabled`` value must be REJECTED, never
    # silently enabling the venue the caller meant to disable.
    b = _Bundle(venue_simulated=True)

    b.apply("venue:paper", "enabled", "false")

    assert b.venue_store.upsert_count == 0  # nothing persisted
    assert "paper" not in b.venue_store.rows
    assert b.bus.warnings[0].details["reason"] == "validation-failed"


def test_venue_enabled_real_bool_still_applies() -> None:
    # WR-01 regression guard: a genuine bool still works.
    b = _Bundle(venue_simulated=True)

    b.apply("venue:paper", "enabled", False)

    assert b.venue_store.rows["paper"]["enabled"] is False
    assert b.bus.warnings == []


def test_unexpected_store_read_error_surfaced_as_deduped_warning_not_escape() -> None:
    # WR-02: a store-read error OUTSIDE _persist (the venue get) must be converted into a
    # deduped WARNING rejection, not escape apply() to the engine-boundary error policy.
    b = _Bundle(venue_simulated=True)

    def _boom(_name: str) -> None:
        raise SQLAlchemyError("venue get boom")

    b.venue_store.get = _boom  # type: ignore[method-assign]

    b.apply("venue:paper", "enabled", True)  # get() is called before persist

    assert b.venue_store.upsert_count == 0
    assert b.bus.warnings[0].details["reason"] == "apply-failed"
    assert b.router.last_error == "apply-failed"


def test_venue_secret_value_rejected_by_store_no_apply() -> None:
    # V7 secret-scrub: a credential-carrying value is rejected at the write boundary; the router
    # surfaces it as a persist failure and applies NOTHING live.
    b = _Bundle(venue_simulated=True)

    b.apply("venue:paper", "fee_model", {"api_key": "leak-me"})

    assert b.venue_store.upsert_count == 0
    assert b.execution_handler.updates == []
    assert b.bus.warnings[0].details["reason"] == "persist-failed"


# --------------------------------------------------------------------------------------------
# (d) Validation failure — out-of-range value rejects with no persist (D-13)
# --------------------------------------------------------------------------------------------


def test_validation_failure_rejects_before_persist() -> None:
    b = _Bundle()

    # poll_cadence_s has gt=0.0 — a negative value fails validate_assignment.
    b.apply("system", "poll_cadence_s", -5.0)

    assert b.system_store.upsert_count == 0  # nothing persisted
    assert b.config.universe.poll_cadence_s == 60.0  # live value untouched
    assert b.bus.warnings[0].details["reason"] == "validation-failed"


def test_validation_failure_wrong_type_rejects() -> None:
    b = _Bundle()

    b.apply("system", "auto_restart_delay_seconds", "not-an-int")

    assert b.system_store.upsert_count == 0
    assert b.bus.warnings[0].details["reason"] == "validation-failed"


# --------------------------------------------------------------------------------------------
# (e) Persist failure — rejects and applies NOTHING live (D-15)
# --------------------------------------------------------------------------------------------


def test_persist_failure_rejects_and_applies_nothing() -> None:
    b = _Bundle()
    b.order_store._raises = True  # save_config raises

    b.apply("order", "market_execution", "next_bar")

    # config NOT mutated, push NOT called, WARNING emitted.
    assert b.config.order.market_execution is MarketExecution.IMMEDIATE
    assert b.order_handler.updates == []
    assert b.bus.warnings[0].details["reason"] == "persist-failed"


# --------------------------------------------------------------------------------------------
# (f) Idempotency — applying the same event twice leaves ONE row + the same value
# --------------------------------------------------------------------------------------------


def test_idempotency_same_event_twice_one_row_same_value() -> None:
    b = _Bundle()

    b.apply("order", "market_execution", "next_bar")
    b.apply("order", "market_execution", "next_bar")

    # ONE logical row (cardinality-1 upsert overwrite); the field value is stable.
    assert b.order_store.saved == {"market_execution": "next_bar"}
    assert b.config.order.market_execution is MarketExecution.NEXT_BAR
    assert b.bus.warnings == []


# --------------------------------------------------------------------------------------------
# (g) Immutable-key default-deny — rng_seed / environment (RTCFG-04)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["rng_seed", "environment", "name", "debug_mode"])
def test_immutable_base_key_has_no_routable_scope(key: str) -> None:
    # Frozen-base keys are not fields on any mutable sub-model -> no routable (scope,key) exists,
    # so default-deny rejects them structurally (RTCFG-04).
    b = _Bundle()

    b.apply("system", key, 999)

    assert b.system_store.upsert_count == 0
    assert b.bus.warnings[0].details["reason"] == "unknown-key"


# --------------------------------------------------------------------------------------------
# (h) portfolio:{id} scope (BLOCKER coverage, D-21/D-25) — -k portfolio
# --------------------------------------------------------------------------------------------


def test_portfolio_scope_known_id_persists_to_own_store_and_pushes() -> None:
    b = _Bundle()

    b.apply(f"portfolio:{b.known_id}", "max_positions", 10)

    # persisted to the resolved Portfolio's OWN bound store (NOT the system_store), then pushed.
    assert b.portfolio_store.save_count == 1
    assert b.portfolio_store.saved is not None
    assert b.portfolio_store.saved["limits"]["max_positions"] == 10
    assert b.system_store.upsert_count == 0  # NEVER SystemStore (D-21/D-25)
    assert b.call_log == ["persist:portfolio", "push:portfolio"]
    # the resolved Portfolio's update_config push applied the change to its live config.
    assert b.portfolio.config.limits.max_positions == 10
    assert b.portfolio.update_calls == [{"limits": {"max_positions": 10}}]
    assert b.bus.warnings == []


def test_portfolio_scope_unknown_id_default_deny_rejected() -> None:
    b = _Bundle()
    unknown_id = uuid.uuid4()

    b.apply(f"portfolio:{unknown_id}", "max_positions", 10)

    assert b.portfolio_store.save_count == 0  # no persist
    assert b.portfolio.update_calls == []  # no apply
    assert b.bus.warnings[0].details["reason"] == "unknown-portfolio"


def test_portfolio_scope_risk_and_sizing_sections_resolve() -> None:
    b = _Bundle()

    # risk_management section key
    b.apply(f"portfolio:{b.known_id}", "max_risk_per_trade", 0.01)
    # trading_rules section key
    b.apply(f"portfolio:{b.known_id}", "min_trade_amount", "250.0")

    assert b.portfolio.config.risk_management.max_risk_per_trade == 0.01
    assert str(b.portfolio.config.trading_rules.min_trade_amount) == "250.0"
    assert b.bus.warnings == []


# --------------------------------------------------------------------------------------------
# (i) scope_owner_table — every scope persists into its OWN store, never SystemStore
# --------------------------------------------------------------------------------------------


def test_scope_owner_table_each_scope_persists_to_its_own_store() -> None:
    b = _Bundle()

    # system -> SystemStore
    b.apply("system", "auto_restart_delay_seconds", 30)
    assert b.system_store.upsert_count == 1

    # order -> the ORDER store (save_config), NOT SystemStore
    b.apply("order", "market_execution", "next_bar")
    assert b.order_store.save_count == 1

    # venue:{name} -> VenueStore
    b.apply("venue:paper", "enabled", True)
    assert b.venue_store.upsert_count == 1

    # portfolio:{id} -> the resolved Portfolio's OWN bound store, NOT SystemStore
    b.apply(f"portfolio:{b.known_id}", "max_positions", 10)
    assert b.portfolio_store.save_count == 1

    # NEGATIVE: order + portfolio config NEVER centralize into SystemStore (D-21/D-25).
    assert b.system_store.upsert_count == 1  # ONLY the system-scope write landed there
    assert b.bus.warnings == []


@pytest.mark.parametrize(
    "scope, key, value",
    [
        ("system", "auto_restart_delay_seconds", 30),
        ("order", "market_execution", "next_bar"),
        ("venue:paper", "enabled", True),
    ],
)
def test_scope_owner_table_order_and_venue_never_touch_system_store(
    scope: str, key: str, value: Any
) -> None:
    b = _Bundle()

    b.apply(scope, key, value)

    if scope == "system":
        assert b.system_store.upsert_count == 1
    else:
        assert b.system_store.upsert_count == 0  # non-system scopes never write SystemStore
    assert b.bus.warnings == []
