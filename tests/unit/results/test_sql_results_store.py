"""In-process SQLite tests for ``SqlResultsStore`` (RESULT-02/03/04).

Covers the concrete results store end-to-end on a ``:memory:`` SQLite backend (CONTEXT
D-12 — tests use in-process SQLite):

1. round-trip — a saved artifact frame reads back value-equal (D-15).
2. byte-determinism — the gzip codec encodes the same frame to identical bytes (D-10).
3. atomic ``save_run`` — the ``runs`` row and its ``run_portfolios`` rows land together.
4. ranking — ``top_runs`` / ``top_portfolios`` order best-first with the ``run_id`` ASC
   tiebreak and the correct (DESC) drawdown direction (D-18).
5. missing / empty — ``get_artifact`` on an unknown run raises ``ResultsNotFound``;
   ``top_runs`` on a fresh store returns ``[]`` (D-16).

The directory is package-less (NO ``__init__.py``) — matching the sibling
``tests/unit/results/test_results_store_abc.py`` and the ``tests/unit`` convention.
"""

import uuid
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import select

from itrader import idgen
from itrader.config.sql import SqlSettings
from itrader.core.exceptions import ResultsNotFound
from itrader.results.records import PortfolioRecord, RunMetrics, RunRecord
from itrader.results.sql_storage import SqlResultsStore
from itrader.storage import SqlBackend


def _run_id() -> uuid.UUID:
    """A fresh UUIDv7 run id (single UUIDv7 scheme — ``idgen``)."""
    return idgen._uuid7()


def _metrics(**overrides: float) -> RunMetrics:
    """A ``RunMetrics`` with sane defaults, overridable per-metric."""
    base: dict[str, float] = {
        "sharpe": 1.0,
        "sortino": 1.0,
        "cagr": 0.1,
        "calmar": 0.5,
        "max_drawdown": -0.2,
        "profit_factor": 1.5,
        "win_rate": 0.6,
        "total_return": 0.3,
        "final_equity": 130.0,
        "total_realised_pnl": 30.0,
        "trade_count": 10.0,
    }
    base.update(overrides)
    return RunMetrics(**base)


def _portfolio(metrics: RunMetrics, name: str = "p1") -> PortfolioRecord:
    """A ``PortfolioRecord`` carrying ``metrics`` and a trivial params dict."""
    return PortfolioRecord(
        portfolio_id=idgen._uuid7(),
        name=name,
        metrics=metrics,
        params={"fast": 10, "slow": 30},
    )


def _run(
    run_id: uuid.UUID,
    metrics: RunMetrics,
    portfolios: tuple[PortfolioRecord, ...] = (),
) -> RunRecord:
    """A ``RunRecord`` with a curated settings envelope and per-portfolio rows."""
    return RunRecord(
        run_id=run_id,
        metrics=metrics,
        settings={"strategy": "SMA_MACD", "rng_seed": 42},
        per_portfolio=list(portfolios),
    )


def _frame() -> pd.DataFrame:
    """A small round-trip-stable frame (float columns + default RangeIndex)."""
    return pd.DataFrame(
        {"equity": [100.0, 101.5, 99.25], "drawdown": [0.0, -0.5, -1.0]}
    )


@pytest.fixture
def store() -> Any:
    """A fresh ``SqlResultsStore`` over an in-process SQLite spine (``:memory:``)."""
    backend = SqlBackend(SqlSettings())
    results_store = SqlResultsStore(backend)
    try:
        yield results_store
    finally:
        backend.dispose()


# --------------------------------------------------------------------- Task 1: codec + save
def test_codec_roundtrip(store: SqlResultsStore) -> None:
    """``_decode_frame(_encode_frame(df))`` is value-equal to ``df`` (D-10/D-15)."""
    frame = _frame()
    decoded = store._decode_frame(store._encode_frame(frame))
    assert_frame_equal(decoded, frame)


def test_codec_byte_determinism(store: SqlResultsStore) -> None:
    """The gzip codec encodes the same frame to byte-identical blobs (RESULT-04/D-10)."""
    frame = _frame()
    assert store._encode_frame(frame) == store._encode_frame(frame)


def test_codec_roundtrip_preserves_datetime_and_integral_float_dtypes(
    store: SqlResultsStore,
) -> None:
    """CR-01 — the codec is DTYPE-stable for real artifact frames.

    A trade-log-shaped frame carries ``entry_date``/``exit_date`` datetime columns AND an
    integral-valued ``float`` column (``realised_pnl``). Under the old ``orient="split"``
    codec these decoded back as ``int64`` (epoch-millis dates / collapsed integral floats),
    silently changing dtype. The round-trip is asserted against the **ORIGINAL** frame (not
    a re-encoded copy), so the asymmetry the lossy codec hid is now caught.
    """
    frame = pd.DataFrame(
        {
            "entry_date": pd.to_datetime(["2020-01-01", "2020-02-01"]),
            "exit_date": pd.to_datetime(["2020-01-15", "2020-02-15"]),
            "side": ["BUY", "SELL"],
            "realised_pnl": [100.0, 200.0],  # integral-valued floats
            "avg_price": [1.5, 2.5],
        }
    )
    decoded = store._decode_frame(store._encode_frame(frame))
    # Compare against the ORIGINAL frame — the dtypes (datetime64[ns], float64) must survive.
    assert_frame_equal(decoded, frame)


