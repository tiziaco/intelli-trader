"""D-25 — the phase's own end-to-end proof that multi-portfolio live actually works.

The gap this closes: every upstream plan in Phase 11 built a *piece* of the
multi-portfolio surface — per-account bundles (11-07), the definition-row writer +
rehydrate (11-08), the per-portfolio venue-account attach (11-09) — but nothing had
ever driven the WHOLE path end to end: two portfolios trading INDEPENDENTLY against
their own accounts, a fill reaching exactly the RIGHT portfolio, and the ids surviving
a real restart. This file is that proof, and it is deliberately built to be able to
FAIL — a green suite that does not actually demonstrate independent trading is worse
than a red one (T-11-61).

The proof is split into two tests of DIFFERENT natures, because a single offline paper
recipe cannot honestly carry all of it:

  * **Tasks 1 & 2 — OFFLINE, TWO PAPER ACCOUNTS, always run.** Independent sizing and
    fill-attribution-with-the-negative. Paper accounts are compute
    (``SimulatedCashAccount``): ``.cash`` is readable immediately, no Docker, no
    credentials, no network. Built on the offline ``build_paper_replay_system`` seam.
    The load-bearing sizing assertion is ``qty_A != qty_B BECAUSE cash_A != cash_B`` —
    the two paper portfolios are given DIFFERENT starting cash, so a bug that sized both
    against one account could not pass silently. (Two non-identical account objects is a
    VACUOUS fact — every ``add_portfolio`` builds its own ``SimulatedCashAccount`` — so
    it is asserted only as a secondary check, never as co-equal proof.)

  * **Task 3 — POSTGRES-GATED, REAL TEARDOWN + REBUILD.** The restart proof. It creates
    two portfolios through the REAL ``add_portfolio`` on a real booted engine, tears the
    engine down, boots a SECOND ``build_live_system`` over the SAME database, and asserts
    the ids came back FROM THE DEFINITION ROWS — not by object reuse. It is Postgres-gated
    and ``pytest.skip``s when Docker is unavailable, exactly like every other live-SQL
    gate. It reads ``initial_cash`` and the config blob off the definition ROW, never
    ``portfolio.cash`` — the rebuilt portfolio holds a venue-truth account whose ``.cash``
    raises until the first snapshot (D-15/11-09).

**Why paper cannot — and must not pretend to — prove per-account exchange routing (F-3).**
The live composition root hands the paper plugin the ALREADY-BUILT shared simulated
exchange, so two paper accounts necessarily resolve to ONE exchange object. A per-account
routing assertion here would PASS while proving nothing, which is worse than no test. That
gate lives in ``tests/integration/test_per_account_exchange_routing.py`` (plan 11-06) with
a FAKE multi-account venue plugin. This file deliberately makes NO routing assertion.

**Resting-book interference (flagged for the bracket cases).** Plan 11-07's summary left
the shared matching-engine question open; plan 11-10 (ITEM 2) recorded the answer:
cross-portfolio OCO isolation is safe because ``parent_order_id`` is a globally-unique
``OrderId`` and the engine carries zero ``portfolio_id`` awareness. To keep these gates
deterministic and side-step the resting book entirely, the offline cases use plain MARKET
orders with NO bracket (stop_loss/take_profit = 0) — a MARKET order rests one bar and
fills at the next bar's open, with no OCO sibling scan involved.

4-space indentation. The ``integration`` marker is folder-derived, so this file declares
no marker of its own, and ``tests/integration/`` has no ``__init__.py``.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from itrader import idgen
from itrader.core.bar import Bar
from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.core.money import to_money
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from itrader.strategy_handler.base import Strategy
from tests.support.replay_harness import build_paper_replay_system

_SYMBOL = "AAAUSD"
_BASE_MS = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
_DAY_MS = 86_400_000
_SIGNAL_TIME = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)


# ===========================================================================
# Tasks 1 & 2 — OFFLINE, two paper accounts on the shared simulated venue
# ===========================================================================


class _AlwaysBuy(Strategy):
    """Minimal LONG_ONLY strategy that always signals BUY — the fan-out probe.

    Underscore-prefixed so pytest never collects it; ``max_window`` is wide enough for
    the synthetic bar and ``warmup`` stays 0, so ``on_bar`` always reaches
    ``generate_signal`` and the real per-portfolio fan-out loop runs.
    """

    name = "always_buy"
    max_window: int = 1

    def __init__(self) -> None:
        super().__init__(
            timeframe="1d",
            tickers=[_SYMBOL],
            sizing_policy=FractionOfCash(Decimal("0.5")),
            direction=TradingDirection.LONG_ONLY,
        )

    def generate_signal(self, ticker: str):
        return self.buy(ticker)


class _PaperPair:
    """Two paper portfolios on ONE offline ``build_paper_replay_system`` engine.

    Both portfolios name ``DEFAULT_ACCOUNT_ID`` and therefore resolve to the single
    ``('simulated', 'default')`` exchange object — the F-3 reality this test is built
    around, NOT a bug: the per-account routing gate lives elsewhere (see the module
    docstring). What differs between the two portfolios is their CASH, and each holds its
    OWN ``SimulatedCashAccount`` compute leaf.

    Underscore-prefixed so pytest never collects it.
    """

    def __init__(self, system) -> None:
        self.system = system
        exchange = system.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)]
        exchange.register_symbol(_SYMBOL)
        system.feed.bind(system.global_queue, [_SYMBOL])
        self._next_ts = _BASE_MS

    def add_portfolio(self, name: str, cash: Decimal) -> PortfolioId:
        return self.system.portfolio_handler.add_portfolio(
            name=name, exchange="simulated", cash=cash, account_id=DEFAULT_ACCOUNT_ID)

    def portfolio(self, portfolio_id: PortfolioId):
        return self.system.portfolio_handler.get_portfolio(portfolio_id)

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        return self.system.portfolio_handler.available_cash(portfolio_id)

    def _signal(self, portfolio_id: PortfolioId, action: Side, price: str) -> SignalEvent:
        # A bracket-free MARKET signal (stop_loss/take_profit = 0). LONG_SHORT is legal
        # here because a directly-constructed SignalEvent bypasses the add_strategy
        # short-selling gate; sizing is FractionOfCash(0.5) of THIS portfolio's own cash.
        return SignalEvent(
            time=_SIGNAL_TIME,
            order_type=OrderType.MARKET,
            ticker=_SYMBOL,
            action=action,
            price=to_money(price),
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            strategy_id=StrategyId(idgen.generate_strategy_id()),
            portfolio_id=portfolio_id,
            sizing_policy=FractionOfCash(fraction=Decimal("0.5")),
            direction=TradingDirection.LONG_SHORT,
            exit_fraction=Decimal("1"),
        )

    def drive_bar(self, price: str = "100") -> None:
        """Push one flat closed bar through the real feed→queue seam and drain it.

        A resting MARKET order fills at this bar's open (next-bar-open contract). The
        monotonic feed guard requires a strictly-increasing timestamp per symbol.
        """
        closed = {
            "ts": self._next_ts,
            "open": to_money(price),
            "high": to_money(price),
            "low": to_money(price),
            "close": to_money(price),
            "volume": to_money("1"),
            "symbol": _SYMBOL,
            "timeframe": "1d",
        }
        self._next_ts += _DAY_MS
        self.system.feed.update(closed)
        self.system.event_handler.process_events()

    def open_long(self, portfolio_id: PortfolioId, price: str = "100") -> None:
        """Real path: BUY market rests this cycle, fills at the next bar's open."""
        self.system.global_queue.put(self._signal(portfolio_id, Side.BUY, price))
        self.system.event_handler.process_events()   # order rests in the book
        self.drive_bar(price)                         # next-bar-open fill

    def position_qty(self, portfolio_id: PortfolioId) -> Decimal:
        position = self.portfolio(portfolio_id).get_open_position(_SYMBOL)
        return position.net_quantity if position is not None else Decimal("0")

    def snapshot(self, portfolio_id: PortfolioId) -> tuple:
        """A byte-comparable snapshot of a portfolio's money state (the negative)."""
        portfolio = self.portfolio(portfolio_id)
        return (
            portfolio.account.balance,
            portfolio.account.available_balance,
            self.position_qty(portfolio_id),
            len(portfolio.transactions),
            portfolio.n_open_positions,
        )


