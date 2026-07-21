# Phase 11 ★: Multi-Portfolio-Live - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 24 new/modified files across the 7 waves (D-28)
**Analogs found:** 22 / 24 (2 no-analog — see § No Analog Found)

> **Indentation is measured per file, in bytes, in every table below.** Never generalize
> a package. `portfolio_handler/` is split (`portfolio.py` TABS / `portfolio_handler.py`
> 4-space); `trading_system/` is split (`live_trading_system.py` 4-space / siblings TABS).
> Measurement command used: `grep -cP '^\t' <file>` vs `grep -cP '^    [^ ]' <file>`.

---

## File Classification

| New/Modified File | Indent (MEASURED) | Role | Data Flow | Closest Analog | Analog Indent | Match |
|---|---|---|---|---|---|---|
| **W1** `itrader/storage/venue_account_store.py` (NEW) | 4-space (new, `storage/` spine) | store | CRUD | `itrader/storage/venue_store.py` | 4-space (0 tab / 35 sp) | **exact** |
| **W1** `itrader/portfolio_handler/storage/portfolio_definition_store.py` (NEW) or in `storage/` | 4-space | store | CRUD | `itrader/storage/strategy_registry_store.py` | 4-space (0 tab / 46 sp) | **exact** |
| **W1** `migrations/versions/p11_venue_accounts_portfolios.py` (NEW, rev 1) | 4-space | migration | batch/DDL | `migrations/versions/p10_strategy_portfolio_subs.py` | 4-space (0 tab / 35 sp) | **exact** |
| **W1** `migrations/versions/p11_b2_uuid_fk_config_move.py` (NEW, rev 2) | 4-space | migration | batch/DDL + data-move | same + its `_refuse_if_subscriptions_hold_data` | 4-space | **exact** |
| **W1** `itrader/portfolio_handler/storage/models.py` (MOD) | 4-space (0 tab / 67 sp) | model | schema | `venue_store.py:80-100` registrar | 4-space | exact |
| **W1** `itrader/portfolio_handler/storage/sql_storage.py` (MOD — D-09 `save/load_config`) | 4-space | store | CRUD | itself `:528-567` (rehome, not rewrite) | 4-space | self |
| **W2** `itrader/config/credential_resolver.py` (NEW — Protocol + env impl) | 4-space (`config/` conv.) | config/protocol | request-response | `itrader/connectors/provider.py:41-56` `ConnectorPlugin` Protocol | 4-space (0 tab / 19 sp) | **exact** |
| **W2** `itrader/venues/bundle.py` (MOD — `credential_model`, `new_account`) | 4-space (0 tab / 47 sp) | protocol | — | itself `:76-93` `VenuePlugin` | 4-space | self |
| **W2/W3** `itrader/venues/okx_plugin.py` (MOD) | 4-space (0 tab / 31 sp) | provider/plugin | event-driven build | itself `:67-117` + `paper_plugin.py:54-78` | 4-space | self |
| **W3** `itrader/venues/paper_plugin.py` (MOD — per-account `SimulatedAccount`) | 4-space (0 tab / 17 sp) | provider/plugin | build | itself `:63-69` (already per-portfolio) | 4-space | self |
| **W3** `itrader/portfolio_handler/account/venue.py` (MOD — D-11 required `account_id`) | 4-space (0 tab / 57 sp) | model | — | `paper_plugin.py:63` required-arg factory shape | 4-space | role-match |
| **W3** `itrader/execution_handler/execution_handler.py` (MOD — D-27 tuple keys) | **TABS** (235 tab / 0 sp) | handler | request-response | `connectors/provider.py:67-80` `_memo` keying | 4-space ⚠️ | **exact (pattern), DIFFERENT INDENT** |
| **W3** `itrader/core/portfolio_read_model.py` (MOD — `account_for`) | 4-space (0 tab / 33 sp) | protocol | read-model | itself `:191` `exchange_for` | 4-space | self |
| **W3** `itrader/portfolio_handler/portfolio_handler.py` (MOD — `account_for`, `add_portfolio`) | 4-space (0 tab / 123 sp) | handler | CRUD | itself `:365-368` `exchange_for` | 4-space | self |
| **W3** `itrader/trading_system/live_trading_system.py` (MOD — D-13 delete singleton) | **4-space** | composition root | wiring | itself `:1571-1600` rehydrate block | 4-space | self |
| **W3** `itrader/portfolio_handler/account/conformance.py` (MOD — docstrings only) | 4-space | test-support | — | itself | 4-space | self |
| **W4** `itrader/portfolio_handler/portfolio.py` (MOD — F-1/F-5 ctor params) | **TABS** (846 tab / 0 sp) | model | — | itself `:54-73` | TABS | self |
| **W4** `itrader/trading_system/system_spec.py` (MOD — `PortfolioSpec.account_id`, D-26 rename) | **TABS** | config | — | itself `:39-48` | TABS | self |
| **W5** `itrader/execution_handler/exchanges/okx.py` (MOD — D-16/D-18) | **TABS** (per RESEARCH) | service | request-response | itself `:204-232` | TABS | self |
| **W5** `itrader/execution_handler/exchanges/venue_correlation.py` (MOD — D-16) | **TABS** (287 tab / 0 sp) | service | event-driven | itself `:81-94` `_extract_client_order_id` | TABS | self |
| **W6** `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` (MOD) | 4-space (0 tab / 22 sp) | service | batch | itself `:80-216` | 4-space | self |
| **W6** `itrader/trading_system/safety/safety_controller.py` (MOD — per-portfolio quarantine) | 4-space (0 tab / 50 sp) | service | event-driven | itself `:146,151,265,289` global scalars | 4-space | **exact** |
| **W6** `itrader/order_handler/admission/admission_manager.py` (MOD — 1 guard clause) | **TABS** (980 tab / 0 sp) | service | request-response | itself (already `portfolio_id`-keyed, 10 sites) | TABS | self |
| **W7** `tests/integration/test_multi_portfolio_lifecycle.py` (NEW) | 4-space | test | e2e | `tests/integration/test_paper_restart_restore.py` | 4-space | **exact** |
| **W7** `tests/integration/test_per_account_exchange_routing.py` (NEW) | 4-space | test | e2e | `tests/integration/test_live_system_okx_wiring.py` | 4-space | role-match |
| **W7** `tests/integration/test_distinct_account_invariant.py` (NEW) | 4-space | test | integration | `test_live_portfolio_durable_wiring.py` | 4-space | role-match |

