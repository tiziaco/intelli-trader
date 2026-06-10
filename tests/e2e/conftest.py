"""Shared end-to-end (E2E) scenario harness (Phase 4 — e2e-harness-framework).

This is the SINGLE shared infrastructure every scenario phase (6-9) and the Plan
03 canary consume. A Phase 6-9 author adds a scenario by editing ONLY their own
leaf folder (a per-folder ``scenario.py`` + a ``golden/`` subdir) — NEVER this
conftest, and never a shared collector/registry. The framework is parallel-safe by
construction: there is no central list of scenarios to edit.

What ``run_scenario`` does (the build→run→read→assemble→diff contract)
----------------------------------------------------------------------
Given a leaf directory ``here`` it:

1. imports the leaf's ``scenario.py`` ``ScenarioSpec`` (in-process, module name
   derived from the FULL leaf path relative to ``tests/e2e/`` and registered in
   ``sys.modules`` under that unique name so two leaves — even same-named ones in
   different parents — never shadow each other — Pitfall 4);
2. wires a real ``TradingSystem`` from the spec (the SAME engine the oracle uses —
   D-03: no parallel/reinvented config schema, the spec carries the real engine
   config objects: strategies, portfolios, window, data path);
3. runs it (``print_summary=False``);
4. reads portfolio state AFTER the run (queue-only — D-07, no mid-run cross-domain
   reads);
5. assembles ``trades`` / ``equity`` / ``summary`` via the SHARED serialization path
   ``itrader.reporting.summary`` (Plan 01, D-16) so the oracle generator and this
   harness cannot drift;
6. DIFFS those artifacts against the leaf's ``golden/`` subfolder using the oracle's
   exact, NO-tolerance ``assert_frame_equal`` mechanic (D-08), diffing ONLY the
   golden files PRESENT (D-05: presence = assertion).

Results stay in memory (D-07) — there is no ``output/`` folder in a leaf. Any disk
debugging uses pytest ``tmp_path`` only, never the committed ``golden/``.

The ``--freeze`` regen discipline (E2E-04 / D-13 — read before using)
---------------------------------------------------------------------
Without ``--freeze`` the harness DIFFS and FAILS on any drift — goldens NEVER
auto-heal (T-04-03). ``--freeze`` is the deliberate, OFF-by-default regen flag that
WRITES goldens (chosen over an env var — RESEARCH alt-table). Discipline (Pitfall 5):
freeze ONE scenario at a time, after HAND-VERIFYING its expected fills/PnL, and
commit it WITH a VERIFY note. A regression-lock proves *stability*, not
*correctness* — verification happens once, before the freeze, never via a blind
12-scenario ``--freeze`` sweep.

OPEN Q1 — the ``spec.exchange`` fee/slippage seam (deferred to Phase 7)
-----------------------------------------------------------------------
``TradingSystem(exchange="csv")`` ignores fee/slippage at construction. When a spec
carries a non-None ``exchange`` (an ``ExchangeConfig``) the harness applies it
post-construction, pre-``run()`` via
``system.execution_handler.exchanges['simulated'].update_config(**fields)``. The
Plan 03 canary's ``spec.exchange`` is None → this is a no-op today; the real
fee/slippage threading is Phase 7 work.

Indentation: 4 spaces (matches ``tests/conftest.py``).
"""

import importlib.util
import io
import json
import pathlib
import sys

import pandas as pd
import pandas.testing as pdt
import pytest

from itrader.core.enums.order import OrderStatus
from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.reporting.orders import (
    ORDER_SNAPSHOT_COLUMNS,
    build_orders_snapshot,
)
from itrader.reporting.summary import (
    FLOAT_FORMAT,
    SLIPPAGE_COLUMNS,
    attach_slippage,
    build_metrics_block,
    build_summary,
)


# --- Commission golden column (D-07/D-08, oracle-dark, ALWAYS-ON) ------------
# A conftest-LOCAL column: the per-trade commission sourced from the real
# Position.commission property (buy_commission + sell_commission, position.py:131).
# It is appended after SLIPPAGE_COLUMNS in the E2E trade goldens ONLY — it is
# DELIBERATELY NOT added to itrader.reporting.frames.TRADE_COLUMNS, because that
# pin feeds scripts/run_backtest.py + the BTCUSD oracle (test_backtest_oracle.py),
# which must stay byte-exact (oracle-dark, D-08). Always-on: written for every
# leaf, including zero-fee exchange=None leaves (commission=0.00).
COMMISSION_COLUMN = ["commission"]