@pytest.fixture
def paper_pair():
    """An offline two-paper-portfolio harness; drains and stops on teardown."""
    system, _ = build_paper_replay_system()
    pair = _PaperPair(system)
    try:
        yield pair
    finally:
        system.stop(timeout=5.0)


# --- Task 1: two paper accounts trading independently (D-25 / MPORT-03) ------


def test_two_paper_portfolios_hold_two_distinct_account_objects(paper_pair) -> None:
    """Two portfolios, two distinct ``SimulatedCashAccount`` leaves.

    This is a SECONDARY (deliberately near-vacuous) check: every ``add_portfolio``
    builds its own account regardless of ``account_id``, so non-identity here proves
    little on its own. The load-bearing independence proof is the differing order
    quantities from differing cash in ``test_each_portfolio_sizes_against_its_own_cash``.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    pf_a = paper_pair.portfolio(pid_a)
    pf_b = paper_pair.portfolio(pid_b)

    assert pf_a.account is not pf_b.account
    # Each holds its OWN starting cash, readable immediately (compute leaf, not venue).
    assert paper_pair.available_cash(pid_a) == Decimal("100000.00")
    assert paper_pair.available_cash(pid_b) == Decimal("50000.00")


def test_one_signal_fans_out_to_each_subscribed_portfolio(paper_pair) -> None:
    """One strategy intent → exactly one ``SignalEvent`` per subscribed portfolio.

    Drives the REAL ``StrategiesHandler.on_bar`` fan-out loop on the system's own
    handler; the loop iterates ``strategy.subscribed_portfolios`` and stamps one event
    per portfolio id. Mutation: subscribe only one portfolio → only one event → RED.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    strategy = _AlwaysBuy()
    strategy.subscribe_portfolio(pid_a)
    strategy.subscribe_portfolio(pid_b)
    paper_pair.system.strategies_handler.add_strategy(strategy)

    bar = Bar(time=_SIGNAL_TIME, open=Decimal("100"), high=Decimal("100"),
              low=Decimal("100"), close=Decimal("100"), volume=Decimal("1"))
    paper_pair.system.strategies_handler.on_bar(BarEvent(time=_SIGNAL_TIME, bars={_SYMBOL: bar}))

    # Non-destructive snapshot of the priority bus (its PriorityQueue is at ._pq holding
    # (tier, seq, event) tuples; a plain Queue exposes .queue with bare events).
    bus = paper_pair.system.global_queue
    raw = getattr(bus, "_pq", bus)
    events = [item[2] if isinstance(item, tuple) else item
              for item in list(getattr(raw, "queue", []))]
    signals = [e for e in events if isinstance(e, SignalEvent)]

    assert len(signals) == 2
    assert {s.portfolio_id for s in signals} == {pid_a, pid_b}
    assert {s.strategy_id for s in signals} == {strategy.strategy_id}