---

## Pattern Assignments

### `itrader/storage/venue_account_store.py` (NEW — store, CRUD) — **W1, D-05**

**Analog:** `itrader/storage/venue_store.py` — **4-space**, 210 lines. This is a near
line-for-line template: same spine, same registrar convention, same three-lifecycle
column split D-05 asks for.

**Module docstring pattern** (`venue_store.py:1-24`) — note the decision-tag citations and
the explicit indentation declaration on the last line. Copy this structure verbatim:

```python
"""Durable per-venue config store — enabled flag + JSON config, secret-scrub guarded (STORE-02).

A per-venue durable store on the shared ``SqlEngine`` spine: ``upsert(venue_name, config,
enabled, at)`` persists one row per NATURAL ``venue_name`` (D-06 — no UUIDv7 surrogate,
``idgen`` never imported), with a typed ``enabled`` Boolean column (queryable — serves
``list_enabled``) alongside the portable JSON ``config_json`` (D-08). A disciplined clone of
the ``HaltRecordStore`` template (STORE-04 / D-01): composes ``SqlEngine`` by reference, owns
its ``build_venue_store_table`` registrar (single source of truth for BOTH the test-path
``create_all`` and Plan 04-03's ``migrations/env.py``), schema-pure (WR-03/D-14 — no runtime
``create_all``; Alembic-owned in production, ``provision_schema`` in tests), caller-supplied
``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only (SEC-01 / T-04-02).

4-space indentation (matches the ``itrader/storage`` spine layer).
"""
```

**Imports pattern** (`venue_store.py:26-34`):

```python
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import Boolean, Column, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine, RowMapping

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant
```

**Table registrar pattern — THE D-05 template** (`venue_store.py:80-100`). Note the
idempotent re-registration guard (required — the metadata is shared), and the
typed-`enabled` + `json_variant()` + `UtcIsoText` triple:

```python
def build_venue_store_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``venue_store`` table on ``metadata`` and return it.
    ...
    """
    if "venue_store" in metadata.tables:
        return metadata.tables["venue_store"]
    return Table(
        "venue_store",
        metadata,
        Column("venue_name", String, primary_key=True),
        Column("enabled", Boolean, nullable=False),
        Column("config_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )
```

**D-05 adaptation:** composite natural PK — two `primary_key=True` columns
(`venue_name`, `account_id`), plus `secret_ref` `String` **nullable=True** (NULL for paper,
D-06), `venue_uid` nullable (TOFU, D-04), `enabled` Boolean, `config_json` `json_variant()`,
`updated_at` `UtcIsoText`. **Column MUST be named `secret_ref`, never `credentials`** — see
the denylist excerpt below.

**Ctor pattern — schema-pure, composes the spine by reference** (`venue_store.py:115-121`):

```python
    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.venue_store: Table = build_venue_store_table(sql_engine.metadata)
        # WR-03/D-14 — schema-pure: register the table, never create it (Alembic-owned in
        # production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="VenueStore")
```

**Write pattern — guard-first, portable delete-then-insert in ONE transaction, Core-parameterized** (`venue_store.py:127-153`):

```python
    def upsert(
        self, venue_name: str, config: dict[str, Any], enabled: bool, at: datetime
    ) -> None:
        _assert_no_secret_keys(config)
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.venue_store).where(
                    self.venue_store.c.venue_name == venue_name
                )
            )
            connection.execute(
                insert(self.venue_store),
                [
                    {
                        "venue_name": venue_name,
                        "enabled": enabled,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )
```

**Read patterns** — `get` returns `Optional[Mapping]` (`:155-167`), `read_all` is the
rehydrate read (`:190-200`), `_row_to_dict` is a `@staticmethod` coercing driver bools
(`:202-210`). Copy all three shapes.

**THE SECRET DENYLIST — reuse, do not rebuild** (`venue_store.py:40-53`). Verified by
RESEARCH: `"credential"` (singular) is denied; **`"credentials"` and `"secret_ref"` both
pass**. This is exact lowercased membership:

```python
_SECRET_KEY_DENYLIST: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "passphrase",
        "token",
        "access_token",
        "private_key",
        "credential",
    }
)
```

⚠️ **`"secret"` IS in the denylist and matching is exact-membership, not substring — so a
column named `secret_ref` passes, but a `config_json` KEY named `secret` does not.** The
`venue_accounts.config_json` write path must run `_assert_no_secret_keys` too (D-05's
`config_json` is operator-authored).

---

### `itrader/…/portfolio_definition_store.py` (NEW — store, CRUD) — **W1, D-07/D-08**

**Analog:** `itrader/storage/strategy_registry_store.py` — **4-space**, 410 lines. Use this
one rather than `venue_store.py` because it is the **parent+child multi-table registrar with
a real FK**, which is exactly the `portfolios` → `venue_accounts` shape (and the B2 FK).

**Multi-table registrar + FK pattern** (`strategy_registry_store.py:100-129`) — note the
`tables: dict` return, the per-table idempotency guard, and the FK-inside-composite-PK column:

