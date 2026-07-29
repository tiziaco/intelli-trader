"""The live restart bootstrap — the boot contract as a module, not a region of the root.

Turning a durable database back into a running engine has a load-bearing ORDER, and until
now that order existed only as a run of statements in the middle of a 1,577-line builder,
where nothing named it and nothing could test it in isolation. This module is that
sequence, extracted verbatim:

  1. **Probe for the ``portfolios`` table.** A not-yet-provisioned table is the first-start
     state, NOT a fault. The probe is deliberately narrow — it asks for the TABLE and
     nothing else — so a genuine store fault still propagates LOUD instead of degrading
     into a silent zero-portfolio boot.
  2. **Assert distinct accounts**, before any account exists, so a collision is refused
     rather than half-applied.
  3. **Bring every enabled account online**, from the durable rows. The account SET is
     store-derived; no account identity is computed here.
  4. **Rehydrate portfolios** with their PERSISTED ids, so portfolio-scoped child tables
     and strategy-subscription rows reattach to portfolios that still exist.

**Step 3 before step 4 is a hard dependency, not a style choice.** Assembly must precede
rehydrate so the account manager's online set is full when rehydrate materializes each
row; otherwise a portfolio naming a not-provisioned, disabled or not-online account
silently sits on a compute leaf instead of raising.

**Failure isolation, as it stands today.** The bring-up loop has NO per-row quarantine — a
single row's fault propagates and aborts the boot. That is the CURRENT behaviour and it is
preserved here unchanged; per-row quarantine is a later, deliberate change, not something
this extraction smuggles in.

``layer_persisted_overrides`` lives here as the other half of the restart contract
(``defaults <- env <- persisted``). It is called from a LATER point in the build than
``bootstrap_session`` — after the facade and the config router exist — so it stays a
separate function rather than a step of the sequence above.

Indentation: 4-space. Strict-typed, and deliberately NOT covered by any mypy
``ignore_errors`` override.
"""

from __future__ import annotations

from typing import Any

import pydantic
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError

from itrader.config.order import OrderConfig
from itrader.config.system import SystemSettings
from itrader.config.universe import UniverseConfig
from itrader.core.exceptions.base import ConfigurationError
from itrader.logger import get_itrader_logger
from itrader.portfolio_handler.rehydrate.distinct_account_invariant import (
    assert_distinct_accounts,
)
from itrader.portfolio_handler.rehydrate.portfolio_rehydrate import rehydrate_portfolios

# A bad persisted override is logged and skipped rather than crashing boot, and one bad
# scope never aborts the others. Deliberately NOT a bare ``Exception``: a genuine
# programming error must still surface.
_DEGRADE_CLEAN = (
    SQLAlchemyError, ConfigurationError, pydantic.ValidationError, ValueError)


def bootstrap_session(
    *,
    sql_engine: Any,
    venue_manager: Any,
    portfolio_handler: Any,
    execution_venue: str,
) -> dict[str, Any]:
    """Turn the durable state into online accounts and rehydrated portfolios.

    Parameters
    ----------
    sql_engine : Any
        The shared ``SqlEngine`` spine, or ``None`` on the in-memory arm. ``None`` means
        there is no durable state to restore, so the whole sequence is skipped and a boot
        comes up RUNNING and empty rather than failing.
    venue_manager : Any
        The venue-ACCOUNT domain owner. Supplies the enabled rows and performs each
        bring-up.
    portfolio_handler : Any
        Owns the portfolio definition store; both the rehydrate read and the
        ``add_portfolio`` write-back go through that ONE instance so they cannot diverge.
    execution_venue : str
        The venue whose enabled accounts this boot brings online.

    Returns
    -------
    dict[str, Any]
        One ``VenueLifecycle`` per account, keyed by the row's ``account_id`` — the same
        key the exchange registry and the facade's per-account reads use. Empty on the
        in-memory arm.
    """
    venue_lifecycles: dict[str, Any] = {}
    if sql_engine is None:
        return venue_lifecycles

    logger = get_itrader_logger().bind(component="SessionBootstrap")

    # (1) The store the handler already OWNS — one instance, so the rehydrate read and the
    # add_portfolio write-back can never diverge.
    definition_store = portfolio_handler.definition_store
    has_table = definition_store is not None and sa_inspect(
        sql_engine.engine).has_table("portfolios")
    if definition_store is not None and not has_table:
        logger.warning(
            "The `portfolios` table is not provisioned — skipping portfolio "
            "rehydrate (first start, or the Alembic chain has not run). No "
            "portfolio will be restored until the schema exists.")

    # (2) Runs FIRST, so a collision is refused before any account exists.
    if has_table:
        assert_distinct_accounts(persisted=definition_store.read_all())

    # (3) ``bring_online`` builds the account's spec (carrying its OWN secret_ref and
    # config overrides), assembles the bundle through the shared memo, registers the
    # exchange under the row's (venue, account_id) pair VERBATIM, and arms the UID guard.
    # ``read_enabled_for`` carries its own table probe, so a boot before the account table
    # exists brings up zero accounts rather than raising.
    for row in venue_manager.read_enabled_for(execution_venue):
        record = venue_manager.bring_online(row)
        venue_lifecycles[str(row["account_id"])] = record.lifecycle
    # Finalize the feed's connection binding once the bring-up loop is done. A boot with
    # zero streaming accounts leaves the feed UNBOUND and logs the cause, since
    # bring_online's per-row rebind never ran.
    venue_manager.rebind_feed()

    # (4) Assembly running first changes neither WHICH portfolios rehydrate nor their
    # order — that contract is the store's.
    if has_table:
        rehydrate_portfolios(
            store=definition_store,
            portfolio_handler=portfolio_handler,
        )

    return venue_lifecycles


