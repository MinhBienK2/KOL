"""Offline tests for the pipeline LLM client (provider resolution, cleaning, fallback)."""

import io
import json

import pytest

from pipeline import llm
from pipeline.offline import OfflineNetworkError, offline_mode

OMP_YAML = """providers:
  nine-router:
    baseUrl: http://localhost:20128/v1
    api: openai-completions
    apiKey: test-key-not-real
    models:
      - id: 2tocom/MiniMax-M3
      - id: 2tocom/MiniMax-M3.1-Flash
"""


@pytest.fixture
def omp_config(tmp_path, monkeypatch):
    path = tmp_path / "models.yml"
    path.write_text(OMP_YAML)
    for var in ("LLM_BASE_URL", "ROUTER_URL", "LLM_API_KEY", "ROUTER_API_KEY", "LLM_MODEL", "RESEARCH_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMP_MODELS_PATH", str(path))
    return path


def test_resolves_nine_router_from_omp_config(omp_config):
    provider = llm.resolve_provider()
    assert provider.name == "nine-router"
    assert provider.chat_url == "http://localhost:20128/v1/chat/completions"
    assert provider.api_key == "test-key-not-real"
    assert "2tocom/MiniMax-M3" in provider.models
    assert "test-key-not-real" not in repr(provider)


def test_env_overrides_omp_config(omp_config, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid/v1/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    provider = llm.resolve_provider()
    assert provider.chat_url == "http://example.invalid/v1/chat/completions"
    assert provider.api_key == "env-key"


def test_missing_provider_raises(tmp_path, monkeypatch):
    for var in ("LLM_BASE_URL", "ROUTER_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMP_MODELS_PATH", str(tmp_path / "absent.yml"))
    with pytest.raises(llm.LLMError):
        llm.resolve_provider()


def test_default_model_is_minimax(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    assert llm.default_model() == "2tocom/MiniMax-M3"


def test_clean_completion_strips_think_and_fences():
    raw = "<think>internal reasoning</think>\n```json\n{\"a\": 1}\n```"
    assert llm.clean_completion(raw) == '{"a": 1}'
    assert llm.extract_json(raw) == {"a": 1}
    assert llm.extract_json('Here you go: {"b": [1, 2]} thanks') == {"b": [1, 2]}


def _fake_response(payload):
    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _Resp(json.dumps(payload).encode("utf-8"))


def test_chat_falls_back_to_flash_model(omp_config, monkeypatch):
    calls = []

    def fake_urlopen(req, operation=None, timeout=None):
        body = json.loads(req.data)
        calls.append(body["model"])
        assert req.headers["Authorization"] == "Bearer test-key-not-real"
        if body["model"] == "2tocom/MiniMax-M3":
            return _fake_response({"choices": [{"message": {"content": "<think>x</think>"}}]})
        return _fake_response({"choices": [{"message": {"content": "xin chào"}}], "usage": {"total_tokens": 3}})

    monkeypatch.setattr(llm, "guarded_urlopen", fake_urlopen)
    result = llm.chat("sys", "user")
    assert calls == ["2tocom/MiniMax-M3", "2tocom/MiniMax-M3.1-Flash"]
    assert result["model"] == "2tocom/MiniMax-M3.1-Flash"
    assert result["content"] == "xin chào"


def test_chat_refuses_when_offline(omp_config, monkeypatch):
    monkeypatch.setattr(llm, "guarded_urlopen", lambda *a, **k: pytest.fail("network touched"))
    with offline_mode(True):
        with pytest.raises(OfflineNetworkError):
            llm.chat("sys", "user")