```python
            Column("strategy_type", String, nullable=False),
            # D-06 — runtime state, its OWN column (never inside config_json): keeps
            # list_active() a WHERE query rather than a JSON scan.
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )

    if "strategy_portfolio_subscriptions" in metadata.tables:
        tables["strategy_portfolio_subscriptions"] = metadata.tables[
            "strategy_portfolio_subscriptions"
        ]
    else:
        tables["strategy_portfolio_subscriptions"] = Table(
            "strategy_portfolio_subscriptions",
            metadata,
            # FK back to the registry natural name key; part of the composite PK.
            Column(
                "strategy_name",
                String,
                ForeignKey("strategy_registry.strategy_name"),
                primary_key=True,
                nullable=False,
            ),
            # String (not Uuid): to_dict serializes each handle via str(pid) and
            # rehydrate parses it back. A Uuid column is open as B2, not decided.
            Column("portfolio_id", String, primary_key=True, nullable=False),
        )

    return tables
```

**B2 fold-in acts on the last two lines above.** Change `String` → `Uuid` and add
`ForeignKey("portfolios.portfolio_id", ondelete="CASCADE")`. **Delete the "A Uuid column is
open as B2, not decided" comment** — it becomes false the moment the change lands.

**D-07 adaptation:** `portfolios(portfolio_id Uuid PK, name, venue_name, account_id NOT NULL,
initial_cash, enabled Boolean, config_json json_variant(), updated_at UtcIsoText)` plus a
composite `ForeignKeyConstraint(["venue_name","account_id"], ["venue_accounts.venue_name",
"venue_accounts.account_id"])` and the D-14 **plain** `UniqueConstraint("venue_name",
"account_id")`. A composite FK needs the table-level `ForeignKeyConstraint`, **not** the
column-level `ForeignKey` shown above.

**Money note:** `initial_cash` is money → `Decimal`. Enter via `to_money(str(x))`
(`core/money.py`), never `Decimal(float)`.

---

### `migrations/versions/p11_*.py` (NEW ×2 — migration) — **W1, D-29**

**Analog:** `migrations/versions/p10_strategy_portfolio_subs.py` — **4-space**, 157 lines.
Chain head is `p10_strategy_portfolio_subs`; rev 1 revises it, rev 2 revises rev 1.

**Revision header pattern** (`:46-60`):

```python
Revision ID: p10_strategy_portfolio_subs
Revises: system_stats
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "p10_strategy_portfolio_subs"
down_revision: Union[str, Sequence[str], None] = "system_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**THE REFUSE-IF-NON-EMPTY GUARD — the D-29 pattern for the B2 type change** (`:63-81`).
Copy this shape exactly, including the actionable multi-sentence remediation message:

```python
def _refuse_if_subscriptions_hold_data() -> None:
    """A1 GUARD (T-10-08) — raise rather than drop a ``strategy_subscriptions`` with rows.

    Runs BEFORE any destructive op. Parameter-free count via the migration's own bind.
    """
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM strategy_subscriptions")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"REFUSING to drop 'strategy_subscriptions': the table holds {count} row(s). "
            "This migration (D-06) drops the table on the assumption it is empty in every "
            "deployed DB — an assumption that could not be verified from source, and a "
            "wrong drop is unrecoverable. Inspect the rows "
            "(SELECT * FROM strategy_subscriptions), migrate or archive anything you need "
            "..., then DELETE the rows and re-run 'alembic upgrade head'."
        )
```

**Guard-first ordering + `batch_alter_table` for SQLite** (`:84-102`):

```python
def upgrade() -> None:
    """Add ``strategy_type``, create the portfolio-subscription child, drop the P4 table."""
    # 1. A1 guard FIRST — before any destructive op (T-10-08).
    _refuse_if_subscriptions_hold_data()

    # 2. Non-null ADD COLUMN needs a default to satisfy any EXISTING strategy_registry row
    # ... batch_alter_table: SQLite cannot ALTER a
    # column in place (the store's test path runs on SQLite; the migration test asserts this).
    op.add_column(
        "strategy_registry",
        sa.Column(
            "strategy_type", sa.String(), nullable=False, server_default="UNKNOWN"
        ),
    )
    with op.batch_alter_table("strategy_registry") as batch_op:
        batch_op.alter_column("strategy_type", server_default=None)
```

**`downgrade()` is the exact inverse in reverse order** (`:131-157`).

**Rev-1 ordering (D-29):** `venue_accounts` **then** `portfolios` — the FK direction forces it.
**Rev-2 (D-29):** guard → B2 `String`→`Uuid` via `batch_alter_table` → add the CASCADE FK →
the D-09 config data move. Do **not** use `USING portfolio_id::uuid` (Postgres-only; the test
path is SQLite — this is precisely why P10 needed `batch_alter_table`).

**⚠️ The D-09 data move is the phase's one structurally-undetectable failure (RESEARCH
Pitfall 1).** `load_config()` returning `None` degrades clean with no warning, so a
repointed-but-unmoved config yields a **green suite and default-config portfolios**. The rev-2
plan must carry a migration test asserting the migrated **value** byte-identically, never
`is not None`.

---

### `itrader/config/credential_resolver.py` (NEW — protocol + env impl) — **W2, D-02**

**Analog:** `itrader/connectors/provider.py:41-56` — **4-space**, 91 lines. The
`@runtime_checkable` structural-Protocol-plus-lazy-build seam, and the module is
import-inert (`TYPE_CHECKING`-only annotations under `from __future__ import annotations`)
— which the `test_okx_inertness.py` gate requires of the new resolver too.

**Inert module header** (`provider.py:31-38`):

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
```

**Protocol pattern — note the `@runtime_checkable` + "so a fake is swap-in for tests" rationale** (`provider.py:41-56`):

