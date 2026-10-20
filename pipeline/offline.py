"""Guaranteed offline mode: a single switch plus a guard on every paid network call.

Offline is on when the environment variable ``KOL_OFFLINE`` is truthy (``1``, ``true``,
``yes``, ``on``) or inside an :func:`offline_mode` context. Every HTTP call that can
spend money or leave the machine (video submit/poll/download, TTS, image generation,
LLM router, product-page scraping) goes through :func:`guarded_urlopen` /
:func:`guarded_urlretrieve` (or calls :func:`guard_network` first), which raise
:class:`OfflineNetworkError` while offline. Nothing is silently retried or swallowed:
callers that catch ``Exception`` must re-raise this one.

The override is process-global (not a ``ContextVar``) on purpose: stage 5 renders shots
on a thread pool and the guard must hold in every worker thread.
"""

from __future__ import annotations

import contextlib
import os
import threading
import urllib.request
from typing import Any, Iterator, Optional

_TRUTHY = {"1", "true", "yes", "on"}

_lock = threading.Lock()
#: Stack of active ``offline_mode`` overrides; the innermost one wins.
_overrides: list[bool] = []


class OfflineNetworkError(RuntimeError):
    """A network call was attempted while the pipeline is in offline mode."""


def is_offline() -> bool:
    """True when ``KOL_OFFLINE`` is truthy or an ``offline_mode(True)`` scope is active."""
    with _lock:
        if _overrides:
            return _overrides[-1]
    return os.environ.get("KOL_OFFLINE", "").strip().lower() in _TRUTHY


@contextlib.contextmanager
def offline_mode(enabled: bool = True) -> Iterator[None]:
    """Force offline (or online) behaviour for the duration of the ``with`` block."""
    with _lock:
        _overrides.append(bool(enabled))
    try:
        yield
    finally:
        with _lock:
            _overrides.remove(bool(enabled))


def guard_network(operation: str, target: Optional[str] = None) -> None:
    """Raise :class:`OfflineNetworkError` if offline; otherwise do nothing."""
    if is_offline():
        where = f" -> {target}" if target else ""
        raise OfflineNetworkError(
            f"Offline mode (KOL_OFFLINE=1): refused network call '{operation}'{where}. "
            "No paid generation or remote request may run offline; use the local "
            "placeholder/deterministic path or unset KOL_OFFLINE."
        )


def _target_of(req: Any) -> str:
    return str(getattr(req, "full_url", req))


def guarded_urlopen(req: Any, *, operation: str, **kwargs: Any) -> Any:
    """``urllib.request.urlopen`` that refuses to run while offline."""
    guard_network(operation, _target_of(req))
    return urllib.request.urlopen(req, **kwargs)


def guarded_urlretrieve(url: str, filename: Any, *, operation: str, **kwargs: Any) -> Any:
    """``urllib.request.urlretrieve`` that refuses to run while offline."""
    guard_network(operation, url)
    return urllib.request.urlretrieve(url, filename, **kwargs)
