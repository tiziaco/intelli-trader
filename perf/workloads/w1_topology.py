"""W1 topology wiring helper (PERF-BASELINE §5).

Declarative description of the W1 topology so the runner stays thin:

- ``CSV_PATHS`` — ticker -> committed 5m CSV path.
- 4 coverage strategies / 6 portfolios:
    P1 = A (isolation), P2 = B (isolation), P3 = C (isolation),
    P4 + P5 + P6 = D (1 strategy -> 3 portfolios fan-out).
- ``wire_w1(system)`` — applies the SHORT-selling wiring recipe (VERIFIED from
  ``tests/integration/test_pair_flagship_snapshot.py::_build_flagship_system``)
  and registers all four strategies + six portfolios with the correct
  subscriptions. Does NOT call ``run()`` — wiring only. The resting-limit-id
  tracking (Strategy B's cancel/modify) is the RUNNER's ``on_tick`` concern and
  is intentionally NOT here.

The short-selling recipe order matters: the strategy-handler flags MUST be set
BEFORE ``add_strategy`` (the SHORT_ONLY registration gate, strategies_handler),
and the admission/validator margin flags before the run. The LONG_ONLY strategies
(A, B, C) do not need the short flags, but the system-wide margin flags being on
is harmless for them.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

from perf.strategies import (
    BracketedMomentumStrategy,
    LimitMakerStrategy,
    PyramidingTrendStrategy,
    ShortZScoreStrategy,
)

__all__ = ["CSV_PATHS", "TIMEFRAME", "wire_w1", "W1Topology"]

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Ticker -> committed 5m CSV path (the four validated datasets).
CSV_PATHS: dict[str, str] = {
    "BTCUSDT": str(_DATA_DIR / "BTCUSDT_5m.csv"),
    "ETHUSDT": str(_DATA_DIR / "ETHUSDT_5m.csv"),
    "SOLUSDT": str(_DATA_DIR / "SOLUSDT_5m.csv"),
    "BNBUSDT": str(_DATA_DIR / "BNBUSDT_5m.csv"),
}

TIMEFRAME = "5m"

# Per-portfolio starting cash (Decimal end-to-end). Sized so the LONG books trade
# and over-extend (C) and the short fan-out (D) has independent per-portfolio cash.
_CASH_A = Decimal("100000")
_CASH_B = Decimal("100000")
_CASH_C = Decimal("100000")
_CASH_D = Decimal("100000")


class W1Topology:
    """Handle to the wired W1 system: the strategies, portfolio ids, and the map.

    Attributes
    ----------
    strategy_a/b/c/d : the four coverage strategy instances.
    pid1..pid6 : the six portfolio ids (P1=A, P2=B, P3=C, P4/P5/P6=D fan-out).
    limit_maker : alias for strategy_b (the runner's on_tick tracks its limits).
    """

    def __init__(self, system: Any) -> None:
        self.system = system
        self.strategy_a: BracketedMomentumStrategy
        self.strategy_b: LimitMakerStrategy
        self.strategy_c: PyramidingTrendStrategy
        self.strategy_d: ShortZScoreStrategy
        self.portfolio_ids: list[Any] = []


def _enable_margin_and_shorts(system: Any) -> None:
    """Apply the system-wide short/margin flags (recipe steps 1 + 5).

    Set BEFORE any ``add_strategy`` / ``run`` (the SHORT_ONLY registration gate
    reads the handler flags at ``add_strategy`` time).
    """
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True

    om = system.order_handler.order_manager
    om.admission_manager._enable_margin = True
    om.order_validator.enable_margin = True


def _enable_portfolio_margin(system: Any, portfolio_id: Any) -> None:
    """Apply per-portfolio trading-rules margin + short flags (recipe step 4)."""
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "allow_short_selling": True,
        })})


def wire_w1(system: Any) -> W1Topology:
    """Wire the full W1 topology onto a constructed BacktestTradingSystem.

    Order (the verified recipe):
    1. system-wide short/margin handler + admission/validator flags (BEFORE add).
    2. add the four strategies (A/B/C LONG_ONLY, D SHORT_ONLY).
    3. add the six portfolios; subscribe per topology (A->P1, B->P2, C->P3,
       D->P4/P5/P6 fan-out).
    4. per-portfolio trading-rules margin/short flags for the D-fed portfolios
       (P4/P5/P6 at minimum); applied to all six (harmless for the LONG books).

    Returns a ``W1Topology`` handle the runner reads after ``run()``.
    """
    topo = W1Topology(system)

    # 1. System-wide flags BEFORE add_strategy (registration gate).
    _enable_margin_and_shorts(system)

    # 2. Strategies (each declares its own tickers as class attrs).
    topo.strategy_a = BracketedMomentumStrategy(timeframe=TIMEFRAME)
    topo.strategy_b = LimitMakerStrategy(timeframe=TIMEFRAME)
    topo.strategy_c = PyramidingTrendStrategy(timeframe=TIMEFRAME)
    topo.strategy_d = ShortZScoreStrategy(timeframe=TIMEFRAME)

    sh = system.strategies_handler
    sh.add_strategy(topo.strategy_a)
    sh.add_strategy(topo.strategy_b)
    sh.add_strategy(topo.strategy_c)
    sh.add_strategy(topo.strategy_d)

    # 3. Portfolios + subscriptions (P1=A, P2=B, P3=C, P4/P5/P6=D fan-out).
    ph = system.portfolio_handler
    pid1 = ph.add_portfolio(user_id=1, name="P1_A", exchange="csv", cash=_CASH_A)
    pid2 = ph.add_portfolio(user_id=2, name="P2_B", exchange="csv", cash=_CASH_B)
    pid3 = ph.add_portfolio(user_id=3, name="P3_C", exchange="csv", cash=_CASH_C)
    pid4 = ph.add_portfolio(user_id=4, name="P4_D", exchange="csv", cash=_CASH_D)
    pid5 = ph.add_portfolio(user_id=5, name="P5_D", exchange="csv", cash=_CASH_D)
    pid6 = ph.add_portfolio(user_id=6, name="P6_D", exchange="csv", cash=_CASH_D)
    topo.portfolio_ids = [pid1, pid2, pid3, pid4, pid5, pid6]

    topo.strategy_a.subscribe_portfolio(pid1)
    topo.strategy_b.subscribe_portfolio(pid2)
    topo.strategy_c.subscribe_portfolio(pid3)
    # D fans out to P4/P5/P6 — each sizes/admits the same short signal against its
    # own cash, independently (the 1-strategy -> 3-portfolio path).
    topo.strategy_d.subscribe_portfolio(pid4)
    topo.strategy_d.subscribe_portfolio(pid5)
    topo.strategy_d.subscribe_portfolio(pid6)

    # 4. Per-portfolio trading-rules margin/short flags — ONLY the D-fed shorts
    #    (P4/P5/P6). The LONG books (P1/P2/P3 = A/B/C) stay SPOT: enabling
    #    per-portfolio margin on them would route their long settlements through
    #    the margin lock-and-settle assertion (assert_lock_fits_buying_power),
    #    which RAISES InsufficientFundsError on an over-extended add (Strategy C)
    #    and fail-fast aborts the backtest. In SPOT mode that same over-extension
    #    instead produces the graceful admission-side CASH_RESERVATION rejection
    #    (FillEvent(REFUSED) -> mirror reconcile) the benchmark wants to exercise
    #    (spec §6). The system-wide handler/admission/validator margin flags
    #    (steps 1+5) stay on for the SHORT_ONLY registration gate; the PER-PORTFOLIO
    #    trading-rules margin is the one that branches long settlement.
    for pid in topo.portfolio_ids[3:]:  # P4, P5, P6 (D fan-out) only
        _enable_portfolio_margin(system, pid)

    return topo