def test_each_portfolio_sizes_against_its_own_cash(paper_pair) -> None:
    """THE load-bearing independence gate: qty_A != qty_B BECAUSE cash_A != cash_B.

    Portfolio A starts with exactly twice B's cash. With the SAME FractionOfCash(0.5)
    policy and the SAME fill price, each portfolio must size against ITS OWN balance —
    so A's filled quantity is exactly twice B's. Mutations that make it RED: give both
    the same cash (quantities become equal); size both against one account (equal).
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    paper_pair.open_long(pid_a, price="100")
    paper_pair.open_long(pid_b, price="100")

    qty_a = paper_pair.position_qty(pid_a)
    qty_b = paper_pair.position_qty(pid_b)

    assert qty_a > 0 and qty_b > 0
    # Different balances → different quantities. This is the assertion that fails if a
    # bug sizes both portfolios against a single account.
    assert qty_a != qty_b
    # And the difference tracks the cash difference EXACTLY (2:1), which is what "sizes
    # against its own account" means: 0.5 * 100000 / 100 = 500, 0.5 * 50000 / 100 = 250.
    assert qty_a == Decimal("500.000")
    assert qty_b == Decimal("250.000")
    assert qty_a == qty_b * 2


def test_draining_one_portfolios_cash_leaves_the_other_able_to_order(paper_pair) -> None:
    """Exhausting A's buying power does not touch B's ability to size and fill.

    A spends its whole balance (FractionOfCash(1.0)); B then still fills a fresh order
    against its own untouched cash. A shared-cash bug would starve B here.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    # Drain A: put a full-cash BUY, rest it, fill it.
    drain = SignalEvent(
        time=_SIGNAL_TIME, order_type=OrderType.MARKET, ticker=_SYMBOL, action=Side.BUY,
        price=to_money("100"), stop_loss=Decimal("0"), take_profit=Decimal("0"),
        strategy_id=StrategyId(idgen.generate_strategy_id()), portfolio_id=pid_a,
        sizing_policy=FractionOfCash(fraction=Decimal("1")),
        direction=TradingDirection.LONG_SHORT, exit_fraction=Decimal("1"))
    paper_pair.system.global_queue.put(drain)
    paper_pair.system.event_handler.process_events()
    paper_pair.drive_bar("100")

    assert paper_pair.available_cash(pid_a) == Decimal("0.00")
    b_cash_before = paper_pair.available_cash(pid_b)

    # B is unaffected and still orders and fills against its own balance.
    paper_pair.open_long(pid_b, price="100")
    assert paper_pair.position_qty(pid_b) == Decimal("250.000")
    # B's available cash dropped by ITS OWN fill only, not by A's drain.
    assert paper_pair.available_cash(pid_b) == b_cash_before - Decimal("25000.00")


