"""Wave 0 scaffold for the UUIDv7 identity scheme (M2-01).

These tests lock the contracts the UUID work (Plan 03) must satisfy:

1. ``idgen.generate_*()`` returns a *stdlib* ``uuid.UUID`` — NOT the custom
   ``uuid_utils.UUID`` (Pitfall 1: only ``uuid_utils.compat.uuid7()`` yields the
   native type that the rest of the codebase types against, D-14).
2. Two consecutive ids are unique.
3. uuid7 is time-ordered: two ids generated in sequence are monotonically
   increasing (``a < b``).

They are EXPECTED to fail (red) until Plan 03 replaces the integer
counter+prefix ``IDGenerator`` body with ``uuid_utils.compat.uuid7()``. The
module itself must import and collect cleanly (no syntax error, no collection
error) — only the assertions are allowed to fail. No ``@pytest.mark`` is needed
here: ``conftest.py`` DIR_MARKERS maps ``test_outils`` -> ``unit``.
"""

import uuid

from itrader import idgen


def test_generate_order_id_returns_stdlib_uuid():
	"""Pitfall 1: the id must be a native ``uuid.UUID``, not ``uuid_utils.UUID``."""
	value = idgen.generate_order_id()
	assert type(value) is uuid.UUID


def test_consecutive_ids_are_unique():
	"""Two ids generated back-to-back must differ."""
	a = idgen.generate_order_id()
	b = idgen.generate_order_id()
	assert a != b


def test_consecutive_ids_are_time_ordered():
	"""uuid7 is monotonic: a later id sorts strictly after an earlier one."""
	a = idgen.generate_order_id()
	b = idgen.generate_order_id()
	assert a < b
