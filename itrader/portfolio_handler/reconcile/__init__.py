"""
Reconciliation-cluster primitives for the live/sandbox path (Phase 5).

This package holds the pure, venue-agnostic contracts the drift/halt state machine
(05-04) and the resilience supervisor (05-08) build against. It starts with the
precision-epsilon drift-tolerance helper (D-01); the cached-venue compare/halt body
lands in later plans. Barrel re-exports the public surface.
"""

from .drift import is_within_single_unit_tolerance

__all__ = ["is_within_single_unit_tolerance"]