def test_save_run_atomic_persists_run_and_portfolios(store: SqlResultsStore) -> None:
    """``save_run`` lands the ``runs`` row AND both ``run_portfolios`` rows (D-13)."""
    run_id = _run_id()
    record = _run(
        run_id,
        _metrics(),
        portfolios=(_portfolio(_metrics(), "p1"), _portfolio(_metrics(), "p2")),
    )

    returned = store.save_run(record)
    assert returned == run_id

    with store.engine.connect() as connection:
        runs = connection.execute(select(store.runs)).mappings().all()
        portfolios = connection.execute(
            select(store.run_portfolios)
        ).mappings().all()

    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert len(portfolios) == 2
    assert {row["name"] for row in portfolios} == {"p1", "p2"}


# ------------------------------------------------------------------ Task 2: reads
def test_get_artifact_roundtrip_keyed_collection(store: SqlResultsStore) -> None:
    """``get_artifact`` returns ``{(portfolio_id, type): frame}`` value-equal (D-15)."""
    run_id = _run_id()
    portfolio = _portfolio(_metrics(), "p1")
    store.save_run(_run(run_id, _metrics(), portfolios=(portfolio,)))

    frame = _frame()
    store.save_artifact(run_id, portfolio.portfolio_id, "equity_curve", frame)

    artifacts = store.get_artifact(run_id)
    assert set(artifacts) == {(portfolio.portfolio_id, "equity_curve")}
    assert_frame_equal(artifacts[(portfolio.portfolio_id, "equity_curve")], frame)


def test_get_artifact_handles_null_portfolio_key(store: SqlResultsStore) -> None:
    """An aggregate-level frame (``portfolio_id=None``) keys on ``(None, type)`` (D-07)."""
    run_id = _run_id()
    store.save_run(_run(run_id, _metrics()))
    frame = _frame()
    store.save_artifact(run_id, None, "trade_log", frame)

    artifacts = store.get_artifact(run_id)
    assert (None, "trade_log") in artifacts
    assert_frame_equal(artifacts[(None, "trade_log")], frame)


def test_get_artifact_unknown_run_raises(store: SqlResultsStore) -> None:
    """``get_artifact`` on an unknown ``run_id`` raises ``ResultsNotFound`` (D-16)."""
    store.save_run(_run(_run_id(), _metrics()))  # populate so the table is non-empty
    with pytest.raises(ResultsNotFound):
        store.get_artifact(uuid.uuid4())


def test_top_runs_empty_table_returns_empty(store: SqlResultsStore) -> None:
    """``top_runs`` on a fresh store returns ``[]`` (empty-safe, D-16)."""
    assert store.top_runs("sharpe", 5) == []
    assert store.top_portfolios("sharpe", 5) == []


# ----------------------------------------------------------------- Task 3: ranking (D-18)
def test_top_runs_orders_best_first(store: SqlResultsStore) -> None:
    """``top_runs`` returns the highest-``metric`` runs, best first (DESC)."""
    low = uuid.UUID(int=1)
    mid = uuid.UUID(int=2)
    high = uuid.UUID(int=3)
    store.save_run(_run(low, _metrics(sharpe=0.5)))
    store.save_run(_run(high, _metrics(sharpe=2.0)))
    store.save_run(_run(mid, _metrics(sharpe=1.0)))

    top = store.top_runs("sharpe", 2)
    assert [r.run_id for r in top] == [high, mid]
    assert [r.metrics.sharpe for r in top] == [2.0, 1.0]


def test_top_runs_runid_asc_tiebreak(store: SqlResultsStore) -> None:
    """Equal-metric runs break ties by ``run_id`` ASC (deterministic ordering, D-18)."""
    run_a = uuid.UUID(int=10)
    run_b = uuid.UUID(int=20)
    # Insert the higher run_id first to prove the ORDER BY (not insert order) decides.
    store.save_run(_run(run_b, _metrics(sharpe=3.0)))
    store.save_run(_run(run_a, _metrics(sharpe=3.0)))

    top = store.top_runs("sharpe", 2)
    assert [r.run_id for r in top] == [run_a, run_b]


def test_top_runs_max_drawdown_direction(store: SqlResultsStore) -> None:
    """``max_drawdown`` ranks DESC: the least-bad (closest-to-zero) drawdown wins (D-18).

    Drawdown is stored NEGATIVE, so an ASC ordering would surface the WORST run; the
    largest-signed (least-negative) value is the best and must come first.
    """
    worst = uuid.UUID(int=100)
    least_bad = uuid.UUID(int=200)
    mid = uuid.UUID(int=300)
    store.save_run(_run(worst, _metrics(max_drawdown=-0.9)))
    store.save_run(_run(least_bad, _metrics(max_drawdown=-0.1)))
    store.save_run(_run(mid, _metrics(max_drawdown=-0.5)))

    top = store.top_runs("max_drawdown", 1)
    assert len(top) == 1
    assert top[0].run_id == least_bad
    assert top[0].metrics.max_drawdown == -0.1


def test_top_portfolios_orders_best_first(store: SqlResultsStore) -> None:
    """``top_portfolios`` ranks ``run_portfolios`` rows best-first by ``metric`` (D-06/D-18)."""
    run_id = _run_id()
    best = _portfolio(_metrics(sortino=5.0), "best")
    worst = _portfolio(_metrics(sortino=0.5), "worst")
    store.save_run(_run(run_id, _metrics(), portfolios=(worst, best)))

    top = store.top_portfolios("sortino", 2)
    assert [p.name for p in top] == ["best", "worst"]
    assert [p.metrics.sortino for p in top] == [5.0, 0.5]