# --- Task 2: fill attribution, with the negative asserted (MPORT-04) ---------


def test_a_fill_for_a_changes_a_and_leaves_b_byte_unchanged(paper_pair) -> None:
    """A's fill mutates A and leaves B byte-for-byte unchanged — the NEGATIVE.

    Asserting only that A received the fill does not exclude B ALSO being mutated, which
    is exactly the accounting corruption two-key attribution exists to prevent (T-11-58).
    B's cash, positions and transaction count are snapshotted BEFORE A's fill and
    compared after.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    a_before = paper_pair.snapshot(pid_a)
    b_before = paper_pair.snapshot(pid_b)

    paper_pair.open_long(pid_a, price="100")

    # A changed.
    assert paper_pair.snapshot(pid_a) != a_before
    assert paper_pair.position_qty(pid_a) == Decimal("500.000")
    # B is byte-for-byte unchanged — asserted, not inferred.
    assert paper_pair.snapshot(pid_b) == b_before


def test_a_fill_for_b_changes_b_and_leaves_a_byte_unchanged(paper_pair) -> None:
    """The reverse direction — B's fill leaves A untouched (attribution is symmetric)."""
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    a_before = paper_pair.snapshot(pid_a)
    b_before = paper_pair.snapshot(pid_b)

    paper_pair.open_long(pid_b, price="100")

    assert paper_pair.snapshot(pid_b) != b_before
    assert paper_pair.position_qty(pid_b) == Decimal("250.000")
    assert paper_pair.snapshot(pid_a) == a_before


