"""LLM client for the pipeline's text stages (research, concepts, scriptwriting).

Talks to an OpenAI-compatible chat-completions endpoint. The provider is resolved, in order:

1. Environment: ``LLM_BASE_URL`` (or legacy ``ROUTER_URL``), ``LLM_API_KEY`` (or legacy
   ``ROUTER_API_KEY``), ``LLM_MODEL`` (or legacy ``RESEARCH_MODEL``).
2. The omp agent config (``~/.omp/agent/models.yml``, override with ``OMP_MODELS_PATH``),
   provider ``nine-router`` (override with ``LLM_PROVIDER``). The key is read at call time and
   never written to artifacts, telemetry or logs.

The default model is MiniMax M3 served through nine-router, with MiniMax M3.1 Flash as the
fallback. Every call goes through the offline guard.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from pipeline.offline import OfflineNetworkError, guard_network, guarded_urlopen

DEFAULT_PROVIDER = "nine-router"
DEFAULT_MODEL = "2tocom/MiniMax-M3"
FALLBACK_MODELS = ("2tocom/MiniMax-M3.1-Flash", "MiniMax-M3.1-Flash")
DEFAULT_OMP_MODELS_PATH = Path.home() / ".omp" / "agent" / "models.yml"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    """The LLM provider is not configured or every model attempt failed."""


@dataclass
class LLMProvider:
    name: str
    base_url: str
    api_key: Optional[str]
    models: List[str] = field(default_factory=list)

    @property
    def chat_url(self) -> str:
        url = self.base_url.rstrip("/")
        return url if url.endswith("/chat/completions") else f"{url}/chat/completions"

    def __repr__(self) -> str:  # never leak the key
        return f"LLMProvider(name={self.name!r}, base_url={self.base_url!r}, models={self.models!r})"


def _load_omp_provider(provider_name: str, models_path: Path) -> Optional[LLMProvider]:
    if not models_path.is_file():
        return None
    try:
        import yaml  # local import: only needed when falling back to the omp config
    except ImportError:
        return None
    try:
        data = yaml.safe_load(models_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    entry = (data.get("providers") or {}).get(provider_name)
    if not isinstance(entry, dict) or not entry.get("baseUrl"):
        return None
    models = [m.get("id") for m in entry.get("models") or [] if isinstance(m, dict) and m.get("id")]
    return LLMProvider(name=provider_name, base_url=str(entry["baseUrl"]), api_key=entry.get("apiKey"), models=models)


def resolve_provider() -> LLMProvider:
    """Resolve the chat-completions provider from env first, then the omp agent config."""
    provider_name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    omp = _load_omp_provider(provider_name, Path(os.environ.get("OMP_MODELS_PATH", DEFAULT_OMP_MODELS_PATH)))

    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("ROUTER_URL") or (omp.base_url if omp else None)
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ROUTER_API_KEY") or (omp.api_key if omp else None)
    if not base_url:
        raise LLMError(
            f"No LLM provider configured: set LLM_BASE_URL/LLM_API_KEY or add provider "
            f"'{provider_name}' to the omp models.yml"
        )
    return LLMProvider(name=provider_name if omp else "env", base_url=base_url, api_key=api_key,
                       models=omp.models if omp else [])


def default_model() -> str:
    return os.environ.get("LLM_MODEL") or os.environ.get("RESEARCH_MODEL") or DEFAULT_MODEL


def clean_completion(content: str) -> str:
    """Strip reasoning blocks and markdown fences from a completion."""
    text = _THINK_BLOCK.sub("", content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a completion (tolerates prose around it)."""
    cleaned = clean_completion(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("completion contains no parseable JSON")


def _post_chat(provider: LLMProvider, model: str, messages: list, timeout: int,
               temperature: Optional[float], max_tokens: Optional[int]) -> dict:
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    # Cloudflare-fronted gateways reject urllib's default User-Agent with 403 / error 1010.
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    req = urllib.request.Request(provider.chat_url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with guarded_urlopen(req, operation="llm.chat_completion", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise LLMError(f"{model}: HTTP {e.code} {detail}") from e


def chat(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    timeout: int = 90,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    fallback_models: Optional[tuple] = None,
) -> dict:
    """Run one chat completion; try fallback models on failure.

    Returns ``{"content", "model", "usage"}``. Raises :class:`LLMError` when every model fails
    and re-raises :class:`OfflineNetworkError` untouched.
    """
    provider = resolve_provider()
    guard_network("llm.chat_completion", provider.chat_url)
    primary = model or default_model()
    candidates = [primary] + [m for m in (FALLBACK_MODELS if fallback_models is None else fallback_models)
                              if m != primary]
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    errors = []
    for candidate in candidates:
        try:
            res = _post_chat(provider, candidate, messages, timeout, temperature, max_tokens)
            content = clean_completion(res["choices"][0]["message"].get("content") or "")
            if not content:
                raise LLMError(f"{candidate}: empty completion")
            return {"content": content, "model": candidate, "usage": res.get("usage") or {}}
        except OfflineNetworkError:
            raise
        except Exception as e:  # noqa: BLE001 - collect and try the next model
            errors.append(str(e))
    raise LLMError("; ".join(errors) or "no model attempted")
