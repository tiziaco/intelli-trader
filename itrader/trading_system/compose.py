"""Shared component-graph wiring seam + commission adapter (D-14/D-14a/D-15).

``compose_engine`` is the SHARED, mode-agnostic wiring seam both
``build_backtest_system`` (now) and a future ``build_live_system`` (fast-follow)
consume. It builds the component graph extracted from the fat
``BacktestTradingSystem.__init__`` body — queue, clock, store, feed, signal
store, strategies/screeners/portfolio/execution handlers, the commission
adapter, order handler, event handler — and returns them as a small ``Engine``
holder.

D-14a boundary: ``compose_engine`` must NOT hardcode a run-mode backend string
(no backtest/live literal). The mode-specific FACTORY (``build_backtest_system``)
selects the concrete backends (the order-storage + signal-store backends) via
their respective factories, plus the construction-time
``ExchangeConfig`` (with the complete symbol set already folded in — D-13/Trap 1)
and passes them IN. The seam wires the graph from those injected concretes,
staying run-mode-agnostic (mirrors the injected ``CommissionEstimator`` /
``PortfolioReadModel`` DI rationale).

D-15: ``FeeModelCommissionEstimator`` promotes the inline ``_estimate_commission``
closure to a typed adapter conforming to the ``core`` ``CommissionEstimator``
Protocol. It holds the EXCHANGE ref and reads ``exchange.fee_model`` at CALL
time (late binding) — ``update_config`` may rebuild the fee model, and a stale
capture would silently use the wrong estimator. The golden run pins fees 0
(ZeroFeeModel), so the estimate is ``Decimal("0")`` exactly as today.

Indentation: TABS (``trading_system/`` package convention).
"""

import queue
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from itrader.core.clock import BacktestClock
from itrader.config import ExchangeConfig, OrderConfig
from itrader.events_handler.full_event_handler import EventHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.order_handler.base import OrderStorage
from itrader.order_handler.order_handler import OrderHandler
from itrader.outils.time_parser import to_timedelta
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.strategy_handler.storage import SignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.trading_system.simulation.time_generator import TimeGenerator
from itrader.universe import Universe


class FeeModelCommissionEstimator:
	"""Typed commission-estimate adapter over the exchange (D-15, Trap 2).

	Promotes the inline ``_estimate_commission`` closure. Holds the EXCHANGE
	REF and reads ``exchange.fee_model`` inside ``__call__`` (LATE BINDING) —
	NEVER captures ``fee_model`` at ``__init__``. ``update_config`` may rebuild
	the exchange's fee model; a construction-time capture would silently use a
	stale estimator. Conforms structurally to the ``core`` ``CommissionEstimator``
	Protocol (``(Decimal, Decimal) -> Decimal``).

	The ``side="buy", order_type="market"`` admission convention is preserved
	(D-04). A non-``SimulatedExchange`` (or a None exchange) yields ``Decimal("0")``
	— byte-identical to the closure's isinstance guard, so the golden run's
	ZeroFeeModel estimate stays exactly 0.
	"""

	def __init__(self, exchange: Optional[Any]) -> None:
		# Hold the REF only — late binding reads exchange.fee_model in __call__.
		self._exchange = exchange

	def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
		if not isinstance(self._exchange, SimulatedExchange):
			return Decimal("0")
		return self._exchange.fee_model.calculate_fee(
			quantity, price, side="buy", order_type="market")


@dataclass
class Engine:
	"""The wired component graph ``compose_engine`` returns (D-04).

	A dumb holder of the pre-built handlers/read-models. The FACTORY constructs
	the ``BacktestRunner`` over this engine and injects both into the thin
	``BacktestTradingSystem`` holder. Fields are populated in wiring order so the
	downstream session-setup / run-loop ordering stays byte-exact (Trap 4/6).
	"""

	global_queue: "queue.Queue[Any]"
	clock: BacktestClock
	store: CsvPriceStore
	feed: BacktestBarFeed
	signal_store: SignalStore
	strategies_handler: StrategiesHandler
	screeners_handler: ScreenersHandler
	portfolio_handler: PortfolioHandler
	execution_handler: ExecutionHandler
	order_handler: OrderHandler
	event_handler: EventHandler
	time_generator: TimeGenerator
	# INST-03 (D-06/D-08): the symbol->Instrument read-model, constructed at the
	# Trap-4 wiring point in the runner (_initialise_backtest_session) and set
	# onto the engine there. None until wiring — populated before the run loop.
	universe: Optional[Universe] = None