```python
@runtime_checkable
class ConnectorPlugin(Protocol):
    """Structural per-venue connector build recipe (VENUE-03 / D-04).

    ``@runtime_checkable`` (mirrors the ``LiveConnector`` / ``VenuePlugin`` seams)
    so a fake plugin is swap-in for tests. ``build`` is the D-04 triple-deferral
    seam: a concrete implementation keeps the connector concretion ``import`` AND
    the ``OkxSettings()`` credential construction INSIDE the body — never at
    module top, never at register time. ...
    """

    def build(self, spec: Any) -> LiveConnector:
        """Build ONE ``LiveConnector`` (concretion + credentials constructed inside)."""
        ...
```

**⚠️ D-10's own correction applies here too:** `VenuePlugin` is a *structural* Protocol that
plugins do not subclass, and `(*args: Any, **kwargs: Any)` satisfies **any** Protocol method
under mypy. A Protocol method is a **code-location** decision, not a wrong-wiring guard. The
guard is D-11's required keyword arg — see below.

---

### `itrader/venues/*_plugin.py` (MOD — plugin, build) — **W2/W3, D-03/D-10/D-11**

**Analogs:** `okx_plugin.py` (4-space, 145 lines) and `paper_plugin.py` (4-space, 78 lines).

**THE D-11 TRAP — the arg-swallowing arm being replaced** (`okx_plugin.py:101-110`). Read
this as the *anti-pattern*:

```python
        def account_factory(*args: Any, **kwargs: Any) -> Account:
            # D-07: a single default VenueAccount bound to the shared connector (the
            # per-portfolio account_id fan-out is P11). Args are absorbed so the
            # 05-06 assemble_venue can call this uniformly with the paper factory.
            return VenueAccount(
                connector,
                quote_currency=quote,
                market_type="spot",
                symbol=symbol,
            )
```

**THE TARGET SHAPE — `paper_plugin.py:63-69` already has the real per-portfolio signature.**
This is what `new_account()` should look like:

```python
        def account_factory(portfolio: Any, initial_cash: Any = 0.0) -> Account:
            # Mirror the portfolio leaf-selection (portfolio.py:136-140): the margin
            # superset when enabled, else the verbatim-critical spot cash leaf (the
            # SMA_MACD byte-exact oracle path, D-04).
            if portfolio.config.trading_rules.enable_margin:
                return SimulatedMarginAccount(portfolio, initial_cash=initial_cash)
            return SimulatedCashAccount(portfolio, initial_cash=initial_cash)
```

**D-04 lazy-import discipline — MUST be preserved in `new_account()`** (`okx_plugin.py:79-82`,
and the `DO NOT hoist` warning at `:18-22`). Every concretion import stays **inside** the
method body:

```python
    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the OKX execution ``VenueBundle`` over the shared connector."""
        # D-04: OKX concretions lazy-imported inside the body (never module top).
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.portfolio_handler.account import VenueAccount
        from itrader.venues.bundle import VenueBundle
```

**Connector memo key — the D-12/D-27 reference keying** (`okx_plugin.py:94-99`):

```python
        # D-03/D-07: the SAME memoized connector for ("okx", account_id) the data
        # arm borrows; account_id=None resolves to the "default" logical account.
        account_id = spec.account_id or "default"
        connector = connectors.get("okx", account_id, spec)

        exchange = OkxExchange(ctx.bus, connector)
```

⚠️ **`:138-139` in `OkxDataPlugin.build_provider` keeps `spec.account_id or "default"`
verbatim (D-26 defers the data arm).** Only the execution arm goes per-account.

**Protocol-method addition** — `bundle.py:76-93` is where `new_account` and
`credential_model` land, beside `build_bundle`:

```python
@runtime_checkable
class VenuePlugin(Protocol):
    """Structural build seam for an execution venue (VENUE-02 / D-04).
    ...
    """

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the execution ``VenueBundle`` (concretions lazy-imported inside)."""
        ...
```

---

### `itrader/connectors/provider.py` → the D-27 keying reference — **W3**

**This is the shipped `(venue, account_id)` memo `ExecutionHandler.exchanges` is being
converted to match** (`provider.py:67-80`, **4-space**):

```python
    def __init__(self, plugins: dict[str, ConnectorPlugin]) -> None:
        self._plugins = plugins
        self._memo: dict[tuple[str, str], LiveConnector] = {}
        self.logger = get_itrader_logger().bind(component="ConnectorProvider")

    def get(self, venue: str, account_id: str, spec: Any) -> LiveConnector:
        """Return the shared connector for ``(venue, account_id)``; build it once on first call.

        Fails loud with ``KeyError`` when ``venue`` has no registered plugin.
        """
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = self._plugins[venue].build(spec)
        return self._memo[key]
```

⚠️ **D-12 caveat, verified:** `:79` reads `self._plugins[venue]` — **venue-only**. Two
`account_id`s today build two connectors from **identical** `OkxSettings()`. VENUE-03 does
not give per-account credential isolation; D-02's resolver is what closes it.

---

### `itrader/execution_handler/execution_handler.py` (MOD — handler, request-response) — **W3, D-27**

**Indent: TABS (235 tab lines / 0 space-indented).** The keying analog
(`connectors/provider.py`) is 4-space — **transcribe the pattern, not the whitespace.**

**The D-27 change site** (`execution_handler.py:123-134`, TABS):

```python
	def on_order(self, event: OrderEvent) -> None:
		"""Route an order event to the configured exchange's order router."""
		try:
			exchange = self.exchanges.get(event.exchange)
			if not exchange:
				self.logger.error('Unknown exchange specified: %s for order %s %s',
								event.exchange, event.ticker, event.action)
				return
			exchange.on_order(event)
		except Exception as e:
			self.logger.error('Unexpected error routing order for %s %s: %s',
							 event.ticker, event.action, str(e), exc_info=True)
```

**THE `id()` ALIAS DEDUP — DO NOT TOUCH** (`execution_handler.py:136-150`, TABS). RESEARCH
Item 3 verified this is correct-by-construction under tuple keys, and that the byte-exact
oracle depends on it. A name-based or key-based "cleanup" would double-drive the resting book
and break `134 / 46189.87730727451`:

