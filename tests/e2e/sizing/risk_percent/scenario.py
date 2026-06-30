"""SIZE-02: RiskPercent sizing off a DECISION-TIME stop — spec + VERIFY derivation.

The first hand-verified fill for the ``RiskPercent`` Van-Tharp sizing policy (D-02/
D-13). A BUY declaring ``sizing_policy=RiskPercent(risk_pct=Decimal("0.02"))`` AND an
explicit script ``"sl"`` distinct from the decision price sizes the entry off the
STOP DISTANCE:

    qty = (total_equity * risk_pct) / |decision_price - stop|

(``sizing_resolver.py:124``). The stop is the SAME explicit ``"sl"`` the script
declares — so it both (a) sizes the position and (b) becomes the resting STOP-loss
bracket child that closes the trade.

CRITICAL (D-13 / RESEARCH Pitfall 3): RiskPercent REQUIRES a decision-time stop
distinct from the decision price. The script MUST declare an explicit non-zero
``"sl"`` — ``strategies_handler`` stamps ``stop_loss = to_money(0)`` when none is
declared, and ``Decimal("0") or None`` -> ``None`` -> ``SizingPolicyViolation`` ->
an audited REJECTED order (NOT a sized trade). NEVER use ``PercentFromFill`` here
(the fill price is unknown at resolve -> circular). The acceptance criterion is a
CLOSED TRADE row; a REJECTED order in the mirror is the Pitfall-3 warning sign.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-09a/D-13): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100    <- BUY decided here (close=100, sl=80)
    2    2020-01-03   100    105    99     100    <- MARKET entry fills @ open=100, SL arms
    3    2020-01-04   90     92     79     82      <- SL STOP @80 triggers (low 79 <= 80)
    4    2020-01-05   82     86     80     84      <- trailing bar

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04):
a MARKET BUY with an explicit ``sl = Decimal("80")`` on the 2020-01-02 decision bar.
``sizing_policy = RiskPercent(risk_pct=Decimal("0.02"))`` — risk 2% of total equity.

Sizing (RiskPercent arm — sizing_resolver.py:118-124; D-13 decision-time stop):
  * decision price = bar1 close = 100 (strategies_handler.py:141 stamps
    ``price = to_money(bar.close)`` at decision time).
  * total_equity at decision = 10_000 (all cash, no prior position).
  * stop = the declared sl = 80, DISTINCT from the decision price 100 (so the
    SizingPolicyViolation guard at sizing_resolver.py:118 does NOT fire).
  * stop distance = |100 - 80| = 20.
  * qty = (total_equity * risk_pct) / |price - stop|
        = (10_000 * 0.02) / 20 = 200 / 20 = 10 units (round, hand-derivable).
    Sanity: the dollar risk if the stop fills exactly at 80 is
    (100 - 80) * 10 = 200 = 2% of the 10_000 equity — the textbook RiskPercent
    outcome. 10 units @ 100 = 1_000 notional, well within cash (admitted).

Lifecycle (decision bar -> fill bar; the next-bar-open rule, MARKET-entry bracket):

    decision bar1 (2020-01-02): script hits BUY (sl=80) -> a MARKET parent +
        a DORMANT STOP(SELL @80) child rest in the book (the explicit sl creates
        the bracket child, order_manager.py:640-652; D-13 explicit-level path).
    bar2 (2020-01-03): the MARKET parent fills at bar2 OPEN = 100, stamped
        2020-01-03; it leaves the book, ARMING the STOP(SELL @80) child against
        bar2's own high/low. bar2 low = 99 > 80, so the SL does NOT trigger on the
        arming bar — it rests, now armed. Position opens LONG 10 @ 100.
    bar3 (2020-01-04): the SL STOP(SELL @80) triggers — low = 79 <= 80, so it
        fills at ``min(open, trigger) = min(90, 80) = 80`` (matching_engine.py:160-161,
        pessimistic gap-down: open 90 > trigger 80, so the in-bar touch fills at the
        trigger 80, stamped 2020-01-04). Position closes.
    bar4 (2020-01-05): trailing bar — nothing rests, nothing fills.

Entry (BUY parent, filled bar2 @100):
  * total_bought = 10 * 100 = 1_000.00; avg_bought = 100.
Exit (SL STOP, filled bar3 @80 — the trigger price):
  * total_sold = 10 * 80 = 800.00; avg_sold = 80.

Resulting SINGLE round-trip trade (fees 0, slippage model NONE):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 100
  * exit_date  = 2020-01-04, avg_sold  = 80
  * net_quantity = 0 (fully closed by the SL)
  * realised_pnl = (avg_sold - avg_bought) * qty = (80 - 100) * 10 = -200.00
    (exactly the 2% risk — a CLOSED TRADE, NOT a REJECTED order; confirms the
    decision-time stop wired correctly, T-07-09 mitigation).
  * commission = 0.00 (exchange = None).

Final cash (ledger): start - buy_notional + sell_notional
    = 10_000 - 1_000 + 800 = 9_800.00
    cross-check: starting_cash + realised_pnl = 10_000 + (-200) = 9_800.00. OK.

Slippage columns (slippage model = NONE; slippage = fill price - the STORE bar
immediately before the fill bar — attach_slippage indexes the store close series):
  * slippage_entry = bar2 open (100) - bar1 close (100) = 0.0
  * slippage_exit  = bar3 SL fill (80) - bar2 close (100) = -20.0

Final portfolio: final_cash = final_equity = 9_800.00, trade_count = 1.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import RiskPercent
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a MARKET BUY decided 2020-01-02 with an EXPLICIT sl = 80
# (D-13 / Pitfall 3) DISTINCT from the decision-bar close (100). The sl both sizes
# the RiskPercent entry AND becomes the resting STOP-loss child that closes the
# trade on bar3. NO PercentFromFill (circular — the fill is unknown at resolve).
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": Decimal("80")},
}

# SIZE-02 (D-02/D-13): RiskPercent risks 2% of total equity per trade; the quantity
# is (equity * risk_pct) / stop_distance (Pitfall 1 string-path Decimal).
_SIZING = RiskPercent(risk_pct=Decimal("0.02"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(name="size02_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage — sizing is the only moving part.
)
