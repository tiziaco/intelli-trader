"""Shared deep-merge helper for the canonical ``update_config`` contract (D-07/D-09).

Promoted verbatim from ``PortfolioHandler._deep_merge`` so every config-model
``update_config`` body merges a partial nested update onto the dumped model
identically — do NOT re-derive a fresh recursive merge per handler.

WR-04 sibling-preservation: a plain ``{**base, **updates}`` is a SHALLOW merge —
passing a partial nested submodel (e.g. ``{"limits": {"max_portfolios": 50}}``)
would REPLACE the whole ``limits`` dict, silently resetting sibling fields like
``max_positions``. Recursing into nested dicts preserves the sibling fields a
caller did not intend to change.
"""

from typing import Any


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``updates`` into ``base`` without mutating either.

    Nested ``dict`` values are merged recursively (sibling-preserving, WR-04);
    every other value type is replaced wholesale by the ``updates`` value.
    """
    merged = dict(base)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