```python
	def on_market_data(self, bar: BarEvent) -> None:
		"""Drive resting-order matching on each exchange with a new bar."""
		# Dedup by instance identity: multiple venue aliases (e.g. 'simulated' and 'csv')
		# may point to the same exchange object; driving it once per bar avoids
		# double-matching the resting-order book (DEF-01-B alias, Plan 01-04).
		seen: set[int] = set()
		for name, exchange in self.exchanges.items():
			if exchange is None or id(exchange) in seen:
				continue
			seen.add(id(exchange))
			try:
				exchange.on_market_data(bar)
			except Exception as e:
				self.logger.error('Error matching resting orders on %s: %s',
								 name, str(e), exc_info=True)
```

**The hardcoded-`'simulated'` sites that break under tuple keys** (`:96` and `:115`, identical
shape — this is the `update_config` one):

```python
		exchange = self.exchanges.get('simulated')
		if not isinstance(exchange, SimulatedExchange):
			raise ConfigurationError(
				config_key='simulated',
				reason='no simulated exchange wired to update')
```

⚠️ **RESEARCH F-4: this is a 10-site change, not 1.** `execution_handler.py:96,115,126,238,241`
plus `live_trading_system.py:1473,1514,1553-1555,582-584`. RESEARCH also flags that
`tests/` and `scripts/` were **not** grepped (assumption A4) — do that before finalizing.
Use a module-level `_DEFAULT_ACCOUNT_ID = 'default'` so `init_exchanges` keys
`('simulated', _DEFAULT_ACCOUNT_ID)` / `('csv', …)` and the alias identity is preserved.

**`on_order` needs `PortfolioReadModel` injected** — `ExecutionHandler` has none today. That
is a ctor change on a class the **backtest** composition root builds → oracle-gated.

---

### `itrader/core/portfolio_read_model.py` + `portfolio_handler.py` (MOD — `account_for`) — **W3, D-27**

**Analog: the sibling method, 4 lines** (`portfolio_handler.py:365-368`, **4-space**):

```python
    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on (admission metadata, OQ1)."""
        exchange: str = self.get_portfolio(portfolio_id).exchange
        return exchange
```

**Protocol side** (`core/portfolio_read_model.py:191+`, 4-space) — docstring carries the
`Parameters` NumPy block and the OQ1 rationale:

```python
    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on.

        Admission metadata (OQ1): exchange routing is part of order
        admission, not portfolio internals.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.
```

`account_for` mirrors both exactly. **This is the queue-only-compliant seam** — do NOT import
`PortfolioHandler` into `execution_handler`.

---

### `itrader/execution_handler/exchanges/{okx,venue_correlation}.py` (MOD) — **W5, D-16/D-18**

**Both TABS.** `venue_correlation.py`: 287 tab / 0 space.

**D-18 — the strippable assert** (`okx.py:228-231`, TABS). Under `python -O` this vanishes
entirely, leaving a venue-bound identifier unguarded:

```python
		# WR-04 rendering contract: alphanumeric + within OKX's 32-char clOrdId
		# limit. A full 128-bit base62 token is <=22 chars, so "it" + token <=24.
		assert clordid.isalnum() and len(clordid) <= 32, (
			f"clOrdId {clordid!r} violates the OKX charset/length contract")
		return clordid
```

**Convert to a real raise.** The house precedent is `reconciliation_coordinator.py:166`'s
`RuntimeError` — quoted in § Shared Patterns below.

**D-16 — the venue-vocabulary helper already exists; consolidate INTO it** (`venue_correlation.py:81-94`, TABS). The wire spellings `clOrdId`/`clientOrderId` stay
**verbatim** — they are OKX's API contract:

```python
def _extract_client_order_id(trade: Any) -> Optional[str]:
	"""Pull the echoed client order id (clOrdId) off a ccxt-unified trade.

	ccxt surfaces it as ``clientOrderId`` at the top level, or the raw OKX
	``clOrdId``/``clientOrderId`` under ``info``. Returns None when neither is present so the
	caller falls through to the buffer path.
	"""
	if not isinstance(trade, dict):
		return None
	cid = trade.get("clientOrderId")
	if cid is None:
		info = trade.get("info")
		if isinstance(info, dict):
			cid = info.get("clOrdId") or info.get("clientOrderId")
	return str(cid) if cid else None
```

**The rename target** (`venue_correlation.py:139-151`, TABS) — `_orders_by_clOrdId` →
`_orders_by_client_order_id`; note `_clordid_by_venue_id` at the bottom is a second
engine-side identifier in the same rename set:

```python
		# The three correlation maps (formerly inline on OkxExchange).
		self._orders_by_venue_id: Dict[str, OrderEvent] = {}
		self._venue_id_by_order_id: Dict[OrderId, str] = {}
		self._orders_by_clOrdId: Dict[str, OrderEvent] = {}
		...
		# venue_id -> clOrdId, so ``release`` can drop the clOrdId map entry too (R2 bound).
		self._clordid_by_venue_id: Dict[str, str] = {}
```

⚠️ **RESEARCH C-1: `clOrdId` spans THREE files, not two.** The third is a `RuntimeError`
message string at `reconciliation_coordinator.py:172` — which **W3 deletes**. W5 is marked
parallelizable, so a completion grep must be **repo-wide** (`grep -rn clOrdId itrader/`) and
must state the W3-before-W5 ordering, or it produces a false failure / false pass.

---

### `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` (MOD) — **W6, D-19..D-22**

**4-space** (0 tab / 22 sp), 216 lines — the whole file fits in context.

**The ctor scalars D-19 drops** (`:80-100`):