# --- Exact-diff column contract (reused VERBATIM from the oracle, D-08) ------
# Identity columns are the behavioral law (which trade, which bar); the remaining
# columns are auto-derived numeric and diffed EXACT. NO float tolerance — a
# tolerance would mask real regressions (T-04-04 / the oracle abandoned tolerance).
_TRADE_IDENTITY_COLUMNS = ["entry_date", "exit_date", "side", "pair"]
_EQUITY_IDENTITY_COLUMNS = ["timestamp"]
# Orders-snapshot identity (Phase 6, D-08): which logical order on which ticker.
_ORDERS_IDENTITY_COLUMNS = ["role", "ticker", "order_type", "action"]
# Sort keys used before comparing (stable order, independent of insertion order).
_TRADE_SORT_KEYS = ["entry_date", "exit_date", "side"]
_EQUITY_SORT_KEYS = ["timestamp", "total_equity"]
# IN-02: ``time`` is a frozen golden identity column but is omitted from the
# identity/sort keys above; append it as a TRAILING sort key so row alignment is
# fully determined even when role/order_type/action/price collide on the same
# ticker (otherwise the tiebreak is non-deterministic and the row-aligned diff
# could spuriously fail).
_ORDERS_SORT_KEYS = ["role", "order_type", "action", "price", "time"]


def pytest_addoption(parser):
    """Register the deliberate ``--freeze`` golden-regen flag (E2E-04 / D-13).

    OFF by default: default runs DIFF and fail on drift. ``--freeze`` WRITES the
    leaf's goldens — use one scenario at a time, after hand-verifying it (Pitfall 5).
    """
    parser.addoption(
        "--freeze",
        action="store_true",
        default=False,
        help="WRITE e2e golden fixtures instead of diffing them (E2E-04). "
        "OFF by default; goldens never auto-heal. Freeze one hand-verified "
        "scenario at a time (Pitfall 5).",
    )


def _load_spec(scenario_path):
    """Import a leaf's ``scenario.py`` in-process and return its ``SCENARIO`` spec.

    Generalizes the oracle's ``_load_run_backtest_module`` (Don't Hand-Roll). The
    module name is derived from the FULL leaf path (relative to ``tests/e2e/``) so
    two leaves with the same folder name in different parents — e.g.
    ``smoke/single_market_buy`` and a future ``regression/single_market_buy`` —
    never collide, and the module is registered in ``sys.modules`` under that
    unique name so the advertised collision-prevention is actually engaged
    (Pitfall 4).
    """
    scenario_path = pathlib.Path(scenario_path)
    if not scenario_path.exists():
        pytest.fail(f"scenario spec missing: {scenario_path}")
    # Unique module name per leaf: derive from the full leaf path relative to this
    # conftest's directory (tests/e2e/) so two leaves with the same folder name in
    # different parents produce DISTINCT module names (Pitfall 4). Fall back to the
    # leaf folder name if the scenario lives outside the e2e tree.
    try:
        rel = scenario_path.parent.relative_to(pathlib.Path(__file__).parent)
        suffix = "_".join(rel.parts)
    except ValueError:
        suffix = scenario_path.parent.name
    module_name = f"e2e_scenario_{suffix}"
    spec = importlib.util.spec_from_file_location(module_name, scenario_path)
    assert spec is not None and spec.loader is not None, f"cannot load {scenario_path}"
    module = importlib.util.module_from_spec(spec)
    # Register under the unique name BEFORE exec so dataclass pickling and any
    # intra-scenario relative imports resolve to this module (Pitfall 4) — the
    # mechanism the docstring/comments advertise is now actually engaged.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    # The leaf publishes its typed ScenarioSpec as ``SCENARIO`` (Plan 03 defines the
    # concrete class; the harness only reads its attributes — D-02 consuming contract).
    assert hasattr(module, "SCENARIO"), (
        f"{scenario_path} must expose a module-level SCENARIO (a ScenarioSpec)"
    )
    return module.SCENARIO


