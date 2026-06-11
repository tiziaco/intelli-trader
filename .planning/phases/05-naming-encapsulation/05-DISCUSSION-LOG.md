# Phase 5: Naming & Encapsulation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 5-naming-encapsulation
**Areas discussed:** Count-by-status canonical name (NAME-01), Strategy rename scope (NAME-02), routes accessor + exchange seam shape (NAME-03), Test-hygiene boundary (NAME-04)

---

## NAME-01 — Count-by-status canonical name

| Option | Description | Selected |
|--------|-------------|----------|
| get_orders_count_by_status | Align façade to the existing storage name; base.py Protocol untouched | |
| get_orders_summary | Align storage to the façade name; changes the storage Protocol + both backends | |
| count_orders_by_status (fresh) | New verb-first name across all four layers | ✓ |

**User's choice:** Fresh name — locked **`count_orders_by_status`**.
**Notes:** User rejected `get_orders_summary` outright ("it's really not a summary, it just returns
a count"). Initially proposed `count_orders`; Claude refined to `count_orders_by_status` because the
method returns `Dict[str, int]` (status → count), so bare `count_orders` would mislead a caller into
expecting an `int`. User agreed. Drops the `get_` prefix the encapsulation cleanup is moving away
from. Blast radius: façade (OrderHandler), OrderManager, base.py storage Protocol, both storage
backends (postgres is the deferred stub).

---

## NAME-02 — Strategy rename scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full: attrs + module files | Rename instance attrs AND module files | |
| Attrs too, keep filenames | Rename class + config Fields + instance attrs; leave module filenames | ✓ |
| Class + config only | Rename only class names + pydantic Field names (literal ROADMAP wording) | |

**User's choice:** "Attrs too, keep filenames" (the middle option).
**Notes:** Claude endorsed this as the sweet spot — full internal naming consistency
(class + config Fields + `self.FAST/SLOW/WIN` → `self.fast_window/slow_window/signal_window`)
without the import-path churn / git-history break of renaming module files. `my_strategies/**`
explicitly excluded (off-path, mypy `ignore_errors`).

---

## NAME-03 — routes accessor + exchange seam shape

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only @property | Public `routes` property over a private backing field | |
| Rename field _routes→routes | Plain public attribute rename, no property | ✓ |
| get_routes() method | Public getter method | |

**User's choice:** Plain field rename `_routes → routes` (the second option, confirmed in the batch
where user endorsed second options for 02/03/04).
**Notes:** Requirement only asks for "a public name/accessor"; plain rename is the smallest diff and
the mutable-dict exposure is theoretical — routes is wired once at construction under the
single-writer contract and nothing mutates it at runtime. `register_symbol()` + `update_config`
completeness-audit carry the rest of NAME-03 (Claude's discretion on signatures).

---

## NAME-04 — Test-hygiene boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing public APIs only | Rewrite tests via existing public APIs; add no production API | |
| Add public APIs where genuinely missing | Prefer existing; add a minimal public query when a test needs state nothing exposes | ✓ |

**User's choice:** "Add public APIs where genuinely missing" (the second option).
**Notes:** A test reaching for state with no public equivalent is itself an encapsulation gap worth
closing. Guardrail locked: any new API must be a legitimate read/query (no test-only backdoors, no
setters, no mutable-internal exposure beyond a copy), justified by a real read need not test
convenience alone.

---

## Claude's Discretion

- Plan/wave decomposition across NAME-01..04.
- Exact `register_symbol` signature/return and whether it validates the symbol string.
- Whether/which new NAME-04 public query method is warranted (apply the D-09 guardrail).
- Extent of touched-path opportunistic cleanup (CLEANUP-STANDARD.md).
- Home/wording of the `update_config` completeness-audit note.

## Deferred Ideas

- `order_manager.py` god-module SPLIT → Phase 6 (isolated, FRAGILE-zone).
- Off-path naming in `strategy_handler/my_strategies/**`, live `TradingInterface`, screeners
  (mypy `ignore_errors`, PROJECT.md-deferred).
- Strategy-setting-system refactor (next milestone) — reason D-03 stops at class/config/attr names.