```python
    def __init__(
        self,
        *,
        portfolio_handler: Any,
        seed_applied_trades: Callable[[Iterable[str]], None],
        order_storage: Any,
        venue_account: "VenueAccount | None",
        connector: Any,
        exchange: Any,
        global_queue: "Queue[Any]",
        halt: Callable[[str], None],
    ) -> None:
```

Note the keyword-only `*` and the injected-`halt`-as-`Callable` seam ("so this collaborator
does not depend on the concrete `SafetyController`", `:25-27`). D-22's quarantine callable
should be injected the same way.

**THE DELETION TARGET (MPORT-01)** — `_link_venue_account_to_portfolios` + its guard
(`:151-176`). Its docstring is also the clearest statement of *why* P11 exists:

```python
        active_portfolios = self._portfolio_handler.get_active_portfolios()
        if len(active_portfolios) > 1:
            raise RuntimeError(
                "Live venue-account wiring supports at most one active portfolio "
                f"(found {len(active_portfolios)}). Sharing one VenueAccount "
                "across portfolios would conflate their buying power / positions "
                "and discard each SimulatedAccount ledger. Multi-portfolio-live "
                "requires a per-portfolio VenueAccount keyed by venue sub-account "
                "(AccountId) with position attribution by clOrdId/tag — deferred "
                "work; wire that before running more than one live portfolio.")
        # Zero -> no-op; exactly one -> link the venue-cached account onto it.
        for portfolio in active_portfolios:
            portfolio.account = account
```

**THE F-2 / D-20 / D-21 rewrite site** (`:193-216`). Three defects in 24 lines: the global
single-symbol read (`:193-195`), the loop-invariant `precision` (`:198`), and the
first-mismatch `return` (`:216`):

```python
        from itrader import config as _system_config
        symbol = _system_config.stream.okx_stream_symbol
        venue_qty = account.positions.get(symbol, Decimal("0"))
        # F/U-6: reuse the per-instrument drift epsilon (the same band the on-fill drift
        # compare keys off the wired instrument's quantity precision).
        precision = self._portfolio_handler._drift_precision(symbol)
        for portfolio in self._portfolio_handler.get_active_portfolios():
            engine_position = portfolio.get_open_position(symbol)
            engine_qty = (
                engine_position.net_quantity if engine_position is not None
                else Decimal("0")
            )
            if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
                continue  # base-asset balance == believed position — trustworthy.
            # Unexplained base-asset residual: NEVER auto-adopt exposure of unknown origin —
            # latch HALT BEFORE trading (D-04/D-05) with the FIXED literal reason (V7).
            self.logger.error(
                "Session-start baseline guard: unexplained base-asset residual — "
                "halting before trading (venue exposure the engine cannot explain)",
                symbol=symbol,
                engine_qty=str(engine_qty),
                venue_qty=str(venue_qty))
            self._halt(HaltReason.BASELINE_RESIDUAL.value)
            return
```

**Preserve the FIXED-literal reason discipline** (`HaltReason.X.value`, never `str(exc)` —
ASVS V7, and there is a grep-0 enforcing it). D-22's quarantine reason must be a fixed
literal too. `precision` moves **inside** the per-symbol iteration under D-20.

---

### `itrader/trading_system/safety/safety_controller.py` (MOD — per-portfolio quarantine) — **W6, D-22/D-23**

**4-space** (0 tab / 50 sp). D-22 is "a per-portfolio set beside" these — verified: the
existing global scalars have exactly the target shape.

**State + locked-flag pattern** (`:140-149`):

```python
        self._status = SystemStatus.STOPPED
        self._status_lock = threading.Lock()
        self._last_error: Optional[str] = None
        # 05-04 (D-07): machine-readable halt reason surfaced on get_status().
        self._halt_reason: Optional[str] = None
        # 05-08 (D-19): REVERSIBLE pause-on-disconnect state (distinct from HALT).
        self._submission_paused = False
        self._paused_reason: Optional[str] = None
```

**Locked-read accessor — the admission gate's read shape** (`:265-268`):

```python
    def is_submission_paused(self) -> bool:
        """Whether NEW order submission is reversibly paused on a disconnect (D-19)."""
        with self._status_lock:
            return self._submission_paused
```

**Snapshot read-model — the D-24 surface pattern; note "all read under one `_status_lock`
acquisition so the snapshot is internally consistent"** (`:269-287`):

```python
    def status_snapshot(self) -> dict[str, Any]:
        """Read-only snapshot of the safety-owned status fields (D-07/D-19).
        ...
        """
        with self._status_lock:
            return {
                'status': self._status,
                'halt_reason': self._halt_reason,
                'paused': self._submission_paused,
                'paused_reason': self._paused_reason,
                'last_error': self._last_error,
            }
```

**Reversible-quiesce docstring (D-23's operator-only release is the *opposite* posture — halt
discipline, not pause discipline)** (`:289-300`) — read it to know what NOT to copy:

```python
    def pause_submission(self, reason: str) -> None:
        """Reversibly pause NEW order submission on a venue-stream disconnect (D-19).

        Distinct from ``halt()``: this is a REVERSIBLE quiesce ... A
        terminal HALT supersedes a pause, so this is a no-op while HALTED. Idempotent
        (a second pause with a new reason keeps the first). Thread-safe (a locked flag
        flip) so the connector-loop reconnect callback can call it without blocking I/O.
```

---

### `itrader/trading_system/live_trading_system.py` (MOD) — **W3/W4, D-08/D-09/D-13**

**4-space** — and its siblings (`system_spec.py`, `backtest_trading_system.py`,
`compose.py`, `engine_context.py`) are **TABS**. Under a mypy `ignore_errors` override.

**THE P10 QUARANTINE READ-MODEL — the D-24 template, verbatim rationale** (`:923-929`):

```python
                # D-19 (10-05): the strategies that could not be rehydrated at boot and are
                # therefore NOT trading, despite their registry rows still declaring them
                # enabled (the row is never rewritten — the DB holds operator INTENT). A
                # DEDICATED field rather than part of 'last_error': that one is
                # single-valued and would be overwritten by the next error, losing exactly
                # the list an operator needs to see. Directly renderable by the future UI.
                'quarantined_strategies': list(self._quarantined_strategies),
```

Backed by `self._quarantined_strategies: list[str] = []` (`:221`) and assigned from the
rehydrate return (`:1625`). **D-24's `quarantined_portfolios` mirrors all three sites.**

**THE REHYDRATE PLACEMENT BLOCK — the four-constraint comment W4 must REWRITE, not just
insert above** (`:1571-1600`):

```python
        # touch only the mutable sub-models.
        _layer_persisted_overrides(
            _system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
        )

        # STRATEGY REHYDRATE (D-01/STRAT-01): the stored roster becomes live instances.
        # THIS EXACT POSITION satisfies four independent constraints at once:
        #  (1) portfolios are already layered ABOVE (_layer_persisted_overrides iterates
        #      portfolio_handler._portfolios), so subscribe_portfolio binds to ids that
        #      already exist and are restart-stable — portfolios-before-strategies holds.
        ...
        #  (3) NOT inside _initialize_live_session: three integration tests — including a
        #      RESTART test — monkeypatch that method to a no-op, so rehydrate placed there
        #      would be silently lost exactly where it matters most.
        #  (4) the rehydrate collaborator import stays LAZY inside this gate and is never
        #      barrel-exported, keeping the backtest import path SQL-free (GATE-01).
```

⚠️ **RESEARCH Item 1: clause (1) is false in BOTH halves today**, and
`_layer_persisted_overrides` must **MOVE BELOW** portfolio rehydrate — it iterates
`portfolio_handler._portfolios`, which is empty before D-08 lands. Required W4 order:
invariant check → portfolio rehydrate → account minting → `_layer_persisted_overrides` →
strategy rehydrate. Constraint (3) transfers verbatim and with *more* force: put portfolio
rehydrate in `build_live_system`, **never** in `_initialize_live_session`.

⚠️ **Pitfall 4:** after deleting `self._venue_account` (`:191,195`, read at `:368,1666`),
`grep -n "_venue_account" itrader/` must return zero. mypy `ignore_errors` will not catch a
leftover.

---

### W7 test files (NEW ×3 — test, e2e) — **D-25, F-3**

**Analog: `tests/integration/test_paper_restart_restore.py`** — 4-space. Best analog for the
D-25 two-paper-account lifecycle+restart test: it drives the **real** `LiveTradingSystem.start()`
fully offline, which is exactly D-25's "test the external path" mandate.

**Docstring pattern — states the gap closed, the mechanism, and the indentation/marker
convention** (`:1-27`):

```python
"""D-23 — a durable paper/simulated engine restart restores its persisted cash + realised PnL.

The gap this closes (D-23, owner-locked option (a) scalar-restore): ...

Both tests drive the REAL ``LiveTradingSystem.start()`` fully OFFLINE (no OKX network, no
credentials, no Postgres) on ``exchange="paper"``: ``_initialize_live_session`` is coerced
to a no-op, the durable-store gate is opened by exposing a ``rehydrate`` attr on
``_order_storage``, and a rehydrate spy halts the engine right after the restore so
``start()`` refuses RUNNING and never spawns the processing thread.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""
```

⚠️ **Note the offline-drive recipe** (no-op `_initialize_live_session`, `rehydrate` attr on
`_order_storage`, halt-spy) — reuse it verbatim. And **no `@pytest.mark.integration`**: the
marker is folder-derived by `tests/conftest.py`. **No `__init__.py`** in the dir.

⚠️ **RESEARCH F-3:** this analog's `_initialize_live_session` no-op is the same monkeypatch
that would silently swallow a misplaced portfolio rehydrate — its behavior assumptions need
review, and its docstring references the deleted link function.

**Analog: `tests/integration/test_live_system_okx_wiring.py:280-325`** — for the MPORT-07
routing test. These are the two cases that **hard-break** when MPORT-01 deletes the link
function, and the second is the direct ancestor of the D-15 refuse-to-start test:

```python
def test_link_venue_account_two_portfolios_fails_loud(monkeypatch) -> None:
    """Two active portfolios: wiring FAILS LOUD rather than sharing one VenueAccount (WR-02).
    ...
    """
    _set_okx_env(monkeypatch)
    system = LiveTradingSystem.for_exchange("okx")

    system._venue_account = MagicMock(name="venue_account")
    p1 = MagicMock(name="portfolio_1")
    p2 = MagicMock(name="portfolio_2")
    system.portfolio_handler.get_active_portfolios = MagicMock(  # type: ignore[method-assign]
        return_value=[p1, p2])

    coordinator = system._build_reconciliation_coordinator()
    with pytest.raises(RuntimeError, match="at most one active portfolio"):
        coordinator._link_venue_account_to_portfolios(system._venue_account)

    # The guard raises BEFORE any assignment — no portfolio received the shared
    # venue account (each ``.account`` is an untouched auto-child mock, not it).
    assert p1.account is not system._venue_account
    assert p2.account is not system._venue_account
```

Note the **"raises BEFORE any assignment"** post-assertion — D-15's "hard fail before any
account is minted" needs exactly this shape (assert no account was minted, not just that it
raised).