def compose_engine(
	*,
	order_storage: OrderStorage,
	signal_store: SignalStore,
	csv_paths: Optional[dict[str, "str | Path"]] = None,
	start_date: Optional[str] = None,
	end_date: Optional[str] = None,
	timeframe: str = "1d",
	exchange_config: Optional[ExchangeConfig] = None,
	order_config: Optional[OrderConfig] = None,
) -> Engine:
	"""Wire the shared component graph mode-agnostically (D-14/D-14a).

	The mode-specific concretes (``order_storage``, ``signal_store``, the
	symbol-seeded ``exchange_config``) are SELECTED BY THE FACTORY and passed in
	— this seam never names a run mode (no backend-string literal, D-14a). The
	wiring body is
	extracted verbatim (re-ordered to nothing) from
	``BacktestTradingSystem.__init__`` so the constructed graph is byte-identical.

	Parameters
	----------
	order_storage : OrderStorage
		The mode-specific order-mirror backend selected by the factory (D-14a).
	signal_store : SignalStore
		The mode-specific signal-store sink selected by the factory (D-14a).
	csv_paths : dict[str, str | Path], optional
		Ticker -> CSV path; passes straight through to ``CsvPriceStore`` (the
		Phase-3 multi-ticker injection seam). None falls back to the
		single-golden-ticker default — byte-identical to today.
	start_date, end_date : str, optional
		Run window bounds threaded to the store.
	timeframe : str
		The feed's base timeframe (default ``"1d"``).
	exchange_config : ExchangeConfig, optional
		Construction-time exchange config whose ``limits.supported_symbols``
		already carries the COMPLETE set (default preset ∪ {BTCUSD} ∪ spec
		tickers — D-13/Trap 1). None lets the ExecutionHandler build its
		TEMPORARY default-preset ∪ {BTCUSD} backward-compat config.
	order_config : OrderConfig, optional
		Order-domain config (``market_execution``). None defaults to
		``OrderConfig.default()`` ("immediate").
	"""
	global_queue: "queue.Queue[Any]" = queue.Queue()

	# Determinism seam (D-09/D-10): the injected BacktestClock staged on the
	# determinism seam (no domain consumer yet — result determinism comes from
	# passing the bar time explicitly to record_metrics in the runner).
	clock = BacktestClock()

	# Store + look-ahead-safe feed read-model. csv_paths passes straight through;
	# None falls back to the single-golden-ticker default (byte-identical).
	store = CsvPriceStore(
		csv_paths=csv_paths,
		start_date=start_date,
		end_date=end_date or None)
	feed = BacktestBarFeed(store, to_timedelta(timeframe))

	# Signal-store sink (read-model): one SignalRecord per non-None intent,
	# read post-run; the queue-only contract is preserved (handler writes
	# locally, the holder reads after the run). The backend is selected by the
	# FACTORY and injected (D-14a) — the seam never names a run mode.
	strategies_handler = StrategiesHandler(global_queue, feed, signal_store)
	# ScreenersHandler is a deferred subsystem (ignore_errors override).
	screeners_handler = ScreenersHandler(global_queue, feed)  # type: ignore[no-untyped-call]
	portfolio_handler = PortfolioHandler(global_queue)

	# Execution handler is constructed BEFORE the order handler so the admission
	# gate's commission estimator can adapt the simulated exchange's fee model
	# (D-04). The construction-time ExchangeConfig threads the complete symbol
	# set (D-13). Construction-order only — runtime stays queue-mediated.
	execution_handler = ExecutionHandler(global_queue, exchange_config=exchange_config)

	# Commission estimator for the admission cash-reservation gate (D-04/D-15):
	# the typed FeeModelCommissionEstimator adapter holds the exchange ref and
	# reads fee_model at call time (late binding). The golden run pins fees 0,
	# so the reservation equals price x quantity exactly (value-preserving).
	simulated_exchange = execution_handler.exchanges.get('simulated')
	commission_estimator = FeeModelCommissionEstimator(simulated_exchange)

	# Plan 02-03 (D-09/D-14): thread the portfolio's margin settings into the
	# order domain at construction so the admission leverage cap (D-04) and the
	# margin reservation branch (D-08) are gated correctly. Read from the
	# portfolio config's TradingRules (config_data.trading_rules). With the
	# default PortfolioConfig (enable_margin=False / max_leverage=1) the order
	# domain stays on the spot byte-exact arm. The Universe itself is injected
	# later via order_handler.set_universe at the Trap-4 wiring point (the runner
	# builds it after this construction).
	trading_rules = portfolio_handler.config_data.trading_rules
	resolved_order_config = order_config or OrderConfig.default()
	order_handler = OrderHandler(
		global_queue, portfolio_handler, order_storage,
		order_config=resolved_order_config,
		commission_estimator=commission_estimator,
		enable_margin=trading_rules.enable_margin,
		portfolio_max_leverage=trading_rules.max_leverage)

	time_generator = TimeGenerator()
	# The TIME route's BarEvent source is the feed-owned factory (D-20).
	event_handler = EventHandler(
		strategies_handler,
		screeners_handler,
		portfolio_handler,
		order_handler,
		execution_handler,
		feed.generate_bar_event,
		global_queue
	)

	return Engine(
		global_queue=global_queue,
		clock=clock,
		store=store,
		feed=feed,
		signal_store=signal_store,
		strategies_handler=strategies_handler,
		screeners_handler=screeners_handler,
		portfolio_handler=portfolio_handler,
		execution_handler=execution_handler,
		order_handler=order_handler,
		event_handler=event_handler,
		time_generator=time_generator,
	)