def _make_on_tick(spec, portfolio_id):
    """Translate ``spec.actions`` into an oracle-inert ``on_tick`` operator hook (D-06/D-07).

    Returns ``None`` when ``spec.actions`` is empty — no hook is wired, so the run
    stays byte-identical to today (oracle-dark). Otherwise returns an
    ``on_tick(system, time_event)`` that, on a scheduled bar-date hit, resolves the
    target by PREDICATE (ticker + the sole resting/PENDING order — D-07) and calls
    the REAL ``OrderHandler.modify_order``/``cancel_order`` round-trip (D-05). The
    resolved ``order.id`` (a UUIDv7) is passed — NEVER a literal int (GAP #2).
    """
    actions = getattr(spec, "actions", ())
    if not actions:
        return None  # oracle-inert: no actions → no hook wired (D-06)

    by_date: dict[str, list] = {}
    for action in actions:
        by_date.setdefault(action.bar_date, []).append(action)

    def on_tick(system, time_event):
        # WR-03: anchor the date key to a FIXED frame (UTC), independent of the
        # Settings.timezone default. csv_store localizes the bar index to TIMEZONE
        # (Europe/Paris), so a naive strftime would couple action.bar_date to that
        # default and roll to the wrong day near a boundary. tz_convert("UTC") here
        # and the matching conversion in ScriptedEmitter keep both producers and the
        # hand-authored action.bar_date strings anchored to the same UTC frame.
        key = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        for action in by_date.get(key, []):
            candidates = system.order_handler.get_orders_by_ticker(
                action.ticker, portfolio_id)
            resting = [o for o in candidates if o.status == OrderStatus.PENDING]
            # WR-01/WR-02: this is test infra, so a silently-skipped or
            # silently-failed operator round-trip must be a HARD failure — a green
            # test that never ran the scheduled action would defeat the operator
            # leaves. Assert exactly ONE PENDING order to honor the "sole resting
            # order" predicate (D-07) instead of arbitrarily picking the first.
            assert resting, (
                f"operator action {action.kind} on {action.ticker} @ {key}: "
                f"no PENDING order to target (check bar_date/ticker)")
            if len(resting) != 1:
                pytest.fail(
                    f"operator predicate expected exactly ONE PENDING "
                    f"{action.ticker} order @ {key}, found {len(resting)} — the "
                    f"'sole resting order' contract (D-07) is violated")
            order = resting[0]  # "the sole resting order" predicate (D-07)
            if action.kind == "cancel":
                ok = system.order_handler.cancel_order(order.id, portfolio_id)
            elif action.kind == "modify":
                ok = system.order_handler.modify_order(
                    order.id,
                    new_price=action.new_price,
                    new_quantity=action.new_quantity,
                    portfolio_id=portfolio_id,
                )
            else:
                raise ValueError(f"unknown action.kind: {action.kind!r}")
            # WR-01: both cancel_order/modify_order return result.success and can
            # return False (not found, validation/transition failure) WITHOUT
            # raising — surface that as a hard failure so a broken round-trip can't
            # masquerade as a passing test.
            assert ok, (
                f"operator {action.kind} round-trip failed for {order.id}")

    return on_tick


def _build_and_run(spec):
    """Wire a ``TradingSystem`` from ``spec``, run it, and read state AFTER the run.

    Reproduces the oracle generator's wiring sequence (``scripts/run_backtest.py``)
    generalized over the spec. The ``TradingSystem`` import is DEFERRED into this
    function body so ``--collect-only`` stays clean even with zero scenarios wired.
    """
    # Deferred import: only executed when a scenario actually runs (collect-clean).
    from itrader.trading_system.backtest_trading_system import TradingSystem

    # D-03: the spec carries the REAL engine window + data path — no parallel schema.
    system = TradingSystem(
        exchange="csv",
        start_date=spec.start,
        end_date=spec.end,
        timeframe=spec.timeframe,
        csv_paths=spec.data,
    )

    # D-14 — fee/slippage seam (Phase 7). Canary leaves with spec.exchange = None
    # skip this block entirely → byte-identical to today (oracle-dark). A non-None
    # ExchangeConfig is applied post-construction, pre-run by re-running the EXACT
    # constructor path SimulatedExchange.__init__ uses (simulated.py:70-74): assign
    # the config object, then re-init the fee/slippage models from it. CRITICAL
    # (PATTERNS A2): do NOT touch simulated._supported_symbols — execution_handler
    # (L104-109) added BTCUSD to the instance set POST-construction, and the default
    # ExchangeConfig.limits has no BTCUSD; re-deriving the symbol set would WIPE that
    # admission and every order would silently REFUSE. The two model re-inits are the
    # entire fix and nothing more.
    exchange_config = getattr(spec, "exchange", None)
    if exchange_config is not None:
        simulated = system.execution_handler.exchanges["simulated"]
        simulated.config = exchange_config
        simulated.fee_model = simulated._init_fee_model()
        simulated.slippage_model = simulated._init_slippage_model()

    for strategy in spec.strategies:
        system.strategies_handler.add_strategy(strategy)

    # IN-03: fail with an explanatory message (consistent with _load_spec's
    # spec-shape failures) instead of a bare IndexError from portfolio_ids[0]
    # below when a spec declares no portfolios.
    assert spec.portfolios, "scenario spec must declare at least one portfolio"

    portfolio_ids = []
    for pf in spec.portfolios:
        pid = system.portfolio_handler.add_portfolio(
            user_id=pf.user_id,
            name=pf.name,
            exchange="csv",
            cash=pf.cash,
        )
        portfolio_ids.append(pid)
        for strategy in spec.strategies:
            strategy.subscribe_portfolio(pid)

    # Phase 6 (D-06): build the operator hook from spec.actions. Empty actions →
    # _make_on_tick returns None → byte-exact run (oracle-dark).
    system.run(print_summary=False, on_tick=_make_on_tick(spec, portfolio_ids[0]))

    # Read portfolio state AFTER the run (queue-only — D-07). The canary scenarios
    # are single-portfolio; the assembled summary pins from portfolios[0]. The
    # portfolio_id is threaded out so _assemble can query the order mirror.
    portfolio = system.portfolio_handler.get_portfolio(portfolio_ids[0])
    return system, portfolio, portfolio_ids[0]