⚠️ **F-3:** the MPORT-07 routing test needs a **fake multi-account venue plugin**, not paper —
`live_trading_system.py:1473` gives `PaperVenuePlugin` the already-built shared
`SimulatedExchange`, so two paper accounts necessarily share one exchange object. Assert
`exchanges[(v,'a')] is not exchanges[(v,'b')]` and that portfolio-B's order never reaches
exchange-A.

---

## Shared Patterns

### Loud rejection over silent no-op (D-11/D-15/D-18/D-29)
**Source:** `reconciliation_coordinator.py:159-162` (docstring) + `:166-173` (the raise)
**Apply to:** D-11's required ctor arg, D-15's refuse-to-start, D-18's assert→raise, D-29's guard
```
Until it exists, FAIL LOUD on MORE THAN ONE active portfolio (a
``RuntimeError``, not a strippable ``assert``, so the guard holds under ``python
-O``). Zero active portfolios is a benign no-op; exactly one is the supported
single-portfolio-live path.
```
The error message names the count, the consequence, and the remediation. `p10_strategy_portfolio_subs.py:72-81` is the migration-flavored version of the same rule.

### Store template: schema-pure + registrar-as-single-source-of-truth
**Source:** `venue_store.py:80-100` (registrar), `:115-121` (ctor), `:123-125` (`dispose`)
**Apply to:** both new W1 stores
- `build_*_table(metadata) -> Table` with an idempotent `if "<name>" in metadata.tables` guard
- register on `sql_engine.metadata`, **never** `create_all` at runtime (Alembic in prod,
  `tests.support.schema.provision_schema` in tests)
