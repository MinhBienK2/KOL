"""Shared pytest configuration for the test suite.

``tests/dashboard_fixtures.py`` owns the synthetic run-tree fixtures consumed by the
dashboard test modules. Registering them here makes them visible to every test in this
package instead of each module having to re-export them (``pytest_plugins`` cannot be
used because this conftest is not the top-level one).
"""

from __future__ import annotations

from tests.dashboard_fixtures import run_tree  # noqa: F401  (re-exported fixture)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _kol_offline_unset_by_default(monkeypatch):
    """A developer's ``KOL_OFFLINE=1`` must not flip mocked-API tests; offline tests opt in explicitly."""
    monkeypatch.delenv("KOL_OFFLINE", raising=False)


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch, tmp_path_factory):
    """Tests must never reach the real nine-router/MiniMax provider from the developer's omp config."""
    monkeypatch.setenv("OMP_MODELS_PATH", str(tmp_path_factory.getbasetemp() / "no-omp-models.yml"))
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    for var in ("ROUTER_URL", "LLM_API_KEY", "ROUTER_API_KEY", "LLM_MODEL", "RESEARCH_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_real_asr_network(monkeypatch):
    """Speech-verification tests must never reach the 2tocom transcription endpoint.

    Tests that exercise ``transcribe`` replace ``pipeline.asr.guarded_urlopen`` with their own fake.
    """
    from pipeline import asr

    def _blocked(req, *, operation, **kwargs):
        raise RuntimeError(f"tests may not call the real ASR endpoint ({operation})")

    monkeypatch.setattr(asr, "guarded_urlopen", _blocked)