def _assemble(spec, system, portfolio, portfolio_id):
    """Assemble trades / equity / summary / orders via the SHARED reporting path (D-16)."""
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)

    # Phase 6 (D-08): the order-mirror snapshot for the opt-in orders.csv golden.
    # Queried AFTER the run (queue-only — D-07) for the spec's ticker + portfolio.
    orders = build_orders_snapshot(
        system.order_handler.get_orders_by_ticker(spec.ticker, portfolio_id))

    # D-17: post-hoc slippage attribution from the store's close series.
    closes = system.store.read_bars(spec.ticker)["close"]
    trades = attach_slippage(trades, closes)

    # D-07/D-08: attach the always-on commission column from the REAL
    # Position.commission property (buy_commission + sell_commission). It cannot
    # ride build_trade_log (that frame restricts to TRADE_COLUMNS, and
    # Position.to_dict() emits no commission key), so attach it here exactly like
    # attach_slippage. Order-INDEPENDENT key-merge on (entry_date, exit_date, side)
    # — never a positional zip (RESEARCH Open Q1). float(p.commission) narrows the
    # Decimal at this CSV edge only. For leaves with no closed positions the merged
    # column is absent, so default it to 0.00 to keep the schema uniform (D-08).
    if not trades.empty:
        commission_rows = [
            {
                "entry_date": p.entry_date,
                "exit_date": p.exit_date,
                "side": p.side.name,
                "commission": float(p.commission),
            }
            for p in portfolio.closed_positions
        ]
        commission_frame = pd.DataFrame(
            commission_rows,
            columns=["entry_date", "exit_date", "side", "commission"],
        )
        # WR-03: validate=one_to_one so a non-unique (entry_date, exit_date, side)
        # key (e.g. two round-trips opening/closing on the same bars) raises a
        # pandas MergeError instead of silently many-to-many duplicating trade rows
        # or mis-attributing commission. Converts a confusing golden-diff into a
        # hard, diagnosable failure for future multi-trade leaves.
        trades = trades.merge(
            commission_frame, on=["entry_date", "exit_date", "side"], how="left",
            validate="one_to_one"
        )
        trades["commission"] = trades["commission"].fillna(0.0)
    else:
        trades["commission"] = pd.Series(dtype=float)

    # The summary pins the starting cash from the spec (or fall back to portfolios[0]).
    starting_cash = getattr(spec, "starting_cash", None)
    if starting_cash is None:
        starting_cash = spec.portfolios[0].cash

    summary = build_summary(
        portfolio,
        trades,
        ticker=spec.ticker,
        timeframe=spec.timeframe,
        start_date=spec.start,
        end_date=spec.end,
        starting_cash=starting_cash,
    )
    # D-15: nested derived-metrics block — produced every run.
    summary["metrics"] = build_metrics_block(equity, trades)
    return trades, equity, summary, orders


