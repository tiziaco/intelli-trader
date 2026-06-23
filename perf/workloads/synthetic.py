"""W2 synthetic OHLCV generator (PERF-BASELINE §7 W2).

``make_synthetic_ohlcv(n_bars, n_symbols, seed=42)`` produces deterministic,
seeded-RNG OHLCV frames for the scaling sweep — NO new dependency (uses
``numpy.random.default_rng(seed)``; numpy is already a dep, reusing the
``performance.rng_seed = 42`` discipline).

Generation (spec §7): per bar, draw an M-step sub-bar GBM path, then set
``O = first sub-step``, ``C = last sub-step``, ``H = max``, ``L = min`` over the
sub-steps, and ``V`` = a positive random draw. The sub-bar step is what
GUARANTEES the OHLC invariants (``L <= O,C <= H``) — a naive close-only random
walk produces invalid bars that mislead / crash the matching engine.

Each frame has the SAME canonical shape the feed/store path consumes downstream:
a tz-aware ``DatetimeIndex`` named ``date`` and float64
``open/high/low/close/volume`` columns. Determinism: the same seed yields
byte-identical frames. OHLC invariants are asserted internally for every bar.
"""

import numpy as np
import pandas as pd

__all__ = ["make_synthetic_ohlcv"]

# Sub-bar GBM steps per bar — a small constant. Each bar's OHLC is built from this
# many intra-bar sub-steps so the invariants hold by construction.
_SUBSTEPS = 8
# GBM parameters (per sub-step). Tiny drift, modest vol — a plausible 5m-ish path.
_MU = 0.0
_SIGMA = 0.01
_START_PRICE = 100.0
# Synthetic bar grid: a fixed 5-minute cadence from a pinned epoch (tz-aware UTC).
_EPOCH = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
_FREQ = pd.Timedelta(minutes=5)


def _one_symbol(rng: np.random.Generator, n_bars: int,
                index: pd.DatetimeIndex) -> pd.DataFrame:
    """Generate one symbol's canonical OHLCV frame from a sub-bar GBM path."""
    # Draw all sub-steps at once: shape (n_bars, _SUBSTEPS).
    increments = rng.normal(
        loc=_MU, scale=_SIGMA, size=(n_bars, _SUBSTEPS))
    # Cumulative log-return path, continuous across bars: flatten, cumsum, reshape.
    log_path = np.cumsum(increments.reshape(-1)) + np.log(_START_PRICE)
    prices = np.exp(log_path).reshape(n_bars, _SUBSTEPS)

    open_ = prices[:, 0]
    close = prices[:, -1]
    high = prices.max(axis=1)
    low = prices.min(axis=1)
    volume = rng.uniform(1.0, 1000.0, size=n_bars)

    frame = pd.DataFrame(
        {
            "open": open_.astype(float),
            "high": high.astype(float),
            "low": low.astype(float),
            "close": close.astype(float),
            "volume": volume.astype(float),
        },
        index=index,
    )
    frame.index.name = "date"

    # Internal invariant assertion (every bar): L <= O,C <= H and H >= L.
    ok = (
        (frame["low"] <= frame["open"])
        & (frame["low"] <= frame["close"])
        & (frame["high"] >= frame["open"])
        & (frame["high"] >= frame["close"])
        & (frame["high"] >= frame["low"])
    )
    assert bool(ok.all()), "synthetic OHLC invariant violated"
    return frame


def make_synthetic_ohlcv(
    n_bars: int, n_symbols: int, seed: int = 42
) -> dict[str, pd.DataFrame]:
    """Return ``{ticker: canonical OHLCV frame}`` for the W2 scaling sweep.

    Deterministic: the same ``(n_bars, n_symbols, seed)`` yields byte-identical
    frames. Tickers are ``SYN000``..``SYN{n_symbols-1:03d}``. Each frame shares
    the canonical store/feed column shape (date index + float64 OHLCV).
    """
    if n_bars <= 0:
        raise ValueError(f"n_bars must be > 0, got {n_bars}")
    if n_symbols <= 0:
        raise ValueError(f"n_symbols must be > 0, got {n_symbols}")

    rng = np.random.default_rng(seed)
    index = pd.DatetimeIndex(
        [_EPOCH + i * _FREQ for i in range(n_bars)], name="date")

    frames: dict[str, pd.DataFrame] = {}
    for i in range(n_symbols):
        ticker = f"SYN{i:03d}"
        frames[ticker] = _one_symbol(rng, n_bars, index)
    return frames