- typed columns for queryable state (`enabled`), `json_variant()` for portable config,
  `UtcIsoText` for caller-supplied `at` (clock-free)
- parameterized Core only (SEC-01) — no string SQL
- `dispose()` delegates to `self.backend.dispose()`, never `engine.dispose()`

### Import inertness (GATE-01)
**Source:** `bundle.py:32-44`, `provider.py:31-38`, `okx_plugin.py:18-22`
**Apply to:** `CredentialResolver`, `credential_model`, both new stores
```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
```
Concretion imports live **inside** method bodies. New store imports stay lazy inside the
`build_live_system` gate. **Never barrel-export.** Gate: `tests/integration/test_okx_inertness.py`.

### Logger binding
**Source:** `venue_store.py:121`, `provider.py:70`, `reconciliation_coordinator.py:100`
**Apply to:** every new class
```python
        self.logger = get_itrader_logger().bind(component="VenueStore")
```

### Docstring decision-tag citation
**Source:** every analog read — `venue_store.py:1-24`, `bundle.py:1-30`, `provider.py:1-29`
**Apply to:** all new/modified modules. Tags (`D-05`, `MPORT-07`, `F-1`, `WR-04`) are
load-bearing references to planning artifacts — preserve the style. Every analog module
docstring also **declares its own indentation** on the last line; new files should too.

### Money = Decimal
**Apply to:** `portfolios.initial_cash`, any balance crossing the venue edge.
Enter via `to_money(str(x))` (`core/money.py`); never `Decimal(float)`. `float()` only at the
serialization/logging edge — note the analogs log money as `str(engine_qty)`
(`reconciliation_coordinator.py:213-214`), not `float(...)`.

### IDs
`portfolio_id` stays UUIDv7 via the `idgen` singleton. F-1 makes it **supplyable**, never
re-schemed. `venue_accounts` uses a **natural composite key** — no surrogate id (D-06/P4 D-06;
`venue_store.py:6` explicitly notes "``idgen`` never imported").

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| The D-09 config **data-movement** step in rev 2 | migration | data-transform | No prior migration in the chain moves *data* between tables — every existing revision is pure DDL (verified across all 11 revisions). `p10_strategy_portfolio_subs.py` supplies the guard + `batch_alter_table` shape but has no data-move arm. Use RESEARCH Item 2's four preservation conditions as the spec instead. |
| CONTROL verb + route for D-23 quarantine release | route/handler | event-driven | CONTEXT names `LiveRouteRegistrar` as supporting it, but no existing operator-release CONTROL verb was found to copy (`reset_halt()` is a facade method, not a CONTROL command). Planner should locate the registrar's existing verb registrations during W6 planning. |

---

## Cross-Cutting Warnings for the Planner

1. **Indentation:** three modified files are TABS (`execution_handler.py`, `okx.py`,
   `venue_correlation.py`, `admission_manager.py`, `portfolio.py`, `system_spec.py`) while
   their pattern-analogs are 4-space. Transcribe the *pattern*, retype the whitespace.
   Verification gates must scan **added diff lines only** — a whole-file "no space-indented
   lines" check false-fails on untouched TAB files (wrapped docstring prose is space-aligned).
2. **F-5:** `Portfolio.__init__` and `add_portfolio` need `portfolio_id` (F-1) + `account_id`
   (D-06) + `venue_name`-derived `exchange` (D-07) — **one signature change each**, spanning
   `portfolio.py` (TABS) and `portfolio_handler.py` (4-space). New params **must default** so
   `backtest_trading_system.py:517` is untouched (oracle).
3. **Oracle-gated edits:** D-27's `PortfolioReadModel` injection into `ExecutionHandler` and
   F-5's `add_portfolio` params are both on the backtest-shared path. Run
   `tests/integration/test_backtest_oracle.py` on **every** commit in W3/W4.
4. **`live_trading_system.py` is under mypy `ignore_errors`** — dead code and orphaned imports
   pass both mypy and the suite. Sweep by grep after D-13's deletion.

---

## Metadata

**Analog search scope:** `itrader/storage/`, `itrader/venues/`, `itrader/connectors/`,
`itrader/portfolio_handler/`, `itrader/execution_handler/`, `itrader/trading_system/`,
`itrader/core/`, `migrations/versions/`, `tests/integration/`
**Files read in full:** 6 (`venue_store.py`, `p10_strategy_portfolio_subs.py`, `bundle.py`,
`okx_plugin.py`, `paper_plugin.py`, `provider.py`, `reconciliation_coordinator.py`)
**Files read targeted:** 9 (non-overlapping ranges)
**Indentation measured (bytes):** 18 files
**Pattern extraction date:** 2026-07-21
</content>
</invoke>
