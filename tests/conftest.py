"""Shared pytest configuration for the test suite.

``tests/dashboard_fixtures.py`` owns the synthetic run-tree fixtures consumed by the
dashboard test modules. Registering them here makes them visible to every test in this
package instead of each module having to re-export them (``pytest_plugins`` cannot be
used because this conftest is not the top-level one).
"""

from __future__ import annotations

from tests.dashboard_fixtures import run_tree  # noqa: F401  (re-exported fixture)
