"""
Stateless bracket-level helper — pure ± pct math (D-08/D-13, RESEARCH Pattern 5).

`_bracket_levels` is moved VERBATIM (as a module-level function) from
`order_manager.py` (D-13): it was a method but uses no instance state beyond its
args, so it extracts cleanly to a stateless module function. Kept STATELESS and
imported by BOTH the bracket-assembly path (`_assemble_bracket_and_emit`) AND the
fill-anchored path (`_create_fill_anchored_children`) so neither admission nor
reconcile needs a brackets-collaborator ref (D-08).

`_ONE = Decimal("1")` is the module-private constant used ONLY by
`_bracket_levels`; it travels here with its sole consumer. Decimal end-to-end
(the policy types enforce string-path constants, Pitfall 1).

This module mirrors the `core/money.py` shape — a pure-function module plus a
leading-underscore module-level constant, no class, no state.
"""

from decimal import Decimal
from ...core.enums import Side
from ...core.sizing import SLTPPolicy

_ONE = Decimal("1")


def _bracket_levels(policy: SLTPPolicy, anchor: Decimal,
                    action: str) -> "tuple[Decimal, Decimal]":
	"""
	Compute (stop_loss, take_profit) percent-offset levels from ``anchor``.

	D-13: for a BUY parent the stop sits BELOW the anchor and the target
	ABOVE — sl = anchor * (1 - sl_pct), tp = anchor * (1 + tp_pct);
	mirrored for a SELL parent. The anchor is the decision price for
	PercentFromDecision and the actual fill price for PercentFromFill —
	identical ± pct math, different anchoring moment. Decimal end-to-end
	(the policy types enforce string-path constants, Pitfall 1).
	"""
	if action == Side.SELL.value:
		return anchor * (_ONE + policy.sl_pct), anchor * (_ONE - policy.tp_pct)
	return anchor * (_ONE - policy.sl_pct), anchor * (_ONE + policy.tp_pct)
