"""CSV-backed price store (M5-05, D-16) — the golden-dataset read path.

``CsvPriceStore`` inherits the proven ``data_provider._load_csv_data`` logic
nearly verbatim (CONTEXT.md "Reusable Assets"): Binance-kline header
validation, ``utc -> TIMEZONE`` tz-aware index named ``'date'``, explicit
date-window pinning (D-02), and a loud raise on an empty post-slice frame.

Run path is READ-ONLY (FR6): ``write_bars`` raises ``NotImplementedError``.
FR7 — read accessors raise ``MissingPriceDataError`` for unknown tickers,
never returning ``None`` (replacing the legacy bare-``except:`` -> ``None``
accessor defect in ``data_provider.py``).
"""

from pathlib import Path

import pandas as pd

from itrader.config import TIMEZONE
from itrader.core.exceptions import MalformedDataError, MissingPriceDataError
from itrader.logger import get_itrader_logger

from .base import PriceStore


class CsvPriceStore(PriceStore):
    """Read-only price store serving canonical OHLCV frames loaded from CSV.

    Loads every configured CSV eagerly at construction. Multi-symbol mappings
    are supported (the 06-03 megaframe fixture seed); symbols are keyed
    upper-cased, matching the legacy ``self.prices`` keying.

    Parameters
    ----------
    csv_paths : dict[str, str | Path], optional
        Mapping of ticker -> CSV path. ``None`` defaults to
        ``{CSV_TICKER: CSV_DEFAULT_PATH}`` (the committed golden dataset).
    start_date : str, optional
        Inclusive start of the date window; ``None`` -> ``CSV_START_DATE``.
    end_date : str, optional
        Inclusive end of the date window; ``None`` -> ``CSV_END_DATE``.
    """

    # Default golden dataset for the offline/csv backtest feed (D-01).
    CSV_DEFAULT_PATH = 'data/BTCUSD_1d_ohlcv_2018_2026.csv'
    # Explicit date window for the offline oracle (D-02). Pinned on the store
    # side so the oracle is insulated if the CSV is ever regenerated.
    CSV_START_DATE = '2018-01-01'
    CSV_END_DATE = '2026-06-03'
    # Fixed ticker for the offline feed (D-03/D-06).
    CSV_TICKER = 'BTCUSD'

    def __init__(self, csv_paths: dict[str, str | Path] | None = None,
                 start_date: str | None = None,
                 end_date: str | None = None) -> None:
        if csv_paths is None:
            csv_paths = {self.CSV_TICKER: self.CSV_DEFAULT_PATH}
        self.start_date = start_date if start_date is not None else self.CSV_START_DATE
        self.end_date = end_date if end_date is not None else self.CSV_END_DATE

        # Canonical frames keyed by upper-cased ticker (legacy prices keying).
        self._prices: dict[str, pd.DataFrame] = {}
        for ticker, path in csv_paths.items():
            self._prices[ticker.upper()] = self._load_csv(path)

        self.logger = get_itrader_logger().bind(component="CsvPriceStore")
        self.logger.info(
            'Csv price store initialized (%d symbols)', len(self._prices))

    # -- Read accessors (run path — raise, never return None: FR7) -----------

    def read_bars(self, ticker: str) -> pd.DataFrame:
        """Return the full canonical OHLCV frame for a ticker.

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.

        Returns
        -------
        pd.DataFrame
            Canonical frame: tz-aware ``DatetimeIndex`` named ``'date'``,
            float64 ``open/high/low/close/volume`` columns.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the store (FR7).
        """
        frame = self._prices.get(ticker)
        if frame is None:
            raise MissingPriceDataError(
                ticker, "ticker not loaded in CsvPriceStore")
        return frame

    def has(self, ticker: str) -> bool:
        """Return whether the store holds bars for a ticker."""
        return ticker in self._prices

    def symbols(self) -> list[str]:
        """Return all tickers served by this store."""
        return list(self._prices.keys())

    def index(self, ticker: str) -> pd.DatetimeIndex:
        """Return the bar index for a ticker (feeds ``TimeGenerator.set_dates``).

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the store (FR7).
        """
        return self.read_bars(ticker).index

    # -- Write surface (offline ingestion only — FR6) ------------------------

    def write_bars(self, ticker: str, frame: pd.DataFrame) -> None:
        """Reject writes — the CSV store is read-only on the run path (FR6)."""
        raise NotImplementedError(
            "CsvPriceStore is read-only on the run path — ingestion is offline (FR6)")

    # -- CSV loading (inherited from data_provider._load_csv_data) -----------

    def _load_csv(self, csv_path: str | Path) -> pd.DataFrame:
        """Load one CSV into the EXACT canonical frame shape.

        Mirrors ``data_provider._load_csv_data``: lowercase OHLCV columns and
        a tz-aware ``DatetimeIndex`` named ``'date'`` converted to TIMEZONE.

        Pitfall 6: the ping clock is derived from this same frame index
        (``TimeGenerator.set_dates``), so the index tz is the ping tz by
        construction — one tz, no double-convert.

        V5 / T-06-04: the CSV is trusted-but-verified — a malformed header or
        empty post-slice frame raises loudly instead of silently yielding
        empty bars (which would produce a silently-wrong oracle / zero trades).

        Parameters
        ----------
        csv_path : str | Path
            Path to a Binance-kline-shaped CSV file.

        Returns
        -------
        pd.DataFrame
            The canonical OHLCV frame for the pinned date window.

        Raises
        ------
        MalformedDataError
            If required Binance-kline columns are missing (T-06-04).
        MissingPriceDataError
            If the date-window slice yields an empty frame (T-06-05).
        """
        # Trusted-but-verify: validate the Binance-kline header before mapping.
        expected_cols = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']
        raw = pd.read_csv(csv_path)
        missing = [col for col in expected_cols if col not in raw.columns]
        if missing:
            raise MalformedDataError(
                str(csv_path), f"missing columns {missing}")

        # Map Open time->date, Open/High/Low/Close/Volume->lowercase, drop the
        # trailing Binance-kline columns (Close time, Quote asset volume,
        # Number of trades, Taker buy base/quote, Ignore).
        data = raw[expected_cols].copy()
        data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']

        # Format index exactly like the legacy csv path: tz-aware then convert
        # to the configured timezone so it matches the ping clock by construction.
        data = data.set_index('date')
        data.index = pd.to_datetime(data.index, utc=True)
        data.index = data.index.tz_convert(TIMEZONE)
        data.index.name = 'date'
        data = data.astype(float)

        # D-02: pin the date window explicitly on the store side so the oracle
        # is insulated if the CSV is regenerated. The slice bounds are
        # localized to the index tz to match correctly.
        start = pd.Timestamp(self.start_date, tz=TIMEZONE)
        end = pd.Timestamp(self.end_date, tz=TIMEZONE) + pd.Timedelta(days=1)
        data = data.loc[start:end]

        if data.empty:
            raise MissingPriceDataError(
                str(csv_path),
                f"empty frame after the {self.start_date} -> "
                f"{self.end_date} window slice")

        return data
