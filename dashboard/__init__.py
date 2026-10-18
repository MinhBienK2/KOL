"""Supervisor dashboard package: run discovery (``runs``) and the FastAPI app (``server``)."""

from __future__ import annotations

from typing import Any

__all__ = ["runs", "server", "create_app", "discover_runs", "resolve_run", "build_view"]


def __getattr__(name: str) -> Any:
    """Lazily expose the heavier ``server`` symbols without importing FastAPI eagerly."""
    if name == "server":
        from dashboard import server as server_module

        return server_module
    if name == "create_app":
        from dashboard.server import create_app

        return create_app
    if name in ("discover_runs", "resolve_run", "build_view", "RunRef", "RunNotFound", "PathEscape"):
        from dashboard import runs as runs_module

        return getattr(runs_module, name)
    raise AttributeError(f"module 'dashboard' has no attribute {name!r}")