def test_two_portfolios_hold_independent_positions_in_the_same_symbol(paper_pair) -> None:
    """Both portfolios hold their OWN position in one symbol — separate quantities.

    Two portfolios trading one symbol is the most likely place a shared-state bug hides;
    the positions must stay independent, sized from each portfolio's own cash.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    paper_pair.open_long(pid_a, price="100")
    paper_pair.open_long(pid_b, price="100")

    pos_a = paper_pair.portfolio(pid_a).get_open_position(_SYMBOL)
    pos_b = paper_pair.portfolio(pid_b).get_open_position(_SYMBOL)

    assert pos_a is not None and pos_b is not None
    assert pos_a is not pos_b
    assert pos_a.net_quantity == Decimal("500.000")
    assert pos_b.net_quantity == Decimal("250.000")


def test_the_durable_order_row_carries_the_ordering_portfolio_id(paper_pair) -> None:
    """Each filled order in the mirror carries its ordering portfolio's id.

    The order-row ``portfolio_id`` is the second independent attribution mechanism — the
    one that survives a process restart. Each portfolio's FILLED order names ONLY that
    portfolio, never the other.
    """
    pid_a = paper_pair.add_portfolio("pf_a", Decimal("100000"))
    pid_b = paper_pair.add_portfolio("pf_b", Decimal("50000"))

    paper_pair.open_long(pid_a, price="100")
    paper_pair.open_long(pid_b, price="100")

    manager = paper_pair.system.order_handler.order_manager
    filled_a = manager.get_orders_by_status(OrderStatus.FILLED, pid_a)
    filled_b = manager.get_orders_by_status(OrderStatus.FILLED, pid_b)

    assert len(filled_a) == 1 and len(filled_b) == 1
    assert {o.portfolio_id for o in filled_a} == {pid_a}
    assert {o.portfolio_id for o in filled_b} == {pid_b}
    # And they are genuinely different orders attributed to different portfolios.
    assert filled_a[0].id != filled_b[0].id


# ===========================================================================
# Task 3 — POSTGRES-GATED, a REAL teardown + rebuild (D-25 / F-1 / D-08)
#
# Everything below drives the REAL build_live_system twice over the SAME database. The
# fixture machinery (live_db / _spec / okx_env / seeding) is copied from
# test_distinct_account_invariant.py / test_multi_account_composition.py — it lives
# INLINE there, not in a shared conftest. These gates are Postgres-gated and SKIP when
# Docker is unavailable (D-11), exactly like every other live-SQL gate. Docker IS up in
# the phase environment, so they RUN.
# ===========================================================================

from itrader.config.sql import SqlDriver, SqlSettings  # noqa: E402
from itrader.core.sizing import FractionOfCash as _FractionOfCash  # noqa: E402,F811
from itrader.storage import SqlEngine  # noqa: E402
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore  # noqa: E402
from itrader.storage.strategy_registry_store import StrategyRegistryStore  # noqa: E402
from itrader.storage.venue_account_store import VenueAccountStore  # noqa: E402
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy  # noqa: E402
from itrader.trading_system.live_trading_system import build_live_system  # noqa: E402
from itrader.trading_system.system_spec import PortfolioSpec, SystemSpec  # noqa: E402
from itrader.trading_system.venue_spec import build_venue_spec  # noqa: E402
from tests.support.replay_harness import TestDataPlugin  # noqa: E402
from tests.support.schema import provision_schema, seed_portfolio_definitions  # noqa: E402
from tests.support.strategy_catalog import seeded_registry_rows, test_catalog  # noqa: E402

_AT = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
_VENUE = "okx"


@pytest.fixture
def okx_env(monkeypatch):
    """A stubbed OKX credential triple — enough to construct connectors offline.

    ``OkxConnector`` construction is I/O-free (``connect()`` is deferred to ``start()``),
    so this drives the whole composition root with no socket.
    """
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def _spec(account_ids, primary=None):
    """A ``SystemSpec`` whose PORTFOLIOS name the accounts (MPORT-05)."""
    return SystemSpec(
        start="2024-01-01", end="2024-01-02", timeframe="1d", ticker="BTCUSDT",
        starting_cash=10_000, data={}, strategies=[],
        portfolios=[
            PortfolioSpec(name=f"pf-{index}", cash=10_000, account_id=account_id)
            for index, account_id in enumerate(account_ids)
        ],
        execution_venue=_VENUE,
        account_id=primary,
    )


@pytest.fixture
def live_db(pg_database_env):
    """A handle on the SAME database ``build_live_system`` builds its own engine on.

    Purges portfolios + accounts before and after: the container is session-scoped, and
    the composite FK from ``portfolios`` onto ``venue_accounts`` means a leaked row makes
    the next test's account upsert fail with a foreign-key violation rather than anything
    that points at the real cause.
    """
    engine = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
    PortfolioDefinitionStore(engine)
    VenueAccountStore(engine)
    # Register the strategy stores too so their tables land on this engine's metadata —
    # ``provision_schema`` then creates all four, and ``_purge`` can clear the strategy
    # subscription/registry rows the 3b subscription-rebind test seeds.
    StrategyRegistryStore(engine)
    provision_schema(engine)
    _purge(engine)
    try:
        yield engine
    finally:
        _purge(engine)
        engine.dispose()


def _purge(engine) -> None:
    """Drop every portfolio + account row so the session-scoped container stays clean."""
    metadata = engine.metadata
    with engine.engine.begin() as connection:
        connection.execute(metadata.tables["strategy_portfolio_subscriptions"].delete())
        connection.execute(metadata.tables["strategy_registry"].delete())
        connection.execute(metadata.tables["portfolios"].delete())
        connection.execute(metadata.tables["venue_accounts"].delete())


def _seed_venue_account(engine, account_id: str) -> None:
    """Seed the ``venue_accounts`` parent row an ``add_portfolio`` definition write FKs onto."""
    VenueAccountStore(engine).upsert(
        _VENUE, account_id, secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)


# --- Task 3a — the real restart: stable ids + persisted cash and config ------


def test_a_full_restart_returns_both_portfolios_with_stable_ids(live_db, okx_env) -> None:
    """THE restart proof (F-1/D-08): two portfolios survive a full teardown + rebuild.

    Both portfolios are created through the REAL ``add_portfolio`` on a real booted
    engine — the definition rows come from PRODUCTION's writer, not a fixture. A SECOND
    ``build_live_system`` over the SAME database must find both and return the SAME ids,
    with names, account ids, persisted cash and per-portfolio config read BACK OFF THE
    DEFINITION ROWS. ``initial_cash`` is read off the row, never ``portfolio.cash`` — the
    rebuilt account is venue-truth and raises until the first snapshot (D-15/11-09).
    """
    _seed_venue_account(live_db, "acct-a")
    _seed_venue_account(live_db, "acct-b")

    # --- first boot: create BOTH portfolios through the live handler ----------
    system = build_live_system(_spec([]))
    try:
        id_a = system.portfolio_handler.add_portfolio(
            name="pf-a", exchange=_VENUE, cash=Decimal("25000.00"),
            account_id="acct-a", venue_name=_VENUE)
        id_b = system.portfolio_handler.add_portfolio(
            name="pf-b", exchange=_VENUE, cash=Decimal("70000.00"),
            account_id="acct-b", venue_name=_VENUE)
    finally:
        system.stop(timeout=5.0)

    # Persist a distinctive NON-DEFAULT per-portfolio config blob on each definition row
    # (D-09). A non-null check would be worthless: the layering consumer guards on
    # truthiness and degrades to a warning, so a lost config yields a green suite and
    # silently default-config portfolios (T-11-60). We compare the VALUE.
    store = PortfolioDefinitionStore(live_db)
    store.upsert(id_a, name="pf-a", venue_name=_VENUE, account_id="acct-a",
                 initial_cash=Decimal("25000.00"), enabled=True,
                 config={"limits": {"max_positions": 7}}, at=_AT)
    store.upsert(id_b, name="pf-b", venue_name=_VENUE, account_id="acct-b",
                 initial_cash=Decimal("70000.00"), enabled=True,
                 config={"limits": {"max_positions": 9}}, at=_AT)

    # --- restart: a brand-new engine over the SAME database -------------------
    system2 = build_live_system(_spec([]))
    try:
        # Both ids came back FROM THE DEFINITION ROWS (rehydrate reads portfolio_id ASC;
        # UUIDv7 is monotonic, so id_a precedes id_b).
        assert set(system2.portfolio_handler._portfolios) == {id_a, id_b}, (
            "a portfolio did not survive the restart — either add_portfolio persisted no "
            "definition row, or rehydrate minted a fresh id")

        pf_a = system2.portfolio_handler.get_portfolio(id_a)
        pf_b = system2.portfolio_handler.get_portfolio(id_b)
        assert (pf_a.name, pf_a.account_id) == ("pf-a", "acct-a")
        assert (pf_b.name, pf_b.account_id) == ("pf-b", "acct-b")

        rows = {r["portfolio_id"]: r for r in PortfolioDefinitionStore(live_db).read_all()}
        # Persisted cash reattaches — read off the ROW (never portfolio.cash, D-15).
        assert rows[id_a]["initial_cash"] == Decimal("25000.00")
        assert rows[id_b]["initial_cash"] == Decimal("70000.00")
        # Config survives BY VALUE (equality, not a non-null check).
        assert rows[id_a]["config"] == {"limits": {"max_positions": 7}}
        assert rows[id_b]["config"] == {"limits": {"max_positions": 9}}

        # And the layering applied that surviving config to the live portfolio object.
        assert pf_a.config.limits.max_positions == 7
        assert pf_b.config.limits.max_positions == 9
    finally:
        system2.stop(timeout=5.0)


# --- Task 3b — strategy subscriptions rebind to the SAME ids across a restart -


def _build_paper(**kwargs):
    """Build a paper live system through the REAL factory with the replay data plugin.

    Mirrors ``build_paper_replay_system`` but calls ``build_live_system`` directly so the
    ``strategy_catalog`` injection seam is exercised as production would reach it — the
    same helper ``test_strategy_registry_restart.py`` uses.
    """
    plugin = TestDataPlugin()
    spec = build_venue_spec("paper", data_provider="replay")
    return build_live_system(spec, data_plugins={"replay": plugin}, **kwargs)


def _seed_strategy(store: StrategyRegistryStore, strategy, portfolio_ids) -> None:
    """Seed a strategy registry row + its portfolio-subscription child rows.

    The subscription child FKs onto ``portfolios`` (ON DELETE CASCADE), so every
    subscribed id needs a real definition row first — ``seed_portfolio_definitions`` is
    the one helper that knows the minimum row shape.
    """
    registry_rows, subscription_rows = seeded_registry_rows([strategy])
    for row in registry_rows:
        store.upsert(row["strategy_name"], row["strategy_type"], row["config_json"],
                     row["enabled"], _AT)
    seed_portfolio_definitions(store.backend, list(portfolio_ids))
    for portfolio_id in portfolio_ids:
        store.add_portfolio_subscription(strategy.name, portfolio_id)


def test_a_strategy_subscription_rebinds_to_the_same_portfolio_ids_across_a_restart(
    live_db,
) -> None:
    """MPORT-03 fan-out survives the restart: subscriptions rebind to the SAME ids.

    A strategy subscribed to TWO portfolio ids is seeded into the durable registry along
    with those portfolios' definition rows. The first boot rehydrates it subscribed to
    both; a full teardown + rebuild resumes it subscribed to the SAME two ids, so the
    per-portfolio fan-out still reaches both portfolios. Before this phase those persisted
    subscription rows dangled after every restart.
    """
    id_a = PortfolioId(uuid.uuid4())
    id_b = PortfolioId(uuid.uuid4())
    store = StrategyRegistryStore(
        SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)))
    provision_schema(store.backend)
    try:
        strategy = SMAMACDStrategy(
            timeframe="1d", tickers=["BTCUSD"],
            sizing_policy=_FractionOfCash(Decimal("0.75")))
        strategy.name = "sma_macd"
        strategy.subscribe_portfolio(id_a)
        strategy.subscribe_portfolio(id_b)
        _seed_strategy(store, strategy, [id_a, id_b])

        expected = {str(id_a), str(id_b)}

        # --- first boot -------------------------------------------------------
        system = _build_paper(strategy_catalog=test_catalog())
        try:
            registered = system.strategies_handler.strategies
            assert [s.name for s in registered] == ["sma_macd"]
            assert set(str(p) for p in registered[0].subscribed_portfolios) == expected
            # Portfolios exist BEFORE start() — the ordering constraint, non-vacuous:
            # the ids the strategy re-subscribed to are the ids that actually rehydrated.
            assert set(system.portfolio_handler._portfolios) == {id_a, id_b}
        finally:
            system.stop(timeout=5.0)

        # --- restart: a brand-new engine over the SAME database ---------------
        system2 = _build_paper(strategy_catalog=test_catalog())
        try:
            resumed = system2.strategies_handler.strategies
            assert [s.name for s in resumed] == ["sma_macd"]
            assert set(str(p) for p in resumed[0].subscribed_portfolios) == expected
            assert set(system2.portfolio_handler._portfolios) == {id_a, id_b}
        finally:
            system2.stop(timeout=5.0)
    finally:
        store.delete("sma_macd")
        store.dispose()