def _diff_frame(fresh, gold, identity_columns, sort_keys):
    """Diff one fresh-vs-golden frame EXACT (D-08) — identity + auto-numeric split.

    Reuses the oracle's mechanic VERBATIM: sort both by the sort keys, assert the
    identity columns EXACT, then auto-derive the numeric remainder from the golden
    header and assert it EXACT. NO float tolerance is ever passed to the compare.
    """
    fresh_sorted = fresh.sort_values(sort_keys).reset_index(drop=True)
    gold_sorted = gold.sort_values(sort_keys).reset_index(drop=True)

    assert len(fresh_sorted) == len(gold_sorted), (
        f"row count drift: fresh={len(fresh_sorted)} golden={len(gold_sorted)}"
    )

    # Identity columns present in BOTH (a golden may omit e.g. 'pair' on a single-
    # ticker scenario; intersect so the law covers only what was frozen).
    identity = [c for c in identity_columns if c in gold_sorted.columns]
    if identity:
        pdt.assert_frame_equal(
            fresh_sorted[identity],
            gold_sorted[identity],
            check_exact=True,
            check_like=True,
        )

    # Auto-derived numeric remainder from the golden header (D-08 — freezes whatever
    # columns the leaf actually committed).
    numeric = [c for c in gold_sorted.columns if c not in identity]
    if numeric:
        pdt.assert_frame_equal(
            fresh_sorted[numeric],
            gold_sorted[numeric],
            check_exact=True,
            check_like=True,
        )


def _diff_summary(fresh_summary, golden_summary):
    """Diff the summary EXACT — whole ``metrics`` dict + key-by-key scalar compare."""
    # The whole derived-metrics block as one exact dict comparison (D-15 discipline).
    if "metrics" in golden_summary:
        assert fresh_summary.get("metrics") == golden_summary["metrics"], (
            f"summary metrics drift: fresh={fresh_summary.get('metrics')} "
            f"golden={golden_summary['metrics']}"
        )
    # Scalar key-set equality FIRST so additive drift is caught too (WR-04): the
    # key-by-key golden loop below only catches renamed/removed keys (golden key
    # absent from fresh → None mismatch), not a SPURIOUS extra key emitted by a
    # regressed build_summary. The harness is a no-tolerance regression lock, so
    # an extra top-level key must fail just like a missing one.
    fresh_scalar = {k for k in fresh_summary if k != "metrics"}
    gold_scalar = {k for k in golden_summary if k != "metrics"}
    assert fresh_scalar == gold_scalar, (
        f"summary key drift: extra={fresh_scalar - gold_scalar} "
        f"missing={gold_scalar - fresh_scalar}"
    )
    # Every other scalar key in the golden, compared key-by-key EXACT.
    for key, gold_value in golden_summary.items():
        if key == "metrics":
            continue
        assert fresh_summary.get(key) == gold_value, (
            f"summary drift on '{key}': fresh={fresh_summary.get(key)} "
            f"golden={gold_value}"
        )


def _freeze(golden_dir, trades, equity, summary, orders):
    """WRITE goldens using the SAME serialization as the oracle generator (D-06).

    Default freeze = trades.csv + summary.json (always). equity.csv AND orders.csv
    are opt-in (D-06/D-09): only (re)written when one already exists in the leaf's
    golden/. A pure-fill scenario (MATCH-01/02/03) never freezes orders.csv.
    """
    golden_dir.mkdir(parents=True, exist_ok=True)

    trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN].to_csv(
        golden_dir / "trades.csv", index=False, float_format=FLOAT_FORMAT
    )
    with open(golden_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)

    # equity.csv is opt-in (D-06): only refreshed if the leaf already froze it.
    if (golden_dir / "equity.csv").exists():
        equity[EQUITY_COLUMNS].to_csv(
            golden_dir / "equity.csv", index=False, float_format=FLOAT_FORMAT
        )

    # orders.csv is opt-in (D-09): only refreshed if the leaf already froze it
    # (matching scenarios whose assertion is the final order-mirror state).
    if (golden_dir / "orders.csv").exists():
        orders[ORDER_SNAPSHOT_COLUMNS].to_csv(
            golden_dir / "orders.csv", index=False, float_format=FLOAT_FORMAT
        )


