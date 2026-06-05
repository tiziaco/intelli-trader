"""Unit-layer conftest (D-13/D-15).

Unit tests drive ONE collaborating component in isolation (the D-15 unit boundary):
they may import several classes from their own domain and use a real ``global_queue``
(provided by the root conftest), but they do NOT assert cross-component cascades.

The folder-derived ``unit`` marker is applied automatically by the root
``pytest_collection_modifyitems`` hook for everything under ``tests/unit/``. This
conftest is the layer anchor and the home for any future unit-only fixtures; shared
cross-cutting fixtures (e.g. ``global_queue``) stay in the root conftest.
"""