def layer_persisted_overrides(
    config: Any,
    *,
    system_store: Any,
    venue_store: Any,
    order_handler: Any,
    portfolio_handler: Any,
    execution_handler: Any,
) -> None:
    """Boot restart-layering: apply each scope's persisted config from its OWN store.

    The sequence is ``defaults <- env <- persisted``. Frozen base params
    (``rng_seed`` / ``environment`` / identity) resolve at CONSTRUCTION and are never
    persisted-overridden. Each scope is read back from its OWNING module store — system
    from ``SystemStore``, order from the ORDER store, venue from ``VenueStore``, portfolio
    from each Portfolio's own bound ``state_storage`` — so config is never read back from
    ``SystemStore`` for the order/portfolio scopes.

    Degrade-clean: the durable config schema is Alembic-owned, so a boot against a
    not-yet-provisioned schema must NOT crash — a missing config table just means "no
    persisted overrides yet". Never ``create_all`` here; the store stays schema-pure.
    """
    logger = get_itrader_logger().bind(component="SessionBootstrap")

    try:
        for row in system_store.read_all():
            key = row["key"]
            value = row["value"]
            stored = value.get("value") if isinstance(value, dict) else value
            if key.startswith("config.system."):
                field = key[len("config.system."):]
                if field in SystemSettings.model_fields:
                    setattr(config.system, field, stored)
            elif key.startswith("config.universe."):
                field = key[len("config.universe."):]
                if field in UniverseConfig.model_fields:
                    setattr(config.universe, field, stored)
    except _DEGRADE_CLEAN as exc:
        logger.warning(
            "Skipping persisted SYSTEM-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)

    try:
        order_cfg = order_handler.storage.load_config()
        if order_cfg:
            applied = {
                field: val
                for field, val in order_cfg.items()
                if field in OrderConfig.model_fields
            }
            for field, val in applied.items():
                setattr(config.order, field, val)
            if applied:
                order_handler.update_config(applied)
    except _DEGRADE_CLEAN as exc:
        logger.warning(
            "Skipping persisted ORDER-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)

    # The read_all() acquisition keeps its own guard; the per-row push is then guarded PER
    # ENTRY so one poisoned venue degrades only that venue.
    try:
        venue_rows = venue_store.read_all()
    except _DEGRADE_CLEAN as exc:
        logger.warning(
            "Skipping persisted VENUE-config restart layering — schema unavailable "
            "(%s); boot degrades clean", exc)
        venue_rows = []
    for row in venue_rows:
        try:
            venue_cfg = row.get("config") or {}
            push = {
                k: v
                for k, v in venue_cfg.items()
                if k in {"fee_model", "slippage_model"}
            }
            if push:
                execution_handler.update_config(push)
        except _DEGRADE_CLEAN as exc:
            logger.warning(
                "Skipping persisted VENUE-config layering for %s — stored override "
                "invalid (%s); boot degrades clean", row.get("venue_name"), exc)

    # Resolved via the handler's PUBLIC all_portfolios(), never the private registry. The
    # guard is PER ENTRY so one poisoned config_json degrades only that portfolio;
    # all_portfolios() is a pure copy, so the loop needs no acquisition guard.
    for _pid, portfolio in portfolio_handler.all_portfolios().items():
        try:
            portfolio_cfg = portfolio.state_storage.load_config()
            if portfolio_cfg:
                portfolio.update_config(portfolio_cfg)
        except _DEGRADE_CLEAN as exc:
            logger.warning(
                "Skipping persisted PORTFOLIO-config restart layering for %s — schema "
                "unavailable or a stored override is invalid (%s); boot degrades clean",
                _pid, exc)