def _roundtrip(frame, columns):
    """Serialize ``frame[columns]`` the SAME way ``_freeze`` writes a golden, then
    reload it — so the diff compares apples-to-apples (D-08).

    The in-memory fresh frame carries engine dtypes (tz-aware ``Timestamp`` dates,
    full-precision ``Decimal``-as-object money); the committed golden is whatever
    ``pd.read_csv`` produces from the ``float_format=FLOAT_FORMAT`` CSV (object dates,
    float money). Round-tripping the fresh frame through the identical CSV serialization
    (``to_csv(..., float_format=FLOAT_FORMAT)`` -> ``read_csv``) normalizes BOTH sides to
    the same dtypes and the same 10-dp float repr, so ``assert_frame_equal`` compares the
    frozen bytes — not engine-internal dtype/precision artifacts. This mirrors the oracle,
    which reads BOTH fresh and golden from CSV (``test_backtest_oracle.py``).
    """
    buffer = io.StringIO()
    frame[columns].to_csv(buffer, index=False, float_format=FLOAT_FORMAT)
    buffer.seek(0)
    return pd.read_csv(buffer)


def _diff(golden_dir, trades, equity, summary, orders):
    """DIFF ONLY the golden files PRESENT in the leaf (D-05: presence = assertion).

    A leaf that froze only trades.csv + summary.json asserts only those; equity.csv
    and orders.csv are diffed only if the leaf committed one. Goldens never
    auto-heal here (D-13).
    """
    assert golden_dir.exists(), (
        f"no golden/ in {golden_dir.parent} — run with --freeze first after "
        f"hand-verifying the scenario (Pitfall 5)"
    )

    trades_golden = golden_dir / "trades.csv"
    if trades_golden.exists():
        gold = pd.read_csv(trades_golden)
        # Serialize the fresh trades the SAME way the golden was written, then reload,
        # so the diff compares apples-to-apples (same float formatting, same columns).
        fresh = _roundtrip(trades, TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN)
        _diff_frame(fresh, gold, _TRADE_IDENTITY_COLUMNS, _TRADE_SORT_KEYS)

    equity_golden = golden_dir / "equity.csv"
    if equity_golden.exists():
        gold = pd.read_csv(equity_golden)
        fresh = _roundtrip(equity, EQUITY_COLUMNS)
        _diff_frame(fresh, gold, _EQUITY_IDENTITY_COLUMNS, _EQUITY_SORT_KEYS)

    orders_golden = golden_dir / "orders.csv"
    if orders_golden.exists():
        gold = pd.read_csv(orders_golden)
        fresh = _roundtrip(orders, ORDER_SNAPSHOT_COLUMNS)
        _diff_frame(fresh, gold, _ORDERS_IDENTITY_COLUMNS, _ORDERS_SORT_KEYS)

    summary_golden = golden_dir / "summary.json"
    if summary_golden.exists():
        with open(summary_golden, encoding="utf-8") as handle:
            gold_summary = json.load(handle)
        _diff_summary(summary, gold_summary)


@pytest.fixture
def run_scenario(request):
    """The shared E2E harness fixture: build→run→read→assemble→diff-what's-frozen.

    Returns a callable ``_run(here)`` a leaf's ``test_scenario.py`` invokes with its
    own directory (``pathlib.Path(__file__).parent``). Under ``--freeze`` it WRITES
    the leaf's goldens; otherwise it DIFFS only the goldens present (D-05) with the
    oracle's exact no-tolerance mechanic (D-08) and fails on any drift (D-13).

    Single-scenario freeze discipline (Pitfall 5) is mechanically enforced, not
    just documented: ``--freeze`` is REFUSED when more than one test is selected
    in the session, so a blind ``pytest tests/e2e --freeze`` sweep cannot
    blind-overwrite every golden. Combine ``--freeze`` with a ``-k``/path selector
    that narrows the session to exactly one hand-verified scenario.
    """
    freeze = request.config.getoption("--freeze")
    if freeze:
        # IN-02: enforce the "freeze ONE hand-verified scenario at a time"
        # discipline mechanically. request.session.items is the full collected
        # set for this run; refusing >1 prevents the blind multi-scenario sweep
        # the docstring warns against (Pitfall 5).
        selected = len(getattr(request.session, "items", []))
        if selected > 1:
            pytest.fail(
                f"--freeze refuses to run with {selected} selected tests: freeze "
                f"ONE hand-verified scenario at a time (Pitfall 5). Re-run with a "
                f"-k/path selector that narrows the session to a single scenario."
            )

    def _run(here):
        here = pathlib.Path(here)
        spec = _load_spec(here / "scenario.py")
        system, portfolio, portfolio_id = _build_and_run(spec)
        trades, equity, summary, orders = _assemble(spec, system, portfolio, portfolio_id)

        golden_dir = here / "golden"
        if freeze:
            _freeze(golden_dir, trades, equity, summary, orders)
        else:
            _diff(golden_dir, trades, equity, summary, orders)

    return _run
