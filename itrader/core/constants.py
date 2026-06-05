"""Cross-cutting reference-data constants (D-03, M2-06).

Plain module-level literals relocated out of the deleted flat ``itrader/config.py``
shadow. These are reference data — not configuration the user tunes — so they live
in ``core/`` as constants rather than in a Pydantic config model.

The ``FORBIDDEN_SYMBOLS`` literal carried an implicit string-concatenation bug in the
flat shadow (adjacent string literals with a missing comma silently concatenate in
Python): ``'BTG/USDT' 'USDP/USDT'`` became the single token ``'BTG/USDTUSDP/USDT'``
and ``'BCHABC/USDT' '1INCH/USDT'`` became ``'BCHABC/USDT1INCH/USDT'``. The commas are
restored here so each pair is a distinct list entry.
"""

from typing import Dict, List, Set

# Quote currencies the screener/universe layer recognises as base settlement assets.
SUPPORTED_CURRENCIES: Set[str] = {"USDT", "BUSD"}

# Exchanges the screener/universe layer recognises.
SUPPORTED_EXCHANGES: Set[str] = {"BINANCE", "KUCOIN"}

# Symbols excluded from the tradable universe, keyed by quote currency. Stablecoin /
# wrapped-asset / fiat pairs that are not meaningful trading targets.
FORBIDDEN_SYMBOLS: Dict[str, List[str]] = {
    "BUSD": [
        "BUSD/BUSD", "TUSD/BUSD", "GBP/BUSD", "BTCST/BUSD", "BTG/BUSD",
        "USDP/BUSD", "USDC/BUSD", "PAX/BUSD", "USDS/BUSD", "USDSB/BUSD", "UST/BUSD",
        "1INCH/BUSD", "T/BUSD", "PAXG/BUSD", "USTC/BUSD", "EUR/BUSD", "AUD/BUSD",
        "USDP/BUSD", "WBTC/BUSD", "BETH/BUSD",
    ],
    "USDT": [
        "BUSD/USDT", "TUSD/USDT", "GBP/USDT", "BTCST/USDT", "BTG/USDT",
        "USDP/USDT", "USDC/USDT", "PAX/USDT", "USDS/USDT", "USDSB/USDT", "UST/USDT",
        "T/USDT", "PAXG/USDT", "USTC/USDT", "EUR/USDT", "AUD/USDT",
        "USDP/USDT", "BCHABC/USDT", "1INCH/USDT",
    ],
}
