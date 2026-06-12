# Phase 1: Engine Hygiene - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 1-Engine Hygiene
**Areas discussed:** `_ONE` duplication, Validator retype, Cleanup discipline

---

## `_ONE` duplication

User first asked to clarify, expressing a preference for consolidating and avoiding
duplicates. Claude verified `core/money.py` ↔ `core/sizing.py` have no mutual import
(safe canonical home, no circular-import risk) and surfaced a third copy in
`core/sizing.py:59` beyond the two named in the requirement.

| Option | Description | Selected |
|--------|-------------|----------|
| Canonical `ONE` in core/money.py, all 3 | Public `ONE = Decimal("1")` in core/money.py; import in core/sizing.py, sizing_resolver.py, brackets/levels.py. Fully eliminates duplication. Byte-exact. | ✓ |
| Canonical `ONE`, only the 2 named files | Consolidate the two order_handler copies; leave core/sizing.py copy (3→2). | |
| Put `ONE` in core/sizing.py instead | Reuse existing sizing.py copy as canonical; avoid touching money.py. | |
| (earlier) Document the deliberate duplication | Keep module-private copies, add doc comments. | |

**User's choice:** Canonical `ONE` in core/money.py, all three sites.
**Notes:** Public name (no underscore) since it's now shared. `_ZERO` left untouched (no duplication). Byte-exact: `Decimal("1")` is value-identical anywhere.

---

## Validator retype

| Option | Description | Selected |
|--------|-------------|----------|
| Strict `Decimal` | price/quantity/commission → `Decimal`. Cleanest policy honoring. | ✓ |
| `Decimal \| int` | Allow int alongside Decimal. | |
| Money-coercible + `to_money` | Accept broader type, coerce inside validator. | |

**User's choice:** Strict `Decimal`.
**Notes:** Coercion stays out of a pure validator. Planner to confirm callers pass Decimal; an int/float caller is a defect to surface, not a reason to widen the type.

---

## Cleanup discipline

| Option | Description | Selected |
|--------|-------------|----------|
| Strict — named items only | Touch only enumerated items (+ agreed 3rd `_ONE`). Residue → deferred. | ✓ |
| Opportunistic adjacent cleanup | Also fix sibling residue in same files. Wider diff. | |

**User's choice:** Strict — named items only.
**Notes:** Preserves the unambiguous byte-exact golden gate.

---

## Claude's Discretion

- Exact public query APIs for the `test_position_manager.py` rewrite.
- Precise wording of the softened `TYPE_CHECKING` doc comment.

## Deferred Ideas

- `_ZERO` consolidation (`core/sizing.py:72`) — single copy, no dedup needed now.
- Opportunistic mypy-override / residue sweep — captured, not fixed (strict scope).
